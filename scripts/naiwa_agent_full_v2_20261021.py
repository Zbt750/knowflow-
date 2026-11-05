"""Scoped real-browser V2 acceptance runtime for the retained isolated station.

This wrapper uses the real Vue/FastAPI business routes and an isolated DB. It
starts sealed, records every physical HTTPX dispatch in a fresh 40-call ledger,
and permits writes only through enumerated UI routes in registered sessions.
It does not run migrations, seed data, or clean the retained database.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.restore_naiwa_experience_20261020 import (  # noqa: E402
    DATABASE,
    HOME,
    MODULES,
    RUN as OLD_RUN,
    existing_manager,
    database_url,
    save,
)
DATABASE = os.environ.get("NAIWA_ISOLATED_DATABASE", DATABASE)
from scripts.naiwa_freeze_gate_20261021 import (  # noqa: E402
    BudgetStop,
    FinalRoundGate,
    ROUND,
    SCENE,
    atomic_json,
    disable_provider_retries,
    process_started,
)

OUT = ROOT / "storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021"
RUN = HOME / "agent-full-v2-20261021"
LEDGER_DIR = OUT
LEDGER_PATH = LEDGER_DIR / "provider-ledger.json"
CONTROL_PATH = LEDGER_DIR / "control.json"
BASELINE_PATH = OUT / "v2-baseline.json"
ACTIVE_SOURCE_PATH = RUN / "active-source-hashes.json"
SCENE_CAPS = {"A": 4, "B": 5, "C": 7, "D": 7, "E": 5, "F": 4, "H": 4, "R": 4}
TEXT_PURPOSES = {"agent_text", "text_completion", "text_stream", "classification"}
PURPOSE_POLICY = {name: TEXT_PURPOSES | ({"variant_generation"} if name in {"C", "R"} else set())
                  for name in SCENE_CAPS}
OLD_LEDGERS = [
    ROOT / "storage/quality-audits/naiwa-real-20261020/provider-ledger.json",
    ROOT / "storage/quality-audits/naiwa-real-retest-20261020-budget7/provider-ledger.json",
    ROUND / "provider-ledger.json",
]
TABLES = (
    "chat_sessions", "chat_messages", "questions", "question_versions", "knowledge_points",
    "daily_plans", "practice_items", "question_attempts", "learning_events", "learning_tasks",
    "practice_requests",
    "personal_generation_batches", "materials", "document_chunks", "message_citations", "kp_states",
)
TASK_ATTACHMENT = Path(r"C:\Users\ZBT\.codex\attachments\9f074547-9a08-459e-a7fb-e28725215cdf\已粘贴的文本.txt")
DAILY_PORTS = (5433, 8000, 5173)
PORTS = (63044, 63045, 63046)
EXPERIENCE_HEADER = "naiwa-agent-full-v2-20261021"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files() -> list[Path]:
    result = [ROOT / Path(*name.split(".")).with_suffix(".py") for name in MODULES]
    result.extend([
        ROOT / "scripts/restore_naiwa_experience_20261020.py",
        ROOT / "scripts/naiwa_freeze_gate_20261021.py",
        Path(__file__).resolve(),
        ROOT / "backend/api/routes/chat.py",
        ROOT / "backend/api/routes/learning_tasks.py",
        ROOT / "backend/api/routes/study.py",
        ROOT / "backend/services/assistant_router.py",
        ROOT / "backend/services/assistant_data_queries.py",
        ROOT / "backend/services/composite_bank_plan.py",
        ROOT / "backend/services/material_search_service.py",
        ROOT / "backend/services/question_generation.py",
        ROOT / "backend/services/personal_question_service.py",
        ROOT / "backend/services/generation_formula_consistency.py",
        ROOT / "backend/chat/http_clients.py",
    ])
    result.extend(p for p in (ROOT / "frontend/src").rglob("*") if p.is_file())
    result.extend([ROOT / "frontend/vite.config.ts", ROOT / "frontend/package.json"])
    return sorted(set(p.resolve() for p in result if p.is_file()))


def source_hashes() -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files()}


def assert_ports_free() -> None:
    for port in DAILY_PORTS + PORTS:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"required_port_not_free:{port}") from exc


def pg_owner_preflight(allow_live_identity=None):
    pg = existing_manager()
    assert pg.owner["cluster_id"] == "eb3800c77c3c40f6ac12eb21112df36c"
    assert pg.cluster.resolve() == (HOME / "owned-pg/KaoyanStudy/postgres/cluster").resolve()
    assert (pg.cluster / "PG_VERSION").read_text(encoding="ascii").strip() == "18"
    identity = pg._identity()
    if identity:
        try:
            process_started(identity[0])
        except ProcessLookupError:
            stale_pid = True
        else:
            expected = allow_live_identity
            if expected is None and (OUT / "runtime-v2.json").is_file():
                runtime_state = read(OUT / "runtime-v2.json")
                if runtime_state.get("status") in {"starting", "running"}:
                    expected = tuple(runtime_state["postgres_identity"])
            if expected is None or identity != tuple(expected):
                raise RuntimeError("retained_pg_pid_is_live_or_reused_stop_for_identity_check")
            stale_pid = False
    else:
        stale_pid = False
    return pg, {"cluster_id": pg.owner["cluster_id"], "cluster": str(pg.cluster.resolve()),
                "port": pg.port, "database": DATABASE, "role": "kaoyan_app",
                "postmaster_identity": list(identity) if identity else None,
                "postmaster_pid_proven_stale": stale_pid,
                "owner_marker_sha256": sha(pg.marker), "credentials_sha256": sha(pg.credentials)}


def prepare() -> None:
    if not TASK_ATTACHMENT.is_file():
        raise RuntimeError("authorized_task_attachment_not_found")
    assert_ports_free()
    pg, owner = pg_owner_preflight()
    runtime = read(OLD_RUN / "runtime.json")
    assert runtime["cluster_id"] == owner["cluster_id"]
    assert runtime["database"] == {"db": DATABASE, "role": "kaoyan_app", "port": "63044"}
    assert read(HOME / "initialized.json")["synthetic_test_data"] is True
    assert read(HOME / "control.json")["paid_enabled"] is False
    old_hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in OLD_LEDGERS}
    baseline_path = ROOT / "storage/quality-audits/naiwa-final-zero-precheck-20261021/ledger-verification.json"
    previous = read(baseline_path)
    assert previous["counts"] == [19, 5, 0]
    assert previous["unchanged"] is True
    assert len(SCENE_CAPS) == 8 and sum(SCENE_CAPS.values()) == 40
    if RUN.exists():
        raise RuntimeError("v2_run_directory_already_exists_do_not_reuse")
    OUT.mkdir(parents=True, exist_ok=True)
    prior_files = {p.name for p in OUT.iterdir()}
    if prior_files - {"gate-junit.xml", "gate-v2-final-junit.xml"}:
        raise RuntimeError("v2_audit_directory_contains_unexpected_prior_files")
    RUN.mkdir(parents=True, exist_ok=False)
    gate = FinalRoundGate(LEDGER_DIR, simulated=False, preparation=False,
        global_limit=40, scene_caps=SCENE_CAPS, purpose_policy=PURPOSE_POLICY,
        seal_on_scene_cap=False)
    assert gate.records == [] and read(CONTROL_PATH)["paid_enabled"] is False
    hashes = source_hashes()
    save(ACTIVE_SOURCE_PATH, {"epoch": 0, "source_sha256": hashes, "recorded_at": time.time()})
    save(RUN / "authorization.json", {
        "explicit_attachment_authorization": True,
        "attachment_sha256": sha(TASK_ATTACHMENT), "global_physical_request_cap": 40,
        "scene_caps": SCENE_CAPS, "scene_budget_transfer": False,
        "real_model_exit_enabled": False, "provider_key_logged": False,
    })
    save(BASELINE_PATH, {
        "created_at": time.time(), "workspace": str(ROOT), "isolated_database": DATABASE,
        "cluster": owner, "old_ledger_sha256": old_hashes,
        "prior_zero_precheck_ledger_sha256": previous["sha256"],
        "current_v2_ledger": str(LEDGER_PATH), "current_v2_count": 0,
        "current_paid_enabled": False, "scene_caps": SCENE_CAPS,
        "purpose_policy": {k: sorted(v) for k, v in PURPOSE_POLICY.items()},
        "attachment_sha256": sha(TASK_ATTACHMENT), "source_epoch_0": hashes,
        "daily_ports_listened": False, "no_model_requests": True,
    })
    gate.uninstall()
    print("PREPARED: isolated owner verified; V2 ledger=0/40; paid switch remains closed; no DB/model operation")


def snapshot_database(path: Path, *, allow_live_identity=None) -> dict:
    from sqlalchemy import create_engine, text
    pg, _owner = pg_owner_preflight(allow_live_identity=allow_live_identity)
    engine = create_engine(database_url(pg))
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                identity = dict(connection.execute(text(
                    "SELECT current_database() AS db,current_user AS role,current_setting('port') AS port"
                )).one()._mapping)
                revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                data = {table: [dict(row._mapping) for row in connection.execute(text(
                    "SELECT * FROM public." + table
                ))] for table in TABLES}
                data["identity"] = identity
                data["schema_revision"] = revision
        clean = json.loads(json.dumps(data, ensure_ascii=False, default=str))
        save(path, clean)
        return clean
    finally:
        engine.dispose()


def _row_multiset(rows):
    return sorted(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in rows)


def compare_snapshot(before: dict, after: dict, *, mutable_session_ids=(), mutable_plan_id=None,
                     mutable_practice_request_ids=()) -> dict:
    mutable_sessions = {str(v) for v in mutable_session_ids}
    mutable_practice_requests = {str(v) for v in mutable_practice_request_ids}
    diff = {"tables": {}, "preexisting_rows_preserved": True}
    for table in TABLES:
        old_rows = before.get(table, [])
        new_rows = after.get(table, [])
        mutable = set()
        if table == "chat_sessions":
            mutable = mutable_sessions
        elif table == "daily_plans" and mutable_plan_id:
            mutable = {str(mutable_plan_id)}
        elif table == "practice_requests":
            mutable = mutable_practice_requests
        kept_old = [row for row in old_rows if str(row.get("id", "")) not in mutable]
        kept_new = [row for row in new_rows if str(row.get("id", "")) not in mutable]
        old_bag, new_bag = _row_multiset(kept_old), _row_multiset(kept_new)
        # Every pre-existing row outside the narrowly authorized UI-owned
        # session/current plan must remain byte-equivalent; extra new rows are OK.
        remaining = list(new_bag)
        missing = []
        for row in old_bag:
            try:
                remaining.remove(row)
            except ValueError:
                missing.append(row)
        diff["tables"][table] = {
            "before": len(old_rows), "after": len(new_rows),
            "added": max(0, len(new_rows) - len(old_rows)), "missing_or_changed_preexisting": len(missing),
            "authorized_mutable_preexisting": len(mutable & {str(r.get("id", "")) for r in old_rows}),
        }
        if missing:
            diff["preexisting_rows_preserved"] = False
    return diff


def verify_integrity(*, gate=None, scene=None, request=None):
    active = read(ACTIVE_SOURCE_PATH)
    current_hashes = source_hashes()
    if current_hashes != active["source_sha256"]:
        raise RuntimeError("unrecorded_source_hash_change")
    baseline = read(BASELINE_PATH)
    if {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in OLD_LEDGERS} != baseline["old_ledger_sha256"]:
        raise RuntimeError("protected_historical_ledger_changed")
    mutable = read(RUN / "session-registry.json") if (RUN / "session-registry.json").exists() else {"sessions": []}
    snapshot = snapshot_database(OUT / "integrity-current.json")
    before = read(OUT / "database-before.json")
    plan_id = read(RUN / "runtime-data.json").get("today_plan_id") if (RUN / "runtime-data.json").exists() else None
    diff = compare_snapshot(before, snapshot,
        mutable_session_ids=[s["session_id"] for s in mutable.get("sessions", [])], mutable_plan_id=plan_id)
    if not diff["preexisting_rows_preserved"]:
        save(OUT / "integrity-failure.json", {"scene": scene, "request_id": getattr(request, "url", None).__str__(),
            "diff": diff, "time": time.time()})
        raise RuntimeError("preexisting_database_rows_changed")
    save(OUT / "latest-integrity-diff.json", {"scene": scene, "diff": diff, "time": time.time()})


def _load_live_settings():
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    settings = get_settings()
    effective = load_local_settings(settings)
    key = effective.llm_api_key
    key = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key or "")
    if not key or effective.llm_model != "deepseek-flash" or effective.llm_base_url.rstrip("/") != "https://api.deepseek.com":
        raise RuntimeError("authorized_deepseek_configuration_unavailable")
    return effective, key


def _read_db_registry(factory, task_id: str) -> bool:
    from sqlalchemy import select
    from backend.models.learning_task import LearningTask
    sessions = read(RUN / "session-registry.json").get("sessions", [])
    ids = {UUID(row["session_id"]) for row in sessions}
    try:
        tid = UUID(task_id)
    except ValueError:
        return False
    with factory() as db:
        task = db.get(LearningTask, tid)
        return bool(task and task.session_id in ids)


def real_app():
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    from backend.chat import http_clients
    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    expected_port = int(os.environ.get("NAIWA_ISOLATED_PG_PORT", "63044"))
    expected_database = os.environ.get("NAIWA_ISOLATED_DATABASE", DATABASE)
    if (settings.app_env != "test" or (url.host, url.port, url.database) !=
            ("127.0.0.1", expected_port, expected_database)):
        raise RuntimeError("v2_runtime_database_identity_mismatch")
    if os.environ.get("NAIWA_FRESH_TEST_DATABASE") == "1":
        # Env vars alone never grant access: verify the live database against
        # this disposable runtime's owned cluster marker first.
        from scripts.naiwa_differentiated_test_runtime_20261024 import verify_fresh_database_identity
        verified_identity = verify_fresh_database_identity()
        http_clients.configure_isolated_provider_http(
            settings, verified_fresh_identity=verified_identity)
    else:
        http_clients.configure_isolated_provider_http(settings)
    effective, _key_not_for_manifest = _load_live_settings()
    if effective.llm_model != settings.llm_model or effective.llm_base_url.rstrip("/") != settings.llm_base_url.rstrip("/"):
        raise RuntimeError("provider_settings_disagree")
    gate = FinalRoundGate(LEDGER_DIR, simulated=False, preparation=False,
        global_limit=40, scene_caps=SCENE_CAPS, purpose_policy=PURPOSE_POLICY,
        seal_on_scene_cap=False)
    gate.seal("v2_runtime_started_closed_waiting_for_ui_scene")
    gate.before_send = lambda scene, req: verify_integrity(gate=gate, scene=scene, request=req)
    gate.install()
    sys.addaudithook(gate.socket_guard)
    try:
        sys.audit("socket.connect", None, ("192.0.2.1", 443))
    except BudgetStop:
        pass
    else:
        raise RuntimeError("non_model_network_self_check_failed")

    from backend.chat.service import Provider
    disable_provider_retries(Provider)
    from backend.chat.http_clients import policy
    import httpx
    sync_probe = http_clients.sync_client(timeout=1)
    async_probe = http_clients.async_client(timeout=1)
    transport_probe = {"sync_pool": type(getattr(sync_probe._transport, "_pool", None)).__name__,
                       "async_pool": type(getattr(async_probe._transport, "_pool", None)).__name__,
                       "sync_transport_retries": getattr(getattr(sync_probe._transport, "_pool", None), "_retries", None),
                       "async_transport_retries": getattr(getattr(async_probe._transport, "_pool", None), "_retries", None),
                       "sync_proxy_pool": "Proxy" in type(sync_probe._transport).__name__ or "Proxy" in type(getattr(sync_probe._transport, "_pool", None)).__name__,
                       "async_proxy_pool": "Proxy" in type(async_probe._transport).__name__ or "Proxy" in type(getattr(async_probe._transport, "_pool", None)).__name__}
    sync_probe.close()
    import asyncio
    asyncio.get_running_loop().create_task(async_probe.aclose())
    if (policy()["trust_env"] is not False or transport_probe["sync_proxy_pool"]
            or transport_probe["async_proxy_pool"] or transport_probe["sync_transport_retries"] != 0
            or transport_probe["async_transport_retries"] != 0):
        raise RuntimeError("isolated_http_transport_preflight_failed")

    from backend.app import create_app
    app = create_app()
    app.state.final_round_gate = gate
    runtime_data = read(RUN / "runtime-data.json")
    save(RUN / "loaded-code.json", {
        "pid": os.getpid(), "workspace": str(ROOT), "python": sys.executable,
        "source_sha256": source_hashes(), "source_epoch": read(ACTIVE_SOURCE_PATH)["epoch"],
        "provider": effective.llm_model, "endpoint": "https://api.deepseek.com/chat/completions",
        "provider_key_logged": False, "database": {"db": expected_database, "role": "kaoyan_app", "port": expected_port,
            "cluster_id": runtime_data["cluster_id"]},
        "ports": {"postgres": expected_port,
            "api": int(os.environ.get("NAIWA_ISOLATED_API_PORT", "63045")),
            "web": int(os.environ.get("NAIWA_ISOLATED_WEB_PORT", "63046"))},
        "http_policy": policy(), "transport_probe": transport_probe,
        "network_guard_installed": True, "provider_retries_disabled": True,
        "paid_enabled_on_start": False, "physical_gate": {"ledger": str(LEDGER_PATH),
            "global_limit": 40, "scene_limits": SCENE_CAPS, "purpose_policy":
                {k: sorted(v) for k, v in PURPOSE_POLICY.items()}, "scene_cap_seals_global": False},
        "production_routes_only": True, "loaded_at": time.time(),
    })

    class Scoped:
        async def __call__(self, scope, receive, send):
            from starlette.responses import JSONResponse
            method = scope.get("method", "GET").upper()
            path = scope.get("path", "")
            headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
            scene = headers.get("x-naiwa-v2-scene", "")
            nonce = headers.get("x-naiwa-v2-nonce", "")
            control = read(CONTROL_PATH)
            valid = bool(nonce) and hmac.compare_digest(nonce, (RUN / "browser-nonce.txt").read_text(encoding="utf-8").strip())
            active = bool(valid and scene in SCENE_CAPS and control.get("paid_enabled")
                          and control.get("authorization_received") and control.get("active_scene") == scene)
            sessions_doc = read(RUN / "session-registry.json") if (RUN / "session-registry.json").exists() else {"sessions": []}
            session_ids = {s["session_id"] for s in sessions_doc.get("sessions", [])}
            permitted = method in {"GET", "HEAD", "OPTIONS"}
            create_chat = method == "POST" and path == "/api/chat/sessions"
            create_material_session = method == "POST" and path == "/api/chat/material-search/session" and scene == "C"
            update_material_scope = method == "PATCH" and path == "/api/chat/material-search/scope" and scene == "C"
            stream_match = re.fullmatch(r"/api/chat/sessions/([0-9a-f-]{36})/(assistant:stream|answers:stream)", path)
            send_chat = method == "POST" and stream_match and stream_match[1] in session_ids
            task_match = re.fullmatch(r"/api/learning-tasks/([0-9a-f-]{36})/(confirm|cancel|run)", path)
            task_action = bool(method == "POST" and task_match and await self._task_owned(app, task_match[1], session_ids))
            practice_decline_match = re.fullmatch(r"/api/practice-requests/([0-9a-f-]{36})/decline", path)
            practice_decline = bool(method == "POST" and active and practice_decline_match
                and _practice_request_owned(app.state.session_factory, practice_decline_match[1], sessions_doc, scene))
            today_append = method == "POST" and re.fullmatch(r"/api/plans/[0-9a-f-]{36}/questions", path) and scene == "D"
            today_generate = method == "POST" and path == "/api/plans/today/generate" and scene == "D"
            attempt_match = re.fullmatch(r"/api/practice-items/([0-9a-f-]{36})/(answer-submissions|process-reviews|answer-reveal|self-assessments)", path)
            allowed_item = bool(attempt_match and await self._item_in_today_plan(app, attempt_match[1]))
            permitted = permitted or active and (create_chat or create_material_session or update_material_scope
                or send_chat or task_action or practice_decline or today_append or today_generate
                or (method == "POST" and allowed_item))
            if method not in {"GET", "HEAD", "OPTIONS"} and not permitted:
                with (OUT / "blocked-ui-writes.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"time": time.time(), "method": method,
                        "path": path, "scene": scene or None, "active_authorization": active,
                        "reason": "route_or_session_not_scoped"}, ensure_ascii=False) + "\n")
                return await JSONResponse({"error": {"code": "v2_ui_write_not_authorized",
                    "message": "仅允许本轮已授权场景中的奶蛙页面操作。"}}, status_code=403)(scope, receive, send)
            token = SCENE.set(scene if active else None)
            capture = create_chat or create_material_session
            body_chunks = []
            async def labeled(message):
                if message["type"] == "http.response.start":
                    message.setdefault("headers", []).extend([
                        (b"x-naiwa-experience", EXPERIENCE_HEADER.encode()),
                        (b"x-naiwa-backend-pid", str(os.getpid()).encode()),
                        (b"x-naiwa-active-scene", (scene if active else "closed").encode()),
                    ])
                if capture and message["type"] == "http.response.body" and message.get("body"):
                    body_chunks.append(message["body"])
                if capture and message["type"] == "http.response.body" and not message.get("more_body", False):
                    try:
                        payload = json.loads(b"".join(body_chunks).decode("utf-8"))
                        sid = payload.get("session_id")
                        if sid:
                            registry = read(RUN / "session-registry.json") if (RUN / "session-registry.json").exists() else {"sessions": []}
                            sessions = registry.setdefault("sessions", [])
                            if not any(item["session_id"] == sid for item in sessions):
                                sessions.append({"session_id": sid, "scene_created": scene,
                                    "purpose": payload.get("purpose", "materials" if create_material_session else None),
                                    "title": payload.get("title"), "registered_at": time.time()})
                            save(RUN / "session-registry.json", registry)
                    except (ValueError, UnicodeDecodeError, TypeError):
                        pass
                await send(message)
            try:
                await app(scope, receive, labeled)
            finally:
                SCENE.reset(token)

        async def _task_owned(self, application, task_id, session_ids):
            if not (RUN / "session-registry.json").exists():
                return False
            from backend.models.learning_task import LearningTask
            with application.state.session_factory() as db:
                try:
                    row = db.get(LearningTask, UUID(task_id))
                except ValueError:
                    return False
                return bool(row and str(row.session_id) in session_ids)

        async def _item_in_today_plan(self, application, item_id):
            from backend.models.learning import PracticeItem
            plan_id = read(RUN / "runtime-data.json").get("today_plan_id")
            if not plan_id:
                return False
            with application.state.session_factory() as db:
                try:
                    row = db.get(PracticeItem, UUID(item_id))
                except ValueError:
                    return False
                return bool(row and str(row.plan_id) == plan_id)

    scoped = Scoped()
    scoped.audit_session_factory = lambda: app.state.session_factory
    return scoped


def _practice_request_owned(factory, request_id, sessions_doc, scene):
    """Scope decline to an unconfirmed request owned by this run's QA session."""
    from backend.models.practice_request import PracticeRequest
    try:
        request_uuid = UUID(request_id)
    except (TypeError, ValueError):
        return False
    registered = {
        str(item.get("session_id"))
        for item in sessions_doc.get("sessions", [])
        if item.get("scene_created") == scene and item.get("purpose") == "qa"
    }
    with factory() as db:
        row = db.get(PracticeRequest, request_uuid)
        return bool(row and row.source_conversation_id is not None
            and str(row.source_conversation_id) in registered
            and row.status in {"draft", "pending", "planning", "proposed", "failed"})


