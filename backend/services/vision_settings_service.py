"""Independent local vision credentials; never copy or return the chat key."""
import json
import os
import secrets

from backend.errors import AppError
from backend.services.model_settings_service import (
    ModelSettingsUpdate, ModelSettingsView, decode_settings, encode_settings,
)


class VisionSettingsUpdate(ModelSettingsUpdate):
    reuse_chat_model: bool = True


class VisionSettingsView(ModelSettingsView):
    reuse_chat_model: bool
    configured: bool


def settings_path(settings):
    return settings.model_settings_path.with_name("vision-model-settings.bin")


def load_vision_settings(settings):
    path = settings_path(settings)
    if not path.exists():
        return VisionSettingsUpdate(base_url="https://api.deepseek.com", model="deepseek-flash"), False
    try:
        return VisionSettingsUpdate.model_validate_json(decode_settings(path.read_bytes())), False
    except (OSError, ValueError):
        # Corrupt independent config must not silently fall back to the chat key.
        return VisionSettingsUpdate(base_url="https://api.deepseek.com", model="deepseek-flash",
                                    reuse_chat_model=False), True


def vision_settings_view(settings, token):
    body, warning = load_vision_settings(settings)
    key = settings.llm_api_key if body.reuse_chat_model else body.api_key
    configured = bool(not warning and key and key.get_secret_value()
                      and (settings.llm_model and settings.llm_base_url if body.reuse_chat_model else True))
    return VisionSettingsView(base_url=body.base_url, model=body.model,
                              max_output_tokens=body.max_output_tokens, timeout_seconds=body.timeout_seconds,
                              key_configured=bool(body.api_key and body.api_key.get_secret_value()),
                              reuse_chat_model=body.reuse_chat_model, configured=configured,
                              csrf_token=token, storage_warning=warning)


def save_vision_settings(settings, body):
    previous, warning = load_vision_settings(settings)
    key = None if body.clear_key else body.api_key or (previous.api_key if not warning else None)
    payload = body.model_dump(mode="json")
    payload["api_key"] = key.get_secret_value() if key else None
    payload["clear_key"] = not bool(key)
    path = settings_path(settings)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        encrypted = encode_settings(json.dumps(payload).encode("utf-8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encrypted)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError):
        raise AppError("settings_storage_failed") from None
    finally:
        temporary.unlink(missing_ok=True)


def effective_vision_settings(settings):
    body, warning = load_vision_settings(settings)
    if warning:
        raise AppError("vision_not_configured")
    if body.reuse_chat_model:
        effective = settings.model_copy()
    else:
        effective = settings.model_copy(update={"llm_base_url": body.base_url, "llm_model": body.model,
                                                "llm_api_key": body.api_key,
                                                "llm_timeout_seconds": body.timeout_seconds,
                                                "llm_max_output_tokens": body.max_output_tokens})
    if not effective.llm_api_key or not effective.llm_api_key.get_secret_value() or not effective.llm_model or not effective.llm_base_url:
        raise AppError("vision_not_configured")
    return effective
