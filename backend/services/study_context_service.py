"""Resolve every study identifier server-side; never trust client state text."""
from datetime import datetime, timezone
from sqlalchemy import select
from backend.errors import AppError
from backend.models.chat import ChatSession
from backend.models.learning import KnowledgePoint, Question, QuestionAttempt, PracticeItem, DailyPlan
from backend.models.learning_task import LearningTask
from backend.models.rag import Material, DocumentChunk
from backend.schemas.learning_assistant import StudyContext


def invalid():
    raise AppError("study_context_invalid", status_code=422)


def validate_study_context(db, *, session_id, context=None, now=None):
    session=db.get(ChatSession, session_id)
    if session is None or session.archived_at is not None: raise AppError("chat_session_not_found", status_code=404)
    ctx=(context or StudyContext()).model_copy(deep=True)
    if ctx.conversation_id and ctx.conversation_id!=session_id: invalid()
    ctx.conversation_id=session_id
    ctx.generated_at=now or datetime.now(timezone.utc)
    item=db.get(PracticeItem,ctx.practice_item_id) if ctx.practice_item_id else None
    if ctx.practice_item_id and item is None: invalid()
    if item:
        if item.question_id is None: invalid()
        if ctx.question_id and ctx.question_id!=item.question_id: invalid()
        if ctx.daily_plan_id and ctx.daily_plan_id!=item.plan_id: invalid()
        ctx.question_id,ctx.daily_plan_id=item.question_id,item.plan_id
    q=db.get(Question,ctx.question_id) if ctx.question_id else None
    if ctx.question_id and q is None: invalid()
    attempt=db.get(QuestionAttempt,ctx.attempt_id) if ctx.attempt_id else None
    if ctx.attempt_id and attempt is None: invalid()
    if attempt:
        if q and attempt.question_id!=q.id: invalid()
        if item and attempt.practice_item_id!=item.id: invalid()
        if not item:
            item=db.get(PracticeItem,attempt.practice_item_id)
            if not item or item.question_id!=attempt.question_id: invalid()
            if ctx.daily_plan_id and ctx.daily_plan_id!=item.plan_id: invalid()
            ctx.practice_item_id,ctx.daily_plan_id=item.id,item.plan_id
        ctx.question_id=attempt.question_id
        q=db.get(Question,ctx.question_id)
        if q is None: invalid()
    plan=db.get(DailyPlan,ctx.daily_plan_id) if ctx.daily_plan_id else None
    if ctx.daily_plan_id and plan is None: invalid()
    if plan and q and not item:
        linked=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==plan.id,PracticeItem.question_id==q.id))
        if not linked: invalid()
        ctx.practice_item_id=linked.id; item=linked
    ids=list(dict.fromkeys(ctx.knowledge_node_ids))
    if q:
        if ids and ids!=[q.kp_id]: invalid()
        ids=[q.kp_id]
    nodes=[db.get(KnowledgePoint,k) for k in ids]
    if any(n is None or not n.is_active for n in nodes): invalid()
    if plan and ids and not q:
        plan_scope=set(db.scalars(select(PracticeItem.kp_id).where(PracticeItem.plan_id==plan.id)))
        if not set(ids).issubset(plan_scope): invalid()
    if session.mode=="user" and (q or attempt or ids or ctx.task_id or ctx.daily_plan_id):
        raise AppError("forbidden", status_code=403)
    subjects={n.subject for n in nodes}
    aliases={"数学二":"考研数学","math2":"考研数学"}
    if ctx.subject and subjects and aliases.get(ctx.subject,ctx.subject) not in subjects: invalid()
    if ctx.subject and not subjects:
        if db.scalar(select(KnowledgePoint.id).where(KnowledgePoint.subject==aliases.get(ctx.subject,ctx.subject),KnowledgePoint.is_active.is_(True)).limit(1)) is None: invalid()
        ctx.subject=aliases.get(ctx.subject,ctx.subject)
    if len(subjects)==1: ctx.subject=next(iter(subjects))
    ctx.knowledge_node_ids=ids
    material=db.get(Material,ctx.material_id) if ctx.material_id else None
    chunk=db.get(DocumentChunk,ctx.chunk_id) if ctx.chunk_id else None
    if ctx.chunk_id and chunk is None: invalid()
    if chunk:
        if ctx.material_id and chunk.material_id!=ctx.material_id: invalid()
        material=db.get(Material,chunk.material_id); ctx.material_id=chunk.material_id
    if ctx.material_id and material is None: invalid()
    if material:
        if material.source_type!=session.mode: raise AppError("forbidden",status_code=403)
        if session.material_scope_ids and str(material.id) not in session.material_scope_ids:raise AppError("forbidden",status_code=403)
        if material.status!="ready": raise AppError("material_not_ready",status_code=409)
        if chunk and chunk.index_version!=material.active_index_version: invalid()
    if ctx.task_id:
        task=db.get(LearningTask,ctx.task_id)
        if not task or task.session_id!=session_id: invalid()
    return ctx
