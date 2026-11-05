"""Fresh, disposable PostgreSQL runtime for the 2026-10-24 differentiated audit.

This runtime never attaches to the retained experience cluster. It reuses the
already-authorized append-only DeepSeek ledger and existing transport gate, but
creates a new PG18 cluster, a new *_test database, and separate loopback ports.
Browser URL safety stops remain in force; service probes are backend-route
evidence only and are never described as browser/UI testing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_TAG = os.environ.get("NAIWA_DIFFERENTIATED_RUNTIME_TAG", "r13")
AUDIT = ROOT / "storage/quality-audits/naiwa-differentiated-acceptance-20261024" / f"fresh-runtime-{RUNTIME_TAG}"
DATA_HOME = ROOT / "storage/manual-experience" / f"naiwa-differentiated-test-20261024-{RUNTIME_TAG}"
# Reuse only the fresh r8 cluster created by this task. It is PG18, stopped,
# unseeded and has no target database; avoids another Windows initdb invocation.
OWNED_DATA = ROOT / "storage/manual-experience/naiwa-differentiated-test-20261024-r8/owned-pg"
RUN_OVERRIDE = ROOT / "storage/manual-experience/naiwa-real-20261020" / f"agent-full-v33-continue-20261023-r8z-fresh-20261024-{RUNTIME_TAG}"
PG_BIN = Path("C:/Program Files/PostgreSQL/18/bin")
DATABASE = os.environ.get("NAIWA_DIFFERENTIATED_DATABASE", f"naiwa_differentiated_{RUNTIME_TAG}_test")
PG_PORT = int(os.environ.get("NAIWA_DIFFERENTIATED_PG_PORT", "64314"))
API_PORT = int(os.environ.get("NAIWA_DIFFERENTIATED_API_PORT", "64545"))
WEB_PORT = int(os.environ.get("NAIWA_DIFFERENTIATED_WEB_PORT", "64546"))
OLD_HOME = ROOT / "storage/manual-experience/naiwa-real-20261020"
OLD_RUNTIME = ROOT / "storage/manual-experience/naiwa-real-20261020/agent-full-v33-continue-20261023-r8z-fresh-20261024-closeout1"
SOURCE_EPOCH = 32
NODE = Path(r"D:\应用安装包\node.exe")
ROUND_BASELINE_REQUEST_COUNT = 3
ROUND_MAX_NEW_REQUESTS = 19  # 24 user cap, reduced to keep at least 14 of the 40-request ledger unused.
ROUND_EXPECTED_LEDGER_SHA256 = "f7604d731228aadf794db70bbd04b836fc9115d16397c5e353f9d8805d48c590"

# All child processes, including the service probe, bind to the same new run
# directory and database identity. The canonical request ledger remains r8z.
os.environ.update({
    "NAIWA_V33_CONTINUATION_TAG": "r8z",
    "NAIWA_V33_EXPLORATORY_LEDGER_TAG": "r8z",
    "NAIWA_V33_CONTINUATION_RUN": str(RUN_OVERRIDE),
    "NAIWA_ISOLATED_DATABASE": DATABASE,
    "NAIWA_ISOLATED_PG_PORT": str(PG_PORT),
    "NAIWA_ISOLATED_API_PORT": str(API_PORT),
    "NAIWA_ISOLATED_WEB_PORT": str(WEB_PORT),
    "NAIWA_FRESH_TEST_DATABASE": "1",
    "NAIWA_FRESH_AUDIT_DIR": str(AUDIT),
})
os.environ.pop("NAIWA_EDGE_AUTH", None)

sys.path.insert(0, str(ROOT))
from desktop.postgres import ADMIN, APP_USER, ManagedPostgres
from desktop.runtime_paths import RuntimePaths
from scripts import naiwa_v33_paid_continuation_20261023 as runtime
from scripts.naiwa_freeze_gate_20261021 import atomic_json


def _new_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _port_is_free(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _assert_preflight() -> dict:
    if any(path.exists() for path in (AUDIT, DATA_HOME, RUN_OVERRIDE)):
        raise RuntimeError("fresh_round_paths_already_exist_stop_without_overwrite")
    if not OLD_RUNTIME.joinpath("active-source-hashes.json").is_file():
        raise RuntimeError("source_epoch_26_manifest_missing")
    if not all(path.is_file() for path in (PG_BIN / "postgres.exe", PG_BIN / "initdb.exe",
                                            PG_BIN / "pg_ctl.exe", NODE,
                                            ROOT / "frontend/node_modules/vite/bin/vite.js")):
        raise RuntimeError("required_isolated_runtime_binary_missing")
    for port in (PG_PORT, API_PORT, WEB_PORT):
        if not _port_is_free(port):
            raise RuntimeError(f"new_loopback_port_unavailable:{port}")
    runtime.validate_parent_ledger()
    runtime.paid.validate_history()
    ledger = runtime.read(runtime.LEDGER)
    control = runtime.read(runtime.OUT / "control.json")
    expected_scene_counts = {"A": 3, "B": 2, "C": 4, "D": 1, "E": 2, "F": 2, "H": 1, "R": 0}
    actual_scene_counts = {scene: sum(row.get("case_id") == scene for row in ledger.get("requests", []))
                           for scene in runtime.ROUND_GATE_SCENE_CAPS}
    if (len(ledger.get("requests", [])) != 15 or _sha(runtime.LEDGER) != ROUND_EXPECTED_LEDGER_SHA256
            or actual_scene_counts != expected_scene_counts or ledger.get("stop_reason")
            or any(not row.get("finished") for row in ledger["requests"])
            or sum(row.get("case_id") == "A" for row in ledger["requests"]) != 3
            or control.get("paid_enabled")):
        raise RuntimeError("active_ledger_or_provider_control_not_ready")
    if int(ledger.get("limits", {}).get("max_requests", 0)) != 40:
        raise RuntimeError("current_round_ledger_limit_mismatch")
    return {
        "status": "PREPARED_CLOSED",
        "active_ledger": str(runtime.LEDGER),
        "active_ledger_sha256": _sha(runtime.LEDGER),
        "active_ledger_count": len(ledger["requests"]),
        "active_ledger_remaining": 40 - len(ledger["requests"]),
        "current_differentiated_round_new_requests": len(ledger["requests"]) - ROUND_BASELINE_REQUEST_COUNT,
        "current_differentiated_round_remaining": ROUND_BASELINE_REQUEST_COUNT + ROUND_MAX_NEW_REQUESTS - len(ledger["requests"]),
        "active_scene_counts": actual_scene_counts,
        "parent_ledger_sha256": _sha(runtime.PARENT_LEDGER),
        "paid_enabled": False,
        "ports_available": {str(port): True for port in (PG_PORT, API_PORT, WEB_PORT)},
    }


def _provider_settings() -> tuple[object, str]:
    from backend.config import get_settings
    prior = os.environ.get("APP_ENV")
    os.environ["APP_ENV"] = "dev"
    get_settings.cache_clear()
    try:
        effective, key = runtime.legacy._load_live_settings()
        if not key:
            raise RuntimeError("authorized_deepseek_configuration_unavailable")
        return effective, key
    finally:
        if prior is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = prior
        get_settings.cache_clear()


def _write_epoch_manifest() -> dict:
    previous = runtime.read(OLD_RUNTIME / "active-source-hashes.json")
    if int(previous.get("epoch", -1)) != SOURCE_EPOCH - 1:
        raise RuntimeError("unexpected_predecessor_source_epoch")
    RUN_OVERRIDE.mkdir(parents=True, exist_ok=False)
    _new_json(RUN_OVERRIDE / "active-source-hashes.json", previous)
    before = previous.get("source_sha256", {})
    current = runtime.source_hashes()
    changed = sorted(name for name in set(before) | set(current) if before.get(name) != current.get(name))
    if not changed:
        raise RuntimeError("fresh_runtime_source_revision_not_detected")
    runtime.record_source_revision(changed, "fresh disposable PG cluster and loopback ports; previous epoch retained")
    active = runtime.read(RUN_OVERRIDE / "active-source-hashes.json")
    if active.get("epoch") != SOURCE_EPOCH or active.get("source_sha256") != current:
        raise RuntimeError("fresh_runtime_source_epoch_verification_failed")
    _new_json(RUN_OVERRIDE / "session-registry.json", {"sessions": []})
    with (RUN_OVERRIDE / "browser-nonce.txt").open("x", encoding="ascii") as stream:
        stream.write(os.urandom(32).hex())
    return active


def _seed_fresh_database(database_url: str) -> dict:
    from backend.db import create_db_engine, create_session_factory
    from backend.models.learning import KnowledgePoint
    from scripts.seed import seed_all

    engine = create_db_engine(database_url)
    factory = create_session_factory(engine)
    math_node_id = UUID("32a29e1e-8ae3-41fc-9322-43f727596819")
    cs_node_id = UUID("bf1bae96-320f-42d1-acbd-f17de7709dd4")
    try:
        with factory.begin() as db:
            # Explicitly synthetic routing fixtures. The 408 node intentionally
            # has no system lesson; it exists only to exercise ordinary-QA fallback.
            db.add_all([
                KnowledgePoint(id=math_node_id, code="math.calculus.limit.lhopital",
                    name="洛必达法则（隔离测试节点）", subject="考研数学", ordinal=999,
                    is_assessable=True, is_active=True,
                    summary="隔离测试节点，不代表额外正式课程内容。"),
                KnowledgePoint(id=cs_node_id, code="fixture.cs.ds",
                    name="线性表（隔离测试节点）", subject="408", ordinal=999,
                    is_assessable=True, is_active=True,
                    summary="合成测试知识点；本节点故意没有系统讲义。"),
            ])
            db.flush()
            seed_result = seed_all(db, include_exam_references=False)
        with engine.connect() as connection:
            from sqlalchemy import text
            counts = {}
            for table in ("knowledge_points", "questions", "question_versions", "kp_states",
                          "chat_sessions", "chat_messages", "practice_requests", "learning_tasks",
                          "daily_plans", "practice_items", "question_attempts", "learning_events"):
                counts[table] = int(connection.scalar(text(f"SELECT count(*) FROM public.{table}")))
        if counts["chat_sessions"] or counts["chat_messages"] or counts["practice_requests"]:
            raise RuntimeError("fresh_database_unexpected_user_history")
        return {"seed_result": seed_result, "row_counts_after_seed": counts,
                "test_nodes": {"lhopital": str(math_node_id), "linear_list": str(cs_node_id)},
                "synthetic_fixture_marking": "explicit; no authentic exam provenance asserted"}
    finally:
        engine.dispose()
def verify_fresh_database_identity(**_kwargs) -> dict[str, object]:
    """Called at each provider dispatch; verifies the live app DB target."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    settings = get_settings()
    parsed = make_url(str(settings.active_database_url))
    expected = ("127.0.0.1", PG_PORT, DATABASE)
    if (settings.app_env != "test" or (parsed.host, parsed.port, parsed.database) != expected
            or os.environ.get("NAIWA_CLUSTER_ID") != os.environ.get("NAIWA_EXPECTED_CLUSTER_ID")):
        raise RuntimeError("fresh_isolated_database_identity_mismatch")
    marker_path = Path(os.environ["NAIWA_CLUSTER_MARKER"])
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("cluster_id") != os.environ.get("NAIWA_EXPECTED_CLUSTER_ID"):
        raise RuntimeError("fresh_isolated_cluster_marker_mismatch")
    engine = create_engine(str(settings.active_database_url), pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            identity = tuple(connection.execute(text(
                "SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()"
            )).one())
        if identity != (DATABASE, APP_USER, "127.0.0.1", PG_PORT):
            raise RuntimeError("fresh_isolated_database_connection_identity_mismatch")
    finally:
        engine.dispose()
    return {"cluster_id": os.environ["NAIWA_EXPECTED_CLUSTER_ID"],
            "database": DATABASE, "role": APP_USER, "host": "127.0.0.1", "port": PG_PORT}


def app_factory():
    # Imported only by the isolated Uvicorn process after its complete environment is set.
    import scripts.naiwa_v33_paid_continuation_20261023 as continuation
    if continuation.RUN.resolve() != RUN_OVERRIDE.resolve():
        raise RuntimeError("fresh_runtime_directory_mismatch")
    return continuation.real_app()


def _start_services(env: dict[str, str], identity: dict) -> None:
    import httpx
    commands = [
        [sys.executable, "-m", "uvicorn", "scripts.naiwa_differentiated_test_runtime_20261024:app_factory",
         "--factory", "--host", "127.0.0.1", "--port", str(API_PORT)],
        [str(NODE), "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(WEB_PORT), "--strictPort"],
    ]
    logs: list[object] = []
    children: list[subprocess.Popen] = []
    opened = []
    try:
        for name, command, cwd in zip(("backend", "frontend"), commands, (ROOT, ROOT / "frontend")):
            log_path = AUDIT / f"{name}.log"
            handle = log_path.open("x", encoding="utf-8")
            opened.append(log_path)
            logs.append(handle)
            children.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=handle,
                stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        _new_json(AUDIT / "service-processes.json", {
            "backend_pid": children[0].pid, "frontend_pid": children[1].pid,
            "ports": {"postgres": PG_PORT, "api": API_PORT, "web": WEB_PORT},
            "database_identity": identity, "source_epoch": SOURCE_EPOCH,
            "browser_ui_controlled": False, "browser_reason": "Computer Use URL safety stop remains active",
        })
        with httpx.Client(trust_env=False, timeout=3, follow_redirects=False) as client:
            for _ in range(90):
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("isolated_service_child_exited_check_audit_logs")
                try:
                    response = client.get(f"http://127.0.0.1:{API_PORT}/api/health")
                    if response.status_code == 200:
                        body = response.json()
                        if body.get("database") != "connected":
                            raise RuntimeError("fresh_runtime_database_health_failed")
                        if runtime.read(runtime.OUT / "control.json").get("paid_enabled"):
                            raise RuntimeError("provider_gate_open_during_startup")
                        loaded = runtime.read(RUN_OVERRIDE / "loaded-code.json")
                        db_loaded = loaded.get("database", {})
                        if (db_loaded.get("db"), db_loaded.get("role"), db_loaded.get("port"),
                                db_loaded.get("cluster_id")) != (DATABASE, APP_USER, PG_PORT, identity["cluster_id"]):
                            raise RuntimeError("loaded_backend_database_identity_mismatch")
                        _new_json(AUDIT / "startup-verification.json", {
                            "status": "READY_CLOSED", "health_status": 200,
                            "health": body, "loaded_code_sha256": loaded.get("source_sha256"),
                            "loaded_source_epoch": loaded.get("source_epoch"),
                            "loaded_database": db_loaded, "ports": [PG_PORT, API_PORT, WEB_PORT],
                            "browser_ui_tested": False,
                        })
                        if env.get('NAIWA_CLOSEOUT_RECORD_AUTH_PROBE') == '1':
                            from scripts.naiwa_closeout_fixtures_20261024 import probe_record_authorization
                            probe_record_authorization(runtime, audit=AUDIT,
                                database_url=env['TEST_DATABASE_URL'],api_port=API_PORT,web_port=WEB_PORT)
                        probe_batch = json.loads(env.get("NAIWA_PROBE_BATCH_JSON", "[]"))
                        for probe_item in probe_batch:
                            probe(
                                probe_item["case_id"], probe_item["title"], probe_item["prompt"],
                                probe_item["route"], probe_item["context_key"], probe_item["purpose"])
                        if probe_batch and env.get('NAIWA_KEEP_CLOSED_STATION') != '1':
                            return
                        while True:
                            if (AUDIT / "stop.request").is_file():
                                return
                            if any(child.poll() is not None for child in children):
                                raise RuntimeError("isolated_service_child_exited_during_runtime")
                            time.sleep(1)
                except httpx.HTTPError:
                    time.sleep(1)
            raise RuntimeError("isolated_api_health_timeout")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            runtime.paid.gate().seal("fresh_differentiated_runtime_stopped")
        except Exception:
            pass
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    # Only these child handles belong to this runner.
                    child.kill()
                    child.wait(timeout=10)
        for handle in logs:
            handle.close()


def serve() -> None:
    from psycopg import sql
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    from backend.db import create_db_engine
    from alembic import command
    from alembic.config import Config

    preflight = _assert_preflight()
    AUDIT.mkdir(parents=True, exist_ok=False)
    DATA_HOME.mkdir(parents=True, exist_ok=False)
    epoch = _write_epoch_manifest()
    manager = ManagedPostgres(
        RuntimePaths.windows(resources=ROOT / "backend", local_app_data=OWNED_DATA), PG_BIN, port=PG_PORT)
    owned = False
    try:
        manager.start()
        owned = True
        if manager.owner["cluster_id"] == runtime.read(OLD_HOME / "owned-pg/KaoyanStudy/config/postgres-owner.json").get("cluster_id"):
            raise RuntimeError("fresh_cluster_reused_retained_cluster_id")
        if manager.cluster.resolve() == (OLD_HOME / "owned-pg/KaoyanStudy/postgres/cluster").resolve():
            raise RuntimeError("fresh_cluster_path_matches_retained_experience")
        with manager._connect() as admin:
            found = admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,)).fetchone()
            if found:
                raise RuntimeError("fresh_target_database_already_exists_stop")
            admin.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                sql.Identifier(DATABASE), sql.Identifier(APP_USER)))
            system_identifier = str(admin.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
        with manager._connect(user=APP_USER, database=DATABASE) as app_connection:
            db_identity = app_connection.execute(
                "SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()"
            ).fetchone()
        if db_identity != (DATABASE, APP_USER, "127.0.0.1", PG_PORT) or PG_PORT == 5433:
            raise RuntimeError("fresh_target_database_identity_failed")
        db_url = make_url(manager.database_url).set(database=DATABASE).render_as_string(hide_password=False)

        # Load the user-authorized DeepSeek config in memory; never persist or log the key.
        effective, api_key = _provider_settings()
        setup_env = {
            **os.environ, "APP_ENV": "test", "DATABASE_URL": db_url,
            "TEST_DATABASE_URL": db_url, "KAOYAN_OWNED_TEST_PORT": str(PG_PORT),
            "PHASE45E_OWNED_TEST_PORT": str(PG_PORT), "NAIWA_CLUSTER_ID": manager.owner["cluster_id"],
            "NAIWA_EXPECTED_CLUSTER_ID": manager.owner["cluster_id"],
            "NAIWA_CLUSTER_MARKER": str(manager.marker.resolve()),
            "ALLOWED_WEB_ORIGINS": json.dumps([f"http://127.0.0.1:{WEB_PORT}"]),
            "VITE_API_PROXY_TARGET": f"http://127.0.0.1:{API_PORT}",
            "UPLOAD_DIR": str(DATA_HOME / "uploads"), "CHROMA_DIR": str(DATA_HOME / "chroma"),
            "MODEL_CACHE_DIR": str(ROOT / "storage/models"), "MODEL_SETTINGS_PATH": str(RUN_OVERRIDE / "model-settings.bin"),
            "LLM_API_KEY": api_key, "LLM_BASE_URL": effective.llm_base_url,
            "LLM_MODEL": effective.llm_model, "LLM_MAX_OUTPUT_TOKENS": str(effective.llm_max_output_tokens),
            "LLM_TIMEOUT_SECONDS": str(effective.llm_timeout_seconds), "LLM_RETRY_MAX_OUTPUT_TOKENS": str(effective.llm_retry_max_output_tokens),
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "ANONYMIZED_TELEMETRY": "False",
            "DO_NOT_TRACK": "1", "OTEL_SDK_DISABLED": "true", "PYTHONIOENCODING": "utf-8",
            "NAIWA_V33_CONTINUATION_TAG": "r8z", "NAIWA_V33_EXPLORATORY_LEDGER_TAG": "r8z",
            "NAIWA_V33_CONTINUATION_RUN": str(RUN_OVERRIDE), "NAIWA_ISOLATED_DATABASE": DATABASE,
            "NAIWA_ISOLATED_PG_PORT": str(PG_PORT), "NAIWA_ISOLATED_API_PORT": str(API_PORT),
            "NAIWA_ISOLATED_WEB_PORT": str(WEB_PORT), "NAIWA_FRESH_TEST_DATABASE": "1",
            "NAIWA_FRESH_AUDIT_DIR": str(AUDIT),
        }
        os.environ.update({key: value for key, value in setup_env.items() if key != "LLM_API_KEY"})
        engine = create_db_engine(db_url)
        try:
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "migrations"))
            command.upgrade(config, "head")
            from backend.db import create_session_factory
            factory = create_session_factory(engine)
            # The target identity was validated before the migration.
            from backend.models.learning import KnowledgePoint
            from scripts.seed import seed_all
            with factory.begin() as db:
                db.add_all([
                    KnowledgePoint(id=UUID("32a29e1e-8ae3-41fc-9322-43f727596819"),
                        code="math.calculus.limit.lhopital", name="洛必达法则（隔离测试节点）",
                        subject="考研数学", ordinal=999, is_assessable=True, is_active=True,
                        summary="隔离测试节点，不代表额外正式课程内容。"),
                    KnowledgePoint(id=UUID("bf1bae96-320f-42d1-acbd-f17de7709dd4"),
                        code="fixture.cs.ds", name="线性表（隔离测试节点）", subject="408", ordinal=999,
                        is_assessable=True, is_active=True,
                        summary="合成测试知识点；本节点故意没有系统讲义。"),
                ])
                db.flush()
                seed_result = seed_all(db, include_exam_references=False)
            from sqlalchemy import text
            with engine.connect() as connection:
                counts = {table: int(connection.scalar(text(f"SELECT count(*) FROM public.{table}")))
                    for table in ("knowledge_points", "questions", "question_versions", "kp_states",
                        "chat_sessions", "chat_messages", "practice_requests", "learning_tasks",
                        "daily_plans", "practice_items", "question_attempts", "learning_events")}
            if any(counts[table] for table in ("chat_sessions", "chat_messages", "practice_requests")):
                raise RuntimeError("fresh_database_unexpected_user_history")
            if os.environ.get('NAIWA_CLOSEOUT_RAG_FIXTURE') == '1':
                from scripts.naiwa_closeout_fixtures_20261024 import prepare_material
                prepare_material(factory, data_home=DATA_HOME, audit=AUDIT)
        finally:
            engine.dispose()

        identity = {
            "cluster_id": manager.owner["cluster_id"], "system_identifier": system_identifier,
            "cluster_directory": str(manager.cluster.resolve()), "database": DATABASE,
            "role": APP_USER, "host": "127.0.0.1", "port": PG_PORT,
            "postmaster_identity": list(manager._owned_identity or ()),
            "retained_experience_cluster_reused": False, "daily_5433_reused": False,
        }
        _new_json(AUDIT / "ports-and-database-identity.json", {
            "preflight": preflight, "identity": identity,
            "row_counts_after_seed": counts, "seed_result": seed_result,
            "synthetic_408_node_has_no_system_lesson": True,
            "target_database_name_is_not_retained_experience_database": DATABASE != "naiwa_experience_test",
            "target_data_directory_is_not_retained_experience_directory": True,
            "captured_at": time.time(),
        })
        runtime_data = {"cluster_id": identity["cluster_id"], "today_plan_id": None,
                        "study_date": time.strftime("%Y-%m-%d"), "today_plan_count": 0}
        _new_json(RUN_OVERRIDE / "runtime-data.json", runtime_data)
        provider_before = _sha(runtime.LEDGER)
        _new_json(AUDIT / "pre-provider-verification.json", {
            "source_epoch": epoch.get("epoch"), "source_sha256": epoch.get("source_sha256"),
            "database_identity": identity, "provider": effective.llm_model,
            "provider_endpoint": effective.llm_base_url, "provider_key_logged": False,
            "active_ledger_sha256": provider_before, "active_ledger_count": preflight["active_ledger_count"],
            "paid_enabled": False, "browser_ui_tested": False,
        })
        _start_services(setup_env, identity)
    except BaseException:
        try:
            runtime.paid.gate().seal("fresh_runtime_setup_failed_closed")
        except Exception:
            pass
        raise
    finally:
        if owned and manager._owned_identity is not None:
            manager.stop()
        if owned:
            try:
                _new_json(AUDIT / "postgres-stop-verification.json", {
                    "cluster_id": manager.owner.get("cluster_id") if manager.owner else None,
                    "postmaster_identity_after_stop": manager._identity(),
                    "stop_verified": manager._identity() is None,
                })
            except FileExistsError:
                pass


