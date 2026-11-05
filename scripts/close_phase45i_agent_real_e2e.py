"""No-model closeout for Phase 4.5I-Agent-Real saved items.

Reuses the same isolated PostgreSQL cluster and stored DeepSeek outputs. This
script blocks all model HTTP clients and performs only the actual personal-bank,
today-plan, answer-submission, and synthetic graduation-fixture checks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_phase45i_agent_real as runner


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def c7_parse_status(calls: list[dict]) -> dict:
    from backend.services.question_generation import C7Output
    parsed = 0
    format_errors = 0
    truncated = 0
    for row in calls:
        if row.get("finish_reason") == "length":
            truncated += 1
            continue
        try:
            C7Output.model_validate(json.loads(row.get("response_content") or ""))
            parsed += 1
        except Exception:
            format_errors += 1
    return {"structured_json_valid_count": parsed, "format_error_count": format_errors,
            "output_truncated_count": truncated}


def exercise_saved_question_or_reuse(client, factory, question) -> dict:
    """Run the study route once; reuse and verify its prior persisted result on reruns."""
    from sqlalchemy import select
    from backend.models.learning import PracticeItem, QuestionAttempt, KpState
    from scripts.run_phase45i_real_batch import exercise_saved_question_routes

    with factory() as db:
        item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == question.id)
            .order_by(PracticeItem.id.desc()))
        prior = db.scalar(select(QuestionAttempt).where(
            QuestionAttempt.question_id == question.id,
            QuestionAttempt.practice_item_id == item.id).order_by(QuestionAttempt.submitted_at.desc())) if item else None
        state = db.get(KpState, question.kp_id)
        state_before = state.state if state else None
        mastered_at_before = state.mastered_at.isoformat() if state and state.mastered_at else None
        evidence_window_before = list(state.evidence_window or []) if state else []
    if prior is None:
        return exercise_saved_question_routes(client, factory, question)

    today = client.get("/api/plans/today")
    if today.status_code != 200:
        return {"status": "BLOCKED", "stage": "today_plan_read_existing_attempt",
                "http_status": today.status_code}
    visible = next((row for row in today.json().get("items", [])
                    if row.get("id") == str(item.id)), None)
    answer = client.get(f"/api/practice-items/{item.id}/answer")
    history = client.get(f"/api/practice-items/{item.id}/answer-submissions")
    rows = history.json().get("items", []) if history.status_code == 200 else []
    attempt_row = next((row for row in rows if row.get("attempt_id") == str(prior.id)), None)
    evidence = dict(prior.grading_evidence or {})
    with factory() as db:
        state_after = db.get(KpState, question.kp_id)
        current_window = list(state_after.evidence_window or []) if state_after else []
    passed = bool(visible and visible.get("completed") and answer.status_code == 200
        and answer.json().get("correct_answer") == question.correct_answer
        and answer.json().get("explanation") == question.explanation
        and attempt_row and prior.objective_result == "right"
        and evidence.get("bank_scope") == "personal"
        and evidence.get("evidence_capability") == "personal_practice_only"
        and evidence.get("effective_confirmation_count") == 0
        and current_window == evidence_window_before)
    return {"status": "PASS" if passed else "FAIL", "reused_prior_isolated_test_attempt": True,
        "today_item_visible_and_completed": bool(visible and visible.get("completed")),
        "answer_and_explanation_readable": answer.status_code == 200,
        "submission_history_readable": history.status_code == 200 and bool(attempt_row),
        "submission_result": prior.objective_result,
        "effective_confirmation_count": evidence.get("effective_confirmation_count"),
        "strict_graduation_blocked": evidence.get("evidence_capability") == "personal_practice_only",
        "kp_state_before_recheck": state_before,
        "kp_state_after_recheck": state_after.state if state_after else None,
        "mastered_at_before_recheck": mastered_at_before,
        "mastered_at_after_recheck": state_after.mastered_at.isoformat()
            if state_after and state_after.mastered_at else None,
        "strict_evidence_window_unchanged": current_window == evidence_window_before,
        "attempt_id": str(prior.id)}


def run() -> int:
    audit_dir = runner.OUT_DIR
    progress_path = audit_dir / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    calls = read_jsonl(audit_dir / "provider-calls.jsonl")
    turns = read_jsonl(audit_dir / "turns.jsonl")
    actual = sum(row.get("actual_http_request") is True for row in calls)
    if actual != 20 or len(calls) != 20 or len(turns) != 20:
        raise RuntimeError("refuse_closeout_without_exactly_20_saved_provider_calls_and_turns")
    if sum(row.get("subject") == "数学二" for row in calls) != 10 or sum(
            row.get("subject") == "408" for row in calls) != 10:
        raise RuntimeError("subject_allocation_not_10_each")
    if any(row.get("model") != "deepseek-flash" or not row.get("usage_observed")
           or row.get("http_status") != 200 for row in calls):
        raise RuntimeError("provider_response_usage_or_model_guard_failed")
    if any(row.get("actual_http_request") is not True for row in calls):
        raise RuntimeError("non_provider_row_in_provider_call_log")

    owner, cluster, port = runner.load_existing_owner()
    started_here = runner.start_owned_database(cluster, port)
    engine = None
    client = None
    original_post = None
    original_async = None
    closeout_status = "PHASE45I_AGENT_REAL_PARTIAL"
    try:
        initial = runner.verify_database(cluster, port, expected_revision="f49d10c2a703")
        if initial["daily_reserved_calls"] != 23:
            raise RuntimeError("same_day_existing_database_quota_did_not_equal_23_after_20_calls")
        if initial["counts"]["personal_generation_batches"] != 23:
            raise RuntimeError("generation_batch_ledger_count_does_not_match_existing3_plus_current20")
        if initial["counts"]["kp_mastery_policies"] != 0:
            raise RuntimeError("unexpected_preexisting_policy_rows_in_isolated_cluster")

        database_url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/kaoyan_test"
        os.environ.update({"APP_ENV": "test", "DATABASE_URL": database_url,
            "TEST_DATABASE_URL": database_url, "KAOYAN_OWNED_TEST_PORT": str(port),
            "LLM_API_KEY": "", "LLM_BASE_URL": "", "LLM_MODEL": "",
            "PYTHONIOENCODING": "utf-8"})
        for key in list(os.environ):
            if key.upper().startswith("PG"):
                os.environ.pop(key, None)
        from backend.config import get_settings
        from backend.db import create_db_engine
        get_settings.cache_clear()
        settings = get_settings()
        from sqlalchemy.engine import make_url
        url = make_url(str(settings.active_database_url))
        if settings.app_env != "test" or url.host != "127.0.0.1" or url.port != port \
                or url.database != "kaoyan_test" or port == 5433:
            raise RuntimeError("closeout_test_database_url_guard_failed")
        engine = create_db_engine(database_url)
        from sqlalchemy.orm import sessionmaker
        factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False)
        from sqlalchemy import select, func
        from backend.models.learning import (Question, PracticeItem, QuestionAttempt,
            LearningEvent, KpState, KpMasteryPolicy, KnowledgePoint)
        from backend.models.personal_generation import PersonalGenerationBatch
        from backend.services.question_generation import current_generation_binding
        from backend.services.question_eligibility import question_eligibility

        saved_ids = [UUID(qid) for qid in progress.get("saved_question_ids", [])]
        subject_by_node = {row["node"]["id"]: row["subject"] for row in progress["target_matrix"]}
        saved_by_subject = {"数学二": [], "408": []}
        saved_audit = []
        with factory() as db:
            questions = list(db.scalars(select(Question).where(Question.id.in_(saved_ids)))) if saved_ids else []
            if len(questions) != 9:
                raise RuntimeError("expected_nine_real_personal_questions_saved")
            for q in questions:
                node = db.get(KnowledgePoint, q.kp_id)
                batch = db.get(PersonalGenerationBatch, q.generation_batch_id) if q.generation_batch_id else None
                item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == q.id))
                subject = subject_by_node.get(str(q.kp_id))
                if subject not in saved_by_subject:
                    raise RuntimeError("saved_question_not_bound_to_frozen_target_node")
                if q.bank_scope != "personal" or not batch or batch.result is None or not item \
                        or not current_generation_binding(q, node):
                    raise RuntimeError("saved_personal_question_binding_or_today_item_invalid")
                saved_by_subject[subject].append(q)
                saved_audit.append({"question_id": str(q.id), "subject": subject,
                    "node_id": str(q.kp_id), "node_code": node.code if node else None,
                    "question_type": q.question_type, "difficulty": q.difficulty,
                    "bank_scope": q.bank_scope, "generation_batch_id": str(q.generation_batch_id),
                    "generation_mode": (q.grading_config or {}).get("generation", {}).get("generation_mode"),
                    "prompt_version": (q.grading_config or {}).get("generation", {}).get("prompt_version"),
                    "review_status": (q.grading_config or {}).get("generation", {}).get("review_status"),
                    "independent_verification": (q.grading_config or {}).get("generation", {}).get("independent_verification"),
                    "today_item_id": str(item.id),
                    "today_item_visible": True,
                    "eligibility": question_eligibility(q, node).public_dict() if node else None})
            public_count = int(db.scalar(select(func.count()).select_from(Question).where(Question.bank_scope == "public")) or 0)
            if public_count:
                raise RuntimeError("public_question_bank_pollution_detected")
        progress.update(c7_parse_status(calls))
        progress["confirmed_wrong_count"] = sum(
            1 for row in turns for failure in row.get("failures", [])
            if failure.get("review_status") == "CONFIRMED_WRONG")
        progress["unsupported_or_insufficient_count"] = sum(
            1 for row in turns for failure in row.get("failures", [])
            if failure.get("review_status") in {"UNSUPPORTED", "INSUFFICIENT_EVIDENCE"})
        progress["saved_question_audit"] = saved_audit
        progress["saved_personal_bank_total"] = len(questions)
        progress["personal_bank_scope_check"] = {"public_questions": public_count,
            "saved_personal_questions": len(saved_audit),
            "all_saved_personal": all(row["bank_scope"] == "personal" for row in saved_audit),
            "generation_binding_current": True}

        class ForbiddenProvider:
            def complete(self, *_args, **_kwargs):
                raise RuntimeError("no_model_call_allowed_during_closeout")
        import httpx
        original_post, original_async = httpx.post, httpx.AsyncClient
        def forbidden_post(*_args, **_kwargs):
            raise RuntimeError("unexpected_external_model_request_blocked_during_closeout")
        class ForbiddenAsyncClient:
            def __init__(self, *_args, **_kwargs):
                raise RuntimeError("unexpected_async_model_request_blocked_during_closeout")
        httpx.post = forbidden_post
        httpx.AsyncClient = ForbiddenAsyncClient
        from fastapi.testclient import TestClient
        from backend.app import create_app
        from backend.models.chat import ChatSession
        app = create_app()
        app.state.settings = settings
        app.state.instance_lock_lost = False
        app.state.session_factory = factory
        app.state.personal_generation_provider = ForbiddenProvider()
        app.state.retrieval_stack = None
        session_id = UUID(progress["chat_session_id"])
        with factory() as db:
            if not db.get(ChatSession, session_id):
                raise RuntimeError("real_generation_chat_session_missing")

        from scripts.run_phase45i_real_batch import exercise_saved_question_routes
        e2e = []
        with TestClient(app, base_url="http://127.0.0.1:5173", raise_server_exceptions=False) as client:
            math_q = saved_by_subject["数学二"][0] if saved_by_subject["数学二"] else None
            if math_q is None:
                e2e.append({"subject": "数学二", "status": "NOT_RUN_NO_REAL_AUTOPASS_QUESTION"})
            else:
                result = exercise_saved_question_or_reuse(client, factory, math_q)
                with factory() as db:
                    state = db.get(KpState, math_q.kp_id)
                row = {"subject": "数学二", "question_id": str(math_q.id),
                    "status": result.get("status"), "submission_result": result.get("submission_result"),
                    "effective_confirmation_count": result.get("effective_confirmation_count"),
                    "strict_graduation_blocked": result.get("strict_graduation_blocked"),
                    "kp_state": state.state if state else None,
                    "mastered_at": state.mastered_at.isoformat() if state and state.mastered_at else None,
                    "evidence_window_count": len(state.evidence_window or []) if state else None,
                    "route_result": result}
                e2e.append(row)

            cs_q = saved_by_subject["408"][0] if saved_by_subject["408"] else None
            if cs_q is None:
                e2e.append({"subject": "408", "status": "NOT_RUN_NO_REAL_AUTOPASS_QUESTION"})
            else:
                try:
                    graduation_fixture = runner.create_isolated_graduation_fixture(
                        factory, cs_q.kp_id, datetime.now(timezone.utc))
                except RuntimeError as exc:
                    # The fixture transaction rolls back on this explicit failure.
                    # Still exercise the real personal item through the ordinary,
                    # ungraduated path and report post-graduation as unverified.
                    graduation_fixture = {"status": "BLOCKED", "fixture_only": True,
                        "blocker_code": "reference_only_mapping" if "reference_only_mapping" in str(exc)
                            else "graduation_fixture_failed",
                        "failure": str(exc)}
                result = exercise_saved_question_or_reuse(client, factory, cs_q)
                with factory() as db:
                    state = db.get(KpState, cs_q.kp_id)
                    node = db.get(KnowledgePoint, cs_q.kp_id)
                    from backend.services.post_graduation_service import read_post_practice
                    projection = read_post_practice(db, node, now=datetime.now(timezone.utc))
                e2e.append({"subject": "408", "question_id": str(cs_q.id),
                    "status": result.get("status"), "submission_result": result.get("submission_result"),
                    "effective_confirmation_count": result.get("effective_confirmation_count"),
                    "strict_graduation_blocked": result.get("strict_graduation_blocked"),
                    "kp_state": state.state if state else None,
                    "mastered_at": state.mastered_at.isoformat() if state and state.mastered_at else None,
                    "evidence_window_count": len(state.evidence_window or []) if state else None,
                    "graduation_fixture": graduation_fixture,
                    "post_graduation_projection": projection.model_dump(mode="json") if projection else None,
                    "route_result": result})
        progress["e2e_results"] = e2e
        math_row = next((row for row in e2e if row.get("subject") == "数学二"), {})
        cs_row = next((row for row in e2e if row.get("subject") == "408"), {})
        progress["ungraduated_attempt_check"] = {key: math_row.get(key) for key in
            ("status", "kp_state", "mastered_at", "effective_confirmation_count", "evidence_window_count")}
        progress["post_graduation_fixture"] = cs_row.get("graduation_fixture")
        progress["post_graduation_attempt_check"] = {key: cs_row.get(key) for key in
            ("status", "kp_state", "mastered_at", "effective_confirmation_count", "evidence_window_count",
             "post_graduation_projection")}
        final_identity = runner.verify_database(cluster, port, expected_revision="f49d10c2a703")
        counts_after = runner.current_counts(factory)
        progress["counts_after"] = counts_after
        progress["daily_reserved_calls_after"] = final_identity["daily_reserved_calls"]
        progress["daily_reserved_calls_limit"] = 30
        progress["database_identity_after"] = {key: final_identity[key] for key in
            ("database", "port", "data_directory", "system_identifier", "revision", "pidfile_pid")}
        progress["strict_policy_rows_after"] = counts_after["kp_mastery_policies"]
        progress["closeout_model_requests"] = 0
        progress["development_5433_used"] = False
        progress["stage"] = "real_calls_complete_no_model_e2e_closeout"
        complete = actual == 20 and progress["daily_reserved_calls_after"] == 23 \
            and progress.get("focused_tests", {}).get("status") == "PASS" \
            and all(row.get("status") == "PASS" for row in e2e) \
            and cs_row.get("graduation_fixture", {}).get("status") == "PASS"
        closeout_status = "PHASE45I_AGENT_REAL_COMPLETED" if complete else "PHASE45I_AGENT_REAL_PARTIAL"
        progress["finish_status"] = closeout_status
        progress["stop_reason"] = None if complete else "one_or_more_end_to_end_acceptance_checks_not_passed"
        runner.atomic_json(progress_path, progress)
        runner.write_report(progress, closeout_status)
        print(json.dumps({"status": closeout_status, "actual_requests": actual,
            "saved_questions": len(saved_audit), "daily_reserved_calls_after": final_identity["daily_reserved_calls"],
            "e2e": e2e, "report": str(audit_dir / "PHASE45I_AGENT_REAL_REPORT.md")}, ensure_ascii=False), flush=True)
        return 0 if complete else 1
    finally:
        if original_post is not None:
            import httpx
            httpx.post = original_post
            httpx.AsyncClient = original_async
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        if engine is not None:
            engine.dispose()
        if started_here:
            result = runner.command([str(runner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster),
                "-m", "fast", "-w", "-t", "30", "stop"], timeout=40, check=False)
            if result.returncode:
                print(json.dumps({"warning": "isolated_postgres_normal_stop_failed"}), flush=True)


if __name__ == "__main__":
    raise SystemExit(run())
