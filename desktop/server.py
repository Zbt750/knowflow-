"""Same-origin desktop backend and built frontend; no database creation/migration."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import PostgresDsn, TypeAdapter
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from desktop.runtime_paths import RuntimePaths

_PAGES = re.compile(r"(?:study|chat|materials|settings|knowledge(?:/[a-z0-9][a-z0-9._-]{0,119}/lesson)?)/?\Z")
_ASSETS = re.compile(r"assets/[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:js|css|woff2?|ttf|svg|png|ico|webp)\Z")


def validate_boot(paths: RuntimePaths, database_url: str, port: int) -> Path:
    from backend.services.model_settings_service import is_loopback

    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise ValueError("desktop_port_invalid")
    # Validate without ever returning/logging the URL or validation input.
    try:
        dsn = TypeAdapter(PostgresDsn).validate_python(database_url)
        hosts = dsn.hosts()
        allowed = (dsn.scheme == "postgresql+psycopg" and not dsn.query and not dsn.fragment
                   and bool(dsn.path and dsn.path != "/") and bool(hosts)
                   and all(is_loopback(host["host"]) for host in hosts))
    except Exception:
        raise ValueError("desktop_database_url_invalid") from None
    if not allowed:
        raise ValueError("desktop_database_must_be_loopback")
    frontend = paths.resources / "frontend" / "dist"
    index = frontend / "index.html"
    if not index.is_file() or not frontend.resolve().is_relative_to(paths.resources):
        raise ValueError("desktop_frontend_build_missing")
    if any(parent.is_symlink() for parent in (index, *index.parents) if parent != paths.resources):
        raise ValueError("desktop_resource_links_forbidden")
    return frontend


def configure_environment(paths: RuntimePaths, database_url: str, port: int) -> Path:
    """Standalone process only; call before importing backend.main/create_app."""
    frontend = validate_boot(paths, database_url, port)
    # No inherited dev-model key, test capture or remote origin configuration.
    for key in tuple(os.environ):
        if key.upper().startswith(("LLM_", "PG")) or key.upper() == "TEST_DATABASE_URL":
            os.environ.pop(key, None)
    os.environ.update({
        "APP_RUNTIME_PROFILE": "desktop", "APP_ENV": "dev",
        "DESKTOP_RESOURCE_ROOT": str(paths.resources),
        "DATABASE_URL": database_url, "CAPTURE_TEST_EVIDENCE": "false",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "LOCAL_MODEL_SETTINGS_ERROR": "false",
        "ALLOWED_WEB_ORIGINS": json.dumps([f"http://127.0.0.1:{port}", f"http://localhost:{port}"]),
        **{name.upper(): str(path) for name, path in paths.settings_overrides().items()},
    })
    from backend.config import get_settings
    get_settings.cache_clear()
    return frontend


class DesktopFrontend(StaticFiles):
    async def get_response(self, path, scope):
        # StaticFiles normalizes using os.path, hence Windows produces backslashes.
        path = path.replace("\\", "/")
        if scope["method"] not in {"GET", "HEAD"}:
            return JSONResponse({"error": {"code": "invalid_request", "message": "此地址不支持该操作"}}, status_code=405)
        # Never swallow an unknown API or missing asset with a success HTML page.
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "接口不存在"}}, status_code=404)
        if path in {"", "."} or _PAGES.fullmatch(path):
            response = await super().get_response("index.html", scope)
            response.headers["Cache-Control"] = "no-store"
        else:
            if path not in {"index.html", "favicon.svg", "favicon.ico"} and not _ASSETS.fullmatch(path):
                return JSONResponse({"error": {"code": "not_found", "message": "页面不存在"}}, status_code=404)
            response = await super().get_response(path, scope)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; img-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response


def attach_frontend(app, frontend: Path, *, port: int):
    from backend.services.model_settings_service import is_loopback

    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{host}" for host in hosts}

    @app.middleware("http")
    async def desktop_access(request, call_next):
        # Bind loopback in the launcher AND validate Host/peer in the application.
        if (request.headers.get("host", "").lower() not in hosts or not request.client
                or not is_loopback(request.client.host)
                or any(name.lower() == "forwarded" or name.lower().startswith("x-forwarded-") for name in request.headers)
                or (request.headers.get("origin") is not None and request.headers["origin"] not in origins)
                or request.headers.get("sec-fetch-site") == "cross-site"):
            return JSONResponse({"error": {"code": "invalid_request", "message": "本地应用不接受此请求来源"}}, status_code=403)
        return await call_next(request)

    # Existing API routes take priority; only immutable dist is exposed, never resources root.
    app.mount("/", DesktopFrontend(directory=frontend, check_dir=True, follow_symlink=False), name="desktop-frontend")
    return app
