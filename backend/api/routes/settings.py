from fastapi import APIRouter, Request, Response, Header
import secrets

from backend.errors import AppError
from backend.services.model_settings_service import (
    ModelSettingsUpdate, ModelSettingsView, SETTINGS_LOCK,
    apply_update, authorize_local, persist_settings, settings_view,
)

router = APIRouter(tags=["settings"])


@router.get("/settings/model", response_model=ModelSettingsView)
def read_model_settings(request: Request, response: Response) -> ModelSettingsView:
    response.headers["Cache-Control"] = "no-store"
    token = authorize_local(request)
    return settings_view(request.app.state.settings, token)


@router.put("/settings/model", response_model=ModelSettingsView)
def update_model_settings(request: Request, body: ModelSettingsUpdate, response: Response, x_settings_token: str | None = Header(default=None)) -> ModelSettingsView:
    response.headers["Cache-Control"] = "no-store"
    token = authorize_local(request)
    supplied = x_settings_token or ""
    if not secrets.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
        raise AppError("settings_token_invalid")
    with SETTINGS_LOCK:
        updated = apply_update(request.app.state.settings, body)
        persist_settings(updated, body)
        request.app.state.settings = updated
    return settings_view(updated, token)
