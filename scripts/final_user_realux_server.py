"""One isolated, metered real-user UX run for the 2026-10-16 final closeout."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "storage/quality-audits/final-real-user-20261016/realux-v1"
PLAN = ROOT / "eval/final-user-realux-v1/plan.json"
DATABASE = "phase5_final_user_realux_20261016_test"
BASE = "phase5_final_retest_base_20261015_test"
PORT = 59271
OWNER_SYSTEM_IDENTIFIER = "7696773489828724208"
URL = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{DATABASE}"
TABLES = ("knowledge_points", "questions", "question_versions", "question_source_attestations",
          "question_answer_consistency_runs", "question_answer_verification_events",
          "question_auto_review_events", "exam_question_references", "kp_graduation_question_set_versions",
          "kp_mastery_policies", "question_attempts", "learning_events", "kp_states", "daily_plans",
          "practice_items", "learning_tasks", "practice_requests", "personal_generation_batches",
          "chat_sessions", "chat_messages", "message_citations", "materials", "document_chunks",
          "chunk_knowledge_points", "document_jobs")


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def verify_cluster():
    import psycopg
    with psycopg.connect(f"postgresql://postgres@127.0.0.1:{PORT}/postgres",
                         options="-c default_transaction_read_only=on", connect_timeout=3) as conn:
        identity = str(conn.execute("select system_identifier from pg_control_system()").fetchone()[0])
        assert identity == OWNER_SYSTEM_IDENTIFIER, "not_the_owned_phase5_eval_cluster"
        assert conn.execute("select current_setting('port')").fetchone()[0] == str(PORT)


def check_cluster():
    verify_cluster()
    print(json.dumps({"database": DATABASE, "port": PORT,
        "system_identifier": OWNER_SYSTEM_IDENTIFIER, "checked": True}))


def configure():
    os.environ.update(APP_ENV="test", DATABASE_URL=URL, TEST_DATABASE_URL=URL,
        KAOYAN_OWNED_TEST_PORT=str(PORT), UPLOAD_DIR=str(OUT / "uploads"),
        CHROMA_DIR=str(OUT / "chroma"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        LLM_STREAM_INCLUDE_USAGE="true", CAPTURE_TEST_EVIDENCE="true",
        ALLOWED_WEB_ORIGINS='["http://127.0.0.1:5184"]')
    from backend.config import get_settings
    get_settings.cache_clear()


def snapshot():
    import psycopg
    verify_cluster()
    with psycopg.connect(URL.replace("postgresql+psycopg", "postgresql"),
                         options="-c default_transaction_read_only=on", connect_timeout=5) as conn:
        return {table: {
            "rows": len(rows := conn.execute(
                f'select row_to_json(t)::text from "{table}" t order by row_to_json(t)::text').fetchall()),
            "sha256": hashlib.sha256("\n".join(row[0] for row in rows).encode()).hexdigest(),
        } for table in TABLES}


def hashes():
    files = [*(ROOT / "backend").rglob("*.py"), *(ROOT / "frontend/src").rglob("*.ts"),
             *(ROOT / "frontend/src").rglob("*.vue"), ROOT / "scripts/phase5_eval_meter.py",
             Path(__file__), ROOT / "scripts/final_user_realux_browser.cjs",
             ROOT / "scripts/final_user_realux_smoke.cjs", ROOT / "scripts/run_final_user_realux_case.ps1", PLAN]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files if path.is_file()}


def evaluation_stream_allowed(case_id, request_path, cases_by_id):
    """Allow only the business stream used by the frozen case's actual surface.

    ChatPage uses ``assistant:stream`` for ordinary QA; the dedicated materials
    search page uses ``answers:stream``.  Case ID prefixes are not a reliable
    proxy for those routes because the QA set contains both surfaces.
    """
    case = cases_by_id.get(case_id)
    if not case:
        return False
    surface = case.get("surface")
    expected_suffix = {
        "materials": "/answers:stream",
        "chat": "/assistant:stream",
        "study": "/assistant:stream",
    }.get(surface)
    return bool(expected_suffix and request_path.endswith(expected_suffix))


def evaluation_stream_rejection_status(case_id, request_path, cases_by_id, allowed_case_ids):
    """Keep the run-scope conflict response while validating the real route contract."""
    if case_id not in allowed_case_ids or not evaluation_stream_allowed(case_id, request_path, cases_by_id):
        return 409
    return None


def prepare():
    import psycopg
    from psycopg import sql
    from sqlalchemy import select, text
    verify_cluster()
    assert not OUT.exists(), "new-run-output-already-exists; never overwrite or resume"
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert plan["physical_provider_request_hard_limit"] == 20
    assert len(plan["cases_in_priority_order"]) == 20
    with psycopg.connect(f"postgresql://postgres@127.0.0.1:{PORT}/postgres", autocommit=True) as conn:
        assert conn.execute("select 1 from pg_database where datname=%s", (DATABASE,)).fetchone() is None, "database_already_exists"
        assert conn.execute("select 1 from pg_database where datname=%s", (BASE,)).fetchone(), "sealed_template_missing"
        conn.execute(sql.SQL("create database {} template {}").format(sql.Identifier(DATABASE), sql.Identifier(BASE)))
    configure()
    from backend.db import create_db_engine, create_session_factory
    from backend.models.learning import KnowledgePoint, KpState
    from scripts.phase5_run_frozen_ai_eval import seed_profile
    from uuid import UUID
    OUT.mkdir(parents=True)
    engine = create_db_engine(URL)
    factory = create_session_factory(engine)
    now = datetime.now(timezone.utc)
    with factory() as db:
        node_map = {}
        for key, code in (("integral", "math.exam.c431f98f817c"),
                          ("determinant", "math.exam.f4e5ed0360ea"),
                          ("derivative", "math.exam.de439863790e"),
                          ("encoding", "cs408.co.topic.324b03e7b481")):
            node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == code))
            assert node is not None, f"required_real_leaf_missing:{code}"
            node_map[key] = {"id": str(node.id), "code": node.code, "name": node.name}
    seed_profile(factory, {"profile": "weak_integral"}, UUID(node_map["integral"]["id"]), now)
    seed_profile(factory, {"profile": "solution_integral"}, UUID(node_map["integral"]["id"]), now - timedelta(days=3))
    seed_profile(factory, {"profile": "graduated_determinant"}, UUID(node_map["determinant"]["id"]), now)
    with factory() as db:
        today = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
        assert db.scalar(text("select count(*) from daily_plans where study_date=:day"), {"day": today}) == 0
        assert db.get(KpState, UUID(node_map["determinant"]["id"])).mastered_at is not None
        counts = {table: db.scalar(text(f'select count(*) from "{table}"')) for table in TABLES}
    engine.dispose()
    write("fixture.json", {"database": DATABASE, "port": PORT, "system_identifier": OWNER_SYSTEM_IDENTIFIER,
        "template_database": BASE, "created_at": now.isoformat(), "nodes": node_map,
        "table_counts": counts, "method": "owned sealed-bank clone; learning evidence seeded through existing test services",
        "source_files_uploaded_by_browser": True})
    write("truth-before.json", snapshot())
    write("runtime-hashes.json", hashes())
    write("authorization.json", {"user_authorization": "Phase 5 final real-user UX prompt: max 20 physical DeepSeek requests",
        "authorized_at": datetime.now(timezone.utc).isoformat(), "plan_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        "provider": "official DeepSeek API", "model": "deepseek-flash", "endpoint_host": "api.deepseek.com",
        "database": DATABASE, "port": PORT, "system_identifier": OWNER_SYSTEM_IDENTIFIER,
        "supplier_hard_currency_cap": False, "peak_price_checked_utc_date": "2026-10-16",
        "input_peak_cny_per_million_conservative": "2.10", "output_peak_cny_per_million_conservative": "8.10",
        "meter_limits": plan["meter_limits"], "paid_judge_requests": 0})
    print(json.dumps({"prepared": True, "database": DATABASE, "system_identifier": OWNER_SYSTEM_IDENTIFIER,
                      "table_counts": counts, "real_provider_requests": 0}, ensure_ascii=False))


def freeze_runtime():
    """Freeze the pre-call runtime once; safe only before the first Provider request."""
    assert (OUT / "authorization.json").exists()
    ledger_path = OUT / "provider-ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert not ledger.get("stop_reason") and not ledger.get("requests"), "cannot_refreeze_after_any_paid_request"
    write("runtime-hashes.json", hashes())
    write("runtime-freeze.json", {"frozen_at": datetime.now(timezone.utc).isoformat(),
        "plan_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        "provider_requests_at_freeze": 0, "meter_empty_at_freeze": True,
        "prompt_or_code_changes_after_freeze": "prohibited"})
    print(json.dumps({"frozen": True, "provider_requests": 0, "hash_count": len(hashes())}))


def preflight():
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    verify_cluster()
    configure()
    settings = get_settings()
    effective = load_local_settings(settings)
    assert effective.llm_base_url.rstrip("/") == "https://api.deepseek.com"
    assert effective.llm_model == "deepseek-flash"
    assert effective.llm_api_key and not effective.local_model_settings_error
    current = snapshot()
    original_baseline = json.loads((OUT / "truth-before.json").read_text(encoding="utf-8"))
    extended_path = OUT / "truth-before-extended.json"
    if extended_path.exists():
        baseline = json.loads(extended_path.read_text(encoding="utf-8"))
    else:
        if not set(original_baseline).issubset(current):
            raise AssertionError("original_business_baseline_has_unknown_tables")
        if any(current[table] != values for table, values in original_baseline.items()):
            raise AssertionError("isolated_business_baseline_changed_before_ai_run")
        write("truth-before-extended.json", current)
        baseline = current
    assert current == baseline, "isolated_business_baseline_changed_before_ai_run"
    result = {"status": "PREFLIGHT_PASS", "database": DATABASE, "port": PORT,
        "system_identifier": OWNER_SYSTEM_IDENTIFIER, "model": effective.llm_model,
        "provider_host": "api.deepseek.com", "api_key_present": bool(effective.llm_api_key),
        "physical_provider_requests": 0,
        "table_counts": {table: values["rows"] for table, values in current.items()},
        "snapshot_scope_extended_without_mutation": sorted(set(current) - set(original_baseline)),
        "snapshot_matches_prepared_baseline": True, "original_development_database_touched": False}
    write("preflight.json", result)
    print(json.dumps(result, ensure_ascii=False))


def app():
    import httpx
    from fastapi.responses import JSONResponse
    from scripts.phase5_eval_meter import Meter
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    verify_cluster()
    assert (OUT / "authorization.json").exists()
    assert hashes() == json.loads((OUT / "runtime-hashes.json").read_text(encoding="utf-8")), "runtime_changed_after_freeze"
    settings = get_settings()
    effective = load_local_settings(settings)
    assert effective.llm_base_url.rstrip("/") == "https://api.deepseek.com"
    assert effective.llm_model == "deepseek-flash"
    assert effective.llm_api_key and not effective.local_model_settings_error
    configure()
    os.environ.update(LLM_API_KEY=effective.llm_api_key.get_secret_value(), LLM_MODEL=effective.llm_model,
        LLM_BASE_URL=effective.llm_base_url, LLM_STREAM_INCLUDE_USAGE="true",
        LLM_MAX_OUTPUT_TOKENS=str(effective.llm_max_output_tokens),
        LLM_RETRY_MAX_OUTPUT_TOKENS=str(effective.llm_retry_max_output_tokens),
        LLM_TIMEOUT_SECONDS=str(effective.llm_timeout_seconds))
    get_settings.cache_clear()
    meter = Meter(OUT, max_requests=20, max_input_tokens=300000, max_output_tokens=80000,
        stop_cny="1.50", input_cny_per_million="2.10", output_cny_per_million="8.10",
        cache_hit_cny_per_million="0.041")
    ledger_path = OUT / "provider-ledger.json"
    if ledger_path.exists():
        previous = json.loads(ledger_path.read_text(encoding="utf-8"))
        if previous.get("stop_reason") or any(row.get("state") != "COMPLETED_USAGE_OBSERVED" for row in previous.get("requests", [])):
            raise RuntimeError("paid_ledger_stopped_or_usage_unobserved; no restart or retry")
        meter.records = previous["requests"]
    meter.install()
    meter.flush()
    from backend.app import create_app
    application = create_app()
    application.state.final_eval_meter = meter
    application.state.final_eval_active = False
    completed_stream_cases = {row["id"] for row in json.loads(PLAN.read_text(encoding="utf-8"))["cases_in_priority_order"]
        if (OUT / f"truth-after-{row['id']}.json").exists()}
    application.state.final_eval_seen = completed_stream_cases
    application.state.final_eval_confirm_used = False
    baseline_path = OUT / "truth-before-extended.json"
    if not baseline_path.exists(): baseline_path = OUT / "truth-before.json"
    application.state.final_eval_approved_snapshot = json.loads(baseline_path.read_text(encoding="utf-8"))
    for row in json.loads(PLAN.read_text(encoding="utf-8"))["cases_in_priority_order"]:
        after_path = OUT / f"truth-after-{row['id']}.json"
        if after_path.exists(): application.state.final_eval_approved_snapshot = json.loads(after_path.read_text(encoding="utf-8"))
        if row["id"] == "Agent-07" and (OUT / "confirmed-plan-mutation.json").exists():
            application.state.final_eval_approved_snapshot = json.loads((OUT / "confirmed-plan-mutation.json").read_text(encoding="utf-8"))["after"]
    allowed = {row["id"] for row in json.loads(PLAN.read_text(encoding="utf-8"))["cases_in_priority_order"]}
    cases_by_id = {row["id"]: row for row in json.loads(PLAN.read_text(encoding="utf-8"))["cases_in_priority_order"]}

    @application.middleware("http")
    async def scope_and_snapshot(request, call_next):
        is_chat = request.method == "POST" and request.url.path.endswith(("/answers:stream", "/assistant:stream"))
        is_confirm = request.method == "POST" and "/api/learning-tasks/" in request.url.path and request.url.path.endswith("/confirm")
        cid = request.headers.get("x-final-eval-case")
        if is_confirm:
            if cid != "Agent-07" or application.state.final_eval_confirm_used:
                return JSONResponse({"error": "only_explicit_agent_07_confirmation_is_allowed"}, status_code=409)
            before = snapshot()
            response = await call_next(request)
            after = snapshot()
            allowed_confirmation_tables = {"daily_plans", "practice_items", "learning_tasks"}
            unchanged_tables = set(TABLES) - allowed_confirmation_tables
            if any(before[key] != after[key] for key in unchanged_tables):
                meter.stop_reason = "confirmed_action_changed_protected_business_facts"
            if response.status_code >= 400:
                meter.stop_reason = "explicit_confirmation_request_failed"
            if (after["daily_plans"]["rows"] <= before["daily_plans"]["rows"]
                    or after["practice_items"]["rows"] <= before["practice_items"]["rows"]):
                meter.stop_reason = "explicit_confirmation_did_not_create_confirmed_plan_items"
            application.state.final_eval_confirm_used = True
            application.state.final_eval_approved_snapshot = after
            (OUT / "confirmed-plan-mutation.json").write_text(json.dumps({"case_id": cid, "before": before,
                "after": after, "protected_tables_unchanged": not meter.stop_reason,
                "daily_plan_created": after["daily_plans"]["rows"] > before["daily_plans"]["rows"],
                "practice_items_added": after["practice_items"]["rows"] - before["practice_items"]["rows"],
                "learning_task_draft_delta": after["learning_tasks"]["rows"] - before["learning_tasks"]["rows"]},
                ensure_ascii=False, indent=2), encoding="utf-8")
            meter.flush()
            return response
        if not is_chat:
            return await call_next(request)
        rejection_status = evaluation_stream_rejection_status(cid, request.url.path, cases_by_id, allowed)
        if rejection_status is not None:
            return JSONResponse({"error": "evaluation_scope_rejected"}, status_code=rejection_status)
        if cid in application.state.final_eval_seen or application.state.final_eval_active:
            return JSONResponse({"error": "duplicate_or_parallel_case_rejected"}, status_code=409)
        if hashes() != json.loads((OUT / "runtime-hashes.json").read_text(encoding="utf-8")):
            meter.stop_reason = "runtime_changed_stop"
        if meter.stop_reason:
            return JSONResponse({"error": meter.stop_reason}, status_code=409)
        application.state.final_eval_seen.add(cid)
        application.state.final_eval_active = True
        meter.case_id = cid
        try:
            response = await call_next(request)
        except BaseException:
            application.state.final_eval_active = False
            meter.case_id = None
            raise
        original = response.body_iterator
        async def tracked_body():
            try:
                async for piece in original:
                    yield piece
            finally:
                after = snapshot()
                before_snapshot = application.state.final_eval_approved_snapshot
                allowed_mutable = {"chat_sessions", "chat_messages", "message_citations"}
                if cid.startswith("Agent-"):
                    allowed_mutable.add("learning_tasks")
                if cid == "QA-01":
                    allowed_mutable.update({"materials", "document_chunks", "chunk_knowledge_points", "document_jobs"})
                protected = set(TABLES) - allowed_mutable
                changed = [table for table in protected
                           if after[table] != before_snapshot[table]]
                if changed:
                    meter.stop_reason = "unexpected_protected_business_mutation_stop"
                else:
                    application.state.final_eval_approved_snapshot = after
                deltas = {table: {"before": before_snapshot[table],
                                  "after": after[table]}
                          for table in TABLES if after[table] != before_snapshot[table]}
                write(f"database-delta-{cid}.json", {"case_id": cid, "changed_tables": deltas,
                    "learning_task_draft_mutation_permitted": cid.startswith("Agent-"),
                    "user_chat_persistence_permitted": True,
                    "user_material_upload_permitted": cid == "QA-01",
                    "daily_plan_and_practice_mutations_permitted": False})
                write(f"truth-after-{cid}.json", after)
                meter.case_id = None
                meter.flush()
                application.state.final_eval_active = False
        response.body_iterator = tracked_body()
        return response
    return application


if __name__ == "__main__" and sys.argv[1:] == ["--prepare"]:
    prepare()
elif __name__ == "__main__" and sys.argv[1:] == ["--freeze-runtime"]:
    freeze_runtime()
elif __name__ == "__main__" and sys.argv[1:] == ["--preflight"]:
    preflight()
elif __name__ == "__main__" and sys.argv[1:] == ["--check-cluster"]:
    check_cluster()
elif __name__ == "__main__":
    raise SystemExit("Use --prepare once, --check-cluster, --preflight, --freeze-runtime before paid calls, then uvicorn scripts.final_user_realux_server:app --factory")
