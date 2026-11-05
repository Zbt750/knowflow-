"""Count-only transport views; pinned candidates remain private until generation."""
from collections import Counter
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import UnmappedInstanceError
from backend.models.learning import DailyPlan, KnowledgePoint, Question
from backend.models.learning_task import LearningTask


def _ids(values):
    result=[]
    for value in values if isinstance(values,(list,tuple)) else []:
        try: result.append(UUID(str(value)))
        except (ValueError,TypeError): pass
    return list(dict.fromkeys(result))


def before_generation(db,row,now):
    """Only release a pinned preview after this task's own commit reads back."""
    if db is None:
        return True
    metrics = getattr(row, 'metrics', None)
    metrics = metrics if isinstance(metrics,dict) else {}
    commit = metrics.get('commit') if isinstance(metrics.get('commit'),dict) else {}
    if commit.get('kind') == 'activity_schedule':
        return False
    plan_id = commit.get('plan_id')
    item_ids = commit.get('item_ids')
    if not plan_id or not isinstance(item_ids, list):
        return True
    context = getattr(row,'context',None)
    context = context if isinstance(context,dict) else {}
    expected = (len(item_ids) if context.get('home_recommendation')
                else commit.get('added_count'))
    if type(expected) is not int:
        return True
    try:
        if db.get(DailyPlan, UUID(str(plan_id))) is None:
            return True
        from backend.services.today_append_result import read_append_result
        receipt = read_append_result(db, operation_id=row.id, plan_id=plan_id,
            item_ids=item_ids, added_count=expected)
    except (ValueError, TypeError):
        return True
    return not (receipt and receipt.get('status') == 'committed'
                and len(receipt.get('items') or []) == expected)


def _eligible_refs(db, refs):
    """Recheck pinned identities internally; expose only the resulting count."""
    if db is None or not callable(getattr(db, 'get', None)):
        return []
    from backend.services.question_eligibility import question_eligibility
    from backend.services.question_versions import question_version_reference
    output=[];seen=set()
    for ref in refs:
        try:question_id=UUID(str(ref.get('question_id')))
        except (ValueError,TypeError):continue
        if question_id in seen:continue
        question=db.get(Question,question_id)
        if question is None:continue
        node=db.get(KnowledgePoint,question.kp_id)
        if node is None or not question_eligibility(question,node).practice_eligible:continue
        expected=ref.get('question_version_id') or ref.get('question_version')
        current=question_version_reference(question)
        if not expected or str(expected)!=str(current):continue
        kp_ref=ref.get('kp_id')
        if kp_ref and str(kp_ref)!=str(question.kp_id):continue
        seen.add(question_id);output.append({**ref,'kp_id':str(question.kp_id)})
    return output


