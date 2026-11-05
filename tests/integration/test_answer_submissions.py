from uuid import UUID

import pytest
from sqlalchemy import select, func, delete

from backend.models.learning import Question, DailyPlan, PracticeItem, QuestionAttempt, KpState, LearningEvent
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock


def verify_synthetic_answer_revision(db, question, key):
    """Bind intentionally edited fixture answers to a new test-only event."""
    from backend.services.answer_verification import answer_version_sha256, verify_answer
    verify_answer(db, question_id=question.id, verification_type="human_verified",
        verifier="isolated-synthetic-test-fixture", method="synthetic test fixture review",
        note="Synthetic fixture-only answer approval; not a real review.",
        idempotency_key=key, expected_answer_sha256=answer_version_sha256(question))


def test_legacy_ai_attempt_response_projects_grading_basis_without_rewriting_node_basis():
    from datetime import datetime, timezone
    from uuid import uuid4
    from backend.services.answer_submission_service import submission_response
    attempt=QuestionAttempt(id=uuid4(),practice_item_id=uuid4(),objective_result="right",
        submitted_at=datetime.now(timezone.utc),result_state="unseen",reason_code="answer_recorded_only",
        grading_evidence={"reason":"ai_answer_exact_option_comparison","method":"ai_answer_single_choice_v1",
            "assisted":False,"evidence_reliability":"ai_consistent_objective",
            "assessment_basis":"legacy_self_reported","effective_confirmation_count":0})
    projected=submission_response(attempt)
    assert projected.assessment_basis=="ai_consistent_reference_v1"
    assert projected.mastery_assessment_basis=="legacy_self_reported"
    assert projected.effective_confirmation_count==0
    assert attempt.grading_evidence["assessment_basis"]=="legacy_self_reported"


@pytest.fixture(autouse=True)
def cleanup_answer_records(session_factory, clean_database):
    # setup 已在隔离测试库清空并灌种子；本模块新增事件必须在 teardown 回收，
    # 不能把它们留给只清资料表、断言“本次问答不写学习事件”的后续测试。
    yield
    with session_factory() as db:
        for model in (QuestionAttempt, LearningEvent, PracticeItem, DailyPlan):
            db.execute(delete(model))
        for state in db.scalars(select(KpState)):
            state.assessment_basis = "legacy_self_reported"
            state.pending_review_question_ids = []
            state.evidence_window = []
            state.state = "unseen"
            state.mastered_at = None
            state.next_review_at = None
            state.review_stage = 0
            state.manual_credit_count = 0
            state.manual_confirmed_at = None
        db.commit()


@pytest.fixture
def item_id(session_factory):
    with session_factory() as db:
        question = db.scalar(select(Question).where(Question.stem == "求极限 lim(x->0) (e^x - 1) / x 的值。"))
        plan = DailyPlan(study_date="2026-01-01", status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=question.id, kp_id=question.kp_id, ordinal=1)
        db.add(item)
        db.commit()
        return str(item.id)


def submit(client, item, answer="1", key="submission-key-0001"):
    return client.post(f"/api/practice-items/{item}/answer-submissions", json={
        "idempotency_key": key, "raw_answer": answer,
    })


def _new_item_for_current_question_version(db, old_item_id):
    """Create a fresh test plan item after mutating its synthetic question.

    Existing items intentionally remain pinned to their original question
    snapshot; tests that exercise a revised answer must submit a newly-created
    item instead of silently retargeting historical plan content.
    """
    from sqlalchemy import func
    old_item = db.get(PracticeItem, UUID(old_item_id))
    plan = DailyPlan(study_date=f"2099-02-{UUID(old_item_id).int % 27 + 1:02d}", status="active")
    db.add(plan)
    db.flush()
    item = PracticeItem(plan_id=plan.id, question_id=old_item.question_id,
        kp_id=old_item.kp_id, ordinal=1)
    db.add(item)
    db.flush()
    return str(item.id)


def test_numeric_submission_adds_objective_confirmation(client, item_id, session_factory):
    response = submit(client, item_id, "2/2")
    assert response.status_code == 200
    assert response.json()["result"] == "right"
    assert response.json()["assisted"] is False
    with session_factory() as db:
        item = db.get(PracticeItem, UUID(item_id))
        assert item.completed_at is not None and item.plan.status == "completed"
        state = db.get(KpState, item.kp_id)
        assert state.state == "consolidating" and len(state.evidence_window) == 1
        assert state.assessment_basis == "objective_v1"
        attempt = db.scalar(select(QuestionAttempt))
        assert attempt.self_grade is None
        assert attempt.grading_evidence["reference_answer"] == "1"
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 1
    today = client.get("/api/plans/today").json()
    assert today["items"][0]["answer_submission"]["raw_answer"] == "2/2"
    node = client.get(f"/api/knowledge/{today['items'][0]['kp_id']}").json()
    assert node["attempts"][0]["self_grade"] is None


