"""P4 is tested ONLY with isolated fixtures and explicitly simulated verification."""
from uuid import UUID
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from backend.models.learning import Question, QuestionAttempt, KpState, PracticeItem, DailyPlan
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock, mark_isolated_question_trusted
from tests.integration.test_answer_submissions import cleanup_answer_records
from tests.integration.test_golden_learning_slice import slice_questions, make_item


@pytest.fixture
def log_item(slice_questions, session_factory):
    _, ids = slice_questions
    with session_factory.begin() as db:
        q = db.get(Question, UUID(ids["M07"]))
        q.grading_config = {"method":"logarithm_final", "verified":True,
            "version":"p4-isolated-simulated-review"}
        mark_isolated_question_trusted(q, db=db)
    item, kp = make_item(session_factory, ids["M07"])
    return item, kp, ids["M07"]


def submit(client, item, answer, key="p4-answer", previous=None):
    return client.post(f"/api/practice-items/{item}/answer-submissions", json={
        "idempotency_key":key, "raw_answer":answer, "expected_previous_attempt_id":previous})


def final_dimension(client, kp):
    return next(d for d in client.get(f"/api/knowledge/{kp}").json()["capability_profile"]["dimensions"] if d["key"] == "final_result")


def make_current_version_item(factory, existing_item_id, question_id, *, study_date="2026-01-02"):
    """Create a new item bound to an edited Question's current immutable version."""
    with factory.begin() as db:
        existing = db.get(PracticeItem, UUID(existing_item_id))
        question = db.get(Question, UUID(question_id))
        plan = DailyPlan(study_date=study_date, status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=question.id,
            kp_id=question.kp_id, ordinal=1)
        db.add(item)
        db.flush()
        return str(item.id)


def test_log_answer_receipt_replay_and_capability_use_same_verified_result(client, session_factory, log_item):
    item, kp, _ = log_item
    result = submit(client, item, r"$\ln(\frac{4}{2})$")
    assert result.status_code == 200
    assert result.json()["result"] == "right" and result.json()["effective_confirmation_count"] == 1
    assert submit(client, item, r"$\ln(\frac{4}{2})$").json() == result.json()
    assert final_dimension(client, kp)["independent_question_count"] == 1
    with session_factory() as db:
        attempt = db.scalar(select(QuestionAttempt))
        assert attempt.grading_evidence["method"] == "exact_logarithm_v1"
        assert attempt.grading_evidence["grading_input_version"] == "bounded-final-input-v2"
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1
    plan = client.get("/api/plans/today").json()
    assert plan["items"][0]["answer_grading_method"] == "logarithm_final"


@pytest.mark.parametrize("answer", ["log(2)", "0.693147", "ln(0)", "ln(4)/2", ""])
def test_unsupported_or_blank_inputs_do_not_confirm_or_become_wrong(client, session_factory, log_item, answer):
    item, kp, _ = log_item
    result = submit(client, item, answer).json()
    assert result["result"] == "unknown" and result["effective_confirmation_count"] == 0
    assert final_dimension(client, kp)["independent_question_count"] == 0
    with session_factory() as db:
        assert not db.get(KpState, UUID(kp)).pending_review_question_ids


def test_unverified_public_log_answer_cannot_enter_new_practice_even_when_matching(client, session_factory, log_item, clock):
    item, kp, qid = log_item
    with session_factory.begin() as db: db.get(Question, UUID(qid)).grading_config = {"verified":False,"method":"logarithm_final"}
    clock.now += timedelta(days=1)
    current_item = make_current_version_item(session_factory, item, qid)
    result = submit(client, current_item, "ln(2)").json()
    # A public question without a current verified grader is archive-only;
    # matching the stored answer must not bypass formal admission.
    assert result["result"] == "unknown" and result["reason"] == "question_not_practice_eligible"
    assert final_dimension(client, kp)["independent_question_count"] == 0
    current_view = next(row for row in client.get("/api/plans/today").json()["items"] if row["id"] == current_item)
    assert current_view["answer_grading_method"] is None


def test_log_wrong_correction_and_fresh_retest_preserve_sequence(client, session_factory, log_item, clock):
    item, kp, qid = log_item
    first = submit(client, item, "ln(3)", "p4-wrong").json()
    assert first["result"] == "wrong"
    second = submit(client, item, "ln(2)", "p4-corrected", first["attempt_id"])
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "practice_item_already_assessed"
    assert final_dimension(client, kp)["status"] == "needs_retest"
    clock.now += timedelta(days=1)
    fresh, _ = make_item(session_factory, qid, "2026-01-02")
    result = submit(client, fresh, "ln 2", "p4-fresh").json()
    assert result["sequence_category"] == "independent_retest_correct" and not result["assisted"]
    assert final_dimension(client, kp)["independent_question_count"] == 1
    with session_factory() as db: assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 2


def test_solution_assistance_never_confirms_new_grader(client, log_item):
    item, kp, _ = log_item
    client.post(f"/api/practice-items/{item}/answer-reveal")
    result = submit(client, item, "ln(2)").json()
    assert result["result"] == "right" and result["assisted"]
    assert final_dimension(client, kp)["independent_question_count"] == 0


def test_misconfigured_proof_cannot_use_log_grader(client, session_factory, log_item):
    item, kp, qid = log_item
    with session_factory.begin() as db: db.get(Question, UUID(qid)).question_type = "proof"
    current_item = make_current_version_item(session_factory, item, qid)
    assert submit(client, current_item, "ln(2)").json()["result"] == "unknown"
    profile = client.get(f"/api/knowledge/{kp}").json()["capability_profile"]
    assert all(d["independent_question_count"] == 0 for d in profile["dimensions"])
