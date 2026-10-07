"""P2 immutable retries, stale requests and fresh-item retests against test PG."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from backend.models.learning import PracticeItem, DailyPlan, QuestionAttempt, LearningEvent, KpState
from backend.services.answer_submission_service import submit_answer
from backend.services.learning_task_tools import TaskTools
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from tests.integration.test_answer_submissions import cleanup_answer_records, item_id


def send(client, item, answer, key, previous=None):
    body = {"raw_answer": answer, "idempotency_key": key}
    if previous is not None: body["expected_previous_attempt_id"] = previous
    return client.post(f"/api/practice-items/{item}/answer-submissions", json=body)


def get_history(client, item):
    response = client.get(f"/api/practice-items/{item}/answer-submissions")
    assert response.status_code == 200
    return response.json()


def test_wrong_then_self_corrected_keeps_both_without_confirming(client, item_id, session_factory):
    first = send(client, item_id, "3", "sequence-first-wrong").json()
    assert first["attempt_number"] == 1 and first["sequence_category"] == "incorrect"
    corrected = send(client, item_id, "1", "sequence-self-correct", first["attempt_id"])
    assert corrected.status_code == 200
    second = corrected.json()
    assert second["result"] == "right" and second["sequence_category"] == "self_corrected"
    assert second["attempt_number"] == 2 and second["previous_attempt_id"] == first["attempt_id"]
    assert not second["assisted"] and second["effective_confirmation_count"] == 0
    assert second["mastery_reason"] == "corrected_answer_recorded"
    assert not second["can_retry"]
    history = get_history(client, item_id)
    assert history["items"] == [first, second]
    # Fake clock makes timestamps identical; latest must still be the second row.
    plan = client.get("/api/plans/today").json()
    assert plan["items"][0]["answer_submission"] == second
    assert plan["completed_count"] == 1 and plan["total_count"] == 1
    with session_factory() as db:
        state = db.get(KpState, db.get(PracticeItem, UUID(item_id)).kp_id)
        assert len(state.pending_review_question_ids) == 1 and not state.evidence_window
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 2
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 2


@pytest.mark.parametrize("exposure", ["solution", "process_review"])
def test_observed_assistance_is_sticky_during_retry(client, item_id, session_factory, clock, exposure):
    first = send(client, item_id, "2", "sequence-assisted-first").json()
    if exposure == "solution":
        assert client.post(f"/api/practice-items/{item_id}/answer-reveal").status_code == 200
    else:
        with session_factory.begin() as db:
            item = db.get(PracticeItem, UUID(item_id))
            db.add(LearningEvent(kp_id=item.kp_id, source_id=item.id, event_type="ai_process_reviewed",
                evidence_level="weak", payload={"feedback": "ISOLATED SIMULATED REVIEW"},
                occurred_at=clock.now, idempotency_key="sequence-review-fixture"))
    second = send(client, item_id, "1", "sequence-assisted-second", first["attempt_id"]).json()
    assert second["assisted"] and second["assistance_level"] == exposure
    assert second["sequence_category"] == ("solution_assisted_correct" if exposure == "solution" else "process_review_assisted_correct")
    assert second["effective_confirmation_count"] == 0
    assert get_history(client, item_id)["items"][0]["assistance_level"] == "none"


def test_retry_receipt_replays_and_conflicting_or_stale_requests_fail(client, item_id):
    first = send(client, item_id, "3", "sequence-idem-first").json()
    second = send(client, item_id, "4", "sequence-idem-second", first["attempt_id"])
    assert second.status_code == 200
    assert send(client, item_id, "4", "sequence-idem-second", first["attempt_id"]).json() == second.json()
    assert send(client, item_id, "4", "sequence-idem-second").status_code == 409
    assert send(client, item_id, "5", "sequence-idem-second", first["attempt_id"]).status_code == 409
    stale = send(client, item_id, "1", "sequence-idem-stale", first["attempt_id"])
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "answer_attempt_conflict"
    assert len(get_history(client, item_id)["items"]) == 2


def test_first_attempt_and_success_cannot_be_forged_into_retry(client, item_id):
    assert send(client, item_id, "1", "sequence-fake-previous", str(uuid4())).status_code == 409
    first = send(client, item_id, "1", "sequence-right-first").json()
    assert first["sequence_category"] == "first_independent_correct"
    assert first["effective_confirmation_count"] == 1
    denied = send(client, item_id, "1", "sequence-repeat-right", first["attempt_id"])
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "answer_retry_not_allowed"
    assert len(get_history(client, item_id)["items"]) == 1


def test_blank_then_correct_is_not_relabelled_as_first_try(client, item_id):
    blank = send(client, item_id, "", "sequence-blank-first").json()
    assert blank["sequence_category"] == "unable_to_grade"
    corrected = send(client, item_id, "1", "sequence-blank-second", blank["attempt_id"]).json()
    assert corrected["sequence_category"] == "correct_after_ungraded"
    assert corrected["effective_confirmation_count"] == 0


def test_changed_question_blocks_retry_but_keeps_old_receipt(client, item_id, session_factory):
    first = send(client, item_id, "3", "sequence-version-first").json()
    with session_factory.begin() as db:
        db.get(PracticeItem, UUID(item_id)).question.stem += "（内容修订）"
    denied = send(client, item_id, "1", "sequence-version-second", first["attempt_id"])
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "answer_question_changed"
    assert send(client, item_id, "3", "sequence-version-first").json() == first
    assert get_history(client, item_id)["items"] == [first]


def next_item(factory, item, study_date):
    with factory.begin() as db:
        old = db.get(PracticeItem, UUID(item))
        plan = DailyPlan(study_date=study_date, status="active")
        db.add(plan); db.flush()
        current = PracticeItem(plan_id=plan.id, question_id=old.question_id, kp_id=old.kp_id, ordinal=1)
        db.add(current); db.flush()
        return str(current.id), str(current.kp_id)


def test_fresh_retest_reads_history_and_deduplicates_confirmation(client, item_id, session_factory, clock):
    first = send(client, item_id, "2", "sequence-fresh-wrong").json()
    send(client, item_id, "1", "sequence-fresh-corrected", first["attempt_id"])
    clock.now += timedelta(days=1)
    item, kp = next_item(session_factory, item_id, "2026-01-02")
    success = send(client, item, "1", "sequence-fresh-retest").json()
    assert success["sequence_category"] == "repeat_correct" and success["effective_confirmation_count"] == 1
    clock.now += timedelta(days=1)
    third, _ = next_item(session_factory, item_id, "2026-01-03")
    repeated = send(client, third, "1", "sequence-fresh-repeat").json()
    assert repeated["sequence_category"] == "repeat_correct" and repeated["effective_confirmation_count"] == 1
    tools = TaskTools(session_factory, budget_minutes=10, now=clock.now, goal="洛必达")
    nodes = tools.execute("search_knowledge", {"query": "洛必达"})["nodes"]
    state = tools.execute("get_learning_state", {"kp_ids": [n["kp_id"] for n in nodes]})["states"][0]
    assert {a["sequence_category"] for a in state["recent_attempts"]} >= {"self_corrected", "incorrect", "repeat_correct"}
    assert all("raw_answer" not in a for a in state["recent_attempts"])
    with session_factory() as db:
        assert db.get(KpState, UUID(kp)).state != "mastered"


def test_wrong_then_fresh_independent_retest_can_confirm(client, item_id, session_factory, clock):
    first = send(client, item_id, "2", "sequence-direct-retest-wrong").json()
    clock.now += timedelta(days=1)
    item, kp = next_item(session_factory, item_id, "2026-01-02")
    result = send(client, item, "1", "sequence-direct-retest-correct").json()
    assert result["sequence_category"] == "independent_retest_correct"
    assert result["effective_confirmation_count"] == 1
    assert result["attempt_number"] == 1 and result["previous_attempt_id"] is None
    assert get_history(client, item_id)["items"] == [first]
    with session_factory() as db:
        assert not db.get(KpState, UUID(kp)).pending_review_question_ids


def test_legacy_history_is_not_invented_as_first_independent_success(client, item_id, session_factory, clock):
    with session_factory.begin() as db:
        old = db.get(PracticeItem, UUID(item_id))
        db.add(QuestionAttempt(practice_item_id=old.id, question_id=old.question_id, kp_id=old.kp_id,
            objective_result="wrong", submitted_at=clock.now, idempotency_key="legacy-sequence-record",
            result_state="stuck", reason_code="legacy_self_report", self_grade="not_mastered"))
    item, _ = next_item(session_factory, item_id, "2026-01-02")
    result = send(client, item, "1", "sequence-legacy-new").json()
    assert result["sequence_category"] == "independent_correct_history_unknown"
    assert result["effective_confirmation_count"] == 0
    assert get_history(client, item_id)["legacy_self_report_count"] == 1


def test_retry_limit_and_final_receipt_idempotency(client, item_id):
    latest = None
    for i in range(20):
        response = send(client, item_id, "99", f"sequence-limit-{i:03}", latest)
        assert response.status_code == 200
        latest = response.json()["attempt_id"]
    assert not response.json()["can_retry"]
    denied = send(client, item_id, "1", "sequence-limit-overflow", latest)
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "answer_attempt_limit"
    assert len(get_history(client, item_id)["items"]) == 20
    assert send(client, item_id, "99", "sequence-limit-000").status_code == 200


def test_two_concurrent_corrections_save_only_one_successor(client, item_id, session_factory, clock):
    first = send(client, item_id, "3", "sequence-race-first").json()
    def correction(index):
        with session_factory() as db:
            try:
                result = submit_answer(db, item_id=UUID(item_id), raw_answer="4", selected_option=None,
                    idempotency_key=f"sequence-race-{index}", now=clock.now,
                    expected_previous_attempt_id=UUID(first["attempt_id"]))
                db.commit(); return result.attempt_number
            except ValueError as exc:
                db.rollback(); return str(exc)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(correction, range(2)))
    assert sorted(map(str, results)) == ["2", "answer_attempt_conflict"]
    assert len(get_history(client, item_id)["items"]) == 2


def test_history_endpoint_is_readonly_and_missing_item_has_envelope(client, item_id, session_factory):
    assert get_history(client, item_id)["items"] == []
    send(client, item_id, "1", "sequence-read-only")
    with session_factory() as db:
        before = db.scalar(select(func.count()).select_from(LearningEvent))
    assert get_history(client, item_id) == get_history(client, item_id)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == before
    missing = client.get(f"/api/practice-items/{uuid4()}/answer-submissions")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "practice_item_not_found"