@pytest.mark.parametrize("answer,verified,result,count", [
    ("-1/4", True, "right", 1), (r"$-\frac14$", True, "right", 1),
    ("-0.249", True, "wrong", 0), ("-1/4", False, "unknown", 0),
])
def test_short_fraction_through_answer_api_preserves_review_gate(client, item_id, session_factory, answer, verified, result, count):
    """SYNTHETIC test-only content; never approve the actual 2025 exam answer."""
    with session_factory.begin() as db:
        q = db.get(PracticeItem, UUID(item_id)).question
        q.stem = "SYNTHETIC TEST ONLY：写出负四分之一。"
        q.explanation = "SYNTHETIC TEST ONLY：负四分之一精确等于-1/4。"
        q.correct_answer = r"$-\frac14$"
        q.grading_config = {"verified": verified, "method": "numeric_final"}
        if verified:
            verify_synthetic_answer_revision(db, q, "short-fraction-answer-revision")
        revised_item_id = _new_item_for_current_question_version(db, item_id)
    response = submit(client, revised_item_id, answer, "short-fraction-api-test")
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["result"] == result
    assert receipt["effective_confirmation_count"] == count
    assert submit(client, revised_item_id, answer, "short-fraction-api-test").json() == receipt
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1
        state = db.get(KpState, db.get(PracticeItem, UUID(revised_item_id)).kp_id)
        assert state.state != "mastered"
        assert len(state.evidence_window) == count


@pytest.mark.parametrize("answer,result,reason", [
    ("3", "wrong", "exact_numeric_comparison"),
    ("", "unknown", "not_answered"),
    ("sqrt(1)", "unknown", "unsupported_answer"),
])
def test_conservative_outcomes(client, item_id, answer, result, reason):
    response = submit(client, item_id, answer)
    assert response.status_code == 200
    assert response.json()["result"] == result and response.json()["reason"] == reason


def test_missing_grader_does_not_produce_objective_result(client, item_id, session_factory):
    with session_factory.begin() as db:
        db.get(PracticeItem, UUID(item_id)).question.grading_config = None
        revised_item_id = _new_item_for_current_question_version(db, item_id)
    response = submit(client, revised_item_id)
    assert response.json()["result"] == "unknown"
    assert response.json()["reason"] == "question_not_practice_eligible"


@pytest.mark.parametrize("answer", ["1", "3"])
def test_unreviewed_public_answer_key_cannot_bypass_formal_admission(client, item_id, session_factory, answer):
    with session_factory.begin() as db:
        question = db.get(PracticeItem, UUID(item_id)).question
        question.grading_config = {"verified": False, "method": None,
            "provenance": {"content_status": "source_transcribed", "source": {"source_type": "exam"}}}
        question.grading_mode = "self_assessed"
        revised_item_id = _new_item_for_current_question_version(db, item_id)
    # The final public-bank rule has no reference-only practice admission path.
    # A retained historical key cannot replace a current content-bound review.
    response = submit(client, revised_item_id, answer)
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["result"] == "unknown"
    assert receipt["reason"] == "question_not_practice_eligible"
    assert receipt["effective_confirmation_count"] == 0
    assert submit(client, revised_item_id, answer).json() == receipt
    with session_factory() as db:
        state = db.get(KpState, db.get(PracticeItem, UUID(revised_item_id)).kp_id)
        assert state.state != "mastered" and not state.pending_review_question_ids


def test_reveal_before_submission_is_assisted(client, item_id):
    assert client.post(f"/api/practice-items/{item_id}/answer-reveal", json={}).status_code == 200
    result = submit(client, item_id).json()
    assert result["assisted"] is True
    assert result["effective_confirmation_count"] == 0


def test_guess_is_not_independent_confirmation(client, item_id):
    result = client.post(f"/api/practice-items/{item_id}/answer-submissions", json={
        "idempotency_key": "guess-key-0001", "raw_answer": "1", "confidence": "guess",
    }).json()
    assert result["result"] == "right"
    assert result["effective_confirmation_count"] == 0
    assert result["mastery_reason"] == "low_confidence_answer_recorded"


def test_wrong_answer_schedules_review_and_retest_clears_it(client, item_id, session_factory):
    first = submit(client, item_id, "3").json()
    assert first["state"] == "stuck"
    with session_factory() as db:
        original = db.get(PracticeItem, UUID(item_id))
        kp_id = original.kp_id
        assert db.get(KpState, kp_id).pending_review_question_ids == [str(original.question_id)]
        plan = DailyPlan(study_date="2026-01-02", status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=original.question_id, kp_id=kp_id, ordinal=1)
        db.add(item)
        db.commit()
        repeat_id = str(item.id)
    result = submit(client, repeat_id, "1", "retest-key-0001").json()
    assert result["effective_confirmation_count"] == 1
    with session_factory() as db:
        assert not db.get(KpState, kp_id).pending_review_question_ids


