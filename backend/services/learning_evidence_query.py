"""Read-only, scope-labelled learning observations and separate student reports."""
import re
from collections import Counter
from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy import select
from backend.models.learning import KnowledgePoint, QuestionAttempt, PracticeItem
from backend.models.chat import ChatMessage
from backend.services.learner_self_report import read_self_reports
from backend.services.question_availability import _descendant_ids


def learning_evidence_query(db, factory, *, session_id, ctx, message, query_type, now, _scope=None, _include_rates=None):
    from backend.services.assistant_data_queries import _subject_from_message
    from backend.services.learning_task_tools import TaskTools
    # Scope-free recursive queries still need the metrics requested by the user.
    # Passing the whole message would incorrectly reapply its node/subject scope.
    include_rates = bool(re.search(r'正确率|答对率', message)) if _include_rates is None else _include_rates
    # A later recommendation's subject must not narrow the records being counted.
    advice_start = re.search(r'(?:并|再|然后|同时)?(?:请)?(?:给我|提供|提出).{0,30}(?:复习|学习)建议', message)
    statistics_message = message[:advice_start.start()] if advice_start else message
    subject = _subject_from_message(statistics_message)
    resolver = TaskTools(factory, budget_minutes=90, now=now, goal=statistics_message)
    roots = list(resolver.explicit_scope or [])
    paper_id = None
    prior_scope = None
    if _scope is None and not roots and not subject and not re.search(r'全局|全库|所有知识点',statistics_message):
        if ctx.daily_plan_id and re.search(r'刚才|本次|今日|今天|当前卷',statistics_message):
            paper_id = ctx.daily_plan_id
        elif re.search(r'核对|重新统计|重新计算|次数不对|记录不对',statistics_message):
            previous = db.scalar(select(ChatMessage).where(ChatMessage.session_id==session_id,
                ChatMessage.role=='assistant',ChatMessage.status=='completed').order_by(ChatMessage.seq.desc()))
            prior = ((previous.metadata_ or {}).get('read_only_data_query') or {}) if previous else {}
            state = prior.get('query_state') or {}
            # Only the latest successful, same-session statistics answer is an antecedent.
            if prior.get('query_status')=='executed' and prior.get('query_type') in {'learning_state','evidence_basis'} and state.get('scope_kind'):
                prior_scope = prior
                subject = state.get('subject')
                roots = [UUID(k) for k in state.get('scope_node_ids',[])]
                if state.get('daily_plan_id'):
                    candidate = UUID(state['daily_plan_id'])
                    if not ctx.daily_plan_id or ctx.daily_plan_id==candidate:
                        paper_id = candidate
                    else:
                        prior_scope=None;roots=[];subject=None
    from backend.services.learner_self_report import extract_self_reports
    claims = extract_self_reports(message)
    asks_to_confirm_claim = query_type == 'evidence_basis' and bool(claims) and bool(re.search(
        r'(?:能|可以|是否|能不能).{0,8}(?:确认|判断).{0,8}(?:掌握|会不会)|(?:确认|判断).{0,8}(?:我|你).{0,8}(?:掌握|会)', message))
    if asks_to_confirm_claim and not roots:
        topic = claims[-1]['topic']
        candidates = list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))))
        matched = [n for n in candidates if topic in n.name or n.name in topic or topic == n.code]
        if matched:
            roots = [n.id for n in matched[:8]]
        else:
            available = [n.name for n in candidates if n.parent_id is None][:12]
            answer = (f'你刚才的自述是「{claims[-1]["statement"]}」，来源为学生自述（self_report），未经独立核验。'
                f'我不能仅凭这条自述确认你已掌握「{topic}」。当前知识树没有找到与该名称精确对应的活动节点，'
                '也没有读取到这个主题的对应作答记录；我不能拿全库数字或其他知识点替代判断。')
            if available:
                answer += ' 你可以从现有知识树范围中选择：' + '、'.join(available) + '。'
            answer += ' 自述不会修改掌握状态或毕业资格。'
            return {'answer': answer, 'evidence': {'query_type': query_type,
                'query_status': 'unresolved_self_report_topic', 'claim_topic': topic,
                'learner_self_reports': claims, 'matched_knowledge_node_ids': [],
                'tools_used': ['resolve_knowledge_scope'], 'writes': False, 'model_called': False}}
    composite = (_scope is None and bool(re.search(r'全局|全库', message))
        and bool(re.search(r'单独|知识点|数字|正确率|分别', message)))
    if composite:
        global_result=learning_evidence_query(db,factory,session_id=session_id,ctx=ctx,message='',query_type=query_type,now=now,_scope=[],_include_rates=include_rates)
        selected=roots or list(ctx.knowledge_node_ids)
        if not selected:
            return {'answer':global_result['answer']+'\n\n请指定要对比的知识点；没有用全局数字冒充单节点统计。',
                'evidence':{**global_result['evidence'],'comparison_status':'needs_node'}}
        node_result=learning_evidence_query(db,factory,session_id=session_id,ctx=ctx,message=message,query_type=query_type,now=now,_scope=selected,_include_rates=include_rates)
        return {'answer':'## 全局近期统计\n\n'+global_result['answer']+'\n\n## 指定知识点统计\n\n'+node_result['answer'],
            'evidence':{'query_type':query_type,'query_status':'executed','writes':False,'model_called':False,
                'scope_results':[global_result['evidence'],node_result['evidence']]}}
    if _scope is not None:
        roots=list(_scope)
        if not roots: subject=None
    origin = 'explicit_message_scope' if roots else 'global_recent_learning'
    if _scope is None and not roots and not subject and re.search(r'当前(?:这道题|题目)|这个知识点|该知识点', message):
        roots = list(ctx.knowledge_node_ids)
        origin = 'explicit_current_knowledge_context'
    # Retiring a node does not erase its historical observations.
    nodes = select(KnowledgePoint)
    if subject:
        nodes = nodes.where(KnowledgePoint.subject == subject)
    if roots:
        nodes = nodes.where(KnowledgePoint.id.in_(_descendant_ids(db, set(roots))))
    node_rows = list(db.scalars(nodes))
    ids = {n.id for n in node_rows}
    names = [n.name for n in node_rows if n.id in roots]
    label = f'当前今日卷及其重练（{paper_id}，包含卷内全部科目）' if paper_id else ('、'.join(names) if roots else (subject or '全库所有知识点'))
    since = datetime.fromisoformat(prior_scope['time_window']['start']) if prior_scope else now - timedelta(days=30)
    end = datetime.fromisoformat(prior_scope['time_window']['end']) if prior_scope else now
    attempt_query = select(QuestionAttempt).where(
        QuestionAttempt.kp_id.in_(ids), QuestionAttempt.submitted_at >= since,
        QuestionAttempt.submitted_at <= end)
    if paper_id:
        root_items=select(PracticeItem.id).where(PracticeItem.plan_id==paper_id,PracticeItem.retry_source_id.is_(None))
        item_ids=select(PracticeItem.id).where((PracticeItem.id.in_(root_items)) | PracticeItem.retry_source_id.in_(root_items))
        attempt_query=attempt_query.where(QuestionAttempt.practice_item_id.in_(item_ids))
    attempts = list(db.scalars(attempt_query.order_by(QuestionAttempt.submitted_at, QuestionAttempt.id)))
    counts = Counter(independent_right=0, independent_wrong=0, assisted_right=0, assisted_wrong=0, unknown=0)
    for a in attempts:
        receipt = a.grading_evidence or {}
        assisted = receipt.get('assisted')
        if receipt.get('assistance_level') in {'hint_1', 'hint_2', 'solution', 'process_review'}:
            assisted = True
        category = ('assisted_right' if a.objective_result == 'right' and assisted is True else
            'independent_right' if a.objective_result == 'right' and assisted is False else
            'independent_wrong' if a.objective_result == 'wrong' and assisted is False else
            'assisted_wrong' if a.objective_result == 'wrong' and assisted is True else 'unknown')
        counts[category] += 1
    reports = read_self_reports(db, session_id)
    window = {'start': since.isoformat(), 'end': end.isoformat(), 'days': 30, 'end_inclusive': True}
    evidence = {'query_type': query_type, 'scope_source': origin, 'scope_node_ids': [str(k) for k in roots],
        'scope_node_names': names, 'scope_label': label, 'time_window': window,
        'query_status': 'executed', 'model_called': False, 'writes': False,
        'tools_used': ['question_attempts', 'same_session_self_reports'],
        'attempt_count': len(attempts), 'attempt_summary': dict(counts),
        'learner_self_reports': reports, 'attempt_ids': [str(a.id) for a in attempts],
        'records':[{'attempt_id':str(a.id),'knowledge_node_id':str(a.kp_id),'submitted_at':a.submitted_at.isoformat(),
            'objective_result':a.objective_result,'grading_evidence':a.grading_evidence} for a in attempts],
        'query_state': {'subject': subject, 'scope_node_ids': [str(k) for k in roots], 'eligibility': 'all_recorded',
            'scope_kind':'today_paper' if paper_id else 'knowledge_nodes' if roots else 'subject' if subject else 'global_recent',
            'daily_plan_id':str(paper_id) if paper_id else None}}
    if paper_id:evidence['scope_source']='same_session_previous_statistics' if prior_scope else 'explicit_current_paper'
    if prior_scope:evidence['antecedent_message_id']=str(previous.id)
    lines = [f'统计范围：{label}；时间窗口：最近30天（{since.isoformat()} 至 {end.isoformat()}）。',
        f"客观作答记录：独立答对{counts['independent_right']}次、独立答错{counts['independent_wrong']}次、"
        f"看解析或接受辅助后答对{counts['assisted_right']}次、辅助后答错{counts['assisted_wrong']}次、"
        f"无法判定或辅助事实不完整{counts['unknown']}次。"]
    if include_rates:
        graded = counts['independent_right'] + counts['independent_wrong'] + counts['assisted_right'] + counts['assisted_wrong']
        right = counts['independent_right'] + counts['assisted_right']
        independent_graded = counts['independent_right'] + counts['independent_wrong']
        if graded:
            lines.append(f'客观已判定正确率：{right}/{graded}（{right / graded:.1%}；分母只含可判为对/错的记录，无法判定不计入）。')
        else:
            lines.append('客观已判定正确率：暂无可判为对/错的作答，无法计算。')
        if independent_graded:
            lines.append(f'独立作答正确率：{counts["independent_right"]}/{independent_graded}（{counts["independent_right"] / independent_graded:.1%}；不含辅助作答）。')
        else:
            lines.append('独立作答正确率：暂无可判定的独立作答，无法计算。')
    if not attempts:
        lines.append('这个范围和窗口内没有客观作答记录，不能据此判断你薄弱或已经掌握。')
    else:
        lines.append('这是作答观察；参考答案可靠性、题目覆盖和辅助事实仍须分别核对，次数不直接等于独立掌握或毕业。')
        lines.append('记录依据：'+'；'.join(f'{a.id}〔{a.submitted_at.isoformat()}，{a.objective_result}〕' for a in attempts))
    if reports:
        lines.append('本会话已接收并保存的学生自述（self_report，未经独立核验）：' +
            '；'.join(f"{r['statement']}〔消息 {r['message_id']}〕" for r in reports) + '。')
    else:
        lines.append('本会话尚未保存明确的学生自述；不会把模型推测或其他会话内容算成你的自评。')
    if query_type == 'self_report':
        lines.append('已记录在本会话消息中，刷新后可恢复；你可以说“我现在会用某知识点”或“我不会某知识点”更新自述，旧消息保留。')
    if query_type == 'evidence_basis':
        lines.append('判断依据必须分开：以上为客观记录与学生自述；未验证的薄弱点只是待验证假设。若先前直接断言你不会而没有对应证据，该结论不能成立。')
        if asks_to_confirm_claim:
            lines.append(f'你刚才自述「{claims[-1]["statement"]}」，它不是独立作答证据。'
                f'该自述对应的{label}最近30天有 {len(attempts)} 条客观作答记录；'
                + ('因此我不能确认已掌握。' if not attempts else '作答记录只能支持观察，不能仅凭自述或次数直接确认掌握。'))
    lines.append('自述只可影响建议，不会修改客观掌握状态、独立确认次数或毕业资格；没有创建计划或改变今日卷。')
    if _scope is None and re.search(r'(?:复习|学习).{0,8}建议',message):
        from backend.services.learning_assistant_service import explicit_minutes
        from backend.services.study_activity_schedule import build_schedule, validate_schedule
        budget=explicit_minutes(message)
        if budget is not None and 5<=budget<=240:
            advice_subject=_subject_from_message(message[advice_start.start():]) if advice_start else subject
            advice_ids={n.id for n in node_rows if not advice_subject or n.subject==advice_subject}
            context={'planner_handoff':{'target_knowledge_node_ids':[str(k) for k in advice_ids], 'subject':advice_subject,
                'generated_at':now.isoformat()},'learner_self_reports':reports,
                'evidence_attempt_ids':[str(a.id) for a in attempts if a.kp_id in advice_ids],
                'current_plan_id':str(ctx.daily_plan_id) if ctx.daily_plan_id else None}
            draft,advice=build_schedule(db,context,budget)
            if draft:
                validate_schedule(db,draft,budget)
                evidence['study_advice']=draft
                evidence['study_advice_scope']={'subject':advice_subject,'knowledge_node_ids':[str(k) for k in advice_ids]}
                lines.append('## 依据上述记录的复习建议\n\n建议范围：'+(advice_subject or label)+'；建议范围与上面的统计范围分别标明。\n\n'+advice+'\n本节是只读建议，没有创建学习任务或正式计划。')
            else:
                lines.append('无法生成分项建议：'+advice)
        else:
            lines.append('请提供5至240分钟内的本次预算，再按上述证据准备分项建议；未替你采用默认90分钟。')
    return {'answer': '\n\n'.join(lines), 'evidence': evidence}
