from uuid import UUID
from fastapi import APIRouter, Request, Depends
from backend.api.deps import get_time_provider
from backend.chat.service import provider_from_settings
from backend.schemas.learning_task import CreateTask, TaskInput, TaskView, ConfirmTask
from backend.services.learning_task_service import create_task, get_task, modify_task, cancel_task, run_task
from backend.services.learning_task_service import confirm_task
from backend.services.home_task_boundary import public_task, reject_generic_home_mutation

router = APIRouter(tags=["learning-tasks"])

from backend.schemas.paper_adjustment import PaperAdjustmentRequest, PaperAdjustmentConfirmation


@router.post('/paper-adjustments', status_code=201)
def propose_paper_adjustment(request: Request, body: PaperAdjustmentRequest,
                             time_provider=Depends(get_time_provider)):
    from backend.services.paper_adjustment_service import propose_adjustment
    return propose_adjustment(request.app.state.session_factory, body, now=time_provider())


@router.post('/paper-adjustments/{task_id}/confirm')
def confirm_paper_adjustment(request: Request, task_id: UUID, body: PaperAdjustmentConfirmation,
                             time_provider=Depends(get_time_provider)):
    from backend.services.paper_adjustment_service import confirm_adjustment
    return confirm_adjustment(request.app.state.session_factory,task_id,body,now=time_provider())


@router.post("/learning-tasks/{task_id}/confirm", response_model=TaskView)
def confirm(request: Request, task_id: UUID, body: ConfirmTask, time_provider=Depends(get_time_provider)):
    reject_generic_home_mutation(request.app.state.session_factory, task_id)
    return public_task(request.app.state.session_factory,
        confirm_task(request.app.state.session_factory, task_id, body, now=time_provider()),now=time_provider())


@router.post("/learning-tasks", response_model=TaskView, status_code=201)
def create(request: Request, body: CreateTask, time_provider=Depends(get_time_provider)):
    return public_task(request.app.state.session_factory,
        create_task(request.app.state.session_factory, body, now=time_provider()),now=time_provider())


@router.get("/learning-tasks/{task_id}", response_model=TaskView)
def read(request: Request, task_id: UUID, time_provider=Depends(get_time_provider)):
    return public_task(request.app.state.session_factory,
        get_task(request.app.state.session_factory, task_id),now=time_provider())


@router.patch("/learning-tasks/{task_id}", response_model=TaskView)
def modify(request: Request, task_id: UUID, body: TaskInput, time_provider=Depends(get_time_provider)):
    reject_generic_home_mutation(request.app.state.session_factory, task_id)
    return public_task(request.app.state.session_factory,
        modify_task(request.app.state.session_factory, task_id, body, now=time_provider()),now=time_provider())


@router.post("/learning-tasks/{task_id}/cancel", response_model=TaskView)
def cancel(request: Request, task_id: UUID, time_provider=Depends(get_time_provider)):
    reject_generic_home_mutation(request.app.state.session_factory, task_id)
    return public_task(request.app.state.session_factory,cancel_task(request.app.state.session_factory, task_id),now=time_provider())


@router.post("/learning-tasks/{task_id}/run", response_model=TaskView)
def run(request: Request, task_id: UUID, time_provider=Depends(get_time_provider)):
    reject_generic_home_mutation(request.app.state.session_factory, task_id)
    return public_task(request.app.state.session_factory,run_task(request.app.state.session_factory, task_id,
        provider_from_settings(request.app.state.settings), now=time_provider()),now=time_provider())
