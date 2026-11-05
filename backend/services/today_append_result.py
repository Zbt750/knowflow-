"""Read committed items and immutable versions; never infer success from a draft."""
from uuid import UUID
from sqlalchemy import select
from backend.models.learning import PracticeItem,DailyPlan,KnowledgePoint
from backend.services.question_versions import question_for_practice_item
from backend.services.practice_display_order import display_key
from backend.services.question_availability import question_source_category
from backend.schemas.question_source import public_question_source

def source_label(category):
    return {'exam_curated':'整理真题','exam_variant':'真题改编',
        'development_original':'开发原创','personal_ai_practice':'个人 AI 练习',
        'personal_practice':'个人练习','unclassified_public':'其他来源（待核）'}.get(category,'来源待核')

def paper_time_estimates(db,items,questions=None):
    """Use immutable item versions; unknown duration stays unknown."""
    questions=questions if questions is not None else {i.id:question_for_practice_item(db,i) for i in items}
    total=[];remaining=[]
    for item in items:
        question=questions.get(item.id)
        value=getattr(question,'estimated_minutes',None)
        minutes=value if type(value) is int and value>0 else None
        total.append(minutes)
        if item.completed_at is None:remaining.append(minutes)
    estimate=lambda values:None if any(v is None for v in values) else sum(values)
    return {'estimated_minutes':estimate(total),'remaining_minutes':estimate(remaining)}


def render_append_result(result):
    """Describe only items recovered from committed paper/version bindings."""
    if not result or result.get('status') != 'committed' or not result.get('items'):
        return None
    lines = [f"已加入今日卷：新增 {len(result['items'])} 道题，当前今日卷共 {result['total_count']} 道。"]
    remaining=result.get('remaining_minutes')
    lines.append(f'预计剩余{remaining}分钟。' if remaining is not None else '预计剩余时间暂不可核验。')
    for item in result['items']:
        lines.append(f"第{item['number']}题 · {item['kp_name']} · {item['question_type']}")
        lines.append(item['stem'])
        lines.append(f"来源：{source_label(item['source_category'])}")
        if item.get('question_version_id'):lines.append('题目版本：'+item['question_version_id'])
    return '\n'.join(lines)


def read_append_result(db,*,operation_id,plan_id,item_ids,added_count):
    if not item_ids:return None  # Legacy receipt has no reliable item association.
    plan=db.get(DailyPlan,UUID(str(plan_id)))
    if plan is None:return None
    items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==plan.id, PracticeItem.removed_at.is_(None)).order_by(PracticeItem.ordinal)))
    questions={i.id:question_for_practice_item(db,i) for i in items}
    ordered=sorted(items,key=lambda i:display_key(questions[i.id].question_type if questions[i.id] else 'external_exam',i.ordinal))
    positions={str(i.id):n for n,i in enumerate(ordered,1)}
    wanted=set(map(str,item_ids));found=[i for i in ordered if str(i.id) in wanted]
    if len(found)!=len(wanted) or added_count != len(found):return None
    output=[]
    for item in found:
        question=questions[item.id]
        if question is None:return None
        node=db.get(KnowledgePoint,item.kp_id)
        minutes=question.estimated_minutes
        output.append({'item_id':str(item.id),'question_id':str(item.question_id),
            'question_version_id':str(item.question_version_id),'number':positions[str(item.id)],
            'stem':question.stem,'options':question.options,'kp_id':str(item.kp_id),'kp_name':node.name if node else '',
            # The legacy difficulty column has a default label and no independent
            # difficulty assessment provenance. Do not present it as measured.
            'question_type':question.question_type,'difficulty':None,
            'source_category':question_source_category(question),'question_source':public_question_source(question.grading_config).model_dump(mode='json'),
            'estimated_minutes':minutes if type(minutes) is int and minutes>0 else None})
    return {'operation_id':str(operation_id),'plan_id':str(plan.id),'study_date':plan.study_date,
        'status':'committed','number_semantics':'current_position','added_count':added_count,
        'total_count':len(items),'items':output,**paper_time_estimates(db,items,questions)}
