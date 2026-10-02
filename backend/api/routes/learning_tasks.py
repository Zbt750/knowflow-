from uuid import UUID
from fastapi import APIRouter, Request, Depends
from backend.api.deps import get_time_provider
from backend.chat.service import provider_from_settings
from backend.schemas.learning_task import CreateTask, TaskInput, TaskView, ConfirmTask
from backend.services.learning_task_service import create_task, get_task, modify_task, cancel_task, run_task
from backend.services.learning_task_service import confirm_task

router = APIRouter(tags=["learning-tasks"])


@router.post("/learning-tasks/{task_id}/confirm", response_model=TaskView)
def confirm(request: Request, task_id: UUID, body: ConfirmTask, time_provider=Depends(get_time_provider)):
    return confirm_task(request.app.state.session_factory, task_id, body, now=time_provider())


@router.post("/learning-tasks", response_model=TaskView, status_code=201)
def create(request: Request, body: CreateTask):
    return create_task(request.app.state.session_factory, body)


@router.get("/learning-tasks/{task_id}", response_model=TaskView)
def read(request: Request, task_id: UUID):
    return get_task(request.app.state.session_factory, task_id)


@router.patch("/learning-tasks/{task_id}", response_model=TaskView)
def modify(request: Request, task_id: UUID, body: TaskInput):
    return modify_task(request.app.state.session_factory, task_id, body)


@router.post("/learning-tasks/{task_id}/cancel", response_model=TaskView)
def cancel(request: Request, task_id: UUID):
    return cancel_task(request.app.state.session_factory, task_id)


@router.post("/learning-tasks/{task_id}/run", response_model=TaskView)
def run(request: Request, task_id: UUID):
    return run_task(request.app.state.session_factory, task_id, provider_from_settings(request.app.state.settings))