def _check_no_unfinished(gate: FinalRoundGate) -> None:
    if any(not row.get("finished") for row in gate.records):
        raise RuntimeError("unfinished_model_reservation_stop_do_not_restart")


def serve() -> None:
    import httpx
    from desktop.postgres import _run
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings

    if not BASELINE_PATH.is_file() or not LEDGER_PATH.is_file():
        raise RuntimeError("v2_prepare_required")
    assert_ports_free()
    baseline = read(BASELINE_PATH)
    assert source_hashes() == read(ACTIVE_SOURCE_PATH)["source_sha256"], "source_changed_after_recorded_epoch"
    assert {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in OLD_LEDGERS} == baseline["old_ledger_sha256"]
    gate = FinalRoundGate(LEDGER_DIR, simulated=False, preparation=False,
        global_limit=40, scene_caps=SCENE_CAPS, purpose_policy=PURPOSE_POLICY, seal_on_scene_cap=False)
    _check_no_unfinished(gate)
    if gate.stop_reason or read(CONTROL_PATH)["paid_enabled"]:
        raise RuntimeError("v2_gate_not_closed_or_has_stop_reason")
    pg, owner = pg_owner_preflight()
    pg.lock.acquire()
    children, handles = [], []
    runtime = None
    try:
        started = int(time.time())
        result = _run([pg.binary("pg_ctl"), "-D", str(pg.cluster), "-l", str(OUT / "postgres-v2.log"),
            "-o", f"-p {pg.port} -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic",
            "-w", "-t", "30", "start"], timeout=45, capture=False)
        identity = pg._identity()
        if result.returncode or not identity or identity[1] < started - 1:
            raise RuntimeError("owned_pg_start_identity_not_confirmed")
        pg._owned_identity = identity
        if (OUT / "database-before.json").exists():
            snapshot_name = f"database-restart-before-{time.time_ns()}.json"
        else:
            snapshot_name = "database-before.json"
        before = snapshot_database(OUT / snapshot_name, allow_live_identity=identity)
        assert before["identity"] == {"db": DATABASE, "role": "kaoyan_app", "port": "63044"}
        assert before["schema_revision"] == "f55a7b9012c3"
        tasks = before["learning_tasks"]
        if any(row.get("status") in {"running", "queued", "pending"} for row in tasks):
            raise RuntimeError("active_learning_task_exists_stop")
        if any(row.get("status") in {"generating", "streaming", "pending"} for row in before["chat_messages"]):
            raise RuntimeError("active_chat_message_exists_stop")
        study_date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        active = [row for row in before["daily_plans"] if row.get("study_date") == study_date and row.get("status") == "active"]
        today_plan_id = str(active[0]["id"]) if len(active) == 1 else None
        runtime_data = {"cluster_id": owner["cluster_id"], "today_plan_id": today_plan_id,
                        "today_plan_count": len(active), "study_date": study_date, "started_at": time.time()}
        save(RUN / "runtime-data.json", runtime_data)
        if not (RUN / "session-registry.json").exists():
            save(RUN / "session-registry.json", {"sessions": []})
        (RUN / "browser-nonce.txt").write_text(os.urandom(32).hex(), encoding="ascii")

        effective = load_local_settings(get_settings())
        key = effective.llm_api_key
        key = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key or "")
        if not key or effective.llm_model != "deepseek-flash" or effective.llm_base_url.rstrip("/") != "https://api.deepseek.com":
            raise RuntimeError("official_deepseek_configuration_unavailable")
        from sqlalchemy.engine import URL
        db_url = URL.create("postgresql+psycopg", username="kaoyan_app", password=pg._passwords["kaoyan_app"],
                            host="127.0.0.1", port=pg.port, database=DATABASE).render_as_string(hide_password=False)
        web = 63046
        env = {**os.environ,
            "APP_ENV": "test", "DATABASE_URL": db_url, "TEST_DATABASE_URL": db_url,
            "KAOYAN_OWNED_TEST_PORT": str(pg.port), "PHASE45E_OWNED_TEST_PORT": str(pg.port),
            "LLM_API_KEY": key, "LLM_BASE_URL": effective.llm_base_url, "LLM_MODEL": effective.llm_model,
            "LLM_STREAM_INCLUDE_USAGE": "true", "MODEL_SETTINGS_PATH": str(RUN / "isolated-model-settings.bin"),
            "UPLOAD_DIR": str(HOME / "uploads"), "CHROMA_DIR": str(HOME / "chroma"),
            "MODEL_CACHE_DIR": str(ROOT / "storage/models"), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "ANONYMIZED_TELEMETRY": "False", "DO_NOT_TRACK": "1", "OTEL_SDK_DISABLED": "true",
            "PYTHONIOENCODING": "utf-8", "ALLOWED_WEB_ORIGINS": json.dumps([f"http://127.0.0.1:{web}"]),
            "VITE_API_PROXY_TARGET": "http://127.0.0.1:63045", "NAIWA_REAL_RETEST_BUDGET7": "0",
            "NAIWA_FINAL_ROUND_STAGE2": "0", "NAIWA_V2_REAL_AUTHORIZED": "explicit_attachment_cap_40"}
        commands = [
            [sys.executable, "-m", "uvicorn", "scripts.naiwa_agent_full_v2_20261021:real_app", "--factory",
             "--host", "127.0.0.1", "--port", "63045"],
            [str(Path(r"D:\应用安装包\node.exe")), "node_modules/vite/bin/vite.js", "--host", "127.0.0.1",
             "--port", "63046", "--strictPort"],
        ]
        run_number = len(list(OUT.glob("runtime-v2-epoch-*.json"))) + 1
        stop_request = RUN / f"stop-epoch-{run_number}.request"
        runtime = {"workspace": str(ROOT), "cluster_id": owner["cluster_id"], "database": before["identity"],
            "postgres_pid": identity[0], "postgres_identity": list(identity), "supervisor_pid": os.getpid(), "python": sys.executable,
            "provider": effective.llm_model, "provider_key_logged": False, "commands": commands,
            "ports": list(PORTS), "status": "starting", "paid_enabled_on_start": False,
            "started_at": time.time(), "run_number": run_number, "stop_request": str(stop_request)}
        save(OUT / f"runtime-v2-epoch-{run_number}.json", runtime)
        save(OUT / "runtime-v2.json", runtime)
        for name, command, cwd in zip(("backend", "frontend"), commands, (ROOT, ROOT / "frontend")):
            log = (OUT / f"{name}-v2.log").open("a", encoding="utf-8")
            handles.append(log)
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            children.append(child)
        runtime.update(backend_pid=children[0].pid, frontend_pid=children[1].pid,
            backend_started=process_started(children[0].pid), frontend_started=process_started(children[1].pid))
        save(OUT / f"runtime-v2-epoch-{run_number}.json", runtime)
        save(OUT / "runtime-v2.json", runtime)
        with httpx.Client(trust_env=False, timeout=3, follow_redirects=False) as client:
            for _ in range(90):
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("v2_service_child_exited_check_logs")
                try:
                    response = client.get("http://127.0.0.1:63046/api/health")
                    if response.status_code == 200:
                        assert response.headers.get("x-naiwa-experience") == EXPERIENCE_HEADER
                        assert response.json().get("database") == "connected"
                        assert not read(CONTROL_PATH)["paid_enabled"]
                        runtime.update(status="running", health=response.json())
                        save(OUT / f"runtime-v2-epoch-{run_number}.json", runtime)
                        save(OUT / "runtime-v2.json", runtime)
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("v2_startup_health_timeout")
        while not stop_request.exists():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("v2_service_child_exited_during_acceptance")
            time.sleep(1)
    finally:
        FinalRoundGate(LEDGER_DIR, simulated=False, preparation=False, global_limit=40,
            scene_caps=SCENE_CAPS, purpose_policy=PURPOSE_POLICY, seal_on_scene_cap=False).seal("v2_runtime_shutdown")
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=25)
        for log in handles:
            log.close()
        if pg._owned_identity is not None:
            pg.stop()
        else:
            pg.lock.release()
        if runtime:
            runtime["status"] = "stopped"
            runtime["stopped_at"] = time.time()
            save(OUT / f"runtime-v2-epoch-{runtime['run_number']}.json", runtime)
            save(OUT / "runtime-v2.json", runtime)