def paper_summary(db,paper,*,scope_ids=(),budget=None,now=None,ready=False,
                  planned_count=None,activities=None):
    now=now or datetime.now(timezone.utc)
    paper=paper if isinstance(paper,dict) else {}
    raw_refs=[ref for ref in (paper.get('questions') or []) if isinstance(ref,dict)]
    refs=_eligible_refs(db,raw_refs)
    supplied=paper.get('selected_kp_ids') or scope_ids or [q.get('kp_id') for q in refs]
    ids=_ids(supplied)
    can_query = db is not None and callable(getattr(db, 'execute', None))
    hierarchy={row.id:row for row in db.execute(select(KnowledgePoint.id,KnowledgePoint.parent_id,KnowledgePoint.name))} if can_query else {}
    ids=[key for key in ids if key in hierarchy]
    roots=[]
    for key in ids:
        parent=hierarchy[key].parent_id;seen={key}
        while parent in hierarchy and parent not in seen and parent not in ids:
            seen.add(parent);parent=hierarchy[parent].parent_id
        if parent not in ids:roots.append(key)
    assigned=Counter()
    for ref in refs:
        candidates=_ids([ref.get('kp_id')]);key=candidates[0] if candidates else None;seen=set()
        while key in hierarchy and key not in seen and key not in roots:
            seen.add(key);key=hierarchy[key].parent_id
        if key in roots:assigned[key]+=1
    inventory={}
    if roots and can_query:
        from backend.services.home_recommendation_service import _home_inventory
        inventory=_home_inventory(db,roots,now)
    counts={str(node['kp_id']):node for node in inventory.get('recommendation_nodes',[])}
    nodes=[{'kp_id':str(key),'name':hierarchy[key].name,'assigned_count':assigned[key] if refs else None,
        'practice_eligible_count':int(counts.get(str(key),{}).get('practice_eligible_count') or 0)} for key in roots]
    count=sum(assigned.values()) if refs else (planned_count if type(planned_count) is int else 0)
    minutes=paper.get('total_minutes')
    total=minutes if type(minutes) is int and minutes>=0 else None
    proposed_budget=paper.get('budget_minutes',budget)
    proposed_budget=proposed_budget if type(proposed_budget) is int and 5<=proposed_budget<=240 else None
    result={'questions':[],'question_count':count,'available_question_count':sum(n['practice_eligible_count'] for n in nodes),
        'scope_nodes':nodes,'selected_kp_ids':[str(key) for key in roots],
        'total_minutes':total,'budget_minutes':proposed_budget,
        'can_commit':bool(ready and count and count==len(refs) and all(n['assigned_count']<=n['practice_eligible_count'] for n in nodes)),
        'kind':paper.get('kind') if paper.get('kind') in {'activity_schedule','study_plan'} else 'study_plan'}
    if raw_refs and len(refs)!=len(raw_refs):
        result['can_commit']=False
        result['requires_revalidation']=True
    if not refs:
        result['can_commit'] = bool(ready and count > 0 and sum(n['practice_eligible_count'] for n in nodes) >= count
            and not raw_refs)
    if activities:
        labels={'review':'复习','practice':'正式准入题目练习','remediation':'讲义与错题复习','wrap_up':'学习复盘'}
        result['activities']=[{'title':labels.get(a.get('type'),'学习活动'),
            'minutes':a['minutes'],'question_count':a.get('question_count') if type(a.get('question_count')) is int else None,
            'basis':'按真实学习记录、知识点范围和预算安排。'} for a in activities
            if isinstance(a,dict) and type(a.get('minutes')) is int and a['minutes']>0]
    if paper.get('kind')=='activity_schedule':
        result['kind']='activity_schedule'
        result['can_commit']=bool(ready and total is not None and proposed_budget is not None and total<=proposed_budget)
        result['activities']=[{'title':'知识点学习活动','minutes':activity['minutes'],
            'basis':'按知识点和时间预算规划；这不是正式今日卷。'} for activity in paper.get('activities',[])
            if isinstance(activity,dict) and type(activity.get('minutes')) is int and activity['minutes']>0]
    return result


def summary_message(summary,*,ready=False,confirmed_activity=False):
    labels=[]
    for node in summary.get('scope_nodes',[]):
        label=f"{node['name']} · {node['practice_eligible_count']}道可用题"
        if type(node.get('assigned_count')) is int:
            label+=f"（本次安排{node['assigned_count']}道）"
        labels.append(label)
    prefix='活动安排已确认：' if confirmed_activity else '待确认学习方案：' if ready else '当前方案尚未形成可生成的题目集合：'
    text=prefix+('；'.join(labels) if labels else '请明确知识点和预算。')
    if summary.get('question_count') and not any(type(n.get('assigned_count')) is int for n in summary.get('scope_nodes',[])):
        text+=f" 本次计划安排 {summary['question_count']} 道题。"
    if type(summary.get('available_question_count')) is int:
        text+=f" 当前范围共 {summary['available_question_count']} 道符合正式准入条件的可用题。"
    if type(summary.get('total_minutes')) is int:text+=f"。计划预计 {summary['total_minutes']} 分钟。"
    if summary.get('requires_revalidation'):text+=' 部分候选题版本或准入状态已变化，当前方案需重新规划后才能生成。'
    return text+'今日卷尚未生成，确认生成后才能查看具体题目。'


