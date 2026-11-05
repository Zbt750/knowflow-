"""Exercise legacy-set compatibility only against an explicitly named isolated clone."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))
PORT = 59241
DATABASE = os.environ.get("PHASE45Y_API_DB", "phase45ycompat_api_test")
if DATABASE not in {
    "phase45ycompat_api_test",
    "phase45ycompat_api2_test",
    "phase45y_real_sync_api_test",
}:
    raise SystemExit("Refusing API validation: database is not in the isolated clone allow-list")
URL = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{DATABASE}"

parsed = make_url(os.environ.get("TEST_DATABASE_URL", ""))
if (parsed.get_backend_name() != "postgresql" or parsed.host != "127.0.0.1"
        or parsed.port != PORT or parsed.database != DATABASE
        or parsed.port == 5433 or not (parsed.database or "").endswith("_test")):
    raise SystemExit("Refusing API validation: TEST_DATABASE_URL must target the isolated API clone")
if os.environ.get("KAOYAN_OWNED_TEST_PORT") != str(PORT):
    raise SystemExit("Refusing API validation: isolated port ownership marker missing")

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = URL
os.environ["TEST_DATABASE_URL"] = URL

from fastapi.testclient import TestClient  # noqa: E402

from backend.api.deps import get_time_provider  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.models import import_models  # noqa: E402
from backend.models.learning import (  # noqa: E402
    DailyPlan,
    KpMasteryPolicy,
    KpState,
    KnowledgePoint,
    LearningEvent,
    PracticeItem,
    QuestionAttempt,
)
from backend.services.question_versions import question_for_attempt, question_for_practice_item  # noqa: E402

import_models()
engine = create_engine(URL, pool_pre_ping=True)
with engine.connect() as conn:
    identity = dict(conn.execute(text("""
        SELECT current_database() AS database, inet_server_addr()::text AS host,
               current_setting('port') AS port, current_setting('server_version') AS server_version,
               (SELECT version_num FROM alembic_version) AS revision,
               (SELECT system_identifier::text FROM pg_control_system()) AS system_identifier
    """)).mappings().one())
if (identity["database"] != DATABASE or int(identity["port"]) != PORT
        or identity["revision"] != "f54c8a1d7e20"):
    raise SystemExit(f"Isolated API clone identity mismatch: {identity}")

with Session(engine) as db:
    candidates = list(db.execute(
        select(KpState, KnowledgePoint, KpMasteryPolicy)
        .join(KnowledgePoint, KnowledgePoint.id == KpState.kp_id)
        .join(KpMasteryPolicy, KpMasteryPolicy.kp_id == KpState.kp_id)
        .where(KpState.graduation_set_binding_status == "legacy_history_unbound",
               KpMasteryPolicy.policy_version == 3,
               KpMasteryPolicy.graduation_set_version > 0,
               KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))
        .order_by(KnowledgePoint.code)
    ))
    if len(candidates) != 12:
        raise SystemExit(f"Expected exactly 12 active-v3 legacy transition nodes; found {len(candidates)}")
    chosen_state, chosen_node, _ = candidates[0]
    legacy_codes = [node.code for _, node, _ in candidates]
    legacy_ids = [str(node.id) for _, node, _ in candidates]
    legacy_state_before = {
        str(state.kp_id): {
            "binding_status": state.graduation_set_binding_status,
            "set_version": state.graduation_set_version,
            "state": state.state,
            "mastered_at": state.mastered_at.isoformat() if state.mastered_at else None,
            "evidence_window": list(state.evidence_window or []),
        }
        for state, _, _ in candidates
    }
    old_items = list(db.scalars(select(PracticeItem)
        .where(PracticeItem.kp_id.in_([node.id for _, node, _ in candidates]),
               PracticeItem.question_id.is_not(None))
        .order_by(PracticeItem.created_at, PracticeItem.id)))
    if not old_items or any(item.question_version_id is None for item in old_items):
        raise SystemExit("Legacy practice items missing immutable question version bindings")
    old_item = old_items[0]
    old_attempts = list(db.scalars(select(QuestionAttempt)
        .where(QuestionAttempt.kp_id.in_([node.id for _, node, _ in candidates]),
               QuestionAttempt.question_id.is_not(None))))
    if any(attempt.question_version_id is None for attempt in old_attempts):
        raise SystemExit("Legacy attempts missing immutable question version bindings")
    old_item_version_id = str(old_item.question_version_id)
    old_item_question = question_for_practice_item(db, old_item)
    old_item_stem = old_item_question.stem
    old_item_answer = old_item_question.correct_answer
    old_item_explanation = old_item_question.explanation
    old_attempt_versions = {str(a.id): str(a.question_version_id) for a in old_attempts}

# Pick a test date not present in the restored learner history. The app will
# perform normal API writes only against this fresh clone of the merged clone.
with Session(engine) as db:
    used_dates = set(db.scalars(select(DailyPlan.study_date)).all())
fixed_now = next(
    datetime(2040, 5, 20, 12, tzinfo=timezone.utc) + timedelta(days=offset)
    for offset in range(4000)
    if (datetime(2040, 5, 20, 12, tzinfo=timezone.utc) + timedelta(days=offset)).date().isoformat()
    not in used_dates
)
clock = {"now": fixed_now}
app = create_app()
app.dependency_overrides[get_time_provider] = lambda: (lambda: clock["now"])
report: dict = {
    "status": "RUNNING",
    "database_identity": identity,
    "legacy_v3_node_count": len(legacy_ids),
    "legacy_v3_node_codes": legacy_codes,
    "historical_practice_items_with_version": len(old_items),
    "historical_attempts_with_version": len(old_attempts),
    "api_checks": {},
}

try:
    with TestClient(app) as client:
        today_before = client.get("/api/plans/today")
        if today_before.status_code != 200:
            raise RuntimeError(f"today_setup_failed:{today_before.status_code}:{today_before.text[:500]}")
        today_body = today_before.json()
        if today_body.get("status") not in {"setup", "active", "completed"}:
            raise RuntimeError("today_setup_unexpected_shape")
        report["api_checks"]["today_get_before_transition"] = {
            "status_code": today_before.status_code,
            "body_status": today_body.get("status"),
            "returned_legacy_confirmation_recommendations": sum(
                bool(item.get("requires_graduation_set_confirmation"))
                for item in today_body.get("recommendations", [])
            ),
        }

        old_plan_read = client.get(f"/api/plans/{old_item.plan_id}/items")
        if old_plan_read.status_code != 200:
            raise RuntimeError(f"historical_plan_read_failed:{old_plan_read.status_code}:{old_plan_read.text[:500]}")
        old_plan_body = old_plan_read.json()
        old_view = next((item for item in old_plan_body["items"] if item["id"] == str(old_item.id)), None)
        if old_view is None or old_view.get("question_version_id") != old_item_version_id:
            raise RuntimeError("historical_plan_item_version_not_preserved")
        if old_view.get("stem") != old_item_stem:
            raise RuntimeError("historical_plan_item_old_stem_changed")
        old_answer_response = client.get(f"/api/practice-items/{old_item.id}/answer")
        if old_answer_response.status_code != 200:
            raise RuntimeError(f"historical_answer_read_failed:{old_answer_response.status_code}")
        old_answer = old_answer_response.json()
        if (old_answer.get("question_version_id") != old_item_version_id
                or old_answer.get("stem") != old_item_stem
                or old_answer.get("correct_answer") != old_item_answer
                or old_answer.get("explanation") != old_item_explanation
                or not old_answer.get("explanation")):
            raise RuntimeError("historical_answer_not_bound_to_old_version")
        report["api_checks"]["historical_plan_and_answer_use_old_version"] = {
            "plan_status_code": old_plan_read.status_code,
            "answer_status_code": old_answer_response.status_code,
            "practice_item_id": str(old_item.id),
            "question_version_id": old_item_version_id,
            "stem_answer_explanation_match_old_version": True,
            "old_attempt_versions_preserved": old_attempt_versions,
        }

        node_detail = client.get(f"/api/knowledge/{chosen_node.id}")
        if node_detail.status_code != 200:
            raise RuntimeError(f"legacy_node_detail_failed:{node_detail.status_code}:{node_detail.text[:500]}")
        node_view = node_detail.json()["node"]
        if node_view.get("graduation_set_binding_status") != "legacy_history_unbound":
            raise RuntimeError("legacy_node_status_not_exposed")
        report["api_checks"]["legacy_node_detail"] = {
            "status_code": node_detail.status_code,
            "node_code": chosen_node.code,
            "binding_status": node_view.get("graduation_set_binding_status"),
            "state": node_view.get("state"),
        }

        unconfirmed = client.post("/api/plans/today/generate", json={
            "selected_kp_ids": [str(chosen_node.id)], "budget": "light",
        })
        if unconfirmed.status_code not in {400, 409}:
            raise RuntimeError(f"missing_transition_confirmation_not_rejected:{unconfirmed.status_code}")
        if unconfirmed.json().get("error", {}).get("code") != "graduation_set_transition_confirmation_required":
            raise RuntimeError(f"unexpected_unconfirmed_transition_error:{unconfirmed.text[:500]}")
        with Session(engine) as db:
            state = db.get(KpState, chosen_node.id)
            if state.graduation_set_binding_status != "legacy_history_unbound" or state.graduation_set_version is not None:
                raise RuntimeError("unconfirmed_request_mutated_legacy_binding")
        report["api_checks"]["unconfirmed_transition_rejected_without_mutation"] = {
            "status_code": unconfirmed.status_code,
            "error_code": unconfirmed.json()["error"]["code"],
        }

        generated = client.post("/api/plans/today/generate", json={
            "selected_kp_ids": [str(chosen_node.id)],
            "confirm_legacy_set_transition_ids": [str(chosen_node.id)],
            "budget": "light",
        })
        if generated.status_code != 201:
            raise RuntimeError(f"confirmed_plan_generation_failed:{generated.status_code}:{generated.text[:700]}")
        generated_body = generated.json()
        if generated_body["study_date"] != fixed_now.astimezone(timezone.utc).date().isoformat():
            raise RuntimeError("fixed_api_date_mismatch")
        if not generated_body.get("items"):
            raise RuntimeError("confirmed_plan_has_no_items")
        with Session(engine) as db:
            bound = db.get(KpState, chosen_node.id)
            policy = db.get(KpMasteryPolicy, chosen_node.id)
            if (bound.graduation_set_binding_status != "bound"
                    or bound.graduation_set_version != policy.graduation_set_version
                    or bound.graduation_set_started_at is None):
                raise RuntimeError("explicit_transition_did_not_pin_current_set")
            if bound.mastered_at is not None or bound.state == "mastered":
                raise RuntimeError("legacy_transition_falsely_graduated_node")
            created_items = list(db.scalars(select(PracticeItem)
                .where(PracticeItem.plan_id == generated_body["plan_id"]).order_by(PracticeItem.ordinal)))
            created_item_ids = [str(item.id) for item in created_items]
            for item in created_items:
                if item.question_version_id is None:
                    raise RuntimeError(f"new_practice_item_missing_current_version:{item.id}")
            chosen_set_version = bound.graduation_set_version
        if any("correct_answer" in item or "explanation" in item for item in generated_body["items"]):
            raise RuntimeError("today_response_leaked_answer_or_explanation")
        report["api_checks"]["confirmed_transition_and_plan_generation"] = {
            "status_code": generated.status_code,
            "node_code": chosen_node.code,
            "pinned_set_version": chosen_set_version,
            "generated_item_count": len(created_items),
            "all_new_items_have_question_version": True,
            "new_items_do_not_leak_answers": True,
        }

        first_item = generated_body["items"][0]
        answer_response = client.get(f"/api/practice-items/{first_item['id']}/answer")
        if answer_response.status_code != 200:
            raise RuntimeError(f"new_item_answer_endpoint_failed:{answer_response.status_code}:{answer_response.text[:500]}")
        answer = answer_response.json()
        if answer.get("question_version_id") != first_item.get("question_version_id"):
            raise RuntimeError("new_item_answer_endpoint_version_mismatch")
        if not answer.get("explanation"):
            raise RuntimeError("new_item_explanation_not_available")
        payload = {
            "idempotency_key": "PH45Y-LEGACY-API-E2E-001",
            "confidence": "certain",
        }
        if answer.get("question_type") == "single_choice":
            payload["selected_option"] = str(answer["correct_answer"])
        else:
            correct = answer.get("correct_answer")
            payload["raw_answer"] = correct if isinstance(correct, str) else json.dumps(correct, ensure_ascii=False)
        submitted = client.post(f"/api/practice-items/{first_item['id']}/answer-submissions", json=payload)
        if submitted.status_code != 200:
            raise RuntimeError(f"answer_submission_failed:{submitted.status_code}:{submitted.text[:700]}")
        submission = submitted.json()
        if submission.get("question_version_id") != first_item.get("question_version_id"):
            raise RuntimeError("attempt_not_bound_to_submitted_question_version")
        submission_history = client.get(f"/api/practice-items/{first_item['id']}/answer-submissions")
        if submission_history.status_code != 200 or not submission_history.json().get("items"):
            raise RuntimeError("answer_history_not_readable")
        active_today = client.get("/api/plans/today")
        if active_today.status_code != 200 or active_today.json().get("plan_id") != generated_body["plan_id"]:
            raise RuntimeError(f"today_plan_not_restored:{active_today.status_code}:{active_today.text[:500]}")
        with Session(engine) as db:
            attempt_count = db.scalar(select(func.count()).select_from(QuestionAttempt)
                .where(QuestionAttempt.practice_item_id == UUID(first_item["id"]))) or 0
            event_count = db.scalar(select(func.count()).select_from(LearningEvent)
                .where(LearningEvent.kp_id == chosen_node.id)) or 0
            chosen_state_after = db.get(KpState, chosen_node.id)
            if attempt_count != 1 or chosen_state_after.mastered_at is not None:
                raise RuntimeError("attempt_or_non_graduation_invariant_failed")
            others = [db.get(KpState, UUID(kp_id)) for kp_id in legacy_ids if kp_id != str(chosen_node.id)]
            if any(state.graduation_set_binding_status != "legacy_history_unbound"
                   or state.graduation_set_version is not None for state in others):
                raise RuntimeError("unselected_legacy_node_was_mutated")
            old_ids_current = {str(item.id): str(item.question_version_id) for item in db.scalars(
                select(PracticeItem).where(PracticeItem.id.in_([item.id for item in old_items]))) }
            if old_ids_current != {str(item.id): str(item.question_version_id) for item in old_items}:
                raise RuntimeError("legacy_practice_item_bindings_changed")
            new_attempt = db.scalar(select(QuestionAttempt).where(
                QuestionAttempt.practice_item_id == UUID(first_item["id"])))
            resolved_attempt_question = question_for_attempt(db, new_attempt)
            if str(resolved_attempt_question.version_id) != str(first_item["question_version_id"]):
                raise RuntimeError("attempt_question_version_resolution_failed")
        report["api_checks"]["answer_grading_learning_history_and_restoration"] = {
            "answer_status_code": answer_response.status_code,
            "explanation_available": True,
            "submission_status_code": submitted.status_code,
            "submission_result": submission.get("result"),
            "attempt_version_id": submission.get("question_version_id"),
            "answer_history_count": len(submission_history.json()["items"]),
            "learning_events_after_submission_for_node": event_count,
            "today_plan_restored": True,
            "node_not_graduated_after_single_item": True,
            "other_legacy_nodes_unmodified": True,
        }

        # Next-day setup is read-only and exercises the same Agent recommendation
        # projection after a real API submission, without creating another plan.
        clock["now"] = fixed_now + timedelta(days=1)
        tomorrow = client.get("/api/plans/today")
        if tomorrow.status_code != 200 or tomorrow.json().get("status") != "setup":
            raise RuntimeError(f"next_day_agent_setup_failed:{tomorrow.status_code}:{tomorrow.text[:500]}")
        report["api_checks"]["next_day_agent_recommendations"] = {
            "status_code": tomorrow.status_code,
            "status": tomorrow.json().get("status"),
            "recommendation_count": len(tomorrow.json().get("recommendations", [])),
            "selected_node_recommended": any(
                item.get("kp_id") == str(chosen_node.id)
                for item in tomorrow.json().get("recommendations", [])
            ),
        }

    # Ensure every pre-existing attempt still resolves through its original
    # immutable version even after the selected node started its current set.
    with Session(engine) as db:
        attempts_after = {str(a.id): str(a.question_version_id) for a in db.scalars(select(QuestionAttempt)
            .where(QuestionAttempt.id.in_([UUID(key) for key in old_attempt_versions]))) }
        if attempts_after != old_attempt_versions:
            raise RuntimeError("preexisting_attempt_version_bindings_changed")
    report["status"] = "LEGACY_NODE_COMPAT_API_PASS"
finally:
    app.dependency_overrides.clear()
    engine.dispose()

audit_dir = ROOT / "storage/quality-audits/phase45y-final1-20261014/legacy-node-fix-v1"
audit_dir.mkdir(parents=True, exist_ok=True)
report_path = audit_dir / "legacy-node-api-validation.json"
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": report["status"], "report": str(report_path.relative_to(ROOT)),
                  "api_checks": report["api_checks"]}, ensure_ascii=False, indent=2))
