"""QA requests and Planner proposals: two separate confirmations, no grading writes."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from uuid import UUID,uuid4
from sqlalchemy import select
from backend.errors import AppError
from backend.models.practice_request import PracticeRequest
from backend.models.chat import ChatSession,ChatMessage
from backend.models.learning_task import LearningTask
from backend.schemas.learning_assistant import StudyContext,PlannerHandoff
from backend.services.assistant_router import CapabilityRoute
from backend.services.study_context_service import validate_study_context

def view(row,now=None):
    now=now or datetime.now(timezone.utc)
    status=row.status
    if status not in {"accepted","declined"} and row.expires_at<=now:status="expired"
    return {"id":str(row.id),"status":status,"source_conversation_id":str(row.source_conversation_id) if row.source_conversation_id else None,
        "source_message_id":str(row.source_message_id) if row.source_message_id else None,"user_request":row.user_request,
        "details":row.request,"planner_task_id":str(row.planner_task_id) if row.planner_task_id else None,
        "daily_plan_id":str(row.daily_plan_id) if row.daily_plan_id else None,"error_code":row.error_code,
        "created_at":row.created_at.isoformat(),"expires_at":row.expires_at.isoformat(),"handled_at":row.handled_at.isoformat() if row.handled_at else None}

def draft_request(factory,*,ctx,user_id,assistant_id,message,now):
    from backend.services.learning_assistant_service import planner_handoff
    handoff=planner_handoff(factory,ctx=ctx,user_id=user_id,message=message,route=CapabilityRoute("planner","plan",1,"practice_request"),now=now)
    with factory.begin() as db:
        session=db.get(ChatSession,ctx.conversation_id)
        if not session or session.mode!="builtin" or session.purpose!="qa":raise AppError("forbidden",status_code=403)
        old=db.scalar(select(PracticeRequest).where(PracticeRequest.source_message_id==user_id))
        if old:return view(old,now)
        row=PracticeRequest(source_conversation_id=ctx.conversation_id,source_message_id=user_id,user_request=message,
            request={**handoff.model_dump(mode="json"),"reason":"user_requested_practice","learning_problem":message,
                "confirmation_a":False,"confirmation_b":False},expires_at=now+timedelta(days=7),created_at=now)
        db.add(row);db.flush()
        reply=db.get(ChatMessage,assistant_id);reply.metadata_={**reply.metadata_,"practice_request_id":str(row.id),
            "learning_trace":{"resolved_knowledge_node_ids":[str(k) for k in handoff.target_knowledge_node_ids],
                "structured_sections":[],"question_used":False,"origin":"practice_request_draft"}}
        return view(row,now)

def send_request(factory,request_id,*,source_conversation_id,now=None):
    now=now or datetime.now(timezone.utc)
    with factory.begin() as db:
        row=db.get(PracticeRequest,request_id,with_for_update=True)
        if not row:raise AppError("practice_request_not_found",status_code=404)
        if row.source_conversation_id!=source_conversation_id:raise AppError("forbidden",status_code=403)
        if view(row,now)["status"]=="expired":raise AppError("practice_request_expired",status_code=409)
        if row.status in {"pending","planning","proposed","accepted"}:return view(row,now)
        if row.status!="draft":raise AppError("practice_request_conflict",status_code=409)
        if not row.request.get("target_knowledge_node_ids"):raise AppError("practice_scope_required",status_code=422)
        row.status="pending";row.request={**row.request,"confirmation_a":True}
        return view(row,now)

def decline_request(factory,request_id,*,now=None):
    from backend.services.learning_task_service import cancel_task
    with factory.begin() as db:
        row=db.get(PracticeRequest,request_id,with_for_update=True)
        if not row:raise AppError("practice_request_not_found",status_code=404)
        if row.status=="accepted":raise AppError("practice_request_conflict",status_code=409)
        row.status="declined";row.handled_at=now or datetime.now(timezone.utc);task_id=row.planner_task_id
    if task_id:cancel_task(factory,task_id)
    with factory() as db:return view(db.get(PracticeRequest,request_id),now)

def list_requests(factory,*,source_conversation_id=None,now=None):
    now=now or datetime.now(timezone.utc)
    with factory.begin() as db:
        query=select(PracticeRequest).order_by(PracticeRequest.created_at.desc()).limit(100)
        if source_conversation_id:query=query.where(PracticeRequest.source_conversation_id==source_conversation_id)
        else:query=query.where(PracticeRequest.status.in_(["pending","planning","proposed","failed"]))
        rows=list(db.scalars(query.with_for_update(skip_locked=True)))
        for row in rows:
            if row.status=="proposed" and row.planner_task_id:
                task=db.get(LearningTask,row.planner_task_id)
                date=((task.context or {}).get("current_plan") or {}).get("study_date") if task else None
                if date and date!=now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat():row.status='expired';row.error_code='stale_proposal'
            if row.status=="planning":
                task=db.get(LearningTask,row.planner_task_id) if row.planner_task_id else None
                if task and task.status=="ready" and task.draft:row.status="proposed"
                elif task and task.status in {"failed","cancelled"}:row.status="failed";row.error_code=task.error_code or "planning_interrupted"
                elif row.request.get("planning_started_at") and now-datetime.fromisoformat(row.request["planning_started_at"])>timedelta(minutes=6):
                    row.status="failed";row.error_code="planning_interrupted"
        return [view(r,now) for r in rows]

def plan_request(factory,request_id,*,study_session_id,provider,now=None):
    from backend.services.learning_assistant_service import prepare_planner,task_is_current
    from backend.services.learning_task_service import get_task,run_task
    now=now or datetime.now(timezone.utc);token=str(uuid4())
    with factory.begin() as db:
        row=db.get(PracticeRequest,request_id,with_for_update=True)
        if not row:raise AppError("practice_request_not_found",status_code=404)
        session=db.get(ChatSession,study_session_id)
        if not session or session.mode!="builtin" or session.purpose!="study":raise AppError("forbidden",status_code=403)
        if view(row,now)["status"]=="expired":raise AppError("practice_request_expired",status_code=409)
        if row.status=="proposed" and row.planner_task_id:
            prior=db.get(LearningTask,row.planner_task_id)
            if prior and task_is_current(prior,now):return {"request":view(row,now),"task":get_task(factory,prior.id).model_dump(mode="json")}
            raise AppError("practice_request_expired",status_code=409)
        if row.status=="planning":
            if row.planner_task_id:return {"request":view(row,now),"task":get_task(factory,row.planner_task_id).model_dump(mode="json")}
            raise AppError("practice_request_busy",status_code=409)
        if row.status not in {"pending","failed"} or not row.request.get("confirmation_a"):raise AppError("practice_request_conflict",status_code=409)
        ctx=validate_study_context(db,session_id=study_session_id,context=StudyContext(surface="study",knowledge_node_ids=[UUID(k) for k in row.request.get("target_knowledge_node_ids",[])]),now=now)
        handoff=PlannerHandoff.model_validate({k:v for k,v in row.request.items() if k in PlannerHandoff.model_fields})
        old_task_id=row.planner_task_id if row.status=="failed" else None
        row.status="planning";row.request={**row.request,"planning_token":token,"planning_started_at":now.isoformat()};row.error_code=None
    try:
        if old_task_id:
            from backend.services.learning_task_service import cancel_task
            cancel_task(factory,old_task_id)
        task=prepare_planner(factory,ctx=ctx,handoff=handoff,now=now)
        with factory.begin() as db:
            row=db.get(PracticeRequest,request_id,with_for_update=True)
            if row.status!="planning" or row.request.get("planning_token")!=token:
                from backend.services.learning_task_service import cancel_task
                cancel_task(factory,task.task_id);raise AppError("practice_request_conflict",status_code=409)
            row.planner_task_id=task.task_id
            stored=db.get(LearningTask,task.task_id);stored.context={**stored.context,"practice_request_id":str(request_id)}
        result=run_task(factory,task.task_id,provider,now=now)
        with factory.begin() as db:
            row=db.get(PracticeRequest,request_id,with_for_update=True)
            if row.status=="planning" and row.request.get("planning_token")==token:
                row.status="proposed" if result.status=="ready" and result.draft and result.draft.get('questions') else "failed"
                row.error_code=None if row.status=="proposed" else result.error_code or "insufficient_practice_inventory"
                row.handled_at=now
            return {"request":view(row,now),"task":result.model_dump(mode="json")}
    except Exception as exc:
        with factory.begin() as db:
            row=db.get(PracticeRequest,request_id,with_for_update=True)
            if row.status=="planning" and row.request.get("planning_token")==token:row.status="failed";row.error_code=exc.code if isinstance(exc,AppError) else "internal_error"
        raise