def public_task(factory,result,*,now=None):
    now=now or datetime.now(timezone.utc)
    with factory() as db:
        row=db.get(LearningTask,result.task_id)
        if row is None or not before_generation(db,row,now):return result
        context=row.context if isinstance(row.context,dict) else {}
        handoff=context.get('planner_handoff') if isinstance(context.get('planner_handoff'),dict) else {}
        paper=row.draft if isinstance(row.draft,dict) else context.get('baseline')
        safe=paper_summary(db,paper,scope_ids=handoff.get('target_knowledge_node_ids',[]),
            budget=row.budget_minutes,now=now,ready=row.status=='ready')
        safe['planning_origin']='homepage' if context.get('home_recommendation') else 'assistant'
        task_metrics=row.metrics if isinstance(row.metrics,dict) else {}
        commit=task_metrics.get('commit') if isinstance(task_metrics.get('commit'),dict) else {}
        message=(summary_message(safe,ready=row.status=='ready',
            confirmed_activity=commit.get('kind')=='activity_schedule')
            if row.status not in {'cancelled','canceled'} else
            '这份历史学习方案已撤回；没有据此生成今日卷。')
        return result.model_copy(update={'draft':safe if row.draft else None,'trace':[],
            'metrics':{'pre_generation':True,'planning_origin':safe['planning_origin']},'append_result':None,
            'message':message})


def public_practice_details(row,now,*,db=None):
    if db is None:
        try:db=object_session(row)
        except UnmappedInstanceError:db=None
    original=row.request if isinstance(row.request,dict) else {}
    linked_task=None
    if db is not None and getattr(row,'planner_task_id',None):
        linked_task=db.get(LearningTask,row.planner_task_id)
        if linked_task and not before_generation(db,linked_task,now):
            return original
    if not before_generation(db,row,now):return original
    paper=original.get('preview_draft');scope=original.get('target_knowledge_node_ids',[])
    budget=original.get('available_minutes');requested=original.get('requested_question_count')
    if db is not None and getattr(row,'planner_task_id',None):
        linked=linked_task
        linked_context=linked.context if linked and isinstance(linked.context,dict) else {}
        if linked and linked_context.get('practice_request_id')==str(row.id):
            if isinstance(linked.draft,dict):paper=linked.draft
            context=linked_context
            handoff=context.get('planner_handoff') if isinstance(context.get('planner_handoff'),dict) else {}
            scope=handoff.get('target_knowledge_node_ids',scope)
            requested=handoff.get('requested_question_count',requested);budget=linked.budget_minutes
    planned_count=None;activities=None
    if isinstance(original.get('plan_preview'),dict):
        preview=original['plan_preview'];activities=preview.get('activities') or []
        planned_count=sum(a.get('question_count',0) for a in activities
            if isinstance(a,dict) and a.get('type') in {'practice','remediation'}
            and type(a.get('question_count',0)) is int)
        minutes=sum(a.get('minutes',0) for a in activities
            if isinstance(a,dict) and type(a.get('minutes',0)) is int)
        paper={'selected_kp_ids':scope,'total_minutes':minutes,'budget_minutes':budget,'kind':'study_plan'}
    safe=paper_summary(db,paper,scope_ids=scope,budget=budget,now=now,
        ready=row.status in {'draft','proposed'},planned_count=planned_count,activities=activities)
    details={'pre_generation':True,'target_knowledge_node_ids':safe['selected_kp_ids'],
        'requested_question_count':requested if type(requested) is int else None,
        'available_minutes':safe['budget_minutes'],'plan_summary':safe}
    target=original.get('target_study_session_id')
    if target:
        try:details['target_study_session_id']=str(UUID(str(target)))
        except (ValueError,TypeError):pass
    for key in ('confirmation_a','confirmation_b'):
        if type(original.get(key)) is bool:details[key]=original[key]
    return details