def probe(case_id: str, title: str, prompt: str, route: str, context_key: str, purpose: str) -> int:
    import re
    import hashlib
    runtime.validate_parent_ledger()
    runtime.paid.validate_history()
    if (not (AUDIT / "startup-verification.json").is_file()
            or not (RUN_OVERRIDE / "loaded-code.json").is_file()):
        raise RuntimeError("fresh_runtime_not_ready")
    loaded = runtime.read(RUN_OVERRIDE / "loaded-code.json")
    if loaded.get("source_epoch") != SOURCE_EPOCH or loaded.get("database", {}).get("db") != DATABASE:
        raise RuntimeError("probe_loaded_runtime_identity_mismatch")
    scene = {"A-MATH-CORE": "A", "E-408": "B", "E-408-LECTURE": "B", "B-GENERATION": "C",
             "D-RAG": "D", "C-AGENT": "E", "F-COMPOSITE": "F",
             "G-SSE": "H", "H-RETEST": "R"}.get(case_id)
    if scene is None:
        raise RuntimeError("probe_case_not_authorized")
    ledger_before = runtime.read(runtime.LEDGER)
    count_before = len(ledger_before["requests"])
    ledger_sha_before = _sha(runtime.LEDGER)
    if (count_before < ROUND_BASELINE_REQUEST_COUNT
            or count_before >= ROUND_BASELINE_REQUEST_COUNT + ROUND_MAX_NEW_REQUESTS):
        raise RuntimeError("differentiated_round_request_cap_reached")
    if (ledger_before.get("stop_reason") or any(not row.get("finished") for row in ledger_before["requests"])
            or sum(row.get("case_id") == scene for row in ledger_before["requests"])
                >= runtime.ROUND_GATE_SCENE_CAPS[scene]):
        raise RuntimeError("probe_budget_or_request_state_stop")
    if case_id == "D-RAG":
        if route != "materials" or purpose != "qa":
            raise RuntimeError("rag_probe_requires_materials_qa_route")
    elif route != "assistant" or purpose != "study":
        raise RuntimeError("differentiated_probe_requires_study_assistant_route")
    if case_id in {"E-408", "B-GENERATION", "C-AGENT"} and context_key not in {"linear_list", "lhopital"}:
        raise RuntimeError("study_probe_context_invalid")
    if case_id == "E-408-LECTURE" and context_key != "408_sort":
        raise RuntimeError("408_lecture_probe_context_invalid")
    if runtime.read(runtime.OUT / "control.json").get("paid_enabled"):
        raise RuntimeError("paid_gate_unexpectedly_open_before_probe")
    # The probe's local before/after snapshot must point at the same disposable
    # database as the already-running API.  Resolve credentials only in memory
    # from this task-owned cluster; never print or persist the URL.
    probe_pg = ManagedPostgres(
        RuntimePaths.windows(resources=ROOT / "backend", local_app_data=OWNED_DATA),
        PG_BIN, port=PG_PORT,
    )
    probe_pg._load_owner()
    probe_pg._load_passwords()
    from sqlalchemy.engine import make_url
    # ManagedPostgres.database_url intentionally targets its normal desktop
    # default; this round creates a separately named database in that owned
    # cluster, so pin the explicitly authorized database before passing it to
    # the read-only snapshot helper.
    probe_database_url = make_url(probe_pg.database_url).set(database=DATABASE).render_as_string(
        hide_password=False)
    parsed_probe_url = make_url(probe_database_url)
    if (parsed_probe_url.host, parsed_probe_url.port, parsed_probe_url.database,
            parsed_probe_url.username) != ("127.0.0.1", PG_PORT, DATABASE, APP_USER):
        raise RuntimeError("probe_snapshot_database_identity_mismatch")
    gate = runtime.paid.gate()
    control_payload = {"paid_enabled": True, "authorization_received": True,
                       "active_scene": scene, "reason": "explicit_user_authorized_differentiated_probe",
                       "opened_at": time.time(), "case_id": case_id, "scope": "single_probe_process"}
    atomic_json(runtime.OUT / "control.json", control_payload)
    command = [sys.executable, str(ROOT / "storage/quality-audits/naiwa-differentiated-acceptance-20261024/service_probe.py"),
               case_id, title, prompt, route, context_key, purpose]
    env = {**os.environ, "APP_ENV": "test", "NAIWA_ISOLATED_DATABASE": DATABASE,
           "NAIWA_ISOLATED_PG_PORT": str(PG_PORT), "NAIWA_ISOLATED_API_PORT": str(API_PORT),
           "NAIWA_ISOLATED_WEB_PORT": str(WEB_PORT), "NAIWA_V33_CONTINUATION_TAG": "r8z",
           "NAIWA_V33_EXPLORATORY_LEDGER_TAG": "r8z", "NAIWA_V33_CONTINUATION_RUN": str(RUN_OVERRIDE),
           "NAIWA_FRESH_TEST_DATABASE": "1", "DATABASE_URL": probe_database_url,
           "TEST_DATABASE_URL": probe_database_url}
    try:
        completed = subprocess.run(command, cwd=ROOT, env=env, timeout=240,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output = completed.stdout[-4000:]
        ledger_after = runtime.read(runtime.LEDGER)
        added = ledger_after["requests"][count_before:]
        evidence = {
            "case_id": case_id, "scene": scene, "user_prompt": prompt,
            "route": route, "session_purpose": purpose, "context_key": context_key,
            "command_exit_code": completed.returncode, "physical_reservations_added": len(added),
            "request_ids": [row.get("request_id") for row in added],
            "ledger_count_before": count_before, "ledger_count_after": len(ledger_after["requests"]),
            "ledger_sha256_before": ledger_sha_before,
            "ledger_sha256_after": _sha(runtime.LEDGER),
            "provider_records": [{k: row.get(k) for k in ("request_id", "case_id", "purpose", "state",
                "finished", "http_dispatch_attempts", "http_status", "response_model", "finish_reason", "usage", "error_type")}
                for row in added],
            "probe_process_output_tail": output, "browser_ui_tested": False,
            "evidence_level": "real_deepseek_backend_route_not_browser_ui",
            "captured_at": time.time(),
        }
        _new_json(AUDIT / f"{re.sub(r'[^A-Za-z0-9_-]', '_', case_id)}-execution-{time.time_ns()}.json", evidence)
        print(json.dumps({"case_id": case_id, "exit_code": completed.returncode,
                          "physical_requests_added": len(added), "request_ids": evidence["request_ids"],
                          "ledger_count_after": len(ledger_after["requests"]),
                          "evidence_level": evidence["evidence_level"]}, ensure_ascii=False))
        return completed.returncode
    finally:
        gate.seal("single_probe_finished_closed")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    p = sub.add_parser("probe")
    for name in ("case_id", "title", "prompt", "route", "context_key", "purpose"):
        p.add_argument(name)
    args = parser.parse_args()
    if args.command == "serve":
        serve()
        return 0
    return probe(args.case_id, args.title, args.prompt, args.route, args.context_key, args.purpose)


if __name__ == "__main__":
    raise SystemExit(main())
