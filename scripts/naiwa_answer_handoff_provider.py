"""Offline UI handoff adapter: real read-only tools, explicitly simulated text."""
import json
from uuid import UUID

from scripts.manual_naiwa_experience import FixedProvider


def _decode_json_message(message):
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        return None
    try:
        from backend.services.learning_task_context import expand_records
        value = expand_records(json.loads(message["content"]))
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _find_finalization_payload(messages):
    """Return a recognized finalization envelope, even when its evidence is malformed.

    Recognition uses the server-created no-write envelope rather than arbitrary
    user prose, so a missing evidence block is reported as unavailable instead
    of being mistaken for an empty learning history.
    """
    from backend.services.learning_task_service import FINALIZATION_SYSTEM_PROMPT
    trusted_finalizer = any(
        isinstance(message, dict) and message.get("role") == "system"
        and message.get("content") == FINALIZATION_SYSTEM_PROMPT
        for message in messages
    )
    if not trusted_finalizer:
        return False, None
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        payload = _decode_json_message(message)
        if (payload is not None and payload.get("write_permission") is False
                and "goal" in payload and "budget_minutes_upper_bound" in payload
                and "intent" in payload):
            return True, payload
    return False, None


def _summarize_learning_evidence(payload):
    unavailable = {"available": False, "reason": "missing_or_invalid_evidence"}
    if not isinstance(payload, dict) or payload.get("write_permission") is not False:
        return unavailable
    evidence = payload.get("evidence")
    preview = evidence.get("_preview") if isinstance(evidence, dict) else None
    if not isinstance(evidence, dict) or not isinstance(preview, dict):
        return unavailable
    reads = preview.get("read_tool_result_counts")
    read_count = reads.get("get_learning_state") if isinstance(reads, dict) else None
    if type(read_count) is not int or read_count < 1:
        return unavailable
    states = evidence.get("learning_states")
    source_counts = preview.get("source_record_counts")
    shown_counts = preview.get("shown_record_counts")
    if (not isinstance(states, list) or not isinstance(source_counts, dict)
            or not isinstance(shown_counts, dict)):
        return unavailable
    source_nodes = source_counts.get("learning_states")
    shown_nodes = shown_counts.get("learning_states")
    if (type(source_nodes) is not int or type(shown_nodes) is not int
            or source_nodes < len(states) or shown_nodes != len(states)
            or any(not isinstance(state, dict) or not isinstance(state.get("kp_id"), str)
                   for state in states)):
        return unavailable

    attempts = {}
    incomplete = bool(preview.get("is_partial")) or source_nodes != len(states)
    omitted = preview.get("omitted_details")
    if omitted not in (None, []) and not isinstance(omitted, list):
        return unavailable
    incomplete |= bool(omitted)
    for state in states:
        rows = state.get("recent_attempts")
        if not isinstance(rows, list):
            incomplete = True
            continue
        for attempt in rows:
            if (not isinstance(attempt, dict) or not isinstance(attempt.get("attempt_id"), str)
                    or attempt.get("result") not in ("right", "wrong", "unknown")
                    or (attempt.get("assisted") is not True and attempt.get("assisted") is not False
                        and attempt.get("assisted") is not None)):
                incomplete = True
                continue
            attempts.setdefault(attempt["attempt_id"], attempt)
    counts = {"independent_right": 0, "independent_wrong": 0, "assisted_right": 0, "other": 0}
    for attempt in attempts.values():
        result, assisted = attempt.get("result"), attempt.get("assisted")
        if result == "right" and assisted is False:
            counts["independent_right"] += 1
        elif result == "wrong" and assisted is False:
            counts["independent_wrong"] += 1
        elif result == "right" and assisted is True:
            counts["assisted_right"] += 1
        else:
            counts["other"] += 1
    return {"available": True, "partial": incomplete, "nodes": len(states),
            "attempts": len(attempts), "counts": counts}


