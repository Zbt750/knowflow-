"""One assistant conversation, independent QA and existing Planner executors."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import re
import traceback
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import select
from backend.errors import AppError
from backend.models.chat import ChatMessage, ChatSession, MessageCitation
from backend.models.learning import KnowledgePoint, Question, DailyPlan, PracticeItem
from backend.models.learning_task import LearningTask
from backend.schemas.learning_assistant import PlannerHandoff, QAHandoff, StudyContext
from backend.schemas.learning_task import CreateTask, TaskInput
from backend.services.study_context_service import validate_study_context
from backend.services.assistant_router import CapabilityRoute,route_message,assistance_action,answer_reliability_question,evidence_explanation
from backend.services.learning_task_service import create_task,modify_task,run_task,get_task
from backend.services.learning_task_tools import TaskTools
from backend.services.learning_qa_service import record_qa_assistance,safe_hint,final_answer_disclosed,question_relevant,PROMPT_VERSION
from backend.chat.service import answer,stream_answer,encode_sse,citation_payloads

logger = logging.getLogger(__name__)
_CONTEXT_BINDING_FIELDS = ("question_id", "question_version_id", "practice_item_id", "attempt_id", "daily_plan_id",
                           "knowledge_node_ids", "material_id", "chunk_id")


def _may_continue_generation(route, *, mode, qa_action, generation_requested, generation_continuation):
    return bool(mode == "builtin" and qa_action == "auto"
        and (generation_requested or generation_continuation)
        and route.capability != 'data_query'
        and route.reason not in {"explicit_bank_selection", "assistant_capability_inquiry", "explanation_without_selection"})


def _may_classify_data_query(route, *, qa_action, generation_requested):
    return bool(qa_action == "auto" and not generation_requested
        and route.reason not in {"assistant_capability_inquiry", "explanation_without_selection"}
        and (route.capability != "planner" or route.intent == "query"))


def _same_generation_context(original, ctx):
    current = ctx.model_dump(mode="json")
    def value(context, field):
        item = context.get(field)
        return sorted(str(ident) for ident in (item or [])) if field == "knowledge_node_ids" else item
    return all(value(original, field) == value(current, field) for field in _CONTEXT_BINDING_FIELDS)


def _requests_question_reference(message: str, *, has_current_question: bool = False) -> bool:
    """Only resolve a stored question when the user actually refers to one.

    Temporal words such as “刚才” also occur in ordinary follow-ups (“接着刚才
    的例子讲”), so they must be tied to an explicit question/练习 noun before
    we short-circuit the normal conversational QA path.
    """
    text = message.strip()
    refers_to_persisted_question = bool(re.search(
        r"(?:刚(?:才|刚)?生成|你刚?(?:才)?生成|生成|保存|加入(?:到)?今日学习)(?:的)?"
        r".{0,12}(?:题目|题|练习)",
        text,
    ))
    refers_to_active_question = has_current_question and bool(re.search(
        r"(?:这|那)(?:个|道)?(?:题目|题|练习)", text,
    ))
    return refers_to_persisted_question or refers_to_active_question


def _generation_confirmation_turn(db, session_id, body, ctx):
    """Resolve a real confirmation card and preserve its original user message.

    Older clients only send the selected node for legacy single-node cards.
    Multi-node cards require the complete server-issued allocation so a client
    cannot silently accept only one part of the proposed plan. The session row
    is already locked by begin_turn, including double clicks.
    """
    confirmation_id = getattr(body, "personal_generation_confirmation_message_id", None)
    selected = body.personal_generation_confirmed_kp_id
    requested_targets = body.personal_generation_confirmed_targets
    if confirmation_id and (not selected and not requested_targets or body.qa_action != "auto"):
        raise AppError("personal_generation_confirmation_invalid", status_code=409)
    if not selected and not requested_targets:
        return None
    if selected and requested_targets:
        raise AppError("personal_generation_confirmation_invalid", status_code=409)
    if confirmation_id:
        candidate = db.get(ChatMessage, confirmation_id)
        candidates = [candidate] if candidate else []
    else:
        candidates = list(db.scalars(select(ChatMessage).where(
            ChatMessage.session_id == session_id, ChatMessage.role == "assistant",
            ChatMessage.status == "completed").order_by(ChatMessage.seq.desc()).limit(40)))
    for candidate in candidates:
        meta = candidate.metadata_ or {}
        card = meta.get("personal_generation_confirmation")
        if (candidate.session_id != session_id or candidate.role != "assistant"
                or candidate.status != "completed" or not isinstance(card, dict)
                or meta.get("personal_generation_confirmation_status") in {"cancelled", "superseded", "expired"}
                or card.get("question") != body.question
                or meta.get("personal_generation_mode", "ai_generated") != body.personal_generation_mode
                or not _same_generation_context(meta.get("study_context") or {}, ctx)):
            continue
        if requested_targets:
            expected = card.get("proposed_targets")
            if not isinstance(expected, list) or len(expected) != len(requested_targets):
                continue
            expected_contract = [{key: str(target.get(key)) if key == "kp_id" else target.get(key)
                                  for key in ("kp_id", "question_type", "count", "difficulty")}
                                 for target in expected]
            requested_contract = [{"kp_id": str(target.kp_id), "question_type": target.question_type,
                                   "count": target.count, "difficulty": target.difficulty}
                                  for target in requested_targets]
            if expected_contract != requested_contract:
                continue
        else:
            # A multi-node proposal is an atomic allocation. A stale or older
            # client that submits only one selected node must not turn it into
            # a partial generation request.
            if card.get("proposed_targets"):
                continue
            if str(selected) not in {str(node.get("kp_id")) for node in card.get("nodes", [])}:
                continue
        return candidate
    raise AppError("personal_generation_confirmation_invalid", status_code=409)


def _authorized_generation_followup(db, session_id):
    """A genuine prior explicit authoring request may support a follow-up.

    A historical misrouted bank request never grants generation consent.
    """
    latest=db.scalar(select(ChatMessage).where(ChatMessage.session_id==session_id,
        ChatMessage.role=='assistant',ChatMessage.status=='completed').order_by(ChatMessage.seq.desc()).limit(1))
    if not latest:
        return False
    meta=latest.metadata_ or {}
    if not (meta.get('personal_generation') or meta.get('personal_generation_confirmation') or meta.get('generation_context')):
        return False
    context=meta.get('generation_context') or {}
    goal=context.get('instruction') or (meta.get('personal_generation_confirmation') or {}).get('question') or ''
    from backend.services.personal_generation_intent import explicitly_generate
    from backend.services.bank_selection_intent import ambiguous_question_source
    return bool(goal and explicitly_generate(goal) and not ambiguous_question_source(goal))


def begin_turn(factory,*,session_id,body,now=None):
    now=now or datetime.now(timezone.utc)
    with factory.begin() as db:
        session=db.scalar(select(ChatSession).where(ChatSession.id==session_id).with_for_update())
        ctx=validate_study_context(db,session_id=session_id,context=body.study_context,now=now)
        if session.purpose=="study" and session.study_date!=now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat():
            raise AppError("study_session_expired",status_code=409)
        if session.mode=="user" and not session.material_scope_ids:raise AppError("private_scope_required",status_code=422)
        confirmation = _generation_confirmation_turn(db, session_id, body, ctx)
        fingerprint_input={"question":body.question,"action":body.qa_action,"current_work":body.current_work,
            "personal_generation_mode":body.personal_generation_mode,
            "context":ctx.model_dump(mode="json",exclude={"generated_at"})}
        if body.personal_generation_confirmed_kp_id:
            fingerprint_input["personal_generation_confirmed_kp_id"]=str(body.personal_generation_confirmed_kp_id)
        if body.personal_generation_confirmed_targets:
            fingerprint_input["personal_generation_confirmed_targets"]=[
                target.model_dump(mode="json") for target in body.personal_generation_confirmed_targets]
        if confirmation:
            fingerprint_input["personal_generation_confirmation_message_id"] = str(confirmation.id)
        fingerprint=sha256(json.dumps(fingerprint_input,sort_keys=True).encode()).hexdigest()
        if body.request_key:
            old=db.scalar(select(ChatMessage).where(ChatMessage.session_id==session_id,ChatMessage.role=="assistant",
                ChatMessage.metadata_["request_key"].as_string()==str(body.request_key)).order_by(ChatMessage.seq.desc()))
            if old:
                if (old.metadata_ or {}).get("input_sha256")!=fingerprint: raise AppError("idempotency_key_conflict",status_code=409)
                if old.status=="generating": raise AppError("assistant_turn_busy",status_code=409)
                if old.status=="completed": return ctx,old.id,UUID(old.metadata_["source_user_message_id"]),True
                if body.retry_of_message_id != old.id: raise AppError("assistant_retry_invalid",status_code=409)
        if confirmation:
            previous = db.scalar(select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.role == "assistant",
                ChatMessage.metadata_["personal_generation_confirmation_message_id"].as_string() == str(confirmation.id)
            ).order_by(ChatMessage.seq.desc()))
            if previous:
                if (previous.metadata_ or {}).get("input_sha256") != fingerprint:
                    raise AppError("personal_generation_confirmation_invalid", status_code=409)
                if previous.status == "completed":
                    return ctx, previous.id, UUID(previous.metadata_["source_user_message_id"]), True
                if previous.status == "generating":
                    raise AppError("assistant_turn_busy", status_code=409)
                if body.retry_of_message_id != previous.id:
                    raise AppError("assistant_retry_invalid", status_code=409)
        if db.scalar(select(ChatMessage.id).where(ChatMessage.session_id==session_id,ChatMessage.status=="generating")):
            raise AppError("assistant_turn_busy",status_code=409)
        if body.retry_of_message_id:
            failed=db.get(ChatMessage,body.retry_of_message_id)
            if not failed or failed.session_id!=session_id or failed.role!="assistant" or failed.status not in {"failed","cancelled"}: raise AppError("assistant_retry_invalid",status_code=422)
            source=(failed.metadata_ or {}).get("source_user_message_id")
            user=db.get(ChatMessage,UUID(source)) if source else None
            if not user or user.content!=body.question: raise AppError("assistant_retry_invalid",status_code=422)
            original=(failed.metadata_ or {}).get("study_context",{})
            if not _same_generation_context(original, ctx): raise AppError("assistant_retry_invalid",status_code=422)
            if not ctx.task_id and (failed.metadata_ or {}).get("planner_task_id"):
                ctx.task_id=UUID(failed.metadata_["planner_task_id"])
        elif confirmation:
            source = (confirmation.metadata_ or {}).get("source_user_message_id")
            user = db.get(ChatMessage, UUID(source)) if source else None
            if not user or user.role != "user" or user.session_id != session_id or user.content != body.question:
                raise AppError("personal_generation_confirmation_invalid", status_code=409)
        else:
            from backend.services.learner_self_report import extract_self_reports
            user=ChatMessage(session_id=session_id,role="user",content=body.question,status="completed",created_at=now,metadata_={"study_context":ctx.model_dump(mode="json"),
                "learner_self_reports": extract_self_reports(body.question)})
            db.add(user); db.flush()
        if session.title=="新对话": session.title=body.question.replace("\n"," ")[:24]
        from backend.services.generation_conversation import resolve_generation_context
        generation_context = resolve_generation_context(db, session_id, body, ctx,
            continuation=confirmation if confirmation else failed if body.retry_of_message_id else None)
        # A new existing-bank request cannot inherit an earlier authoring card.
        from backend.services.bank_selection_intent import bank_selection_request, ambiguous_question_source
        bank_request = bank_selection_request(body.question)
        generation_followup_authorized = bool(ambiguous_question_source(body.question) and _authorized_generation_followup(db,session_id))
        if ((bank_request and bank_request.get('bank_source')) or
                (ambiguous_question_source(body.question) and not confirmation and not generation_followup_authorized)):
            generation_context = None
        if generation_context and (generation_context.get("reference_source") or {}).get("kind") == "current_user_message":
            generation_context["reference_source"] = {"kind": "user_message", "message_id": str(user.id)}
            for candidate in generation_context.get("reference_candidates", []):
                candidate["reference_source"] = dict(generation_context["reference_source"])
        if generation_context and not confirmation and not body.retry_of_message_id:
            # A new request supersedes a pending card, without deleting its
            # history or making the new user message a retry of that old turn.
            for card in db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id,
                    ChatMessage.role == "assistant", ChatMessage.status == "completed")
                    .order_by(ChatMessage.seq.desc()).limit(30)):
                if (card.metadata_ or {}).get("personal_generation_confirmation"):
                    card.metadata_ = {**card.metadata_, "personal_generation_confirmation_status": "superseded"}
        reply=ChatMessage(session_id=session_id,role="assistant",status="generating",content="",created_at=now,
            metadata_={"study_context":ctx.model_dump(mode="json"),"source_user_message_id":str(user.id),
                "request_key":str(body.request_key or uuid4()),"input_sha256":fingerprint,
                "personal_generation_mode": body.personal_generation_mode,
                "personal_generation_confirmed_kp_id": str(body.personal_generation_confirmed_kp_id) if body.personal_generation_confirmed_kp_id else None,
                "personal_generation_confirmed_targets": ([target.model_dump(mode="json")
                    for target in body.personal_generation_confirmed_targets]
                    if body.personal_generation_confirmed_targets else None),
                "personal_generation_confirmation_message_id": str(confirmation.id) if confirmation else None,
                "current_work": body.current_work, "qa_action": body.qa_action,
                "generation_context": generation_context,
                "generation_followup_authorized": generation_followup_authorized,
                "retry_of_message_id":str(body.retry_of_message_id) if body.retry_of_message_id else None})
        text_confirm = re.fullmatch(r'(?:确定|确认)\s+(.+)', body.question.strip())
        if text_confirm and not confirmation:
            latest = db.scalar(select(ChatMessage).where(ChatMessage.session_id == session_id,
                ChatMessage.role == 'assistant', ChatMessage.status == 'completed').order_by(ChatMessage.seq.desc()).limit(1))
            card = (latest.metadata_ or {}).get('personal_generation_confirmation') if latest else None
            if card and (latest.metadata_ or {}).get('personal_generation_confirmation_status') not in {'cancelled', 'superseded', 'expired'}:
                requested = text_confirm[1].strip()
                options = card.get('nodes', [])
                matches = [n for n in options if requested in {n.get('name'), n.get('code')}]
                reply.metadata_ = {**reply.metadata_, 'generation_confirmation_notice':
                    (f'已匹配「{requested}」，请在原确认卡点击“确认知识点并生成”完成绑定确认。'
                     if len(matches) == 1 else f'未找到知识点「{requested}」。可选现有知识点：' + '、'.join(n['name'] for n in options[:16]) + '。请选择现有节点或取消；没有生成题目。')}
        db.add(reply); db.flush()
        return ctx,reply.id,user.id,False


def task_is_current(task, now):
    context=task.context or {}
    study_date=(context.get("current_plan") or {}).get("study_date")
    if not study_date:
        created=task.created_at
        if created.tzinfo is None: created=created.replace(tzinfo=timezone.utc)
        study_date=created.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    return study_date==now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def active_task(factory,ctx,now=None):
    if not ctx.task_id: return None
    with factory() as db:
        task=db.get(LearningTask,ctx.task_id)
        if not task: return None
        return {"status":task.status,"budget_minutes":task.budget_minutes,
            "budget_explicit":any(((task.context or {}).get('planner_handoff') or {}).get('constraints',{}).get(k) for k in ('time_explicit','time_inherited')),
            "committed":bool((task.metrics or {}).get("commit")) or not task_is_current(task,now or datetime.now(timezone.utc))}


def requested_count(text):
    match=re.search(r"(?:补|安排|练|做|推荐|给我|只要|只做|拿出|取出|挑选|挑出|挑|选出|选|找出|找|抽取)(?:充)?\s*([一二三四五六七八九]十[一二三四五六七八九]?|十[一二三四五六七八九]?|[一二两三四五六七八九]|[1-9]\d?)\s*(?:道|题)",text)
    if not match: return None
    value=match.group(1)
    return chinese_number(value)


def chinese_number(value):
    if value.isdigit(): return int(value)
    digits={c:i for i,c in enumerate("零一二三四五六七八九")}; digits["两"]=2
    if "十" in value:
        left,right=value.split("十",1); return digits.get(left,1)*10+digits.get(right,0)
    return digits[value]


def explicit_minutes(message):
    values=[]
    def current_budget(match):
        before=message[max(0,match.start()-30):match.start()]
        local=re.split(r'[，,；;。！？\n]|改为|改成|调整为|调整到|现在|今天|新的|重新|只学|只有',before)[-1]
        return not re.search(r'刚才|原来|原先|之前|上次|旧(?:的)?|做了|花了|用了',local)
    for match in re.finditer(r"(\d{1,3}|[一二两三四五六七八九十]{1,3})\s*分钟",message):
        if current_budget(match): values.append((match.start(),chinese_number(match.group(1))))
    for match in re.finditer(r"(半|\d|[一二两三四])(?:个)?小时",message):
        if current_budget(match): values.append((match.start(),30 if match.group(1)=="半" else chinese_number(match.group(1))*60))
    return max(values)[1] if values else None


def planner_handoff(factory,*,ctx,user_id,message,route,now):
    explicit=explicit_minutes(message)
    minutes=explicit if explicit is not None else 90
    time_inherited=False
    inherited_activity_schedule=False
    refinement_scope=None
    if ctx.task_id:
        with factory() as db:
            previous=db.get(LearningTask,ctx.task_id)
            if (previous and task_is_current(previous,now) and not (previous.metrics or {}).get("commit")
                    and previous.status in {'created','ready','needs_info','failed'}):
                previous_constraints=((previous.context or {}).get('planner_handoff') or {}).get('constraints',{})
                if explicit is None:
                    minutes=previous.budget_minutes
                    time_inherited=bool(previous_constraints.get('time_explicit') or previous_constraints.get('time_inherited'))
                inherited_activity_schedule=bool(previous_constraints.get('activity_schedule_requested'))
                previous_handoff=(previous.context or {}).get('planner_handoff') or {}
                # A budget/priority refinement belongs to the existing draft's
                # scope unless the learner names a replacement scope. The page's
                # currently selected leaf is not consent to narrow a whole-plan draft.
                names_new_scope=bool(re.search(r'数学二|数二|考研数学|408|计算机统考',message)) or bool(observed_scope := TaskTools(
                    factory,budget_minutes=minutes,now=now,goal=message).explicit_scope)
                if (route.reason=='active_draft_refinement' and not names_new_scope
                        and not re.search(r'当前(?:这道)?题|当前知识点|这个知识点',message)):
                    saved_ids=list(previous_handoff.get('target_knowledge_node_ids') or [])
                    if saved_ids:
                        refinement_scope=[UUID(str(value)) for value in saved_ids]
    if minutes<5 or minutes>240: raise AppError("planning_budget_out_of_range",status_code=422)
    observed=TaskTools(factory,budget_minutes=minutes,now=now,goal=message)
    # A global inventory query never inherits yesterday's question as a hard scope.
    targets=list(observed.explicit_scope or [])[:8]
    scope_origin="explicit_user_scope" if targets else "unresolved"
    if observed.explicit_scope:
        with factory() as db:
            anchors=[n for n in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(observed.explicit_scope)).order_by(KnowledgePoint.code)) if n.parent_id not in observed.explicit_scope]
            targets=[n.id for n in anchors[:8]]
    # "Based on today's learning" requests read today's actual plan, not a partial
    # substring match (e.g. 矩阵 inside 伴随矩阵) that silently drops another subject.
    if ctx.daily_plan_id and re.search(r"^根据(?:我)?今天.{0,45}(?:学习|作答|实际)",message) and not re.search(r"只练|只做|仅练|限定范围|改练|换成",message):
        with factory() as db:
            today_plan=db.get(DailyPlan,ctx.daily_plan_id)
            if today_plan and today_plan.study_date==now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat():
                targets=list(db.scalars(select(PracticeItem.kp_id).where(PracticeItem.plan_id==today_plan.id).distinct().order_by(PracticeItem.kp_id)))[:8]
                if targets: scope_origin="today_evidence_scope"
    if not targets and ctx.task_id and re.search(r"少一点|多一点|只做|只要|基础一点|简单一点|再减少",message):
        with factory() as db:
            previous=db.get(LearningTask,ctx.task_id)
            if previous and task_is_current(previous,now) and not (previous.metrics or {}).get("commit"):
                targets=[UUID(k) for k in ((previous.context or {}).get("planner_handoff",{})).get("target_knowledge_node_ids",[])]
                if targets: scope_origin="current_task_draft"
    if not targets and route.intent!="query":
        targets=list(ctx.knowledge_node_ids)
        if targets: scope_origin="current_study_context"
    if not targets and route.intent!="query" and re.search(r"这种|这个|这样|类似|继续|再补|刚才|我说的",message):
        with factory() as db:
            latest=db.scalar(select(ChatMessage).where(ChatMessage.session_id==ctx.conversation_id,ChatMessage.role=="assistant",ChatMessage.status=="completed").order_by(ChatMessage.seq.desc()))
            ids=((latest.metadata_ or {}).get("learning_trace") or {}).get("knowledge_node_ids_used",[]) if latest else []
            if not ids and latest:ids=((latest.metadata_ or {}).get("learning_trace") or {}).get("resolved_knowledge_node_ids",[])
            if not ids and latest and latest.matched_kp_id: ids=[str(latest.matched_kp_id)]
            parsed=[UUID(k) for k in ids[:8]]
            targets=list(db.scalars(select(KnowledgePoint.id).where(KnowledgePoint.id.in_(parsed),KnowledgePoint.is_active.is_(True))))
            if targets: scope_origin="latest_validated_qa_context"
    if refinement_scope and not TaskTools(factory,budget_minutes=minutes,now=now,goal=message).explicit_scope \
            and not re.search(r'数学二|数二|考研数学|408|计算机统考|当前(?:这道)?题|当前知识点|这个知识点',message):
        targets=refinement_scope
        scope_origin='current_task_draft'
    exclusions=set(observed.excluded_scope)
    if route.intent=="query" and re.search(r"除.{0,24}(?:当前|正在看|这个).{0,12}(?:知识点|节点)",message): exclusions.update(ctx.knowledge_node_ids)
    target_subject=ctx.subject
    if targets:
        with factory() as db:subjects=set(db.scalars(select(KnowledgePoint.subject).where(KnowledgePoint.id.in_(targets))))
        target_subject=next(iter(subjects)) if len(subjects)==1 else None
    # Resolve once, before persisting the goal. Subject requests and validated
    # conversation scope must not silently become the currently viewed leaf.
    from backend.services.learning_planner_scope import resolve_planner_scope
    targets,target_subject,resolved_scope=resolve_planner_scope(
        factory,ctx,message,observed,now,task_is_current,fallback=(targets,scope_origin))
    from backend.services.bank_selection_intent import bank_selection_request
    bank = bank_selection_request(message) if route.reason == 'explicit_bank_selection' else None
    similar_reference = None
    reference_scope_conflict = False
    if bank and bank.get('similar') and ctx.question_id and ctx.question_version_id:
        similar_reference = {'question_id': str(ctx.question_id), 'version_id': str(ctx.question_version_id)}
        # The validated practice context is the referent; do not substitute an unrelated page node.
        with factory() as db:
            reference = db.get(Question, ctx.question_id)
            if reference:
                reference_scope_conflict = bool(observed.explicit_scope and reference.kp_id not in observed.explicit_scope)
                if reference_scope_conflict:
                    similar_reference = None
                else:
                    targets = [reference.kp_id]
                    target_subject = db.get(KnowledgePoint, reference.kp_id).subject
                    resolved_scope = {**resolved_scope, 'scope_origin':'current_study_context',
                        'scope_version':1,'scope_explicit':True,'resolved_scope_node_ids':[str(reference.kp_id)],
                        'unresolved_topics':[]}
    return PlannerHandoff(source_conversation_id=ctx.conversation_id,source_message_id=user_id,
        source_question_id=ctx.question_id,source_attempt_id=ctx.attempt_id,target_knowledge_node_ids=targets,
        subject=target_subject,user_problem=message,request_type=route.intent,
        requested_question_count=(bank['count'] if bank else requested_count(message)),available_minutes=minutes,
        difficulty_preference=(observed.required_difficulty or ("basic" if "基础" in message else None)),
        constraints={"user_problem_is_self_report":True,"current_plan_id":str(ctx.daily_plan_id) if ctx.daily_plan_id else None,
            "existing_bank_only":route.reason=='explicit_bank_selection',
            "include_personal_bank":bool(bank and bank.get('include_personal')),
            "similar_requested":bool(bank and bank.get('similar')),
            "similar_reference":similar_reference,
            "reference_scope_conflict":reference_scope_conflict,
            "activity_schedule_requested":(route.reason=='study_activity_schedule' or
                (route.reason=='active_draft_refinement' and inherited_activity_schedule)),
            "draft_refinement":route.reason=='active_draft_refinement',
            "time_inherited":time_inherited,
            "relax_count":bool(re.search(r"少一点|再减少|不用那么多",message)),"time_explicit":explicit is not None,
            "global_inventory":route.intent=="query" and not observed.explicit_scope,
            "context_node_ids":[str(k) for k in ctx.knowledge_node_ids],
            "scope_origin":scope_origin,
            "inventory_subject":"408" if re.search(r"408",message) else "考研数学" if re.search(r"数学二|数二",message) else None,
            **resolved_scope},
        exclusions=list(exclusions)[:8],generated_at=now)


def qa_handoff(ctx,task_id,message,*,reason="requested_concept_help",scope=None):
    return QAHandoff(source_task_id=task_id,knowledge_node_ids=scope or ctx.knowledge_node_ids,
        question_id=ctx.question_id,reason=reason,learning_problem=message[:1200],suggested_mode="question" if ctx.question_id else "knowledge")


def prepare_planner(factory,*,ctx,handoff,now):
    with factory() as db:
        names=list(db.scalars(select(KnowledgePoint.code).where(KnowledgePoint.id.in_(handoff.target_knowledge_node_ids))))
    goal=("学习范围："+"、".join(names)+"\n" if names else "")+handoff.user_problem
    if len(goal)>1200: raise AppError("learning_goal_too_long",status_code=422)
    prior=get_task(factory,ctx.task_id) if ctx.task_id else None
    with factory() as db:
        prior_row=db.get(LearningTask,ctx.task_id) if ctx.task_id else None
        prior_current=bool(prior_row and task_is_current(prior_row,now))
        request_link=(prior_row.context or {}).get("practice_request_id") if prior_row else None
    separate_preview = bool(re.search(r'(?:不要|不能|别).{0,12}(?:覆盖|替代|替换)|保留.{0,12}(?:原|旧)|新的.{0,12}(?:安排|方案|计划)', handoff.user_problem))
    if prior and prior_current and not separate_preview and prior.status in {"created","ready","needs_info","failed"} and not prior.metrics.get("commit") and handoff.request_type=="plan":
        # 相同失败回合复用任务ID与审计，不把重试当成新规划并清空证据。
        task=(prior if prior.status=='failed' and prior.goal==goal and prior.budget_minutes==handoff.available_minutes else
            modify_task(factory,ctx.task_id,TaskInput(goal=goal,budget_minutes=handoff.available_minutes),now=now))
    else:
        with factory() as db:
            viewed_plan=db.get(DailyPlan,ctx.daily_plan_id) if ctx.daily_plan_id else None
            today_id=ctx.daily_plan_id if viewed_plan and viewed_plan.study_date==now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() else None
        task=create_task(factory,CreateTask(goal=goal,budget_minutes=handoff.available_minutes,session_id=ctx.conversation_id,current_plan_id=today_id),now=now)
    with factory.begin() as db:
        row=db.get(LearningTask,task.task_id)
        recent=list(db.scalars(select(DailyPlan).where(DailyPlan.study_date<now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()).order_by(DailyPlan.study_date.desc()).limit(2)))
        recent_scope=[]
        for plan in recent:
            ids=list(db.scalars(select(PracticeItem.kp_id).where(PracticeItem.plan_id==plan.id).distinct()))
            recent_scope.append({"plan_id":str(plan.id),"study_date":plan.study_date,"status":plan.status,
                "knowledge_node_ids":[str(i) for i in ids],
                "knowledge_nodes":[{"id":str(n.id),"name":n.name,"code":n.code} for n in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(ids)))],
                "unfinished_question_ids":[str(i) for i in db.scalars(select(PracticeItem.question_id).where(PracticeItem.plan_id==plan.id,PracticeItem.completed_at.is_(None),PracticeItem.question_id.is_not(None)))]})
        from backend.services.learner_self_report import read_self_reports
        row.context={**(row.context or {}),"planner_handoff":handoff.model_dump(mode="json"),"study_context":ctx.model_dump(mode="json"),
            "learner_self_reports": read_self_reports(db, ctx.conversation_id),
            "previous_plan_policy": "preserve_existing; preview_only_until_confirmation",
            "recent_learning":recent_scope,"memory_policy":"task-scoped; no QA conversation messages"}
        if prior and prior_current and task.task_id==prior.task_id and request_link:row.context={**row.context,"practice_request_id":request_link}
    return task


def persist_route(factory,message_id,route,extra=None):
    with factory.begin() as db:
        message=db.get(ChatMessage,message_id)
        message.metadata_={**(message.metadata_ or {}),"capability_route":route.public_dict(),**(extra or {})}


def fail_turn(factory,message_id,code,diagnostic=None):
    with factory.begin() as db:
        message=db.get(ChatMessage,message_id)
        if message and message.status=="generating":
            message.status="failed"; message.metadata_={**(message.metadata_ or {}),"assistant_error_code":code,
                **({"assistant_error_details": diagnostic} if diagnostic else {})}


def cancel_generation_confirmation(factory, *, session_id, message_id):
    """Persist 'not now' without creating messages, questions or plans."""
    from backend.chat.service import require_active_session
    with factory.begin() as db:
        require_active_session(db, session_id)
        db.scalar(select(ChatSession).where(ChatSession.id == session_id).with_for_update())
        card = db.get(ChatMessage, message_id)
        meta = dict(card.metadata_ or {}) if card else {}
        if (not card or card.session_id != session_id or card.role != "assistant"
                or not isinstance(meta.get("personal_generation_confirmation"), dict)):
            raise AppError("personal_generation_confirmation_invalid", status_code=409)
        if meta.get("personal_generation_confirmation_status") == "cancelled":
            return {"message_id": str(message_id), "status": "cancelled"}
        continuation = db.scalar(select(ChatMessage.id).where(
            ChatMessage.session_id == session_id, ChatMessage.role == "assistant",
            ChatMessage.metadata_["personal_generation_confirmation_message_id"].as_string() == str(message_id),
            ChatMessage.status.in_(("generating", "completed"))))
        if continuation:
            raise AppError("personal_generation_confirmation_invalid", status_code=409)
        card.metadata_ = {**meta, "personal_generation_confirmation_status": "cancelled"}
        return {"message_id": str(message_id), "status": "cancelled"}


def _safe_failure_details(exc, phase):
    # Only stack locations, never exception text/SQL parameters/user material.
    return {"stage": phase, "exception_type": type(exc).__name__,
        "sqlstate": getattr(getattr(exc, "orig", None), "sqlstate", None),
        "generation_service_entered": phase in {"generation_service", "generation_result_persist"},
        "locations": [f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                      for frame in traceback.extract_tb(exc.__traceback__)[-6:]]}


def present_planner_message(text, task, ctx):
    """Remove identifiers from user presentation, never from factual tool traces."""
    ids={str(ctx.question_id),str(ctx.task_id)}-{"None"}
    for step in task.trace:
        for question in (step.get("result") or {}).get("questions",[]):
            if question.get("question_id"): ids.add(str(question["question_id"]))
    for value in ids:
        for size in range(len(value),7,-1):
            text=re.sub(re.escape(value[:size])+r"(?:…|\.\.\.)", "该题", text)
    return re.sub(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b","该题",text)


def expire_invalid_confirmation(factory, session_id, body):
    """Persist a rejected local card's terminal state; a page reload is not consent.

    Never touch a card from another session, nor any question/learning evidence.
    This runs after the rejected begin_turn transaction has rolled back.
    """
    ident = body.personal_generation_confirmation_message_id
    if not ident:
        return
    with factory.begin() as db:
        card = db.get(ChatMessage, ident, with_for_update=True)
        if (card is not None and card.session_id == session_id and card.role == "assistant"
                and (card.metadata_ or {}).get("personal_generation_confirmation")):
            status = (card.metadata_ or {}).get("personal_generation_confirmation_status")
            if status not in {"cancelled", "superseded", "expired"}:
                card.metadata_ = {**card.metadata_, "personal_generation_confirmation_status":"expired"}


def _bank_confirmation_kind(message: str) -> str | None:
    text = re.sub(r"\s+", "", message or "")
    if re.fullmatch(r"(?:确认|确定|是的|可以|好|好的|就这样|没问题)(?:了|吧|啊|。|！|!|？|\?)?", text):
        return "bare"
    if (re.search(r"(?:加入|添加|放到|放进|放入|加到|加进).{0,100}(?:今日卷|今日学习|预览|候选|这道题|这题)", text)
            or re.search(r"(?:就这题|就这道题|预览的).{0,100}(?:加入|添加|放到|放进|放入|今日卷|今日学习)", text)):
        return "explicit"
    return None


def _normalized_question_reference(value: str) -> str:
    return re.sub(r"[\s\(\)\[\]\{\}（）【】`$，,。！？?；;:：]", "", value or "").lower()


def _question_matches_confirmation(stem: str, message: str) -> bool:
    normalized_stem = _normalized_question_reference(stem)
    normalized_message = _normalized_question_reference(message)
    if len(normalized_stem) >= 12 and normalized_stem in normalized_message:
        return True
    for reference in re.findall(r"[（(]([^()（）]{4,240})[）)]", message or ""):
        normalized = _normalized_question_reference(reference)
        if len(normalized) >= 6 and normalized in normalized_stem:
            return True
    return False


def _same_session_bank_proposals(factory, session_id, now):
    """Recover only bank-only planner tasks explicitly shown in this session."""
    from backend.services.learning_task_service import _draft_version
    with factory() as db:
        messages = db.scalars(select(ChatMessage).where(
            ChatMessage.session_id == session_id, ChatMessage.role == "assistant"
        ).order_by(ChatMessage.seq.desc()).limit(100)).all()
        task_ids = list(dict.fromkeys(
            str((message.metadata_ or {}).get("planner_task_id"))
            for message in messages if (message.metadata_ or {}).get("planner_task_id")
        ))
        proposals = []
        for raw_id in task_ids:
            try:
                task = db.get(LearningTask, UUID(raw_id))
            except (TypeError, ValueError):
                continue
            if not task or task.session_id != session_id:
                continue
            context = task.context or {}
            handoff = context.get("planner_handoff") or {}
            constraints = handoff.get("constraints") or {}
            # Home recommendation previews have their own confirm API and are
            # deliberately excluded from this assistant task flow.
            if context.get("home_recommendation") or not constraints.get("existing_bank_only"):
                continue
            if not task.draft or not task.draft.get("questions"):
                continue
            committed = bool((task.metrics or {}).get("commit"))
            proposals.append({
                "task_id": task.id,
                "draft_version": _draft_version(task),
                "draft": task.draft,
                "status": task.status,
                "committed": committed,
                "current": task_is_current(task, now),
            })
        return proposals


def _select_bank_confirmation(proposals, message: str):
    active = [p for p in proposals if p["status"] == "ready" and not p["committed"] and p["current"]]
    if active:
        if len(active) == 1:
            target = active[0]
            # If the user supplied a concrete formula, it must identify this
            # preview; an unrelated formula is not consent to the visible task.
            formulas = re.findall(r"[（(]([^()（）]{4,240})[）)]", message or "")
            if formulas:
                matched_questions = [q for q in target["draft"].get("questions", [])
                    if _question_matches_confirmation(q.get("stem", ""), message)]
                if len(matched_questions) != 1:
                    return None, "用户提到的题目与当前待确认预览不一致或无法唯一对应；没有加入今日卷。请重新选择该预览中的题目。", "mismatch"
                if len(target["draft"].get("questions", [])) != 1:
                    return None, "这份预览包含多道题，你指向其中一道；为避免把整份方案误当成单题确认，请先生成单题预览再确认。", "partial_selection"
            return target, None, "pending"
        matched = [p for p in active if any(_question_matches_confirmation(q.get("stem", ""), message)
                                             for q in p["draft"].get("questions", []))]
        if len(matched) == 1:
            return matched[0], None, "pending"
        return None, "当前有多个有效的题库预览，无法确定你要确认哪一份。请打开对应预览后再次明确选择；没有写入今日卷。", "ambiguous"

    committed = [p for p in proposals if p["committed"] and p["current"]]
    if len(committed) == 1:
        return committed[0], None, "committed"
    if len(committed) > 1:
        matched = [p for p in committed if any(_question_matches_confirmation(q.get("stem", ""), message)
                                                for q in p["draft"].get("questions", []))]
        if len(matched) == 1:
            return matched[0], None, "committed"
        return None, "当前有多份已确认的题库方案，请说明你要核对哪一份；没有重复写入。", "ambiguous"
    if proposals:
        return None, "当前题库预览已取消、过期或失效，不能确认。请重新检索题目；没有写入今日卷。", "stale"
    return None, "当前没有可确认的有效题库选题预览。请先从题库检索并查看候选题；没有写入今日卷。", "missing"


def _bank_commit_matches_preview(factory, task_view, proposal):
    receipt = (task_view.metrics or {}).get("commit") or {}
    if not receipt or receipt.get("added_count") != len(proposal["draft"].get("questions", [])):
        return False
    plan_id = receipt.get("plan_id")
    expected = {str(q["question_id"]): str(q["question_version"]) for q in proposal["draft"].get("questions", [])}
    if not plan_id or not expected:
        return False
    with factory() as db:
        items = db.scalars(select(PracticeItem).where(
            PracticeItem.plan_id == UUID(plan_id),
            PracticeItem.question_id.in_([UUID(qid) for qid in expected]),
        )).all()
        actual = {str(item.question_id): str(item.question_version_id) for item in items}
        counts = {qid: sum(1 for item in items if str(item.question_id) == qid) for qid in expected}
    return actual == expected and all(count == 1 for count in counts.values())


async def assistant_stream(factory,*,request,session_id,body,stack,provider,now=None,web_search_provider=None):
    now=now or datetime.now(timezone.utc)
    phase = "begin_turn"
    try:
        ctx,message_id,user_id,replay=begin_turn(factory,session_id=session_id,body=body,now=now)
    except AppError as exc:
        if exc.code in {"personal_generation_confirmation_invalid", "study_session_expired"}:
            expire_invalid_confirmation(factory, session_id, body)
        yield encode_sse("error",{"code":exc.code,"message":exc.message,"retryable":exc.retryable is not False}); return
    except Exception as exc:
        logger.error("assistant_turn_failed session_id=%s request_key=%s diagnostic=%s",
                     session_id, body.request_key, json.dumps(_safe_failure_details(exc, phase)))
        yield encode_sse("error", {"code": "internal_error", "message": AppError("internal_error").message,
                                  "retryable": True})
        return
    if replay:
        with factory() as db:
            saved=db.get(ChatMessage,message_id); text=saved.content; meta=dict(saved.metadata_ or {})
            pairs=[(c.label,c.chunk_id) for c in db.scalars(select(MessageCitation).where(MessageCitation.message_id==message_id).order_by(MessageCitation.ordinal))]
        cards=citation_payloads(factory,pairs)
        yield encode_sse("meta",{"message_id":str(message_id),"replayed":True})
        yield encode_sse("delta",{"seq":1,"text":text})
        if meta.get("planner_task_id"): yield encode_sse("planner",get_task(factory,UUID(meta["planner_task_id"])).model_dump(mode="json"))
        if meta.get("personal_generation"): yield encode_sse("personal_generation", meta["personal_generation"])
        if meta.get("personal_generation_confirmation") and meta.get("personal_generation_confirmation_status") not in {"cancelled", "superseded", "expired"}:
            yield encode_sse("personal_generation_confirmation", meta["personal_generation_confirmation"])
        if meta.get("personal_training"):
            yield encode_sse("personal_training", meta["personal_training"])
        yield encode_sse("citations",{"citations":cards})
        yield encode_sse("done",{"message_id":str(message_id),"answer":text,"citations":cards,"status":"completed"})
        return
    with factory() as db:
        session=db.get(ChatSession,session_id);mode=session.mode;purpose=session.purpose
        metadata = db.get(ChatMessage, message_id).metadata_ or {}
        generation_context = metadata.get("generation_context")
        confirmation_notice = metadata.get('generation_confirmation_notice')
    # Explicit independent-training commands use the session-bound training
    # service directly. They are checked before general QA/planner routing so
    # a training request cannot become a daily-paper edit.
    if (mode == "builtin" and purpose in {"qa", "study"}
            and not body.personal_generation_confirmation_message_id and not confirmation_notice):
        from backend.services.personal_training_chat import (
            execute_personal_training_command, parse_training_command,
        )
        # “给刚才第 N 道出一道变式”只生成这道题的变式，不创建专项训练。
        variant_reference = None
        if (re.search(r'变式|新编', body.question)
                and re.search(r'刚才|上面|上一|第\s*[一二两三四五六七八九十\d]+\s*道', body.question)
                and not re.search(r'换一(?:道|个)|换道', body.question)):
            from backend.services.practice_preview_reference import latest_preview
            variant_reference, _variant_error = latest_preview(factory, ctx.conversation_id, body.question, now)
        training_command = None if variant_reference else parse_training_command(body.question)
        if variant_reference:
            with factory() as _db:
                original = _db.get(Question, UUID(str(variant_reference["question_id"])))
                if original is not None:
                    generation_context = {"reference_text": original.stem,
                        "reference_question_id": variant_reference["question_id"],
                        "reference_question_version": variant_reference.get("question_version")}
                    route = CapabilityRoute('generation','generate',1,'explicit_variant_of_preview',write_risk=True)
        if training_command is not None:
            route = CapabilityRoute("personal_training", training_command.action, 1,
                "explicit_personal_training_command", write_risk=training_command.action not in {"list", "status", "mistakes"})
            try:
                result = await asyncio.to_thread(execute_personal_training_command, factory,
                    owner_session_id=session_id, message_id=message_id, text=body.question,
                    now=now, provider=provider, context=ctx)
            except Exception as exc:
                logger.error("personal_training_chat_failed session_id=%s message_id=%s action=%s exception_type=%s",
                    session_id, message_id, training_command.action, type(exc).__name__)
                result = {"action": training_command.action, "status": "failed",
                    "owner_session_id": str(session_id),
                    "summary": "专项操作暂时失败；今日正式卷保持不变。请刷新专项状态后重试。"}
            if result is not None:
                model_called = bool((result.get("generation") or {}).get("model_calls", 0))
                generation_batch = (result.get("generation") or {}).get("batch_id")
                writes = (training_command.action not in {"list", "status", "mistakes"}
                    and (result.get("status") != "failed" or bool(generation_batch)))
                persist_route(factory, message_id, route, {"model_called": model_called, "writes": writes,
                    "personal_training_action": result.get("action"),
                    "personal_training_id": result.get("training_id"),
                    "personal_training_error_code": result.get("error_code")})
                event_data = {key: result.get(key) for key in (
                    "action", "status", "summary", "error_code", "owner_session_id", "training_id", "item_count",
                    "completed_count", "actual_minutes", "target_minutes", "trainings", "wrong_items",
                    "generation_status")
                    if key in result}
                if result.get("generation"):
                    gen = result["generation"]
                    event_data["generation"] = {key: gen.get(key) for key in (
                        "batch_id", "status", "question_ids", "saved_items", "failures") if key in gen}
                answer_text = str(result.get("summary") or "专项操作已处理。")
                with factory.begin() as db:
                    row = db.get(ChatMessage, message_id)
                    row.content = answer_text
                    row.status = "completed"
                    row.metadata_ = {**(row.metadata_ or {}), "answer_source": "business_data",
                        "personal_training": event_data, "model_called": model_called,
                        "writes": writes, "training_data_scope": "session_bound_personal_training"}
                    if result.get("generation"):
                        row.metadata_["personal_generation"] = result["generation"]
                yield encode_sse("meta", {"message_id": str(message_id), "capability": "personal_training",
                    "intent": training_command.action, "model_called": model_called})
                yield encode_sse("route", route.public_dict())
                if result.get("generation"):
                    yield encode_sse("personal_generation", result["generation"])
                yield encode_sse("personal_training", event_data)
                yield encode_sse("delta", {"seq": 1, "text": answer_text})
                yield encode_sse("citations", {"citations": []})
                yield encode_sse("done", {"message_id": str(message_id), "answer": answer_text,
                    "citations": [], "status": "completed"})
                return
    if confirmation_notice:
        with factory.begin() as db:
            row = db.get(ChatMessage, message_id); row.content = confirmation_notice; row.status = 'completed'
            row.metadata_ = {**row.metadata_, 'answer_source': 'notice', 'model_called': False}
        yield encode_sse('meta', {'message_id': str(message_id), 'capability': 'generation_confirmation'})
        yield encode_sse('delta', {'seq': 1, 'text': confirmation_notice})
        yield encode_sse('done', {'message_id': str(message_id), 'answer': confirmation_notice, 'citations': [], 'status': 'completed'})
        return
    from backend.services.exam_source_policy import requests_original_exam, ORIGINAL_EXAM_NOTICE
    if requests_original_exam(body.question):
        with factory.begin() as db:
            saved=db.get(ChatMessage,message_id)
            saved.content=ORIGINAL_EXAM_NOTICE; saved.status='completed'
            saved.metadata_={**(saved.metadata_ or {}),'answer_source':'notice','model_called':False,
                'source_policy':'no_original_exam_inventory','business_writes':False}
        yield encode_sse('meta',{'message_id':str(message_id),'capability':'source_clarification'})
        yield encode_sse('delta',{'seq':1,'text':ORIGINAL_EXAM_NOTICE})
        yield encode_sse('done',{'message_id':str(message_id),'answer':ORIGINAL_EXAM_NOTICE,'status':'completed','citations':[]})
        return
    # The persisted same-session task is authoritative when a client loses its
    # transient task pointer. Never scan another session or inherit committed work.
    from backend.services.assistant_scope_resolution import draft_revision, correction_target
    if not ctx.task_id and (draft_revision(body.question) or correction_target(body.question)):
        with factory() as db:
            candidates=db.scalars(select(LearningTask).where(LearningTask.session_id==session_id,
                LearningTask.status.in_(['ready','needs_info','failed','created']))
                .order_by(LearningTask.created_at.desc()).limit(20))
            prior=next((t for t in candidates if task_is_current(t,now) and not (t.metrics or {}).get('commit')),None)
            if prior:
                ctx=ctx.model_copy(update={'task_id':prior.id})
    # “生成/变式 + 类似题 + 加入今日卷”是 AI 生成后追加，不是题库选题确认。
    if (re.search(r'(?:生成|出一道|出题|新编|变式|再来一道|编一道)', body.question)
            and re.search(r'类似|相似|同类|同类型|变式|新题', body.question)):
        bank_confirmation = None
    else:
        bank_confirmation = _bank_confirmation_kind(body.question)
    # 跨轮“加入今日学习”：优先消费最近一轮真实生成的个人练习题（不重新生成、不查公共题库）。
    if (mode == "builtin" and re.search(r'加入|添加|放进|加到', body.question)
            and not re.search(r'生成一道|生成题|出一道|变式|新编|类似|相似', body.question)):
        with factory() as _db:
            recent_messages = list(_db.scalars(select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.role == "assistant"
            ).order_by(ChatMessage.seq.desc()).limit(8)))
            generated_ids: list[str] = []
            for message in recent_messages:
                ids = ((message.metadata_ or {}).get("personal_generation") or {}).get("question_ids") or []
                if ids:
                    generated_ids = [str(value) for value in ids]
                    break
        if generated_ids:
            from backend.services.personal_question_service import append_personal as _append_personal
            try:
                result = _append_personal(factory, question_ids=generated_ids[:1],
                                          plan_id=ctx.daily_plan_id, now=now)
                added = int(result.get("added") or 0)
                text = (f"已将刚才生成的 AI 练习题加入今日学习（本次新增 {added} 道）。"
                        if added else "这道 AI 练习题已在今日学习中，无需重复添加。")
            except Exception as exc:
                text = "加入今日学习未完成：" + str(exc)[:80]
        else:
            # 最近一次生成失败（未保存题目）时，明确说明原因，不再误报“没有题库预览”。
            with factory() as _db:
                recent_generation = None
                for message in list(_db.scalars(select(ChatMessage).where(
                    ChatMessage.session_id == session_id, ChatMessage.role == "assistant"
                ).order_by(ChatMessage.seq.desc()).limit(8))):
                    generation = (message.metadata_ or {}).get("personal_generation")
                    if generation:
                        recent_generation = generation
                        break
            if recent_generation and (recent_generation.get("status") == "failed"
                                      or not recent_generation.get("question_ids")):
                text = "刚才的题目没有通过校验（答案与独立验证不一致），因此尚未保存，暂时无法加入今日学习。"
            else:
                text = "没有找到刚才生成的题目记录，请先生成一道题，再加入今日学习。"
            with factory.begin() as db:
                saved = db.get(ChatMessage, message_id)
                saved.content = text
                saved.status = "completed"
                saved.metadata_ = {**saved.metadata_, "answer_source": "generated_append", "writes": True,
                                   "generated_question_ids": generated_ids}
            yield encode_sse("meta", {"message_id": str(message_id)})
            yield encode_sse("delta", {"seq": 1, "text": text})
            yield encode_sse("done", {"message_id": str(message_id), "answer": text, "citations": []})
            return
    # 相似题检索结果 → 批量加入今日学习（读取上一轮 similar_items，避免落入题库确认）。
    similar_append = bool(mode == "builtin" and re.search(r'添加|加入|加到|放进|放到', body.question)
        and re.search(r'类似|相似|其中|前\s*[一二两三四五六七八九十\d]+\s*道|第\s*[一二两三四五六七八九十\d]+\s*道|几道|两道|三道|全部|所有|剩下', body.question)
        and not re.search(r'专项|训练|变式|生成|换一(?:道|个)', body.question))
    if similar_append:
        with factory() as _db:
            recent = list(_db.scalars(select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.role == "assistant"
            ).order_by(ChatMessage.seq.desc()).limit(6)))
            prior = next((m for m in recent
                          if (m.metadata_ or {}).get("answer_source") == "similar_questions"), None)
            prior_items = ((prior.metadata_ or {}).get("similar_items") if prior else None) or []
        if not prior_items:
            text = '上一轮没有可用的相似题检索结果；请先问“题库有没有类似的题目”，再指定要加入的题。'
        else:
            from backend.models.learning import Question as _Question, PracticeItem as _PI
            from backend.services.question_admission import formal_use_allowed as _formal_ok
            from backend.services.practice_service import append_questions_to_plan as _append_questions
            with factory() as _db:
                plan = _db.get(DailyPlan, ctx.daily_plan_id) if ctx.daily_plan_id else None
                if plan is None:
                    plan = _db.scalar(select(DailyPlan).where(
                        DailyPlan.study_date == now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
                    ).order_by(DailyPlan.created_at.desc()).limit(1))
                if plan is None:
                    text = "当前没有今日学习计划，未添加题目。请先生成今日学习。"
                else:
                    existing = {str(qid) for qid in _db.scalars(select(_PI.question_id).where(_PI.plan_id == plan.id))}
                    candidates = [item for item in prior_items if not item.get("in_today")]
                    chinese = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
                    def _num(token: str) -> int:
                        return chinese.get(token, int(token) if token.isdigit() else 0)
                    ordinal_tokens = re.findall(r'第\s*([一二两三四五六七八九十\d]+)\s*道', body.question)
                    count_token = re.search(r'(?:前|其中|随便|任意)?\s*([一二两三四五六七八九十\d]+)\s*道', body.question)
                    if ordinal_tokens:
                        wanted = []
                        for token in ordinal_tokens:
                            idx = _num(token) - 1
                            if 0 <= idx < len(prior_items):
                                item = prior_items[idx]
                                if not item.get("in_today") and str(item.get("question_id")) not in existing:
                                    wanted.append(item)
                        chosen = wanted
                    elif re.search(r'所有|全部|剩下|其余', body.question):
                        chosen = candidates
                    else:
                        count = _num(count_token.group(1)) if count_token else 2
                        chosen = candidates[:max(1, count)]
                    picked = []
                    rejected = []
                    skipped = 0
                    for item in chosen:
                        if str(item.get("question_id")) in existing:
                            skipped += 1
                            continue
                        question = _db.get(_Question, UUID(str(item.get("question_id"))))
                        version_ok = bool(question and question.current_version_id)
                        if not question or not version_ok or not _formal_ok(question):
                            rejected.append(item.get("stem", "")[:24])
                            continue
                        picked.append(question.id)
                    added = 0
                    if picked:
                        ordinals = list(_db.scalars(select(_PI.ordinal).where(_PI.plan_id == plan.id)))
                        next_ordinal = (max(ordinals) if ordinals else 0) + 1
                        for qid in picked:
                            question = _db.get(_Question, qid)
                            if question is None:
                                continue
                            _db.add(_PI(plan_id=plan.id, question_id=question.id,
                                        question_version_id=question.current_version_id,
                                        kp_id=question.kp_id, ordinal=next_ordinal))
                            next_ordinal += 1
                            added += 1
                        _db.commit()
                    total = len(list(_db.scalars(select(_PI.id).where(_PI.plan_id == plan.id))))
            lines = [f"已从上一轮相似题检索结果加入 {added} 道到今日学习（当前共 {total} 道）。"]
            if skipped:
                lines.append(f"其中 {skipped} 道已在今日学习，无需重复添加。")
            if rejected:
                lines.append("未加入（版本或正式准入不满足）：" + "、".join(rejected) + "。")
            if not candidates:
                lines.append("上一轮候选题已全部在今日卷中，无需重复添加。")
            text = "\n".join(lines)
        with factory.begin() as db:
            saved = db.get(ChatMessage, message_id)
            saved.content = text
            saved.status = "completed"
            saved.metadata_ = {**saved.metadata_, "answer_source": "similar_append", "writes": True}
        yield encode_sse("meta", {"message_id": str(message_id)})
        yield encode_sse("delta", {"seq": 1, "text": text})
        yield encode_sse("done", {"message_id": str(message_id), "answer": text, "citations": []})
        return
    if bank_confirmation:
        proposals = _same_session_bank_proposals(factory, session_id, now)
        proposal, notice, resolution = _select_bank_confirmation(proposals, body.question)
        confirmation_route = CapabilityRoute("planner", "confirm", 1,
            f"bank_proposal_confirmation_{resolution}", write_risk=proposal is not None and resolution == "pending")
        if proposal is None:
            persist_route(factory, message_id, confirmation_route,
                {"model_called": False, "writes": False, "bank_confirmation_resolution": resolution})
            with factory.begin() as db:
                saved = db.get(ChatMessage, message_id)
                saved.content = notice or "没有可确认的题库预览。"
                saved.status = "completed"
                saved.metadata_ = {**saved.metadata_, "answer_source": "business_notice", "model_called": False,
                    "writes": False, "bank_confirmation_resolution": resolution}
            yield encode_sse("meta", {"message_id": str(message_id), "capability": "planner", "intent": "confirm"})
            yield encode_sse("route", confirmation_route.public_dict())
            yield encode_sse("delta", {"seq": 1, "text": notice or "没有可确认的题库预览。"})
            yield encode_sse("done", {"message_id": str(message_id), "answer": notice or "没有可确认的题库预览。",
                "status": "completed", "citations": []})
            return

        from backend.schemas.learning_task import ConfirmTask
        from backend.services.learning_task_service import confirm_task as commit_task
        was_committed = proposal["committed"]
        try:
            committed_task = commit_task(factory, proposal["task_id"],
                ConfirmTask(draft_version=proposal["draft_version"]), now=now, record_chat_message=False)
        except AppError as exc:
            failure_text = ("这份题库预览已发生变化或不再符合今日卷条件，未能加入。请重新检索并确认最新预览。"
                if exc.code in {"learning_task_conflict", "learning_task_stale_draft", "practice_request_conflict"}
                else "题库预览确认未完成；未报告为成功。请读取今日卷核对回执后再继续。")
            persist_route(factory, message_id, confirmation_route, {"planner_task_id": str(proposal["task_id"]),
                "model_called": False, "writes": False, "assistant_error_code": exc.code,
                "bank_confirmation_resolution": "rejected"})
            with factory.begin() as db:
                saved = db.get(ChatMessage, message_id)
                saved.content = failure_text; saved.status = "failed"
                saved.metadata_ = {**saved.metadata_, "assistant_error_code": exc.code,
                    "assistant_retryable": False, "model_called": False, "writes": False}
            yield encode_sse("meta", {"message_id": str(message_id), "capability": "planner", "intent": "confirm"})
            yield encode_sse("route", confirmation_route.public_dict())
            yield encode_sse("delta", {"seq": 1, "text": failure_text})
            yield encode_sse("error", {"message_id": str(message_id), "code": exc.code,
                "message": failure_text, "retryable": False})
            yield encode_sse("done", {"message_id": str(message_id), "answer": failure_text,
                "status": "failed", "citations": []})
            return

        if not _bank_commit_matches_preview(factory, committed_task, proposal):
            failure_text = "确认回执与题目预览的题目版本无法一致核对，当前不能报告入卷成功。请读取今日卷状态；不会自动重试写入。"
            logger.error("bank_confirmation_readback_mismatch session_id=%s task_id=%s", session_id, proposal["task_id"])
            persist_route(factory, message_id, confirmation_route, {"planner_task_id": str(proposal["task_id"]),
                "model_called": False, "writes": True, "bank_confirmation_resolution": "readback_mismatch"})
            with factory.begin() as db:
                saved = db.get(ChatMessage, message_id); saved.content = failure_text; saved.status = "failed"
                saved.metadata_ = {**saved.metadata_, "assistant_error_code": "bank_confirmation_readback_mismatch",
                    "assistant_retryable": False, "model_called": False, "writes": True}
            yield encode_sse("meta", {"message_id": str(message_id), "capability": "planner", "intent": "confirm"})
            yield encode_sse("route", confirmation_route.public_dict())
            yield encode_sse("planner", committed_task.model_dump(mode="json"))
            yield encode_sse("delta", {"seq": 1, "text": failure_text})
            yield encode_sse("error", {"message_id": str(message_id), "code": "bank_confirmation_readback_mismatch",
                "message": failure_text, "retryable": False})
            yield encode_sse("done", {"message_id": str(message_id), "answer": failure_text,
                "status": "failed", "citations": []})
            return

        confirmed = ("这份题库预览已经加入今日卷；这次重复确认没有新增题目。"
            if was_committed else committed_task.message)
        persist_route(factory, message_id, confirmation_route, {"planner_task_id": str(proposal["task_id"]),
            "model_called": False, "writes": not was_committed, "bank_confirmation_resolution": "confirmed",
            "bank_confirmation_receipt": (committed_task.metrics or {}).get("commit")})
        with factory.begin() as db:
            saved = db.get(ChatMessage, message_id); saved.content = confirmed; saved.status = "completed"
            saved.metadata_ = {**saved.metadata_, "answer_source": "business_confirmation", "model_called": False,
                "writes": not was_committed, "bank_confirmation_resolution": "confirmed"}
        yield encode_sse("meta", {"message_id": str(message_id), "capability": "planner", "intent": "confirm"})
        yield encode_sse("route", confirmation_route.public_dict())
        yield encode_sse("planner", committed_task.model_dump(mode="json"))
        yield encode_sse("delta", {"seq": 1, "text": confirmed})
        yield encode_sse("done", {"message_id": str(message_id), "answer": confirmed,
            "status": "completed", "citations": []})
        return
    task_summary=active_task(factory,ctx,now)
    # 规则优先：route_message 只在自身规则全部未命中时调用 classifier（LLM 兜底）。
    llm_intent_holder: dict = {}
    def _llm_classifier(_text, _context):
        from backend.services.intent_classifier import classify as _classify_intent
        route_enum, structured = _classify_intent(provider, _text, _context)
        if structured:
            llm_intent_holder["intent"] = structured
        return route_enum
    route=route_message(body.question,ctx,action=body.qa_action,task=task_summary,classifier=_llm_classifier)
    if llm_intent_holder:
        persist_route(factory,message_id,route,{"llm_intent": llm_intent_holder["intent"]})
    # 统一意图协调：把本轮的规则/上下文/LLM 结果收敛为一份最终意图（含有序任务）。
    try:
        from backend.services.intent_coordinator import resolve_intent as _resolve_intent
        _training_action = training_command.action if training_command else None
        _coordinator = _resolve_intent(
            body.question, training_action=_training_action,
            bank_confirmation=bool(bank_confirmation), similar_append=bool(similar_append),
            route=route, llm_intent=llm_intent_holder.get("intent"))
        persist_route(factory, message_id, route, {"intent_coordinator": _coordinator})
    except Exception:
        _coordinator = None
    # LLM 判定需要澄清时（缺参数/意图冲突），只询问，不执行任何写操作。
    if (llm_intent_holder.get("intent") or {}).get("needs_clarification"):
        reason = (llm_intent_holder["intent"].get("clarification_reason") or "请说明具体要调整的范围或数量。")
        text = "我需要先确认一下：" + reason
        with factory.begin() as db:
            saved = db.get(ChatMessage, message_id)
            saved.content = text
            saved.status = "completed"
            saved.metadata_ = {**saved.metadata_, "answer_source": "clarification", "writes": False}
        yield encode_sse("meta", {"message_id": str(message_id)})
        yield encode_sse("delta", {"seq": 1, "text": text})
        yield encode_sse("done", {"message_id": str(message_id), "answer": text, "citations": []})
        return
    # route_message 可能把“出一道变式”判为专项/计划；基于预览题的变式必须回到生成。
    if (purpose=="qa" and mode=="builtin"
            and re.search(r'变式|新编', body.question)
            and re.search(r'刚才|上面|上一|第\s*[一二两三四五六七八九十\d]+\s*道', body.question)
            and not re.search(r'换一(?:道|个)|换道', body.question)):
        from backend.services.practice_preview_reference import latest_preview
        variant_ref, _variant_error = latest_preview(factory, ctx.conversation_id, body.question, now)
        if variant_ref:
            with factory() as _db:
                variant_original = _db.get(Question, UUID(str(variant_ref["question_id"])))
                if variant_original is not None:
                    generation_context = {"reference_text": variant_original.stem,
                        "reference_question_id": variant_ref["question_id"],
                        "reference_question_version": variant_ref.get("question_version")}
                    route = CapabilityRoute('generation','generate',1,'explicit_variant_of_preview',write_risk=True)
    from backend.services.bank_selection_intent import ambiguous_question_source
    if (body.qa_action == 'auto' and not body.personal_generation_confirmation_message_id
            and not metadata.get('generation_followup_authorized') and ambiguous_question_source(body.question)):
        route=CapabilityRoute('qa','qa',1,'question_source_clarification')
        persist_route(factory,message_id,route,{'model_called':False,'writes':False})
        notice='你希望从现有题库查找，还是明确要求新编一道题？请说明题目来源；本次没有生成或加入今日卷。'
        with factory.begin() as db:
            saved=db.get(ChatMessage,message_id);saved.content=notice;saved.status='completed'
        yield encode_sse('route',route.public_dict())
        yield encode_sse('delta',{'seq':1,'text':notice})
        yield encode_sse('done',{'message_id':str(message_id),'answer':notice,'status':'completed','citations':[]})
        return
    if (mode == 'builtin' and body.qa_action == 'auto' and
            ((metadata.get('generation_followup_authorized') and ambiguous_question_source(body.question))
             or (body.personal_generation_confirmation_message_id and generation_context))):
        # begin_turn has already validated this card's session, source turn,
        # scope and status. A bank-source request has no generation_context.
        route=CapabilityRoute('generation','generate',1,'authorized_generation_followup')
    from backend.services.personal_generation_intent import explicitly_generate
    from backend.services.assistant_data_queries import (
        classify_session_data_query, execute_read_only_data_query,
        persist_generated_question_refs, resolve_question_reference,
    )
    # 确认轮 body 不再携带生成上下文；从服务器签发的确认卡恢复原题引用，
    # 否则会退化为普通 QA 讲解（确认卡校验通过但没生成）。
    if body.personal_generation_confirmation_message_id and not generation_context:
        with factory() as _db:
            _card = _db.get(ChatMessage, body.personal_generation_confirmation_message_id)
            _card_meta = (_card.metadata_ or {}) if _card else {}
        _conf = _card_meta.get("personal_generation_confirmation") or {}
        if _conf.get("reference_text"):
            generation_context = {"reference_text": _conf["reference_text"],
                "reference_question_id": _conf.get("reference_question_id")}
    generation_requested = explicitly_generate(body.question)
    # Capability questions often mention examples of business operations
    # (e.g. "can you inspect my bank or make a plan?"). Those examples are not
    # an authorization to execute a query. The route-level meta intent must
    # remain authoritative for this turn; a later classifier may only resolve
    # data requests after the user actually asks for one in a follow-up turn.
    data_query_type = (route.intent if route.capability == 'data_query' else
        classify_session_data_query(factory, session_id=session_id, message=body.question,now=now)
        if _may_classify_data_query(route, qa_action=body.qa_action,
            generation_requested=generation_requested) else None)
    generation_continuation = bool(generation_context and any(generation_context.get(key) for key in
        ("waiting_reference", "reference_text", "reference_candidates", "override_difficulty", "override_type")))
    if _may_continue_generation(route, mode=mode, qa_action=body.qa_action,
        generation_requested=generation_requested, generation_continuation=generation_continuation):
        route=CapabilityRoute("generation","generate",1,"explicit_new_question_request")
    from backend.services.assistant_router import post_graduation_review_query
    review_query=mode=='builtin' and body.qa_action=='auto' and post_graduation_review_query(body.question)
    if review_query:route=CapabilityRoute('qa','post_graduation_review',1,'deterministic_review_evidence')
    reference_question = None
    reference_source = None
    reference_status = "not_requested"
    question_reference_request = _requests_question_reference(
        body.question, has_current_question=bool(ctx.question_id))
    if (body.qa_action == "auto" and route.capability != "generation"
            and not review_query and not data_query_type
            and (question_reference_request or question_relevant(body.question,body.qa_action)
                or route.reason=='add_recent_wrong_item')):
        reference_question, reference_source, reference_status = resolve_question_reference(
            factory, session_id=session_id, ctx=ctx, message=body.question)
        if reference_status == "ambiguous_same_session_generation":
            question_reference_request = _requests_question_reference(
                body.question, has_current_question=True)
        if reference_question and reference_source:
            is_generated_ref = reference_source.get("kind") == "same_session_generation"
            updates = {"question_id": reference_question.id,
                "question_version_id": UUID(reference_source["question_version_id"]),
                "knowledge_node_ids": [reference_question.kp_id]}
            if is_generated_ref:
                # A generated preview is not a PracticeItem; do not leave the
                # previously active item's plan/attempt identifiers attached.
                updates.update(practice_item_id=None, attempt_id=None, daily_plan_id=None)
            ctx = ctx.model_copy(update=updates)
            with factory.begin() as db:
                reply = db.get(ChatMessage, message_id)
                if reply is not None:
                    reply.metadata_ = {**(reply.metadata_ or {}),
                        "study_context": ctx.model_dump(mode="json"),
                        "question_reference": reference_source,
                        "question_reference_status": reference_status}
            if is_generated_ref:
                body.current_work = None
    if mode == "builtin" and re.search(r'还有几道|还有几题|继续看|继续展示|剩下的', body.question):
        with factory() as _db:
            recent_assistant = list(_db.scalars(select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.role == "assistant"
            ).order_by(ChatMessage.seq.desc()).limit(6)))
            prior = next((m for m in recent_assistant
                          if (m.metadata_ or {}).get("answer_source") == "similar_questions"), None)
            prior_items = ((prior.metadata_ or {}).get("similar_items") if prior else None) or []
        if prior_items:
            remaining = prior_items[5:]
            if not remaining:
                text = f"上一轮检索到 {len(prior_items)} 道相似题，已展示前 5 道，没有更多未展示题目。"
            else:
                lines = [f"沿用上一轮检索结果：共 {len(prior_items)} 道，前 5 道已展示，以下是剩余 {len(remaining)} 道："]
                for item in remaining:
                    lines.append(f"\n· {item['stem']}…\n  原因：{'、'.join(item['reasons'])}；今日卷：{'已在' if item['in_today'] else '可新增'}。")
                text = "\n".join(lines)
            with factory.begin() as db:
                saved = db.get(ChatMessage, message_id)
                saved.content = text
                saved.status = "completed"
                saved.metadata_ = {**saved.metadata_, "answer_source": "similar_questions_continue", "writes": False}
            yield encode_sse("meta", {"message_id": str(message_id)})
            yield encode_sse("delta", {"seq": 1, "text": text})
            yield encode_sse("done", {"message_id": str(message_id), "answer": text, "citations": []})
            return
    if data_query_type == "similar" and mode == "builtin":
        from backend.models.learning import KnowledgePoint as _KP, QuestionVersion as _QV, PracticeItem as _PI
        from backend.services.question_admission import formal_use_allowed
        with factory() as _db:
            original_version = _db.get(_QV, ctx.question_version_id) if ctx.question_version_id else None
            original = _db.get(Question, ctx.question_id) if ctx.question_id else None
            if original_version is None or original is None:
                text = ('要按“类似题”检索，需要先有参考原题。请先打开一道题，或告诉我参考哪一道；'
                        '本次没有返回库存统计，也没有创建计划。')
            else:
                node = _db.get(_KP, original.kp_id) if original.kp_id else None
                rows = _db.execute(
                    select(Question, _QV).join(_QV, _QV.id == Question.current_version_id)
                    .where(Question.kp_id == original.kp_id, Question.id != original.id,
                           Question.bank_scope == original.bank_scope)
                    .order_by(Question.updated_at.desc()).limit(60)).all()
                today_ids = set()
                today_plan = _db.scalar(select(DailyPlan).where(
                    DailyPlan.study_date == now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
                ).order_by(DailyPlan.created_at.desc()).limit(1))
                if today_plan is not None:
                    today_ids = {str(qid) for qid in _db.scalars(select(_PI.question_id).where(_PI.plan_id == today_plan.id))}
                items = []
                for candidate, version in rows:
                    if not formal_use_allowed(candidate):
                        continue
                    reasons = []
                    if candidate.question_type == original.question_type:
                        reasons.append("题型相同")
                    if str(candidate.difficulty) == str(original.difficulty):
                        reasons.append("难度接近")
                    if not reasons:
                        reasons.append("同知识点")
                    items.append({"question_id": str(candidate.id), "version_id": str(version.id),
                                  "stem": (version.stem or candidate.stem or "")[:90], "reasons": reasons,
                                  "in_today": str(candidate.id) in today_ids})
                similar = [item for item in items if item["reasons"] and set(item["reasons"]) - {"同知识点"}]
                same_kp_only = [item for item in items if item["reasons"] == ["同知识点"]]
                new_items = [item for item in items if not item["in_today"]]
                if not items:
                    text = f"没有找到与当前题「{(node.name if node else '当前知识点')}」同知识点且通过正式准入的其他题目；本次没有返回库存统计。"
                else:
                    label = "相关题" if similar else "同知识点练习"
                    lines = [f"以当前题（{node.name if node else '当前知识点'}）为参考，找到 {len(items)} 道{label}："]
                    if similar:
                        lines.append(f"- {len(similar)} 道在题型或难度上接近；")
                    if same_kp_only:
                        lines.append(f"- {len(same_kp_only)} 道仅同知识点；")
                    lines.append(f"其中 {len(new_items)} 道可新增，{len(items) - len(new_items)} 道已在今日卷。")
                    for item in items[:5]:
                        lines.append(f"\n· {item['stem']}…\n  知识点：{node.name if node else '当前知识点'}；原因：{'、'.join(item['reasons'])}；"
                                     f"今日卷：{'已在' if item['in_today'] else '可新增'}；准入：正式可用。")
                    text = "\n".join(lines)
        with factory.begin() as db:
            saved = db.get(ChatMessage, message_id)
            saved.content = text
            saved.status = "completed"
            saved.metadata_ = {**saved.metadata_, "answer_source": "similar_questions",
                               "similar_reference_question_id": str(ctx.question_id),
                               "similar_reference_version_id": str(ctx.question_version_id),
                               "similar_items": items, "writes": False}
        yield encode_sse("meta", {"message_id": str(message_id)})
        yield encode_sse("delta", {"seq": 1, "text": text})
        yield encode_sse("done", {"message_id": str(message_id), "answer": text, "citations": []})
        return
    if data_query_type:
        route=CapabilityRoute("data_query", data_query_type, 1, "explicit_read_only_business_data_query",
            explanation_request=route.explanation_request)
    elif mode=="user": route=CapabilityRoute("qa","qa",1,"user_material_qa_scope")
    if purpose=='qa' and mode=='builtin' and re.search(r'^(?:我)?(?:不想|不要|不用|不需要|别)[^，,；;。]{0,12}(?:练习|练题|补题|安排|找题)',body.question) and not re.search(r'[，,；;].*(?:先练|想练|补.{0,4}道|安排.{0,6}道)',body.question):
        route=CapabilityRoute('qa','qa',1,'user_declined_practice')
    unsupported_formal=purpose=="qa" and mode=="builtin" and route.capability=="planner" and route.intent=="modify"
    practice_draft=purpose=="qa" and mode=="builtin" and route.capability=="planner" and route.intent in {"plan","recommend"}
    # “把刚才第 N 道换一道”是替换预览目标题，不是生成变式。
    if (purpose=="qa" and mode=="builtin"
            and re.search(r'换一(?:道|个)|换道', body.question)
            and re.search(r'刚才|上面|上一|第\s*[一二两三四五六七八九十\d]+\s*道', body.question)
            and not re.search(r'变式|新编|生成', body.question)):
        generation_context=None
        route=CapabilityRoute('planner','plan',1,'replace_preview',write_risk=False)
        practice_draft=True
        practice_route=route
    # “给刚才第 N 道出一道变式”是基于指定原题生成，不是学习计划。
    if (purpose=="qa" and mode=="builtin"
            and re.search(r'变式|新编|生成.{0,4}(?:类似|相似)|类似的?题|相似的?题', body.question)
            and (re.search(r'刚才|上面|上一|第\s*[一二两三四五六七八九十\d]+\s*道|当前|这道|这题', body.question)
                 or (ctx.question_id and ctx.question_version_id))
            and not re.search(r'换一(?:道|个)|换道', body.question)):
        from backend.services.practice_preview_reference import latest_preview
        reference, _error = latest_preview(factory, ctx.conversation_id, body.question, now)
        if reference is None and ctx.question_id and ctx.question_version_id:
            reference = {"question_id": str(ctx.question_id),
                         "question_version": str(ctx.question_version_id)}
        if reference:
            with factory() as _db:
                original = _db.get(Question, UUID(str(reference["question_id"])))
                original_text = original.stem if original else None
            if original_text:
                generation_context = {"reference_text": original_text,
                    "reference_question_id": reference["question_id"],
                    "reference_question_version": reference.get("question_version")}
                route = CapabilityRoute('generation','generate',1,'explicit_variant_of_preview',write_risk=True)
                practice_draft = False
                practice_route = route
    if not practice_draft and purpose=="qa" and mode=="builtin" and re.search(
            r'\d+\s*(?:分钟|小时)|题量|复盘|缩短|增加|减少|多一点|少一点|积分|极限|线代|高数', body.question):
        from backend.models.practice_request import PracticeRequest
        with factory() as _db:
            pending=_db.scalar(select(PracticeRequest).where(
                PracticeRequest.source_conversation_id==ctx.conversation_id,
                PracticeRequest.status.in_(['draft','proposed','planning'])
            ).order_by(PracticeRequest.created_at.desc()).limit(1))
        if pending is not None:
            practice_draft=True
            practice_route=CapabilityRoute('planner','plan',1,'study_plan_refinement')
    formal_inventory=purpose=="qa" and mode=="builtin" and route.capability=="planner" and route.intent=="query"
    practice_route=route
    if practice_draft:route=CapabilityRoute("qa","practice_request",1,"explicit_user_practice_request",explanation_request=route.explanation_request)
    elif formal_inventory:route=CapabilityRoute("qa","inventory",1,"read_only_inventory_qa")
    elif unsupported_formal:route=CapabilityRoute("qa","qa",1,"unsupported_existing_plan_operation")
    persist_route(factory,message_id,route)
    yield encode_sse("route",route.public_dict())
    phase = "route_execution"
    try:
        if data_query_type:
            phase = "read_only_data_query"
            result = execute_read_only_data_query(factory, session_id=session_id, ctx=ctx,
                message=body.question, query_type=data_query_type, now=now)
            text = result["answer"]
            if data_query_type=='scope_correction' and task_summary and not task_summary['committed']:
                from backend.services.learning_task_service import cancel_task
                withdrawn=cancel_task(factory,ctx.task_id)
                result['evidence']['withdrawn_preview_task_id']=str(withdrawn.task_id)
                result['evidence']['preview_state_changed']=True
                text+=' 上一份未确认草案已撤回，不能继续确认旧范围；原今日卷保持不变。'
                persist_route(factory,message_id,route,{'planner_task_id':str(withdrawn.task_id)})
                yield encode_sse('planner',withdrawn.model_dump(mode='json'))
            lesson_trace = []
            if route.explanation_request:
                tools = TaskTools(factory, budget_minutes=90, now=now, goal=body.question)
                lessons = []
                for node_id in result['evidence'].get('scope_node_ids', [])[:8]:
                    lesson = tools.execute('read_lesson', {'kp_id': node_id})
                    lesson_trace.append({'tool': 'read_lesson', 'kp_id': node_id,
                        'available': bool(lesson.get('available'))})
                    if lesson.get('available'):
                        lessons.append('系统节点讲解 · '+lesson['name']+'\n\n'+lesson['markdown'])
                text = ('\n\n'.join(lessons) or '本次未取得该知识点的系统讲义，不能声称已读取讲解。') + '\n\n## 题库只读预览\n\n' + text
            with factory.begin() as db:
                row = db.get(ChatMessage, message_id)
                row.content = text; row.status = "completed"
                row.metadata_ = {**row.metadata_, "answer_source": "business_data",
                    "qa_information_route": "business_data", "read_only_data_query": result["evidence"],
                    "model_called": False, "writes": bool(result['evidence'].get('preview_state_changed'))}
                if route.explanation_request:
                    row.metadata_ = {**row.metadata_, 'lesson_trace': lesson_trace,
                        'explanation_source': 'system_lesson' if any(t['available'] for t in lesson_trace) else 'unavailable'}
            yield encode_sse("meta", {"message_id": str(message_id), "capability": "data_query",
                "query_type": data_query_type, "model_called": False})
            yield encode_sse("information_source", {"source": "business_data"})
            yield encode_sse("delta", {"seq": 1, "text": text})
            yield encode_sse("citations", {"citations": []})
            yield encode_sse("done", {"message_id": str(message_id), "answer": text,
                "answer_source": "business_data", "citations": [], "status": "completed"})
            return
        if question_reference_request and not reference_question and reference_status in {
            "ambiguous_same_session_generation", "legacy_version_unavailable", "not_found"}:
            text = ("这个会话里最近生成了多道题，请说出知识点或题目序号，我再按对应版本讲解。"
                if reference_status == "ambiguous_same_session_generation" else
                "我没有在当前会话中找到这道题的可用版本。请重新打开对应题目，或把题干贴到这里；我不会猜用其他会话的题。")
            with factory.begin() as db:
                row = db.get(ChatMessage, message_id); row.content = text; row.status = "completed"
                row.metadata_ = {**row.metadata_, "answer_source": "notice", "model_called": False,
                    "question_reference_status": reference_status}
            yield encode_sse("meta", {"message_id": str(message_id), "capability": "question_reference"})
            yield encode_sse("delta", {"seq": 1, "text": text})
            yield encode_sse("citations", {"citations": []})
            yield encode_sse("done", {"message_id": str(message_id), "answer": text,
                "answer_source": "notice", "citations": [], "status": "completed"})
            return
        if review_query:
            from backend.services.post_graduation_service import list_review_needs,read_post_practice
            detail_query=bool(re.search(r'为什么|为何|这个|这项',body.question))
            with factory() as db:
                named=list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True),KnowledgePoint.is_assessable.is_(True))))
                named=[n for n in named if n.name in body.question or n.code in body.question]
                if detail_query or named:
                    nodes=named or [db.get(KnowledgePoint,k) for k in ctx.knowledge_node_ids]
                    facts=[{'kp_id':str(n.id),'name':n.name,'post_graduation':read_post_practice(db,n,now=now).model_dump(mode='json')} for n in nodes if n and n.is_assessable]
                    data={'nodes':facts,'total':len(facts),'truncated':False}
                else:data=list_review_needs(db,now=now)
            # Reuse actual read tools for suggestions; this does not execute a
            # model, create a draft or append questions.
            observed=TaskTools(factory,budget_minutes=90,now=now,goal='推荐已有题')
            observed.intent='recommend'
            for n in data['nodes']:
                if not n['post_graduation']['applicable']:continue
                k=UUID(n['kp_id']) if n.get('kp_id') else next((i for i in ctx.knowledge_node_ids),None)
                if not k:continue
                observed.nodes.add(k)
                observed.execute('get_learning_state',{'kp_ids':[str(k)]})
                stock=observed.execute('find_questions',{'kp_ids':[str(k)]})
                n['practice_options']={'additional_eligible_count':stock.get('additional_eligible_count'),
                    'preview':[{'question_id':q['question_id'],'question_type':q['question_type'],'bank_scope':q['question_trust']['bank_scope']}
                        for q in stock.get('questions',[]) if not q['in_today_plan']][:3]}
            text=(('请指定具体知识点名称或打开该知识点，再问我为什么提示复习。' if detail_query else '当前没有可报告的已毕业节点复习风险；这不证明所有知识点都已熟练。') if not data['nodes'] else
                '\n\n'.join(
                    (f"{n['name']}：该知识点已经正式毕业。毕业事实不会因后续复习答错或近期没有练习而撤销。\n"
                     "以下仅是毕业后复习状态，近期表现与历史毕业证据不是同一概念；近期证据不足不等于毕业失效。\n"
                     "下面的次数仅统计毕业后的近期练习窗口；0次不代表历史上没有练习。\n"
                     if n['post_graduation']['applicable'] else f"{n['name']}：当前没有可确认的正式毕业事实。\n")
                    + f"毕业后复习状态：{n['post_graduation']['label']}。{n['post_graduation']['reason']}\n{n['post_graduation']['evidence_summary']}"
                    for n in data['nodes']))
            if data['truncated']:text+='\n这里只列出部分节点，不是完整列表。'
            for n in data['nodes']:
                options=n.get('practice_options') or {};count=options.get('additional_eligible_count')
                if count==0:text+=f"\n{n['name']}：当前卷外没有合格题可追加；可检查当前卷，或明确要求生成新题。"
                elif count is not None:text+=f"\n{n['name']}：有{count}道已有题可追加，优先换题复测，先提出方案再由你确认。"
            text+='\n可以让我提出复习方案，确认后加入今日学习；题量不足时不会自动出新题。'
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=text;row.status='completed'
                row.metadata_={**row.metadata_,'answer_source':'notice','post_graduation_review':data,'model_called':False}
            yield encode_sse('meta',{'message_id':str(message_id),'capability':'post_graduation_review'})
            yield encode_sse('delta',{'seq':1,'text':text});yield encode_sse('citations',{'citations':[]})
            yield encode_sse('done',{'message_id':str(message_id),'answer':text,'citations':[],'status':'completed'});return
        from backend.services.personal_generation_intent import explicitly_generate, generation_intent, generation_confirmation
        if mode == "builtin" and body.qa_action == "auto" and route.capability == "generation" and (generation_context or explicitly_generate(body.question)):
            phase = "generation_confirmation"
            from backend.services.personal_question_service import run_generation
            from backend.services.question_generation import (configured_provider, Budget, GENERATION_OUTPUT_LIMIT,
                PERSONAL_C6_OUTPUT_LIMIT, PERSONAL_C7_OUTPUT_LIMIT)
            if generation_context and generation_context.get("waiting_reference"):
                text = ("请指出要作为原题的那一道题，或直接贴出题干；我会保留刚才的出题要求。"
                    if generation_context.get("reference_ambiguous") else
                    "请把原题贴过来；我会沿用刚才的难度和题型要求，确认知识点后生成变式题。")
                with factory.begin() as db:
                    row = db.get(ChatMessage, message_id); row.content = text; row.status = "completed"
                    row.metadata_ = {**row.metadata_, "answer_source": "notice", "model_called": False}
                yield encode_sse("meta", {"message_id": str(message_id), "capability": "generation_reference_required"})
                yield encode_sse("delta", {"seq": 1, "text": text})
                yield encode_sse("done", {"message_id": str(message_id), "answer": text, "status": "completed"})
                return
            generation_text = (generation_context or {}).get("instruction", body.question)
            confirmed_node = body.personal_generation_confirmed_kp_id
            confirmed_targets = body.personal_generation_confirmed_targets
            with factory() as db:
                if confirmed_node is None and confirmed_targets is None:
                    # Reuse only a completed, explicitly confirmed scope in the
                    # same study location, and only when the current request
                    # resolves to that exact node. Never infer a new consent.
                    try:
                        proposed = generation_intent(db, generation_text, ctx, user_id,
                            generation_mode=body.personal_generation_mode)
                    except AppError:
                        proposed = None
                    if proposed and len({target.kp_id for target in proposed.targets}) == 1:
                        previous = list(db.scalars(select(ChatMessage).where(
                            ChatMessage.session_id == session_id, ChatMessage.role == "assistant",
                            ChatMessage.status == "completed").order_by(ChatMessage.seq.desc()).limit(20)))
                        for old in previous:
                            meta = old.metadata_ or {}
                            if (meta.get("personal_generation") and meta.get("personal_generation_confirmed_kp_id") == str(proposed.targets[0].kp_id)
                                    and _same_generation_context(meta.get("study_context") or {}, ctx)):
                                confirmed_node = proposed.targets[0].kp_id
                                break
                if confirmed_node is None and confirmed_targets is None:
                    preferred_kp = None
                    if (generation_context or {}).get("reference_question_id"):
                        try:
                            _ref_q = db.get(Question, UUID(str(generation_context["reference_question_id"])))
                            preferred_kp = _ref_q.kp_id if _ref_q else None
                        except (TypeError, ValueError):
                            preferred_kp = None
                    confirmation = generation_confirmation(db, generation_text, ctx, user_id,
                        generation_mode=body.personal_generation_mode, preferred_kp_id=preferred_kp)
                    confirmation["question"] = body.question
                    if (generation_context or {}).get("override_difficulty"):
                        confirmation["difficulty"] = generation_context["override_difficulty"]
                    if (generation_context or {}).get("reference_text"):
                        confirmation["message"] = "已收到原题和出题要求。确认所属知识点后生成，保存后由你决定是否加入今日学习。"
                        confirmation["reference_text"] = generation_context["reference_text"]
                        confirmation["reference_question_id"] = generation_context.get("reference_question_id")
                else:
                    confirmation = None
            if confirmation is not None:
                text = confirmation["message"]
                with factory.begin() as db:
                    row = db.get(ChatMessage, message_id); row.content = text; row.status = "completed"
                    row.metadata_ = {**row.metadata_, "personal_generation_confirmation": confirmation,
                        "answer_source": "notice", "model_called": False}
                yield encode_sse("meta", {"message_id": str(message_id), "capability": "generation_confirmation"})
                yield encode_sse("personal_generation_confirmation", confirmation)
                yield encode_sse("delta", {"seq": 1, "text": text})
                yield encode_sse("done", {"message_id": str(message_id), "answer": text, "citations": [], "status": "completed"})
                return
            phase = "generation_intent"
            with factory() as db:
                # Source user message ID stays stable on retry of a failed turn.
                generation_body = generation_intent(db, generation_text, ctx, user_id,
                    generation_mode=body.personal_generation_mode, confirmed_kp_id=confirmed_node,
                    confirmed_targets=confirmed_targets)
                if (generation_context or {}).get("reference_text"):
                    generation_body.reference_question_id = generation_context.get("reference_question_id")
                    generation_body.reference_text = generation_context["reference_text"]
                    generation_body.reference_source = generation_context.get("reference_source")
                    generation_body.user_requirement = generation_text
                    if not re.search(r"选择|单选|填空|计算题|证明题|大题|程序题|讨论题|算法题", generation_text):
                        source_type = generation_context.get("reference_question_type")
                        if source_type in {"single_choice", "fill_blank", "calculation", "proof", "subjective"}:
                            for target in generation_body.targets:
                                target.question_type = source_type
                from backend.services.generation_difficulty import gradient_requested
                for target in generation_body.targets:
                    if (generation_context or {}).get("override_difficulty") and not gradient_requested(generation_text):
                        target.difficulty = generation_context["override_difficulty"]
                    if (generation_context or {}).get("override_type"):
                        target.question_type = generation_context["override_type"]
                # 在配置Provider之前检查范围，不因不支持的节点消耗模型请求。
                from backend.services.personal_question_families import resolve_family, supports_difficulty
                for target in generation_body.targets:
                    node = db.get(KnowledgePoint, target.kp_id)
                    spec = resolve_family(node.code, target.question_type) if node else None
                    if node is None or not node.is_active or not node.is_assessable:
                        raise AppError("personal_generation_scope_required", status_code=422)
                    if generation_body.generation_mode != "ai_generated":
                        if spec is None: raise AppError("personal_generation_unsupported", status_code=422)
                        if not supports_difficulty(spec, target.difficulty): raise AppError("personal_generation_unsupported_difficulty", status_code=422)
            gen_provider = getattr(request.app.state, "personal_generation_provider", None)
            phase = "generation_provider_setup"
            if generation_body.generation_mode == "deterministic_fast":
                gen_provider = None
            elif gen_provider is None:
                output_limit = (PERSONAL_C7_OUTPUT_LIMIT if generation_body.generation_mode == "ai_generated" else
                    GENERATION_OUTPUT_LIMIT if generation_body.reference_question_id else PERSONAL_C6_OUTPUT_LIMIT)
                try: gen_provider = configured_provider(request.app.state.settings,
                        Budget(max_calls=5, max_output_tokens=output_limit), real_call_authorized=True)
                except ValueError as exc: raise AppError("llm_not_configured") from exc
            yield encode_sse("meta", {"message_id": str(message_id), "capability": "generation"})
            phase = "generation_service"
            pending = asyncio.create_task(asyncio.to_thread(run_generation, factory, generation_body, gen_provider, now=now))
            while not pending.done():
                await asyncio.wait({pending}, timeout=.5)
                if not pending.done(): yield encode_sse("status", {"message": "正在出题并检查题面、答案格式和可核验内容…"})
            generated = await pending
            if generated.get("question_ids"):
                persist_generated_question_refs(factory, message_id=message_id, generation=generated)
            phase = "generation_result_persist"
            text = generated["message"]
            generation_failed = generated.get("status") in {"failed", "running"}
            # 用户明确“生成并加入今日学习”：生成成功后走个人练习入口自动追加。
            if (not generation_failed and generated.get("question_ids")
                    and re.search(r'加入|放进|加到|放到', body.question)
                    and re.search(r'今日|今天|卷', body.question)):
                try:
                    from backend.services.personal_question_service import append_personal as _append_personal
                    appended = _append_personal(factory, question_ids=list(generated["question_ids"])[:1],
                                                plan_id=ctx.daily_plan_id, now=now)
                    added = int(appended.get("added") or 0)
                    text = text + (f"\n已按你的要求加入今日学习（本次新增 {added} 道）。"
                                   if added else "\n这道题已在今日学习中，无需重复添加。")
                    generated = {**generated, "appended_count": added}
                except Exception as exc:
                    text = text + "\n加入今日学习未完成：" + str(exc)[:60]
            with factory.begin() as db:
                row = db.get(ChatMessage, message_id); row.content = text
                row.status = "failed" if generation_failed else "completed"
                row.metadata_ = {**row.metadata_, "personal_generation": generated, "answer_source": "notice",
                    **({"assistant_error_code": "personal_generation_failed", "assistant_retryable": False}
                       if generation_failed else {})}
            yield encode_sse("personal_generation", generated)
            yield encode_sse("delta", {"seq":1, "text": text})
            if generation_failed:
                yield encode_sse("error", {"code": "personal_generation_failed", "message": text,
                    "retryable": False, "message_id": str(message_id),
                    "diagnostics": generated.get('diagnostics', [])})
                return
            yield encode_sse("citations", {"citations": []})
            yield encode_sse("done", {"message_id": str(message_id), "answer": text, "citations": [], "status": "completed"})
            return
        if route.intent=='practice_request_cancel':
            from backend.models.practice_request import PracticeRequest
            from backend.services.practice_request_service import decline_request
            with factory() as db:
                pending=db.scalar(select(PracticeRequest).where(PracticeRequest.source_conversation_id==session_id,
                    PracticeRequest.status.in_(['draft','pending','proposed','failed']))
                    .order_by(PracticeRequest.created_at.desc()).limit(1))
                pending_id=pending.id if pending else None
            if pending_id:
                decline_request(factory,pending_id,now=now)
                text='已撤回本会话最近一份尚未确认的练习需求。没有移除或改写已加入今日卷的题目。'
            else:text='本会话没有可撤回的待确认练习需求。已入卷题目保持不变。'
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=text;row.status='completed'
                row.metadata_={**row.metadata_,'answer_source':'notice','cancelled_practice_request_id':str(pending_id) if pending_id else None}
            yield encode_sse('meta',{'message_id':str(message_id)})
            yield encode_sse('delta',{'seq':1,'text':text})
            yield encode_sse('done',{'message_id':str(message_id),'answer':text,'status':'completed','citations':[]});return
        if unsupported_formal:
            text="当前只支持由奶蛙提出追加练习方案，再经你确认加入今日学习；不支持删除或替换原卷题目。没有修改已有试卷。"
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=text;row.status="completed";row.metadata_={**row.metadata_,"answer_source":"notice"}
            yield encode_sse("meta",{"message_id":str(message_id)});yield encode_sse("delta",{"seq":1,"text":text});yield encode_sse("citations",{"citations":[]});yield encode_sse("done",{"message_id":str(message_id),"answer":text,"citations":[]});return
        if practice_draft:
            from backend.services.practice_request_service import draft_request
            drafted=draft_request(factory,ctx=ctx,user_id=user_id,assistant_id=message_id,message=body.question,now=now,route=practice_route)
            if drafted.get('notice'):
                text=drafted['notice']
                with factory.begin() as db:
                    row=db.get(ChatMessage,message_id);row.content=text;row.status='completed'
                    row.metadata_={**row.metadata_,'answer_source':'notice','selection_trace':drafted.get('trace',[]),
                        'selection_error_code':drafted.get('error_code'),
                        'preview_antecedent_message_id':drafted.get('preview_antecedent_message_id'),
                        'selection_state':drafted.get('selection_state'),
                        'model_called':False,'writes':False}
                yield encode_sse('meta',{'message_id':str(message_id)})
                yield encode_sse('delta',{'seq':1,'text':text})
                yield encode_sse('done',{'message_id':str(message_id),'answer':text,'status':'completed','citations':[]})
                return
            text="可以把这个练习需求交给今日学习里的奶蛙，让它结合学习记录和真实题库提出方案。发送需求不会修改今日练习卷。" if drafted["details"].get("target_knowledge_node_ids") else "请补充具体知识点，我才能把明确的练习需求交给奶蛙。"
            details=drafted['details']
            if 'preview_status' in details:
                text=((details.get('explanation','')+'\n\n') if route.explanation_request else '')+details.get('preview_message','')+'\n\n尚未加入今日卷，题目预览与后续确认见下方。'
            elif details.get('plan_preview'):
                text=((details.get('explanation','')+'\n\n') if route.explanation_request else '')+details['plan_preview'].get('message','')
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=text;row.status="completed";row.metadata_={**row.metadata_,"answer_source":"notice"}
            yield encode_sse("meta",{"message_id":str(message_id)});yield encode_sse("delta",{"seq":1,"text":text})
            yield encode_sse("practice_request",drafted);yield encode_sse("citations",{"citations":[]})
            yield encode_sse("done",{"message_id":str(message_id),"answer":text,"citations":[],"status":"completed"});return
        if formal_inventory:
            from backend.schemas.learning_task import QuestionAvailabilityQuery
            handoff=planner_handoff(factory,ctx=ctx,user_id=user_id,message=body.question,route=CapabilityRoute("planner","query",1,"inventory"),now=now)
            tools=TaskTools(factory,budget_minutes=90,now=now,goal=body.question,handoff=handoff.model_dump(mode="json"))
            with factory() as db:stock=tools.get_question_availability(db,QuestionAvailabilityQuery())
            counts=stock.get("inventory_counts")
            text=(f"当前范围有 {stock['practice_eligible_count']} 道可练题。" if not counts else
                f"按当前排除条件，两科合计 {counts['question_count_total']} 道可练题、{counts['node_count_total']} 个有题节点。"+"；".join(f"{r['subject']}：{r['question_count']} 道题、{r['node_count']} 个节点" for r in counts['subject_totals'])+
                f"。返回 {counts['returned_node_count']} 条节点预览，"+("并非完整列表。" if counts['node_list_is_truncated'] else "未截断。"))
            if stock.get('eligible_nodes'):
                text+='\n\n有题节点预览：\n'+'\n'.join(f"- {n['name']}：{n['practice_eligible_count']} 道" for n in stock['eligible_nodes'])
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=text;row.status="completed";row.metadata_={**row.metadata_,"answer_source":"notice","qa_information_route":"inventory"}
            yield encode_sse("meta",{"message_id":str(message_id)});yield encode_sse("delta",{"seq":1,"text":text});yield encode_sse("citations",{"citations":[]});yield encode_sse("done",{"message_id":str(message_id),"answer":text,"citations":[]});return
        unavailable_lesson_lookup = None
        # A system lesson is a good direct answer for a plain concept question,
        # but it must not take ownership of a question-specific explanation or
        # an evidence question. Those need the bound QuestionVersion / learning
        # records assembled by the normal QA path below.
        lesson_only_request = (
            route.reason == 'explanation_without_selection'
            and (not ctx.question_id or bool(re.search(r'这个知识点|该知识点|当前知识点',body.question)))
            and reference_question is None
            and not question_relevant(body.question, body.qa_action)
            and not (body.qa_action in {None, 'auto'} and evidence_explanation(body.question))
        )
        if lesson_only_request:
            handoff=planner_handoff(factory,ctx=ctx,user_id=user_id,message=body.question,
                route=CapabilityRoute('planner','recommend',1,'lesson_scope_resolution_only'),now=now)
            if handoff.constraints.get('unresolved_topics'):
                text='无法匹配到知识点：'+'、'.join(handoff.constraints['unresolved_topics'])+'。请在知识树选择现有节点；没有用其他知识点替代讲解，也没有创建计划。'
                with factory.begin() as db:
                    saved=db.get(ChatMessage,message_id);saved.content=text;saved.status='completed'
                    saved.metadata_={**saved.metadata_,'model_called':False,'writes':False,'scope_resolution':handoff.constraints['scope_resolution']}
                yield encode_sse('delta',{'seq':1,'text':text})
                yield encode_sse('done',{'message_id':str(message_id),'answer':text,'status':'completed','citations':[]})
                return
            if not handoff.target_knowledge_node_ids or handoff.constraints.get('scope_origin')=='default_learning_scope':
                with factory() as db:
                    previous=db.scalar(select(ChatMessage).where(ChatMessage.session_id==session_id,
                        ChatMessage.role=='assistant',ChatMessage.status=='completed',ChatMessage.id!=message_id).order_by(ChatMessage.seq.desc()))
                    prior_ids=(((previous.metadata_ or {}).get('learning_trace') or {}).get('resolved_knowledge_node_ids',[]) if previous else [])
                    parsed=[]
                    for value in prior_ids[:8]:
                        try:parsed.append(UUID(value))
                        except (ValueError,TypeError):pass
                    ids=list(db.scalars(select(KnowledgePoint.id).where(KnowledgePoint.id.in_(parsed),KnowledgePoint.is_active.is_(True)))) if parsed else []
                handoff=handoff.model_copy(update={'target_knowledge_node_ids':ids,
                    'constraints':{**handoff.constraints,'scope_version':1,'resolved_scope_node_ids':[str(k) for k in ids],
                        'scope_origin':'same_session_latest_lesson'}})
            tools=TaskTools(factory,budget_minutes=handoff.available_minutes,now=now,goal=body.question,handoff=handoff.model_dump(mode='json'))
            if not handoff.target_knowledge_node_ids and re.search(r'这个知识点|该知识点|当前知识点',body.question):
                text='我还不能确定“这个知识点”指什么。请说出知识点名称，或在知识树中选择一个节点；没有用其他主题替代讲解，也没有创建计划。'
                with factory.begin() as db:
                    saved=db.get(ChatMessage,message_id);saved.content=text;saved.status='completed'
                    saved.metadata_={**saved.metadata_,'answer_source':'notice','model_called':False,
                        'writes':False,'scope_resolution_status':'needs_antecedent'}
                yield encode_sse('delta',{'seq':1,'text':text})
                yield encode_sse('done',{'message_id':str(message_id),'answer':text,'status':'completed','citations':[]})
                return
            lessons=[];trace=[]
            for node in handoff.target_knowledge_node_ids[:8]:
                result=tools.execute('read_lesson',{'kp_id':str(node)})
                if result.get('error'):raise AppError('learning_task_failed',detail='lesson_tool_not_available')
                trace.append({'tool':'read_lesson','kp_id':str(node),'available':result.get('available')})
                if result.get('available'):lessons.append('系统节点讲解 · '+result['name']+'\n\n'+result['markdown'])
            if lessons:
                text='\n\n'.join(lessons)
                metadata={
                    'answer_source':'system_lesson',
                    'model_called':False,
                    'lesson_trace':trace,
                    'study_context':ctx.model_dump(mode='json'),
                    'qa_action':body.qa_action,
                    'learning_trace':{'resolved_knowledge_node_ids':[str(k) for k in handoff.target_knowledge_node_ids]},
                }
                if ctx.task_id:
                    metadata['qa_handoff']=qa_handoff(
                        ctx, ctx.task_id, body.question, reason='requested_concept_help',
                        scope=handoff.target_knowledge_node_ids,
                    ).model_dump(mode='json')
                with factory.begin() as db:
                    row=db.get(ChatMessage,message_id);row.content=text;row.status='completed'
                    row.metadata_={**row.metadata_,**metadata}
                yield encode_sse('delta',{'seq':1,'text':text})
                yield encode_sse('done',{'message_id':str(message_id),'answer':text,'status':'completed','citations':[]});return
            # A missing local lesson is not a reason to refuse ordinary concept
            # QA. Preserve the lookup result, then let the normal QA path answer
            # from model knowledge with the existing source disclosure.
            unavailable_lesson_lookup={
                'status':'no_system_lesson_available',
                'trace':trace,
                'resolved_knowledge_node_ids':[str(k) for k in handoff.target_knowledge_node_ids],
            }
            persist_route(factory,message_id,route,{'system_lesson_lookup':unavailable_lesson_lookup})
        if route.capability=="planner" and route.reason == 'add_recent_wrong_item':
            if (reference_question is None or not reference_source
                    or reference_source.get('kind') != 'recent_wrong_attempt'):
                text = '我无法从这条消息的同会话作答证据定位具体错题，所以没有创建任务或改动今日卷。请回到对应题目的作答卡，或从“回看错题”打开后再提出加入。'
                with factory.begin() as db:
                    row = db.get(ChatMessage, message_id)
                    row.content = text; row.status = 'completed'
                    row.metadata_ = {**row.metadata_, 'answer_source': 'notice',
                        'recent_wrong_item_status': 'attempt_reference_unavailable',
                        'model_called': False, 'writes': False}
                yield encode_sse('meta', {'message_id': str(message_id), 'capability': 'recent_wrong_item'})
                yield encode_sse('delta', {'seq': 1, 'text': text})
                yield encode_sse('done', {'message_id': str(message_id), 'answer': text,
                    'status': 'completed', 'citations': []})
                return
            today = now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
            with factory() as db:
                current_plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == today))
                already_in_today = bool(current_plan and db.scalar(select(PracticeItem.id).where(
                    PracticeItem.plan_id == current_plan.id,
                    PracticeItem.question_id == reference_question.id,
                    PracticeItem.question_version_id == UUID(reference_source['question_version_id'])).limit(1)))
            if already_in_today:
                text = '这道错题对应的题目版本已经在今日卷中；我没有重复追加，也没有创建计划。请通过今日卷里的“错题重练”入口再次练习，原始作答会保留。'
                with factory.begin() as db:
                    row = db.get(ChatMessage, message_id)
                    row.content = text; row.status = 'completed'
                    row.metadata_ = {**row.metadata_, 'answer_source': 'notice',
                        'recent_wrong_item_status': 'already_in_today_plan',
                        'question_reference': reference_source, 'model_called': False, 'writes': False}
                yield encode_sse('meta', {'message_id': str(message_id), 'capability': 'recent_wrong_item'})
                yield encode_sse('delta', {'seq': 1, 'text': text})
                yield encode_sse('done', {'message_id': str(message_id), 'answer': text,
                    'status': 'completed', 'citations': []})
                return
        if route.capability=="planner":
            if route.reason=='active_draft_refinement' and not (task_summary and not task_summary['committed']
                    and task_summary['status'] in {'ready','needs_info','failed','created'}):
                notice='当前话题没有可修改的未确认草案。请先说明复习范围和预算以准备预览；没有新建或覆盖正式计划。'
                with factory.begin() as db:
                    saved=db.get(ChatMessage,message_id);saved.content=notice;saved.status='completed'
                yield encode_sse('delta',{'seq':1,'text':notice})
                yield encode_sse('done',{'message_id':str(message_id),'answer':notice,'status':'completed','citations':[]})
                return
            if route.reason=='study_activity_schedule' and explicit_minutes(body.question) is None and not (task_summary and task_summary.get('budget_explicit') and not task_summary.get('committed')):
                budget_notice='今天实际可用多少分钟？请给出本次复习时长，我再按现有题目和学习证据准备活动预览；没有创建任务或正式计划。'
                persist_route(factory,message_id,route)
                with factory.begin() as db:
                    reply=db.get(ChatMessage,message_id);reply.content=budget_notice;reply.status='completed'
                yield encode_sse('delta',{'seq':1,'text':budget_notice})
                yield encode_sse('done',{'message_id':str(message_id),'answer':budget_notice,'status':'completed','citations':[]})
                return
            handoff=planner_handoff(factory,ctx=ctx,user_id=user_id,message=body.question,route=route,now=now)
            if route.explanation_request:
                handoff=handoff.model_copy(update={'constraints':{**handoff.constraints,
                    'explanation_request':route.explanation_request}})
            if route.reason=='select_preview':
                from backend.services.practice_preview_reference import latest_preview
                selected,notice=latest_preview(factory,session_id,body.question,now)
                if notice:
                    with factory.begin() as db:
                        saved=db.get(ChatMessage,message_id);saved.content=notice;saved.status='completed'
                        saved.metadata_={**saved.metadata_,'model_called':False,'writes':False,'selection_error':'preview_reference_unavailable'}
                    yield encode_sse('delta',{'seq':1,'text':notice})
                    yield encode_sse('done',{'message_id':str(message_id),'answer':notice,'status':'completed','citations':[]})
                    return
                from backend.services.practice_preview_reference import preview_question_state
                current=preview_question_state(factory,selected,ctx,now)
                if current and current.get('state') in {'already_in_today_plan','stale_preview'}:
                    text=current['message']
                    with factory.begin() as db:
                        saved=db.get(ChatMessage,message_id);saved.content=text;saved.status='completed'
                        saved.metadata_={**saved.metadata_,'capability_route':route.public_dict(),
                            'answer_source':'notice','selection_state':current,'model_called':False,'writes':False,
                            'preview_antecedent_message_id':selected.get('source_message_id')}
                    yield encode_sse('meta',{'message_id':str(message_id),'capability':'planner',
                        'selection_state':current['state']})
                    yield encode_sse('delta',{'seq':1,'text':text})
                    yield encode_sse('done',{'message_id':str(message_id),'answer':text,
                        'status':'completed','citations':[]})
                    return
                handoff=handoff.model_copy(update={'target_knowledge_node_ids':[UUID(selected['kp_id'])],
                    'requested_question_count':1,'constraints':{**handoff.constraints,'existing_bank_only':True,
                    'scope_version':1,'resolved_scope_node_ids':[selected['kp_id']],'unresolved_topics':[],
                    'selected_question_refs':[selected],'preview_query_state':selected['query_state']}})
            if route.reason == 'add_recent_wrong_item' and reference_question is not None and reference_source:
                # Pin the immutable version resolved from the same-session wrong
                # attempt. The normal planner still validates eligibility and
                # requires the learner's explicit confirmation before commit.
                handoff.target_knowledge_node_ids = [reference_question.kp_id]
                handoff.requested_question_count = 1
                handoff.available_minutes = max(5, min(240, int(reference_question.estimated_minutes or 5)))
                handoff.subject = ctx.subject
                handoff.constraints = {**handoff.constraints,
                    'existing_bank_only': True,
                    'selected_question_refs': [{'question_id': str(reference_question.id),
                        'question_version': reference_source['question_version_id']}],
                    'recent_wrong_attempt_id': reference_source['attempt_id'],
                    'time_explicit': False}
            persist_route(factory,message_id,route,{"planner_handoff":handoff.model_dump(mode="json")})
            task=prepare_planner(factory,ctx=ctx,handoff=handoff,now=now)
            persist_route(factory,message_id,route,{"planner_task_id":str(task.task_id)})
            yield encode_sse("meta",{"message_id":str(message_id),"capability":"planner","task_id":str(task.task_id)})
            if route.explanation_request or route.reason == 'explicit_bank_selection':
                from backend.services.composite_bank_plan import prepare_explained_plan
                pending=asyncio.create_task(asyncio.to_thread(prepare_explained_plan,
                    factory,task.task_id,handoff=handoff,now=now))
            else:
                pending=asyncio.create_task(asyncio.to_thread(run_task,factory,task.task_id,provider,now=now))
            while not pending.done():
                await asyncio.wait({pending},timeout=.5)
                if not pending.done(): yield encode_sse("status",{"message":"正在查看学习记录与题库…"})
            result=await pending
            with factory.begin() as db:
                stored_task=db.get(LearningTask,result.task_id)
                request_link=(stored_task.context or {}).get("practice_request_id")
                if request_link:
                    from backend.models.practice_request import PracticeRequest
                    linked=db.get(PracticeRequest,UUID(request_link),with_for_update=True)
                    if linked and linked.status not in {"accepted","declined","expired"}:
                        linked.status="proposed" if result.status=="ready" and result.draft and result.draft.get('questions') else "failed"
                        linked.error_code=None if linked.status=="proposed" else result.error_code or "insufficient_practice_inventory"
                        linked.handled_at=now
            original=result.message
            visible=present_planner_message(original,result,ctx)
            if (route.intent=='recommend' and not handoff.constraints.get('time_explicit')
                    and not (task_summary and task_summary.get('budget_explicit'))):
                visible=f'你尚未指定本次可用时长；以下仅采用可调整的建议预算 {handoff.available_minutes} 分钟，并非你已确认的时间。\n\n'+visible
            if visible!=original:
                with factory.begin() as db:
                    row=db.get(LearningTask,task.task_id);row.message=visible
                    row.metrics={**row.metrics,"presentation_ids_removed":True,"raw_message_sha256":sha256(original.encode()).hexdigest()}
                result=get_task(factory,task.task_id)
            qh=qa_handoff(ctx,task.task_id,"先解释相关知识点",reason="optional_review_after_planning",scope=handoff.target_knowledge_node_ids)
            persist_route(factory,message_id,route,{"qa_handoff":qh.model_dump(mode="json")})
            with factory.begin() as db:
                reply=db.get(ChatMessage,message_id); reply.content=result.message; reply.status="failed" if result.status=="failed" else "completed"
                if result.status=='failed':
                    guarded=result.error_code in {'provider_dns_policy_blocked','provider_socket_policy_blocked','provider_authorization_revoked','provider_purpose_not_authorized',
                        'provider_proxy_policy_blocked','provider_transport_retry_blocked','provider_scene_not_authorized',
                        'provider_egress_closed','provider_request_policy_blocked','provider_budget_exhausted','provider_request_state_unknown','provider_auth_failed'}
                    reply.metadata_={**reply.metadata_,'assistant_error_code':result.error_code,
                        'assistant_retryable':not guarded,'model_failure':result.metrics.get('model_failure')}
            yield encode_sse("delta",{"seq":1,"text":result.message})
            yield encode_sse("planner",{**result.model_dump(mode="json"),"qa_handoff":qh.model_dump(mode="json")})
            if result.status=='failed':
                yield encode_sse('error',{'message_id':str(message_id),'code':result.error_code,
                    'message':('题库查询或方案校验未完成，节点讲解与原提问已保留；没有加入今日卷。' if route.explanation_request else result.message),'retryable':not guarded})
            yield encode_sse("citations",{"citations":[]})
            yield encode_sse("done",{"message_id":str(message_id),"answer":result.message,"status":"failed" if result.status=="failed" else "completed","citations":[]})
            return
        if ctx.task_id:
            if not ctx.knowledge_node_ids and not ctx.question_id:
                with factory() as db:
                    task=db.get(LearningTask,ctx.task_id)
                    ids=((task.context or {}).get("planner_handoff") or {}).get("target_knowledge_node_ids",[])
                    if ids:
                        ctx=validate_study_context(db,session_id=session_id,context=ctx.model_copy(update={"knowledge_node_ids":[UUID(k) for k in ids[:8]],"daily_plan_id":None,"practice_item_id":None}),now=now)
                persist_route(factory,message_id,route,{"study_context":ctx.model_dump(mode="json")})
            persist_route(factory,message_id,route,{"qa_handoff":qa_handoff(ctx,ctx.task_id,body.question).model_dump(mode="json")})
        action=assistance_action(body.question,explicit=body.qa_action,question_present=bool(ctx.question_id))
        persist_route(factory,message_id,route,{"qa_action":action or "auto"})
        learning={"study_context":ctx.model_dump(mode="json"),"action":action,"current_work":body.current_work,"server_time":now.isoformat()}
        if unavailable_lesson_lookup:
            learning['system_lesson_lookup']=unavailable_lesson_lookup
        from backend.services.qa_information_router import information_route
        info=information_route(body.question,ctx,private=mode=="user")
        if unavailable_lesson_lookup:
            # The requested node lesson was unavailable. Keep this turn on
            # general model knowledge so an unrelated active study scope or
            # stale retrieval result cannot masquerade as support for the new
            # concept question.
            info="general"
        if action and ctx.question_id and info=='general':info='current_question'
        learning["information_route"]=info
        persist_route(factory,message_id,route,{"qa_information_route":info})
        yield encode_sse("information_source",{"source":info})
        notice=None
        if info=="private_scope_required":notice="请到资料库打开对应的私人资料，再针对所选资料提问。这里不会自动搜索你上传的文件。"
        if info=="web":
            from backend.services.web_search_service import search_web
            web=search_web(body.question,provider=web_search_provider)
            if not web.available:notice="当前未配置联网搜索，不能核验最新政策或声称已上网查到。请提供官方来源，或在具备联网能力后再核查。"
            else:
                learning["web_sources"]=web.sources;persist_route(factory,message_id,route,{"web_sources":web.sources})
                yield encode_sse("web_sources",{"sources":web.sources})
        if not ctx.question_id and not ctx.knowledge_node_ids and not ctx.material_id and re.fullmatch(r"(?:帮我)?看看?这个[。？?]?",body.question.strip()):
            notice="可以，先告诉我想看哪道题、哪个知识点或哪份资料。"
        if ctx.question_id and body.qa_action=="auto" and answer_reliability_question(body.question):
            with factory() as db:
                if ctx.practice_item_id:
                    from backend.models.learning import PracticeItem
                    from backend.services.question_versions import question_for_practice_item
                    q=question_for_practice_item(db,db.get(PracticeItem,ctx.practice_item_id))
                else:
                    q=db.get(Question,ctx.question_id)
                if q.answer_provenance=="ai_generated": notice="这道题的参考答案由 AI 生成；多次核对一致也不等于官方或人工核验，不能保证一定正确。可以结合当前题面继续检查思路与适用条件。"
                else: notice="应以这道题实际的来源与核验记录为准；题库核验不等于官方发布，也不能保证每一步推导绝对正确。可以继续检查具体步骤。"
        if notice:
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=notice;row.status="completed"
                row.metadata_={**row.metadata_,"answer_source":"notice","learning_trace":{"prompt_version":PROMPT_VERSION,"study_context":ctx.model_dump(mode="json"),"model_called":False,"direct_notice":True},"generation_trace":{"request_id":str(message_id),"calls":[],"model_called":False}}
            yield encode_sse("meta",{"message_id":str(message_id),"capability":"qa"})
            yield encode_sse("delta",{"seq":1,"text":notice});yield encode_sse("citations",{"citations":[]})
            yield encode_sse("done",{"message_id":str(message_id),"answer":notice,"answer_source":"notice","citations":[]});return
        if stack is None and (mode=="user" or ctx.material_id): raise AppError("retrieval_unavailable")
        if action in {"hint_1","hint_2"}:
            with factory() as db:
                if ctx.practice_item_id:
                    from backend.models.learning import PracticeItem
                    from backend.services.question_versions import question_for_practice_item
                    q=question_for_practice_item(db,db.get(PracticeItem,ctx.practice_item_id))
                else:
                    q=db.get(Question,ctx.question_id)
            guarded={"blocked":False}
            def filter_hint(text):
                filtered,blocked=safe_hint(text,q,action); guarded["blocked"]=blocked
                with factory.begin() as db: record_qa_assistance(db,context=ctx,message_id=message_id,level=action,now=now)
                return filtered
            yield encode_sse("meta",{"message_id":str(message_id),"capability":"qa","buffered_hint":True})
            result,citations,_=await asyncio.to_thread(answer,factory,session_id=session_id,question=body.question,stack=stack,provider=provider,
                pending_assistant_id=message_id,learning_context=learning,response_filter=filter_hint)
            with factory.begin() as db:
                if result.metadata_.get("retrieval_mode") not in {"scope_notice","overview_notice"}: record_qa_assistance(db,context=ctx,message_id=message_id,level=action,now=now)
                row=db.get(ChatMessage,message_id); row.metadata_={**row.metadata_,"hint_guard_blocked":guarded["blocked"]}
            cards=citation_payloads(factory,citations)
            yield encode_sse("delta",{"seq":1,"text":result.content})
            yield encode_sse("citations",{"citations":cards})
            yield encode_sse("done",{"message_id":str(message_id),"answer":result.content,"citations":cards,"response_duration_ms":result.metadata_.get("response_duration_ms")})
            return
        delivered=False; assist_allowed=True; accumulated=""
        async for frame in stream_answer(factory,request=request,session_id=session_id,question=body.question,stack=stack,provider=provider,
            pending_assistant_id=message_id,learning_context=learning):
            decoded=frame.decode(); event=re.search(r"event: (.+)",decoded); payload=re.search(r"data: (.+)",decoded)
            if event and payload:
                data=json.loads(payload.group(1))
                if event.group(1)=="meta": assist_allowed=data.get("retrieval_mode") not in {"scope_notice","overview_notice"}
                if event.group(1)=="delta":
                    accumulated=str(data.get("text","")) if data.get("replace") else accumulated+str(data.get("text",""))
                    if action!="solution" and ctx.question_id and question_relevant(body.question,action) and final_answer_disclosed(accumulated):
                        action="solution";delivered=False
                if event.group(1)=="delta" and data.get("text") and action and not delivered and assist_allowed:
                    with factory.begin() as db: record_qa_assistance(db,context=ctx,message_id=message_id,level=action,now=now)
                    delivered=True
            yield frame
    except asyncio.CancelledError:
        fail_turn(factory,message_id,"cancelled"); raise
    except Exception as exc:
        code=exc.code if isinstance(exc,AppError) else "internal_error"
        # SQLAlchemy exception strings can include SQL parameters and user
        # prompts. Log only safe identifiers, exception type and stack locations.
        diagnostic = _safe_failure_details(exc, phase)
        logger.error("assistant_turn_failed session_id=%s message_id=%s code=%s diagnostic=%s",
                     session_id, message_id, code, json.dumps(diagnostic, ensure_ascii=True))
        fail_turn(factory,message_id,code,diagnostic)
        err=exc if isinstance(exc,AppError) else AppError("internal_error")
        yield encode_sse("error",{"code":code,"message":err.message,"retryable":err.retryable is not False,"message_id":str(message_id)})
