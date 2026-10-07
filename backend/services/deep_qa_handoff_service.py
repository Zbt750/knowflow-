"""Only an explicit deep-QA action creates a formal learning conversation."""
from uuid import UUID
from datetime import datetime,timezone
from sqlalchemy import select
from backend.models.chat import ChatSession,ChatMessage
from backend.models.learning import KnowledgePoint,PracticeItem
from backend.models.learning_task import LearningTask
from backend.errors import AppError
from backend.schemas.learning_assistant import StudyContext,QAHandoff
from backend.services.study_context_service import validate_study_context
from backend.services.learning_qa_service import qa_assistance_for_item

def create_deep_qa(factory,*,source_session_id,context,learning_problem,request_key,now=None):
    now=now or datetime.now(timezone.utc)
    with factory.begin() as db:
        source=db.get(ChatSession,source_session_id,with_for_update=True)
        if not source or source.purpose!="study" or source.mode!="builtin":raise AppError("forbidden",status_code=403)
        ctx=validate_study_context(db,session_id=source_session_id,context=context,now=now)
        if ctx.task_id and not ctx.knowledge_node_ids and not ctx.question_id:
            task=db.get(LearningTask,ctx.task_id)
            ids=((task.context or {}).get('planner_handoff') or {}).get('target_knowledge_node_ids',[])
            if not ids:ids=list(dict.fromkeys(q['kp_id'] for q in (task.draft or {}).get('questions',[])))
            ctx=validate_study_context(db,session_id=source_session_id,context=ctx.model_copy(update={
                'knowledge_node_ids':[UUID(k) for k in ids[:8]],'daily_plan_id':None}),now=now)
        old=db.scalar(select(ChatMessage).where(ChatMessage.metadata_["deep_qa_request_key"].as_string()==str(request_key)))
        if old:
            if old.metadata_.get("source_session_id")!=str(source_session_id) or old.metadata_.get("learning_problem")!=learning_problem:raise AppError("idempotency_key_conflict",status_code=409)
            supplied=ctx.model_dump(mode='json');previous=old.metadata_['study_context']
            if any(supplied.get(k)!=previous.get(k) for k in ('question_id','attempt_id','practice_item_id','daily_plan_id','knowledge_node_ids','material_id','chunk_id')):
                raise AppError('idempotency_key_conflict',status_code=409)
            if old.metadata_['qa_handoff'].get('source_task_id')!=(str(ctx.task_id) if ctx.task_id else None):raise AppError('idempotency_key_conflict',status_code=409)
            return {"session_id":str(old.session_id),"study_context":old.metadata_["study_context"],"handoff":old.metadata_["qa_handoff"]}
        names=list(db.scalars(select(KnowledgePoint.name).where(KnowledgePoint.id.in_(ctx.knowledge_node_ids))))
        item=db.get(PracticeItem,ctx.practice_item_id) if ctx.practice_item_id else None
        assistance='solution' if item and item.answer_revealed_at is not None else qa_assistance_for_item(db,item,now) if item else None
        last=db.scalar(select(ChatMessage).where(ChatMessage.session_id==source.id,ChatMessage.role=="assistant",ChatMessage.status=="completed").order_by(ChatMessage.seq.desc()))
        task=db.get(LearningTask,ctx.task_id) if ctx.task_id else None
        task_facts={'status':task.status,'question_count':len((task.draft or {}).get('questions',[])),
            'has_written_daily_plan':bool((task.metrics or {}).get('commit')),'captured_at':now.isoformat()} if task else None
        handoff=QAHandoff(source_task_id=ctx.task_id,knowledge_node_ids=ctx.knowledge_node_ids,question_id=ctx.question_id,
            reason="requested_concept_help",learning_problem=learning_problem,attempt_id=ctx.attempt_id,
            suggested_mode="question" if ctx.question_id else "knowledge",source_surface="study",assistance_already_given=assistance,
            bounded_summary=last.content[:600] if last else None,task_facts_snapshot=task_facts)
        session=ChatSession(mode="builtin",purpose="qa",title=("深入讲解 · "+("、".join(names) or learning_problem))[:200]);db.add(session);db.flush()
        target=ctx.model_copy(update={"conversation_id":session.id,"task_id":None,"surface":"chat","origin":"conversation"})
        text="从今日学习继续讨论"+("「"+"、".join(names)+"」" if names else "这个问题")+"。你这次希望："+learning_problem
        if task_facts:text+=f"。交接时方案包含 {task_facts['question_count']} 道题，"+('已写入今日学习。' if task_facts['has_written_daily_plan'] else '尚未写入今日学习。')
        db.add(ChatMessage(session_id=session.id,role="assistant",content=text,status="completed",metadata_={
            "deep_qa_request_key":str(request_key),"source_session_id":str(source.id),"learning_problem":learning_problem,
            "qa_handoff":handoff.model_dump(mode="json"),"study_context":target.model_dump(mode="json"),"answer_source":"notice"}))
        return {"session_id":str(session.id),"study_context":target.model_dump(mode="json"),"handoff":handoff.model_dump(mode="json")}
