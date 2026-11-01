"""Restore the retained 19-call experience database with model egress sealed.

No initdb, CREATE DATABASE, migrations, seed, grants, or live credentials.
The original acceptance script/evidence and database remain in place.
"""
from pathlib import Path
import argparse
import hashlib
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOME = ROOT / "storage/manual-experience/naiwa-real-20261020"
RUN = HOME / "restored-offline-20261020"
AUDIT = ROOT / "storage/quality-audits/naiwa-restore-20261020"
ORIGINAL = ROOT / "storage/quality-audits/naiwa-real-20261020"
DATABASE = "naiwa_experience_test"
MODULES = (
    "backend.chat.service", "backend.services.assistant_router",
    "backend.services.learning_task_service", "backend.services.learning_task_tools",
    "backend.services.learning_assistant_service", "backend.services.personal_question_service",
    "backend.services.personal_question_general", "backend.services.generation_formula_consistency",
    "backend.services.question_generation", "backend.services.personal_generation_intent",
    "backend.services.learning_planner_scope",
    "backend.chat.http_clients", "backend.services.model_failure",
    "backend.services.vision_recognition_service", "scripts.phase5_eval_meter",
    "scripts.naiwa_transport_guards_20261021",
)
TABLES = ("chat_sessions", "chat_messages", "questions", "question_versions", "daily_plans",
    "practice_items", "question_attempts", "learning_events", "learning_tasks",
    "personal_generation_batches", "materials", "document_chunks", "message_citations", "kp_states")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def config():
    values = json.loads((HOME / "config.json").read_text(encoding="utf-8"))
    assert set(values) == {"pg_port", "api_port", "web_port"}
    assert len(set(values.values())) == 3
    assert all(type(p) is int and 18000 < p < 65536 and p not in {5433, 8000, 5173} for p in values.values())
    assert json.loads((HOME / "initialized.json").read_text(encoding="utf-8"))["database"] == DATABASE
    assert json.loads((HOME / "control.json").read_text(encoding="utf-8"))["paid_enabled"] is False
    return values


def existing_manager():
    from scripts.naiwa_acceptance_20261020 import manager
    pg = manager()
    assert pg.marker.is_file() and pg.credentials.is_file() and (pg.cluster / "PG_VERSION").is_file()
    pg.preflight()
    pg._load_owner()
    pg._load_passwords()
    previous = json.loads((HOME / "runtime.json").read_text(encoding="utf-8"))
    assert pg.owner["cluster_id"] == previous["cluster_id"]
    assert pg.cluster.resolve() == Path(previous["cluster"]).resolve()
    return pg


def database_url(pg):
    from sqlalchemy.engine import make_url
    url = make_url(pg.database_url).set(database=DATABASE)
    assert (url.host, url.port, url.database) == ("127.0.0.1", config()["pg_port"], DATABASE)
    return url


def snapshot(name):
    from sqlalchemy import create_engine, text
    pg = existing_manager()
    engine = create_engine(database_url(pg))
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            identity = dict(conn.execute(text(
                "SELECT current_database() db,current_user role,current_setting('port') port")).one()._mapping)
            assert identity["db"] == DATABASE and int(identity["port"]) == pg.port
            data = {t: [dict(row._mapping) for row in conn.execute(text("SELECT * FROM public." + t))] for t in TABLES}
            data["identity"] = identity
            data["schema_revision"] = conn.scalar(text("SELECT version_num FROM alembic_version"))
        save(AUDIT / (name + ".json"), data)
        return data
    finally:
        engine.dispose()