def _gate():
    gate = FinalRoundGate(LEDGER_DIR, simulated=False, preparation=False, global_limit=40,
        scene_caps=SCENE_CAPS, purpose_policy=PURPOSE_POLICY, seal_on_scene_cap=False)
    return gate


def open_scene(scene: str) -> None:
    if scene not in SCENE_CAPS:
        raise ValueError("unknown_v2_scene")
    runtime = read(OUT / "runtime-v2.json")
    if runtime.get("status") != "running":
        raise RuntimeError("v2_runtime_not_running")
    if (process_started(runtime["backend_pid"]) != runtime["backend_started"]
            or process_started(runtime["frontend_pid"]) != runtime["frontend_started"]):
        raise RuntimeError("v2_process_identity_changed")
    loaded = read(RUN / "loaded-code.json")
    if (loaded["pid"] != runtime["backend_pid"] or
            loaded["source_sha256"] != read(ACTIVE_SOURCE_PATH)["source_sha256"]):
        raise RuntimeError("v2_loaded_source_epoch_mismatch")
    verify_integrity(scene=scene)
    for port, key in ((63045, "backend_pid"), (63046, "frontend_pid")):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                raise RuntimeError(f"v2_service_not_listening:{port}")
    gate = _gate()
    _check_no_unfinished(gate)
    if gate.stop_reason:
        gate.uninstall()
        raise RuntimeError("v2_gate_stop_reason_requires_stop_not_reauthorization")
    if len(gate.records) >= 40 or sum(r["case_id"] == scene for r in gate.records) >= SCENE_CAPS[scene]:
        gate.uninstall()
        raise RuntimeError("v2_scene_or_global_budget_exhausted")
    with gate.authorization.hold():
        atomic_json(CONTROL_PATH, {"paid_enabled": True, "authorization_received": True,
            "active_scene": scene, "reason": "explicit_user_authorization_attachment_v2", "opened_at": time.time()})
    with (OUT / "authorization-windows.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"scene": scene, "opened_at": time.time(), "global_count": len(gate.records),
            "global_remaining": 40 - len(gate.records), "scene_count": sum(r["case_id"] == scene for r in gate.records),
            "scene_remaining": SCENE_CAPS[scene] - sum(r["case_id"] == scene for r in gate.records)}, ensure_ascii=False) + "\n")
    gate.uninstall()
    print(f"SCENE {scene} OPEN; requests already used={len(read(LEDGER_PATH)['requests'])}; UI only")


