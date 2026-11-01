"""Read committed items and immutable versions; never infer success from a draft."""
from uuid import UUID
from sqlalchemy import select
from backend.models.learning import PracticeItem,DailyPlan,KnowledgePoint
from backend.services.question_versions import question_for_practice_item
from backend.services.practice_display_order import display_key
from backend.services.question_availability import question_source_category
from backend.schemas.question_source import public_question_source

def read_append_result(db,*,operation_id,plan_id,item_ids,added_count):
    if not item_ids:return None  # Legacy receipt has no reliable item association.
    plan=db.get(DailyPlan,UUID(str(plan_id)))
    if plan is None:return None
    items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==plan.id).order_by(PracticeItem.ordinal)))
    questions={i.id:question_for_practice_item(db,i) for i in items}
    ordered=sorted(items,key=lambda i:display_key(questions[i.id].question_type if questions[i.id] else 'external_exam',i.ordinal))
    positions={str(i.id):n for n,i in enumerate(ordered,1)}
    wanted=set(map(str,item_ids));found=[i for i in ordered if str(i.id) in wanted]
    if len(found)!=len(wanted):return None
    output=[]
    for item in found:
        question=questions[item.id]
        if question is None:return None
        node=db.get(KnowledgePoint,item.kp_id)
        minutes=question.estimated_minutes
        output.append({'item_id':str(item.id),'question_id':str(item.question_id),
            'question_version_id':str(item.question_version_id),'number':positions[str(item.id)],
            'stem':question.stem,'options':question.options,'kp_id':str(item.kp_id),'kp_name':node.name if node else '',
            'question_type':question.question_type,'difficulty':question.difficulty,
            'source_category':question_source_category(question),'question_source':public_question_source(question.grading_config).model_dump(mode='json'),
            'estimated_minutes':minutes if type(minutes) is int and minutes>0 else None})
    return {'operation_id':str(operation_id),'plan_id':str(plan.id),'study_date':plan.study_date,
        'status':'committed','number_semantics':'current_position','added_count':added_count,
        'total_count':len(items),'items':output}
