from uuid import UUID
from fastapi import APIRouter,Request,Depends
from pydantic import BaseModel
from datetime import datetime
from typing import Literal
from backend.schemas.learning_task import TaskView
from backend.api.deps import get_time_provider
from backend.chat.service import provider_from_settings
from backend.services.practice_request_service import list_requests,send_request,decline_request,plan_request
from backend.models.practice_request import PracticeRequest
from backend.services.practice_request_service import view
from backend.errors import AppError
router=APIRouter(tags=["practice-requests"])
class SendRequest(BaseModel):
    source_conversation_id:UUID
    target_study_session_id:UUID|None=None
class PlanRequest(BaseModel):study_session_id:UUID
class PracticeRequestView(BaseModel):
    id:UUID
    status:Literal["draft","pending","planning","proposed","accepted","declined","expired","failed"]
    source_conversation_id:UUID|None
    source_message_id:UUID|None
    user_request:str
    details:dict
    planner_task_id:UUID|None
    daily_plan_id:UUID|None
    error_code:str|None
    created_at:datetime
    expires_at:datetime
    handled_at:datetime|None
class PracticeProposal(BaseModel):
    request:PracticeRequestView
    task:TaskView
@router.get("/practice-requests/{request_id}",response_model=PracticeRequestView)
def read(request:Request,request_id:UUID,time_provider=Depends(get_time_provider)):
    with request.app.state.session_factory() as db:
        row=db.get(PracticeRequest,request_id)
        if not row:raise AppError("practice_request_not_found",status_code=404)
        return view(row,time_provider())
@router.get("/practice-requests",response_model=list[PracticeRequestView])
def listing(request:Request,source_conversation_id:UUID|None=None,time_provider=Depends(get_time_provider)):
    return list_requests(request.app.state.session_factory,source_conversation_id=source_conversation_id,now=time_provider())
@router.post("/practice-requests/{request_id}/send",response_model=PracticeRequestView)
def send(request:Request,request_id:UUID,body:SendRequest,time_provider=Depends(get_time_provider)):
    return send_request(request.app.state.session_factory,request_id,source_conversation_id=body.source_conversation_id,
        target_study_session_id=body.target_study_session_id,now=time_provider())
@router.post("/practice-requests/{request_id}/decline",response_model=PracticeRequestView)
def decline(request:Request,request_id:UUID,time_provider=Depends(get_time_provider)):
    return decline_request(request.app.state.session_factory,request_id,now=time_provider())
@router.post("/practice-requests/{request_id}/plan",response_model=PracticeProposal)
def plan(request:Request,request_id:UUID,body:PlanRequest,time_provider=Depends(get_time_provider)):
    return plan_request(request.app.state.session_factory,request_id,study_session_id=body.study_session_id,
        provider=provider_from_settings(request.app.state.settings),now=time_provider())
