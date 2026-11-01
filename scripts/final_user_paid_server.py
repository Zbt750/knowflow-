"""One authorized, bounded real-model browser run on the owned test DB only."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import final_user_acceptance as fixture
from scripts.phase5_eval_meter import Meter

OUT = fixture.OUT / "paid-v2"
PLAN = ROOT / "eval/final-user-acceptance-v1/plan.json"


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def hashes():
    files = [* (ROOT / "backend").rglob("*.py"), * (ROOT / "frontend/src").rglob("*.ts"),
             * (ROOT / "frontend/src").rglob("*.vue"), ROOT / "scripts/phase5_eval_meter.py",
             Path(__file__), ROOT / "scripts/final_user_paid_browser.cjs", PLAN]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def snapshot():
    import psycopg
    fixture.verify()
    tables = ("questions", "question_versions", "question_auto_review_events", "kp_graduation_question_set_versions",
              "kp_mastery_policies", "question_attempts", "learning_events", "kp_states", "daily_plans", "practice_items")
    with psycopg.connect(fixture.URL.replace("postgresql+psycopg", "postgresql"),
            options="-c default_transaction_read_only=on", connect_timeout=5) as conn:
        result = {}
        for table in tables:
            rows = conn.execute(f'select row_to_json(t)::text from "{table}" t order by row_to_json(t)::text').fetchall()
            result[table] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(r[0] for r in rows).encode()).hexdigest()}
    return result


def prepare():
    fixture.verify()
    previous = json.loads((fixture.OUT / "paid-v1/provider-ledger.json").read_text(encoding="utf-8"))
    assert not previous["requests"], "Cannot reset a paid allowance; v1 was UI-only preflight"
    OUT.mkdir()  # Never overwrite or resume a prior paid ledger silently.
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert plan["physical_request_limit_authorized_by_user"] == 20
    write("authorization.json", {"user_approval": "批准：上一条¥2/20次/300k输入/80k输出/¥1.50软件阈值提案",
        "authorized_at": datetime.now(timezone.utc).isoformat(), "proposal_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        "limits": plan["proposal_not_authorization"], "supplier_hard_cap": False,
        "official_price_checked": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        "official_peak_cny_per_million": {"uncached_input": 2, "output": 8},
        "database": fixture.DATABASE, "port": 59271})
    write("truth-before.json", snapshot())
    write("runtime-hashes.json", hashes())
    print("Prepared one bounded paid browser run; actual Provider requests still zero")


def app():
    fixture.verify()
    assert (OUT / "authorization.json").exists()
    assert not (OUT / "provider-ledger.json").exists(), "Never restart/replay a paid run"
    assert hashes() == json.loads((OUT / "runtime-hashes.json").read_text(encoding="utf-8")), "Frozen runtime changed"
    # Read the actual local app configuration before switching only DB/storage to test.
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    effective = load_local_settings(get_settings())
    assert effective.llm_base_url.rstrip("/") == "https://api.deepseek.com"
    assert effective.llm_model == "deepseek-flash"
    assert effective.llm_api_key and not effective.local_model_settings_error
    fixture.configure()
    os.environ.update(LLM_API_KEY=effective.llm_api_key.get_secret_value(),
        LLM_MODEL=effective.llm_model, LLM_BASE_URL=effective.llm_base_url,
        LLM_STREAM_INCLUDE_USAGE="true", CAPTURE_TEST_EVIDENCE="true",
        LLM_MAX_OUTPUT_TOKENS=str(effective.llm_max_output_tokens),
        LLM_RETRY_MAX_OUTPUT_TOKENS=str(effective.llm_retry_max_output_tokens),
        LLM_TIMEOUT_SECONDS=str(effective.llm_timeout_seconds))
    get_settings.cache_clear()
    assert effective.llm_max_output_tokens <= 8000 and effective.llm_retry_max_output_tokens <= 8000
    from backend.app import create_app
    from starlette.responses import JSONResponse
    meter = Meter(OUT, max_requests=20, max_input_tokens=300000, max_output_tokens=80000, stop_cny="1.50")
    meter.install()
    meter.flush()
    application = create_app()  # Real Provider; no replacement or API mocking.
    application.state.final_eval_meter = meter
    application.state.final_eval_active = False
    application.state.final_eval_seen = set()
    allowed = {row["id"] for row in json.loads(PLAN.read_text(encoding="utf-8"))["turns_in_priority_order"]}

    @application.middleware("http")
    async def bounded_eval(request, call_next):
        is_stream = request.method == "POST" and request.url.path.endswith(("/answers:stream", "/assistant:stream"))
        if not is_stream:
            return await call_next(request)
        cid = request.headers.get("x-final-eval-case")
        if cid not in allowed or cid in application.state.final_eval_seen or application.state.final_eval_active:
            return JSONResponse({"error": "evaluation_scope_or_duplicate_rejected"}, status_code=409)
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
            raise
        original = response.body_iterator

        async def tracked_body():
            try:
                async for piece in original:
                    yield piece
            finally:
                after = snapshot()
                if after != json.loads((OUT / "truth-before.json").read_text(encoding="utf-8")):
                    meter.stop_reason = "unexpected_business_mutation_stop"
                write("truth-after.json", after)
                meter.flush()
                application.state.final_eval_active = False
        response.body_iterator = tracked_body()
        return response
    return application


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare"]:
        prepare()
    elif sys.argv[1:] == ["--snapshot-after"]:
        write("truth-after.json", snapshot())
    else:
        raise SystemExit("Use --prepare once or uvicorn factory; never execute unscoped requests")
