from fastapi import APIRouter, Request, Response, Header
import secrets

from backend.errors import AppError
from backend.services.model_settings_service import (
    ModelSettingsUpdate, ModelSettingsView, SETTINGS_LOCK,
    apply_update, authorize_local, persist_settings, settings_view,
)

from backend.services.vision_settings_service import (
    VisionSettingsUpdate, VisionSettingsView, save_vision_settings, vision_settings_view,
)

router = APIRouter(tags=["settings"])


@router.get("/settings/vision", response_model=VisionSettingsView)
def read_vision_settings(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return vision_settings_view(request.app.state.settings, authorize_local(request))


@router.put("/settings/vision", response_model=VisionSettingsView)
def update_vision_settings(request: Request, body: VisionSettingsUpdate, response: Response,
                           x_settings_token: str | None = Header(default=None)):
    response.headers["Cache-Control"] = "no-store"
    token = authorize_local(request)
    if not secrets.compare_digest((x_settings_token or "").encode(), token.encode()):
        raise AppError("settings_token_invalid")
    with SETTINGS_LOCK:
        save_vision_settings(request.app.state.settings, body)
    return vision_settings_view(request.app.state.settings, token)


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