def close_paid(reason="operator_closed") -> None:
    gate = _gate()
    gate.seal(reason)
    with (OUT / "authorization-windows.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"scene": None, "closed_at": time.time(), "reason": reason,
            "global_count": len(gate.records)}, ensure_ascii=False) + "\n")
    gate.uninstall()
    print("PAID EXIT CLOSED")


def record_fix(paths: list[str]) -> None:
    """Explicitly record a business-code fix after preserving first-round evidence."""
    if not paths:
        raise ValueError("record_fix_requires_explicit_relative_paths")
    active = read(ACTIVE_SOURCE_PATH)
    current = source_hashes()
    changed = [name.replace("\\", "/") for name in paths]
    previous = active["source_sha256"]
    unexpected = sorted(name for name in set(previous) | set(current)
                        if previous.get(name) != current.get(name) and name not in changed)
    missing = [name for name in changed if previous.get(name) == current.get(name)]
    if unexpected or missing:
        raise RuntimeError("fix_hash_scope_mismatch:" + json.dumps({"unexpected": unexpected, "unchanged": missing}))
    record = {"epoch": active["epoch"] + 1, "source_sha256": current,
              "changed_paths": changed, "recorded_at": time.time(),
              "prior_epoch_sha256": sha(ACTIVE_SOURCE_PATH)}
    save(RUN / f"source-fix-epoch-{record['epoch']}.json", record)
    save(ACTIVE_SOURCE_PATH, record)
    print(f"RECORDED FIX EPOCH {record['epoch']}; changed paths={len(changed)}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: prepare|serve|open SCENE|close|stop|status|record-fix PATH...")
    command = sys.argv[1]
    if command == "prepare":
        prepare()
    elif command == "serve":
        serve()
    elif command == "open" and len(sys.argv) == 3:
        open_scene(sys.argv[2])
    elif command == "close":
        close_paid("v2_operator_closed")
    elif command == "stop":
        close_paid("v2_stop_requested")
        runtime = read(OUT / "runtime-v2.json")
        Path(runtime["stop_request"]).write_text(str(time.time()), encoding="ascii")
    elif command == "status":
        runtime = read(OUT / "runtime-v2.json")
        gate = _gate()
        print(json.dumps({"runtime": runtime, "count": len(gate.records), "limits": SCENE_CAPS,
            "paid_enabled": read(CONTROL_PATH)["paid_enabled"],
            "unfinished": sum(not r.get("finished") for r in gate.records)}, ensure_ascii=False, default=str))
        gate.uninstall()
    elif command == "record-fix":
        record_fix(sys.argv[2:])
    else:
        raise SystemExit("invalid_command")


if __name__ == "__main__":
    main()
