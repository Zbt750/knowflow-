"""Grounded revision activities, separate from the question-append contract.

Preview reads only. Confirmation records this task's activity agreement, never
creates a paper, an attempt, or an objective mastery observation.
"""
from uuid import UUID
from sqlalchemy import select
from backend.models.learning import KnowledgePoint, PracticeItem, QuestionAttempt
from datetime import datetime, timedelta
from backend.services.question_versions import question_for_practice_item


def build_schedule(db, context, budget):
    handoff = context.get('planner_handoff') or {}
    roots = [UUID(k) for k in handoff.get('target_knowledge_node_ids', [])]
    from backend.services.question_availability import _descendant_ids
    scope = _descendant_ids(db, set(roots)) if roots else set()
    nodes_query = select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))
    if scope:
        nodes_query = nodes_query.where(KnowledgePoint.id.in_(scope))
    elif handoff.get('subject'):
        nodes_query = nodes_query.where(KnowledgePoint.subject == handoff['subject'])
    nodes = list(db.scalars(nodes_query.order_by(KnowledgePoint.code)))
    if not nodes:
        return None, '没有找到本次复习范围中的有效知识点。请指定知识树中现有节点或提供可复盘资料；没有创建正式计划。'
    node_ids = {n.id for n in nodes}
    clock=datetime.fromisoformat(handoff['generated_at'])
    attempts=list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id.in_(node_ids),
        QuestionAttempt.submitted_at>=clock-timedelta(days=30),QuestionAttempt.submitted_at<=clock)
        .order_by(QuestionAttempt.submitted_at,QuestionAttempt.id)))
    if 'evidence_attempt_ids' in context:
        evidence_ids=set(context['evidence_attempt_ids'])
        attempts=[a for a in attempts if str(a.id) in evidence_ids]
    objective=[]
    for attempt in attempts:
        receipt=attempt.grading_evidence or {}
        objective.append({'attempt_id':str(attempt.id),'knowledge_node_id':str(attempt.kp_id),
            'result':attempt.objective_result,'assisted':receipt.get('assisted'),
            'assessment_basis':receipt.get('assessment_basis'),'mastery_reason':receipt.get('mastery_reason')})
    reports = context.get('learner_self_reports', [])
    wrong_nodes={r['knowledge_node_id'] for r in objective if r['result']=='wrong'}
    def priority(node):
        report_help=any(r.get('assessment')=='needs_help' and r.get('topic') and r['topic'] in node.name for r in reports)
        return (0 if str(node.id) in wrong_nodes else 1 if report_help else 2,node.code)
    nodes.sort(key=priority)
    plan_id = context.get('current_plan_id')
    items = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == UUID(plan_id),
        PracticeItem.kp_id.in_(node_ids)).order_by(PracticeItem.ordinal))) if plan_id else []
    references = []
    for item in items:
        q = question_for_practice_item(db, item)
        if q:
            references.append({'practice_item_id':str(item.id),'question_id':str(item.question_id),
                'question_version_id':str(item.question_version_id),'ordinal':item.ordinal,
                'stem':q.stem,'completed':item.completed_at is not None})
    # These activities remain executable without inventing new inventory: the
    # existing knowledge-tree scope and exact paper instances are the materials.
    names = '、'.join(n.name for n in nodes[:8])
    practice_minutes = max(1, budget // 2) if references else 0
    remaining = budget - practice_minutes
    recall = max(1, remaining * 2 // 3)
    summary = remaining - recall
    activities = []
    if references:
        activities.append({'kind':'existing_practice_review','title':'复盘当前卷已绑定题目；已完成题只回忆步骤，不重复提交',
            'minutes':practice_minutes,'practice_items':references,'basis':'当前今日卷的真实题目和绑定版本；不代表已核验答案'})
    activities.append({'kind':'closed_book_recall','title':f'合上解析，回忆 {names} 的适用条件、定义与解题步骤；不确定处标记为待核对',
        'minutes':recall,'knowledge_node_ids':[str(n.id) for n in nodes], 'basis':'现有知识树节点；不假称已读取讲义或证明薄弱'})
    if summary:
        activities.append({'kind':'reflection','title':'对照已有资料或解析核对刚才标记的问题；资料不足时整理待询问清单',
            'minutes':summary,'basis':'复盘活动；不生成新题，不产生掌握或毕业证据'})
    draft = {'kind':'activity_schedule','activities':activities,'total_minutes':budget,
        'paper_estimated_minutes':(context.get('current_plan') or {}).get('remaining_minutes'),
        'questions':[],'review_nodes':[],'review_minutes':0,'rationale':'先复盘有题目依据的内容，回忆范围优先列有错答观察的节点，再列学生自述需要帮助的节点；次数不代表掌握程度，没有证据时不声称最薄弱。',
        'warnings':['这是活动预算，不是今日卷预计作答耗时。','旧今日卷和旧计划保留；确认也不会追加题目。'],
        'learner_self_reports':reports,'objective_observations':objective,
        'time_window':{'start':(clock-timedelta(days=30)).isoformat(),'end':clock.isoformat()},
        'source_policy':'self_report is unverified; observations are not mastery'}
    message = f'本次 {budget} 分钟活动预览，尚未确认；旧计划与今日卷保持不变。\n\n'
    message += '\n'.join(f"{i+1}. {a['minutes']} 分钟：{a['title']}" for i,a in enumerate(activities))
    message += '\n\n' + draft['rationale']
    if reports:
        message += '\n学生自述（未经独立核验）：' + '；'.join(r['statement'] for r in reports)
    message+='\n最近30天实际作答观察：'+str(len(objective))+' 条；其中无辅助答对 '+str(sum(r['result']=='right' and r['assisted'] is False for r in objective))+' 条，答错 '+str(sum(r['result']=='wrong' for r in objective))+' 条，辅助后正确 '+str(sum(r['result']=='right' and r['assisted'] is True for r in objective))+' 条。这些观察不直接等于掌握或毕业。'
    return draft, message


def validate_schedule(db, draft, budget):
    from backend.errors import AppError
    activities = draft.get('activities', [])
    if not activities or any(type(a.get('minutes')) is not int or a['minutes']<=0 for a in activities) or sum(a['minutes'] for a in activities)!=budget:
        raise AppError('learning_task_stale_draft',status_code=409)
    for activity in activities:
        for node_id in activity.get('knowledge_node_ids',[]):
            node=db.get(KnowledgePoint,UUID(node_id))
            if node is None or not node.is_active:
                raise AppError('learning_task_stale_draft',status_code=409)
        for ref in activity.get('practice_items',[]):
            item = db.get(PracticeItem,UUID(ref['practice_item_id']))
            if not item or str(item.question_id)!=ref['question_id'] or str(item.question_version_id)!=ref['question_version_id']:
                raise AppError('learning_task_stale_draft',status_code=409)
