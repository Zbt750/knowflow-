"""Local model settings: no secret in responses; Windows DPAPI at rest."""
from __future__ import annotations

import ctypes
import ipaddress
import json
import os
import secrets
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from backend.config import Settings
from backend.errors import AppError

SETTINGS_LOCK = Lock()


class ModelSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    api_key: SecretStr | None = None
    clear_key: bool = False
    max_output_tokens: int = Field(default=4000, ge=256, le=32768)
    timeout_seconds: float = Field(default=60, ge=5, le=180)

    @field_validator("model")
    @classmethod
    def model_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("invalid model name")
        return value

    @field_validator("api_key")
    @classmethod
    def key_value(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        raw = value.get_secret_value().strip()
        if len(raw) > 4096 or any(ord(char) < 32 for char in raw):
            raise ValueError("invalid key")
        return SecretStr(raw) if raw else None

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        try:
            parsed.port
        except ValueError:
            raise ValueError("invalid endpoint") from None
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(char.isspace() for char in value):
            raise ValueError("invalid endpoint")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback(parsed.hostname)):
            raise ValueError("HTTPS required except for a loopback endpoint")
        return value


class ModelSettingsView(BaseModel):
    base_url: str
    model: str
    key_configured: bool
    max_output_tokens: int
    timeout_seconds: float
    csrf_token: str
    storage_warning: bool = False


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        if getattr(address, "ipv4_mapped", None):
            address = address.ipv4_mapped
        return address.is_loopback
    except ValueError:
        return False


def authorize_local(request: Request) -> str:
    settings = request.app.state.settings
    host = request.headers.get("host", "")
    try:
        hostname = urlsplit("//" + host).hostname or ""
    except ValueError:
        hostname = ""
    if settings.app_env != "dev" or not request.client or not is_loopback(request.client.host) or not is_loopback(hostname):
        raise AppError("settings_local_only")
    if any(name.lower() == "forwarded" or name.lower().startswith("x-forwarded-") for name in request.headers):
        raise AppError("settings_local_only")
    origin = request.headers.get("origin")
    permitted = {f"{request.url.scheme}://{host}", "http://localhost:5173", "http://127.0.0.1:5173"}
    if (origin and origin not in permitted) or request.headers.get("sec-fetch-site") == "cross-site":
        raise AppError("settings_local_only")
    with SETTINGS_LOCK:
        if not getattr(request.app.state, "settings_csrf_token", None):
            request.app.state.settings_csrf_token = secrets.token_urlsafe(32)
        return request.app.state.settings_csrf_token


def _dpapi(data: bytes, decrypt: bool = False) -> bytes:
    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise OSError("system credential protection failed")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


def encode_settings(data: bytes) -> bytes:
    if os.name == "nt":
        return b"DPAPI1\n" + _dpapi(data)
    # Do not silently persist API credentials in clear text on platforms where
    # this application has no OS-backed credential store implementation.
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OSError("secure local credential storage is unavailable") from error
    if payload.get("api_key"):
        raise OSError("secure local credential storage is unavailable")
    return b"LOCAL1\n" + data


def decode_settings(data: bytes) -> bytes:
    if data.startswith(b"DPAPI1\n") and os.name == "nt":
        return _dpapi(data[7:], decrypt=True)
    if data.startswith(b"LOCAL1\n") and os.name != "nt":
        payload = json.loads(data[7:].decode("utf-8"))
        if payload.get("api_key"):
            raise ValueError("refusing to load a plaintext model API key")
        return data[7:]
    raise ValueError("unsupported local settings format")


def apply_update(settings: Settings, body: ModelSettingsUpdate) -> Settings:
    key = None if body.clear_key else body.api_key or settings.llm_api_key
    return settings.model_copy(update={
        "llm_base_url": body.base_url, "llm_model": body.model, "llm_api_key": key,
        "llm_max_output_tokens": body.max_output_tokens, "llm_timeout_seconds": body.timeout_seconds,
        "llm_retry_max_output_tokens": max(settings.llm_retry_max_output_tokens, body.max_output_tokens),
        "local_model_settings_error": False,
    })


def persist_settings(settings: Settings, body: ModelSettingsUpdate) -> None:
    path = settings.model_settings_path
    payload = body.model_dump(mode="json")
    payload["api_key"] = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    payload["clear_key"] = not bool(payload["api_key"])
    temporary: Path | None = None
    try:
        encrypted = encode_settings(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(encrypted)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError):
        raise AppError("settings_storage_failed") from None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)


def load_local_settings(settings: Settings) -> Settings:
    if settings.app_env != "dev" or not settings.model_settings_path.exists():
        return settings
    try:
        body = ModelSettingsUpdate.model_validate_json(decode_settings(settings.model_settings_path.read_bytes()))
        return apply_update(settings, body)
    except (OSError, ValueError):
        # Keep the app/settings page available, but do not silently use an older key.
        return settings.model_copy(update={"llm_api_key": None, "local_model_settings_error": True})


def settings_view(settings: Settings, token: str) -> ModelSettingsView:
    return ModelSettingsView(base_url=settings.llm_base_url or "", model=settings.llm_model or "", key_configured=bool(settings.llm_api_key and settings.llm_api_key.get_secret_value()), max_output_tokens=settings.llm_max_output_tokens, timeout_seconds=settings.llm_timeout_seconds, csrf_token=token, storage_warning=settings.local_model_settings_error)