def sealed_app():
    # Runs only inside the dedicated isolated Uvicorn process.
    c = config()
    assert os.environ["APP_ENV"] == "test"
    from sqlalchemy.engine import make_url
    url = make_url(os.environ["DATABASE_URL"])
    assert (url.host, url.port, url.database) == ("127.0.0.1", c["pg_port"], DATABASE)
    from backend.config import get_settings
    from backend.chat.http_clients import configure_isolated_provider_http, policy
    configure_isolated_provider_http(get_settings())

    from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate, disable_provider_retries
    gate = FinalRoundGate(preparation=True)
    gate.seal('phase1_no_real_model_authorization')
    gate.install()
    sys.addaudithook(gate.socket_guard)
    # Invoke the audit hook directly: this proves denial without DNS or a socket.
    try:
        sys.audit("socket.connect", None, ("192.0.2.1", 443))
    except RuntimeError as exc:
        assert str(exc) == "non_database_socket_closed"
    else:
        raise RuntimeError("sealed_guard_self_check_failed")

    from scripts import manual_naiwa_experience as fixed
    fixed.HOME = RUN  # Fixed-provider request notes belong only to this restore.
    from backend.chat import service
    disable_provider_retries(service.Provider)
    service.Provider = fixed.FixedProvider
    from backend.app import create_app
    application = create_app()
    application.state.final_round_gate = gate
    application.state.personal_generation_provider = fixed.FixedProvider(structured_generation=True)
    loaded = {}
    for name in MODULES:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(ROOT)
        loaded[str(path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (Path(__file__).resolve(), ROOT/'scripts/naiwa_freeze_gate_20261021.py'):
        loaded[str(path.relative_to(ROOT)).replace('\\','/')] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"pid": os.getpid(), "python": sys.executable, "workspace": str(ROOT),
        "source_sha256": loaded, "provider": fixed.FixedProvider().model,
        "outbound_allowed": "only the owned PostgreSQL port", "guard_self_check_passed": True,
        "real_model_requests": 0, "retained_budget_reservations":len(gate.records),
        "historical_counter_semantics":"retained reservations are not confirmed HTTP sends",
        "production_routes_only": True, "loaded_at": time.time(), "http_policy":policy(),
        "physical_gate": {"ledger":str(gate.path), "installed":gate.installed, "global_limit":5,
            "scene_limits":{"AGENT":4,"GENERATE":1}, "preparation_permanently_closed":True,
            "hook":"httpx sync+async _send_single_request; socket audit guard", "legacy_budget_disabled":True}}
    save(RUN / "loaded-code.json", manifest)

    @application.middleware("http")
    async def label(request, call_next):
        # Preparation must not trigger daily material-search expiry cleanup or
        # accidentally create fixed-provider conversations in the retained archive.
        from starlette.responses import JSONResponse
        # Narrow one-time test-paper setup permit; no chat, answer, or material writes.
        permit_path=RUN/'study-setup-permit.json'
        setup_allowed=False
        if request.method=='POST' and permit_path.exists():
            import hmac
            permit=json.loads(permit_path.read_text(encoding='utf-8'))
            supplied=request.headers.get('X-Naiwa-Setup-Nonce','')
            if (permit.get('enabled') and permit.get('expires_at',0)>time.time()
                    and hmac.compare_digest(supplied,str(permit.get('nonce',''))) and supplied):
                payload=await request.json()
                setup_allowed=(request.url.path=='/api/plans/today/generate'
                    and payload=={'selected_kp_ids':['32a29e1e-8ae3-41fc-9322-43f727596819'],
                        'budget':'light','confirm_legacy_set_transition_ids':[]})
                setup_allowed=setup_allowed or (request.url.path==permit.get('append_path')
                    and payload=={'question_ids':['9ba9c177-26a2-4918-bf84-b85159f9b002']})
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not setup_allowed:
            response = JSONResponse({"error": {"code": "experience_preparation_read_only",
                "message": "当前为零付费只读准备阶段，已阻止写入以保留历史验收记录。"}}, status_code=403)
        else:
            response = await call_next(request)
        response.headers["X-Naiwa-Experience"] = "restored-archive-fixed-provider-egress-sealed"
        response.headers["X-Naiwa-Preparation"] = "read-only-archive-protected"
        response.headers["X-Naiwa-Backend-Pid"] = str(os.getpid())
        return response
    return application


def serve():
    import httpx
    from desktop.postgres import _run
    c = config()
    assert os.environ.get('NAIWA_REAL_RETEST_BUDGET7','0')=='0', 'legacy budget7 entry disabled; final round only'
    pg = existing_manager()
    for value in c.values():
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", value))
    pg.lock.acquire()
    children, handles = [], []
    runtime = None
    try:
        # Existing cluster only: pg_ctl validates a stale postmaster.pid itself.
        started = int(time.time())
        result = _run([pg.binary("pg_ctl"), "-D", str(pg.cluster), "-l", str(RUN / "postgres.log"),
            "-o", f"-p {pg.port} -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic",
            "-w", "-t", "30", "start"], timeout=45, capture=False)
        identity = pg._identity()
        assert result.returncode == 0 and identity and identity[1] >= started - 1
        pg._owned_identity = identity
        baseline_name = "database-before" if not (AUDIT / "database-before.json").exists() else f"database-before-{time.time_ns()}"
        before = snapshot(baseline_name)
        assert before["chat_messages"] and before["questions"], "Existing archive required; no empty recovery"
        env = {**os.environ, "APP_ENV": "test", "DATABASE_URL": database_url(pg).render_as_string(hide_password=False),
            "TEST_DATABASE_URL": database_url(pg).render_as_string(hide_password=False),
            "KAOYAN_OWNED_TEST_PORT": str(pg.port), "LLM_API_KEY": "offline-placeholder-not-a-secret",
            "LLM_BASE_URL": "http://127.0.0.1:9", "LLM_MODEL": "FIXED-OFFLINE-NO-PAID-MODEL",
            "MODEL_SETTINGS_PATH": str(RUN / "fixed-settings.bin"), "UPLOAD_DIR": str(HOME / "uploads"),
            "CHROMA_DIR": str(HOME / "chroma"), "MODEL_CACHE_DIR": str(ROOT / "storage/models"),
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "ANONYMIZED_TELEMETRY": "False",
            "DO_NOT_TRACK": "1", "OTEL_SDK_DISABLED": "true", "PYTHONIOENCODING": "utf-8",
            "ALLOWED_WEB_ORIGINS": json.dumps([f"http://127.0.0.1:{c['web_port']}"]),
            "VITE_API_PROXY_TARGET": f"http://127.0.0.1:{c['api_port']}"}
        real_retest = os.environ.get("NAIWA_REAL_RETEST_BUDGET7") == "1"
        final_retest = os.environ.get('NAIWA_FINAL_ROUND_STAGE2') == '1'
        if final_retest:
            from scripts.naiwa_final_real_20261021 import OUT as final_out
            assert json.loads((final_out/'authorization.json').read_text(encoding='utf-8'))['explicit_user_authorized']
            from backend.config import get_settings
            from backend.services.model_settings_service import load_local_settings
            effective = load_local_settings(get_settings())
            assert effective.llm_api_key and effective.llm_model == 'deepseek-flash'
            assert effective.llm_base_url.rstrip('/') == 'https://api.deepseek.com'
            key=effective.llm_api_key
            key=key.get_secret_value() if hasattr(key,'get_secret_value') else str(key)
            env.update(LLM_API_KEY=key,LLM_BASE_URL=effective.llm_base_url,LLM_MODEL=effective.llm_model,
                LLM_STREAM_INCLUDE_USAGE='true',MODEL_SETTINGS_PATH=str(final_out/'isolated-model-settings.bin'))
        if real_retest:
            from scripts.naiwa_real_retest_20261020 import OUT
            assert json.loads((OUT / "counter-selftest.json").read_text())["status"] == "PASS"
            assert json.loads((OUT / "control.json").read_text())["paid_enabled"] is False
            from backend.config import get_settings
            from backend.services.model_settings_service import load_local_settings
            effective = load_local_settings(get_settings())  # Local encrypted settings only; no daily DB.
            assert effective.llm_api_key and effective.llm_model == "deepseek-flash"
            assert effective.llm_base_url.rstrip("/") == "https://api.deepseek.com"
            key = effective.llm_api_key
            key = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
            env.update(LLM_API_KEY=key, LLM_BASE_URL=effective.llm_base_url,
                LLM_MODEL=effective.llm_model, LLM_STREAM_INCLUDE_USAGE="true",
                MODEL_SETTINGS_PATH=str(OUT / "isolated-model-settings.bin"))
        commands = [[sys.executable, "-m", "uvicorn", "scripts.restore_naiwa_experience_20261020:sealed_app",
            "--factory", "--host", "127.0.0.1", "--port", str(c["api_port"])],
            ["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(c["web_port"]), "--strictPort"]]
        if real_retest:
            commands[0][3] = "scripts.naiwa_real_retest_20261020:real_app"
        if final_retest:
            commands[0][3] = 'scripts.naiwa_final_real_20261021:real_app'
        for name, command, cwd in zip(("backend", "frontend"), commands, (ROOT, ROOT / "frontend")):
            handle = (RUN / (name + ".log")).open("a", encoding="utf-8"); handles.append(handle)
            children.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW))
        runtime = {**c, "status": "starting", "workspace": str(ROOT), "python": sys.executable,
            "supervisor_pid": os.getpid(), "backend_pid": children[0].pid, "frontend_pid": children[1].pid,
            "postgres_pid": identity[0], "cluster": str(pg.cluster), "cluster_id": pg.owner["cluster_id"],
            "database": before["identity"], "schema_revision": before["schema_revision"], "commands": commands,
            "frontend_url": f"http://127.0.0.1:{c['web_port']}", "api_url": f"http://127.0.0.1:{c['api_port']}",
            "provider": "fixed-provider; network sealed", "real_model_requests": 0, "data_retained": True,
            "migrations_seed_grants": False, "baseline_snapshot": baseline_name + ".json", "started_at": time.time()}
        save(RUN / "runtime.json", runtime)
        if real_retest:
            runtime["provider"] = "real DeepSeek, browser-scoped budget7, initially sealed"
            save(RUN / "runtime.json", runtime)
        if final_retest:
            runtime['provider']='real DeepSeek final5 browser-scoped; initially closed'
            save(RUN/'runtime.json',runtime)
        with httpx.Client(trust_env=False, timeout=3) as client:
            for _ in range(150):
                assert all(child.poll() is None for child in children), "restored_child_exited"
                try:
                    response = client.get(runtime["frontend_url"] + "/api/health")
                    if response.status_code == 200 and response.json().get("database") == "connected":
                        expected = "real-retest-budget7" if real_retest else "restored-archive-fixed-provider-egress-sealed"
                        if final_retest:expected='final-real-retest5'
                        assert response.headers.get("X-Naiwa-Experience") == expected
                        runtime["health"] = response.json()
                        runtime["status"] = "running"
                        save(RUN / "runtime.json", runtime)
                        after_name = "database-after-start" if not (AUDIT / "database-after-start.json").exists() else f"database-after-start-{time.time_ns()}"
                        snapshot(after_name)
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("restored_startup_timeout")
        while not (RUN / "stop.request").exists():
            assert all(child.poll() is None for child in children), "restored_child_exited"
            time.sleep(1)
    except BaseException as exc:
        save(RUN / "last-error.json", {"type": type(exc).__name__, "message": str(exc)[:160]})
        raise
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate(); child.wait(timeout=25)
        for handle in handles:
            handle.close()
        pg.stop()
        if runtime:
            runtime["status"] = "stopped"; save(RUN / "runtime.json", runtime)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "serve", "status", "stop", "snapshot", "verify"))
    action = parser.parse_args().action
    c = config()
    RUN.mkdir(parents=True, exist_ok=True); AUDIT.mkdir(parents=True, exist_ok=True)
    if action == "serve":
        return serve()
    if action == "snapshot":
        data = snapshot("database-current")
        print(json.dumps({"identity": data["identity"], "counts": {t: len(data[t]) for t in TABLES}}))
        return
    if action == "verify":
        current = json.loads(json.dumps(snapshot("database-current"), default=str))
        baseline = json.loads((AUDIT / "database-before.json").read_text(encoding="utf-8"))
        def row_key(row):
            return str(row.get("id", row.get("kp_id")))
        changes = {}
        for table in TABLES:
            previous = {row_key(row): row for row in baseline[table]}
            present = {row_key(row): row for row in current[table]}
            changes[table] = {"before": len(previous), "current": len(present),
                "missing_original_ids": sorted(set(previous) - set(present)),
                "changed_original_ids": sorted(key for key in previous.keys() & present.keys() if previous[key] != present[key]),
                "new_ids": sorted(set(present) - set(previous))}
        expected = set(json.loads((ORIGINAL / "sessions.json").read_text(encoding="utf-8")).values())
        actual_sessions = {str(row["id"]) for row in current["chat_sessions"]}
        ledger = json.loads((ORIGINAL / "provider-ledger.json").read_text(encoding="utf-8"))
        original_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (ORIGINAL / "provider-ledger.json", ORIGINAL / "journeys.json", ORIGINAL / "sessions.json")}
        evidence_unchanged = {name: value == hashlib.sha256((AUDIT / "previous-evidence" / name).read_bytes()).hexdigest()
            for name, value in original_hashes.items()}
        loaded = json.loads((RUN / "loaded-code.json").read_text(encoding="utf-8"))
        sources = {name: digest == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name, digest in loaded["source_sha256"].items()}
        from backend.services.personal_question_general import GeneralOutput
        generated = []
        for question in baseline["questions"]:
            generation = (question.get("grading_config") or {}).get("generation") or {}
            if generation.get("authoring_mode") != "real_model":
                continue
            candidate = {key: question.get(key) for key in ("stem", "question_type", "options", "correct_answer", "explanation")}
            candidate.update(final_value=generation.get("final_value"), steps=generation.get("explanation_steps") or [])
            try:
                GeneralOutput.model_validate(candidate)
                outcome = "no_confirmed_conflict_found_not_a_correctness_certificate"
                issue = None
            except ValueError as exc:
                outcome = "rejected_by_current_gate_offline_replay"
                issue = [{"field": entry["loc"], "message": entry["msg"], "type": entry["type"]}
                    for entry in exc.errors(include_url=False, include_input=False)] if hasattr(exc, "errors") else type(exc).__name__
            generated.append({"id": question["id"], "version_id": question["current_version_id"], "outcome": outcome, "issue": issue})
        report = {"identity": current["identity"], "table_preservation": changes,
            "historical_session_ids_expected": sorted(expected), "historical_session_ids_missing": sorted(expected - actual_sessions),
            "original_evidence_hash_unchanged": evidence_unchanged,
            "historical_physical_requests": len(ledger["requests"]), "this_restore_physical_requests": 0,
            "loaded_sources_match_current_workspace": sources, "guard_self_check_passed": loaded["guard_self_check_passed"],
            "historical_generated_question_offline_replay": generated,
            "historical_agent_tasks": [{key: row.get(key) for key in ("id", "status", "error_code", "message")}
                for row in baseline["learning_tasks"]]}
        report["all_original_rows_unchanged"] = all(not value["missing_original_ids"] and not value["changed_original_ids"] for value in changes.values())
        save(AUDIT / "restoration-checks.json", report)
        print(json.dumps({key: report[key] for key in ("identity", "historical_session_ids_missing", "historical_physical_requests",
            "this_restore_physical_requests", "all_original_rows_unchanged", "original_evidence_hash_unchanged",
            "loaded_sources_match_current_workspace", "historical_generated_question_offline_replay")}, ensure_ascii=False))
        return
    if action == "status":
        print((RUN / "runtime.json").read_text(encoding="utf-8"))
        return
    if action == "stop":
        (RUN / "stop.request").touch()
        print("Only the restored offline supervisor will stop; database retained.")
        return
    for value in c.values():
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", value))
    for path in (HOME / "runtime.json", HOME / "control.json", HOME / "config.json", HOME / "initialized.json",
            ORIGINAL / "provider-ledger.json", ORIGINAL / "journeys.json", ORIGINAL / "sessions.json"):
        target = AUDIT / "previous-evidence" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(path, target)
    (RUN / "stop.request").unlink(missing_ok=True)
    with (RUN / "supervisor.log").open("a", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__)), "serve"], cwd=ROOT,
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    print(json.dumps({"supervisor_pid": child.pid, "frontend_url": f"http://127.0.0.1:{c['web_port']}", "paid_enabled": False}))


if __name__ == "__main__":
    main()