def test_node_feedback_cannot_add_objective_confirmations(client, item_id, session_factory):
    assert submit(client, item_id).status_code == 200
    with session_factory() as db:
        kp_id = db.get(PracticeItem, UUID(item_id)).kp_id
    response = client.post(f"/api/knowledge/{kp_id}/self-assessment", json={
        "idempotency_key": "feedback-key-0001", "self_grade": "mastered",
    })
    assert response.status_code == 200
    assert response.json()["effective_confirmation_count"] == 1
    assert response.json()["reason_code"] == "self_feedback_only"


def test_later_reveal_does_not_rewrite_submission(client, item_id):
    first = submit(client, item_id).json()
    client.post(f"/api/practice-items/{item_id}/answer-reveal", json={})
    assert submit(client, item_id).json() == first


def test_retry_same_key_is_idempotent_and_changed_payload_conflicts(client, item_id, session_factory):
    first = submit(client, item_id)
    assert submit(client, item_id).json() == first.json()
    assert submit(client, item_id, "3").status_code == 409
    assert submit(client, item_id, key="another-key-0001").status_code == 409
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1


def test_old_answer_get_remains_read_only(client, item_id, session_factory):
    assert client.get(f"/api/practice-items/{item_id}/answer").status_code == 200
    with session_factory() as db:
        assert db.get(PracticeItem, UUID(item_id)).answer_revealed_at is None
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 0


def test_same_key_cannot_enter_old_self_assessment(client, item_id):
    assert submit(client, item_id).status_code == 200
    response = client.post(f"/api/practice-items/{item_id}/self-assessments", json={
        "idempotency_key": "submission-key-0001", "self_grade": "mastered",
    })
    assert response.status_code == 409


def test_key_cannot_be_reused_for_another_item(client, item_id, session_factory):
    assert submit(client, item_id).status_code == 200
    with session_factory() as db:
        first = db.get(PracticeItem, UUID(item_id))
        # 别的计划可以安排同一题，但不能复用本次提交键。
        plan = DailyPlan(study_date="2026-01-02", status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=first.question_id, kp_id=first.kp_id, ordinal=1)
        db.add(item)
        db.commit()
        second_id = str(item.id)
    assert submit(client, second_id).status_code == 409


def test_single_choice_and_proof_are_not_confused(client, item_id, session_factory):
    with session_factory.begin() as db:
        question = db.get(PracticeItem, UUID(item_id)).question
        question.question_type = "single_choice"
        question.grading_config = {"verified": True, "method": "single_choice"}
        question.options = {"A": "1", "B": "2"}
        question.correct_answer = "A"
        verify_synthetic_answer_revision(db, question, "choice-answer-revision")
        revised_item_id = _new_item_for_current_question_version(db, item_id)
    response = client.post(f"/api/practice-items/{revised_item_id}/answer-submissions", json={
        "idempotency_key": "choice-key-0001", "selected_option": "a",
    })
    assert response.json()["result"] == "right"


def test_proof_never_graded_by_numeric_result(client, item_id, session_factory):
    with session_factory.begin() as db:
        question = db.get(PracticeItem, UUID(item_id)).question
        question.question_type = "proof"
        verify_synthetic_answer_revision(db, question, "proof-type-revision")
        revised_item_id = _new_item_for_current_question_version(db, item_id)
    response = submit(client, revised_item_id)
    assert response.json()["result"] == "unknown"
    # A non-objectively-gradable public item is stopped at admission before
    # numeric grading, even when its synthetic answer revision is current.
    assert response.json()["reason"] == "question_not_practice_eligible"
    assert response.json()["effective_confirmation_count"] == 0


def test_concurrent_items_complete_plan(session_factory, item_id, clock):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from backend.services.answer_submission_service import submit_answer
    with session_factory() as db:
        item = db.get(PracticeItem, UUID(item_id))
        question = db.scalar(select(Question).where(Question.id != item.question_id).limit(1))
        second = PracticeItem(plan_id=item.plan_id, question_id=question.id, kp_id=question.kp_id, ordinal=2)
        db.add(second)
        db.commit()
        second_id = second.id
    barrier = Barrier(2)
    def run(target):
        with session_factory() as db:
            target_item=db.get(PracticeItem,target)
            target_question=db.get(Question,target_item.question_id)
            option=next(iter(target_question.options)) if target_question.question_type=='single_choice' else None
            barrier.wait(timeout=5)
            result = submit_answer(db, item_id=target, raw_answer=None if option else "1", selected_option=option,
                                   idempotency_key=f"parallel-{target}", now=clock())
            db.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, target) for target in (UUID(item_id), second_id)]
        for future in futures:
            future.result(timeout=10)
    with session_factory() as db:
        assert db.get(PracticeItem, UUID(item_id)).plan.status == "completed"
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 2