class HandoffEvidenceProvider(FixedProvider):
    """Never infer facts from prompts or open a network/model connection."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = 0
        self.nodes = []
        self.read_tools = set()
        self.states = []
        self.state_evidence_available = False

    def tool_turn(self, messages, tools, *, timeout):
        self.calls += 1
        is_finalization, finalization = _find_finalization_payload(messages)
        final_summary = _summarize_learning_evidence(finalization) if is_finalization else None
        if is_finalization:
            # The finalization request replaces the tool transcript. Its bounded,
            # server-built evidence bundle is the source of truth for this turn.
            self.states = finalization.get("evidence", {}).get("learning_states", []) if isinstance(finalization.get("evidence"), dict) else []
            self.state_evidence_available = bool(final_summary and final_summary.get("available"))
            self.nodes = [state["kp_id"] for state in self.states if isinstance(state, dict) and isinstance(state.get("kp_id"), str)]
        allowed = {tool['function']['name'] for tool in tools}
        records = []
        request_intent = None
        budget = None
        for message in messages:
            data = _decode_json_message(message)
            if data is None:
                continue
            if message.get('role') == 'user' and not self.nodes:
                handoff = data.get('structured_handoff') or {}
                constraints = handoff.get('constraints') or {}
                candidates = constraints.get('resolved_scope_node_ids') or handoff.get('target_knowledge_node_ids') or []
                try:
                    self.nodes = list(dict.fromkeys(str(UUID(str(value))) for value in candidates))[:8]
                except (ValueError, TypeError):
                    self.nodes = []
            if message.get('role') == 'user' and 'intent' in data and 'budget_minutes' in data:
                request_intent, budget = data['intent'], data['budget_minutes']
            if message.get('role') == 'tool':
                records.append(data)
                if isinstance(data.get('states'), list):
                    self.states = data['states']
                    self.state_evidence_available = True
                if not self.nodes and isinstance(data.get('nodes'), list):
                    self.nodes = [n['kp_id'] for n in data['nodes'] if n.get('assessable') and n.get('kp_id')][:8]
        actions = []
        if not is_finalization and not self.nodes and 'search_knowledge' in allowed and 'search_knowledge' not in self.read_tools:
            actions = [('search_knowledge', {'query': '数学二'})]
        elif not is_finalization and self.nodes:
            for name in ('get_learning_state', 'get_question_availability', 'find_questions'):
                if name in allowed and name not in self.read_tools:
                    actions.append((name, {'kp_ids': self.nodes}))
        if actions:
            self.read_tools.update(name for name, _ in actions)
            return {'message': {'tool_calls': [{'id':f'handoff-{self.calls}-{index}', 'type':'function',
                'function':{'name':name,'arguments':json.dumps(args)}} for index,(name,args) in enumerate(actions)]},
                'model':self.model}
        if not is_finalization and request_intent == 'plan' and 'validate_plan' in allowed and 'validate_plan' not in self.read_tools:
            candidates = [q for record in records for q in record.get('questions', [])
                if isinstance(q, dict) and not q.get('in_today_plan')]
            selected, total = [], 0
            for q in candidates:
                minutes = q.get('minutes')
                if (q.get('question_id') and q['question_id'] not in selected and type(minutes) is int
                        and type(budget) is int and minutes > 0 and total + minutes <= budget):
                    selected.append(q['question_id']); total += minutes
            if selected:
                self.read_tools.add('validate_plan')
                return {'message': {'tool_calls': [{'id': f'handoff-validate-{self.calls}', 'type': 'function',
                    'function': {'name': 'validate_plan', 'arguments': json.dumps({'question_ids': selected,
                        'rationale': '固定模拟Provider按本轮工具返回的合格题和实际预计时长提出预览；不是AI规划质量证明。'})}}]}, 'model': self.model}
        intent=finalization.get('intent') if is_finalization else request_intent
        intent=intent.get('kind') if isinstance(intent,dict) else intent
        goal=finalization.get('goal','') if is_finalization else next((
            data.get('goal','') for message in messages if message.get('role')=='user'
            and (data:=_decode_json_message(message)) and 'intent' in data),'')
        from backend.services.learning_task_service import _validated_plan_summary
        plan_summary=(finalization.get('validated_plan') if is_finalization else next((
            _validated_plan_summary(record.get('draft') or {}) for record in reversed(records)
            if record.get('valid') is True and record.get('draft')),None))
        import re
        asks_statistics=bool(re.search(r'统计|正确率|(?:独立答对|独立答错|看解析后答对).{0,8}(?:几道|多少|几次)',goal))
        if intent=='plan' and not asks_statistics:
            message='【固定模拟Provider：选题工具预览，不代表真实AI规划质量】\n\n'+(plan_summary or
                '本轮尚未取得通过校验的选题草案，没有加入今日卷。')
            return {'message':{'content':json.dumps({'message':message,'needs_clarification':not bool(plan_summary)},ensure_ascii=False)},'model':self.model}
        if is_finalization:
            summary = final_summary or {"available": False}
        else:
            summary = _summarize_learning_evidence({
                "write_permission": False, "evidence": {"learning_states": self.states,
                    "_preview": {"is_partial": False,
                        "source_record_counts": {"learning_states": len(self.states)},
                        "shown_record_counts": {"learning_states": len(self.states)},
                        "read_tool_result_counts": {"get_learning_state": int(self.state_evidence_available)},
                        "omitted_details": []}}})
        prefix = '【固定模拟Provider：只读学习证据回读，不是真实AI规划】'
        if not summary.get('available'):
            body = '本轮未取得可核对的学习状态证据，无法确认知识点或近期作答数量；不能据此判断为0条或推断薄弱点。'
        else:
            counts = summary['counts']
            if summary.get('partial'):
                body = (f"定稿证据包不完整：当前可核对{summary['nodes']}个节点、{summary['attempts']}条近期作答，"
                    f"其中独立答对{counts['independent_right']}条、独立答错{counts['independent_wrong']}条、"
                    f"看解析后答对{counts['assisted_right']}条；省略部分无法按0计算。")
            else:
                body = (f"工具证据显示读取{summary['nodes']}个节点、{summary['attempts']}条近期作答："
                    f"独立答对{counts['independent_right']}条、独立答错{counts['independent_wrong']}条、"
                    f"看解析后答对{counts['assisted_right']}条、其他或不完整记录{counts['other']}条。")
            body += '看解析后答对不等于独立掌握。'
        message = (prefix + body + '本轮没有创建或追加正式计划；本结果只验证离线测试证据传递，不代表真实AI规划质量。')
        if intent=='plan' and plan_summary:message+='\n\n'+plan_summary
        return {'message':{'content':json.dumps({'message':message,'needs_clarification':False},ensure_ascii=False)},'model':self.model}
