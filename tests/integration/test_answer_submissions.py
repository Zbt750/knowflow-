from uuid import UUID

import pytest
from sqlalchemy import select, func, delete

from backend.models.learning import Question, DailyPlan, PracticeItem, QuestionAttempt, KpState, LearningEvent
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock


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


@pytest.mark.parametrize("answer,result,reason", [
    ("3", "wrong", "exact_numeric_comparison"),
    ("", "unknown", "not_answered"),
    ("sqrt(1)", "unknown", "unsupported_answer"),
])
def test_conservative_outcomes(client, item_id, answer, result, reason):
    response = submit(client, item_id, answer)
    assert response.status_code == 200
    assert response.json()["result"] == result and response.json()["reason"] == reason


def test_unverified_reference_not_graded(client, item_id, session_factory):
    with session_factory() as db:
        db.get(PracticeItem, UUID(item_id)).question.grading_config = None
        db.commit()
    response = submit(client, item_id)
    assert response.json()["result"] == "unknown"
    assert response.json()["reason"] == "answer_not_verified"


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
    with session_factory() as db:
        question = db.get(PracticeItem, UUID(item_id)).question
        question.question_type = "single_choice"
        question.grading_config = {"verified": True, "method": "single_choice"}
        question.options = {"A": "1", "B": "2"}
        question.correct_answer = "A"
        db.commit()
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json={
        "idempotency_key": "choice-key-0001", "selected_option": "a",
    })
    assert response.json()["result"] == "right"


def test_proof_never_graded_by_numeric_result(client, item_id, session_factory):
    with session_factory() as db:
        db.get(PracticeItem, UUID(item_id)).question.question_type = "proof"
        db.commit()
    response = submit(client, item_id)
    assert response.json()["result"] == "unknown"
    assert response.json()["reason"] == "unsupported_question"


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
            barrier.wait(timeout=5)
            result = submit_answer(db, item_id=target, raw_answer="1", selected_option=None,
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
