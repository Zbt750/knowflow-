from copy import deepcopy
from datetime import timedelta
from uuid import UUID
import pytest
from sqlalchemy import select, func
from backend.models.learning import KnowledgePoint, PracticeItem, QuestionAttempt, LearningEvent, KpState
from backend.services.learning_task_tools import TaskTools
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from tests.integration.test_answer_submissions import cleanup_answer_records, item_id
from tests.integration.test_attempt_sequence import send, next_item


def read(client, factory, item):
    with factory() as db: kp = db.get(PracticeItem, UUID(item)).kp_id
    response = client.get(f"/api/knowledge/{kp}")
    assert response.status_code == 200
    return response.json()["capability_profile"]


def dim(profile, key="final_result"):
    return next(d for d in profile["dimensions"] if d["key"] == key)


def test_independent_result_exposed_identically_to_ui_and_agent(client, session_factory, item_id, clock):
    before = read(client, session_factory, item_id)
    assert all(d["independent_question_count"] == 0 for d in before["dimensions"])
    send(client, item_id, "1", "capability-independent")
    profile = read(client, session_factory, item_id)
    assert dim(profile)["status"] == "independent_evidence"
    assert dim(profile)["independent_question_count"] == 1
    assert dim(profile, "reasoning_process")["independent_question_count"] == 0
    tools = TaskTools(session_factory, budget_minutes=20, now=clock.now, goal="洛必达")
    nodes = tools.execute("search_knowledge", {"query": "洛必达"})["nodes"]
    result = tools.execute("get_learning_state", {"kp_ids": [nodes[0]["kp_id"]]})
    tool_profile = result["states"][0]["capability_profile"]
    assert tool_profile["version"] == profile["version"]
    for summary, full in zip(tool_profile["dimensions"], profile["dimensions"]):
        assert all(full[k] == v for k, v in summary.items())
    assert all("reason" not in d and "independent_question_ids" not in d for d in tool_profile["dimensions"])
    assert "raw_answer" not in str(profile) and "reference_answer" not in str(profile)
    pool = tools.execute("find_questions", {"kp_ids": [nodes[0]["kp_id"]]})
    assert all("capability_keys" in q for q in pool["questions"])


def test_self_correction_stays_pending_and_next_day_retest_changes_dimension(client, session_factory, item_id, clock):
    first = send(client, item_id, "3", "capability-wrong").json()
    send(client, item_id, "1", "capability-corrected", first["attempt_id"])
    profile = read(client, session_factory, item_id)
    assert profile["excluded_confirmation_count"] == 0  # weak evidence is not a rejected confirmation
    d = dim(profile)
    assert d["status"] == "needs_retest" and d["independent_question_count"] == 0
    assert d["recent_attempt_count"] == 2
    clock.now += timedelta(days=1)
    fresh, _ = next_item(session_factory, item_id, "2026-01-02")
    send(client, fresh, "1", "capability-fresh")
    d = dim(read(client, session_factory, fresh))
    assert d["status"] == "independent_evidence" and d["independent_question_count"] == 1
    assert d["pending_review_question_count"] == 0 and d["recent_attempt_count"] == 3


@pytest.mark.parametrize("kind", ["solution", "guess", "blank", "unverified"])
def test_weak_results_never_supply_capability_confirmation(client, session_factory, item_id, kind):
    body = {"idempotency_key": "capability-weak", "raw_answer": "1"}
    if kind == "solution": client.post(f"/api/practice-items/{item_id}/answer-reveal")
    if kind == "guess": body["confidence"] = "guess"
    if kind == "blank": body["raw_answer"] = ""
    if kind == "unverified":
        with session_factory.begin() as db: db.get(PracticeItem, UUID(item_id)).question.grading_config = None
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json=body)
    assert response.status_code == 200
    d = dim(read(client, session_factory, item_id))
    assert d["status"] == "limited_evidence" and d["independent_question_count"] == 0
    assert d["recent_assisted_attempt_count"] == (1 if kind == "solution" else 0)


def test_content_revision_invalidates_view_evidence_without_rewriting_receipt(client, session_factory, item_id):
    saved = send(client, item_id, "1", "capability-hash").json()
    assert dim(read(client, session_factory, item_id))["independent_question_count"] == 1
    with session_factory.begin() as db: db.get(PracticeItem, UUID(item_id)).question.stem += "修订"
    result = read(client, session_factory, item_id)
    assert dim(result)["independent_question_count"] == 0 and result["excluded_confirmation_count"] == 1
    assert send(client, item_id, "1", "capability-hash").json() == saved


def test_role_revision_cannot_relabel_old_basic_result_as_transfer(client, session_factory, item_id):
    send(client, item_id, "1", "capability-role")
    with session_factory.begin() as db: db.get(PracticeItem, UUID(item_id)).question.question_role = "comprehensive"
    result = read(client, session_factory, item_id)
    assert dim(result)["independent_question_count"] == 1
    assert dim(result, "application_transfer")["independent_question_count"] == 0


def test_legacy_window_and_missing_receipt_are_not_invented_evidence(client, session_factory, item_id):
    send(client, item_id, "1", "capability-legacy")
    with session_factory.begin() as db:
        item = db.get(PracticeItem, UUID(item_id)); state = db.get(KpState, item.kp_id)
        state.assessment_basis = "legacy_self_reported"
        state.manual_credit_count = 2
    assert dim(read(client, session_factory, item_id))["independent_question_count"] == 0
    with session_factory.begin() as db:
        state = db.get(KpState, db.get(PracticeItem, UUID(item_id)).kp_id)
        state.assessment_basis = "objective_v1"
        attempt = db.scalar(select(QuestionAttempt)); attempt.grading_evidence = None
    assert dim(read(client, session_factory, item_id))["independent_question_count"] == 0


def test_legacy_pending_flags_cannot_be_promoted_to_objective_retest(client, session_factory, item_id):
    send(client, item_id, "3", "capability-legacy-pending")
    with session_factory.begin() as db:
        item = db.get(PracticeItem, UUID(item_id))
        state = db.get(KpState, item.kp_id)
        assert state.pending_review_question_ids
        state.assessment_basis = "legacy_self_reported"
    result = dim(read(client, session_factory, item_id))
    assert result["status"] == "limited_evidence"
    assert result["pending_review_question_count"] == 0


def test_parent_has_no_capability_profile_and_reads_do_not_write(client, session_factory, item_id):
    send(client, item_id, "1", "capability-readonly")
    with session_factory() as db:
        parent = db.scalar(select(KnowledgePoint).where(KnowledgePoint.is_assessable.is_(False)))
        parent_id = str(parent.id)
        before = db.scalar(select(func.count()).select_from(LearningEvent))
        state = deepcopy(db.get(KpState, db.get(PracticeItem, UUID(item_id)).kp_id).evidence_window)
    assert client.get(f"/api/knowledge/{parent_id}").json()["capability_profile"] is None
    assert read(client, session_factory, item_id) == read(client, session_factory, item_id)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == before
        assert db.get(KpState, db.get(PracticeItem, UUID(item_id)).kp_id).evidence_window == state


def test_current_role_snapshot_supplies_transfer_only_with_matching_mapping(client, session_factory, item_id):
    with session_factory.begin() as db: db.get(PracticeItem, UUID(item_id)).question.question_role = "comprehensive"
    send(client, item_id, "1", "capability-comprehensive")
    assert dim(read(client, session_factory, item_id), "application_transfer")["independent_question_count"] == 1


def test_reference_only_leaf_exposes_unverified_408_process_not_fake_online_pool(client, session_factory):
    from backend.services.exam_reference_service import sync_exam_reference_index
    with session_factory.begin() as db:
        sync_exam_reference_index(db)
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.subject == "408", KnowledgePoint.is_reference_only.is_(True)))
        identifier = str(node.id)
    result = client.get(f"/api/knowledge/{identifier}").json()
    assert result["exam_references"] and not result["questions"]
    d = dim(result["capability_profile"], "algorithm_process")
    assert d["status"] == "not_verified" and d["online_question_count"] == 0
    assert all(d["independent_question_count"] == 0 for d in result["capability_profile"]["dimensions"])


@pytest.mark.parametrize("count", [101, 201])
def test_large_history_is_bounded_and_reported_not_silently_trusted(client, session_factory, item_id, clock, count):
    saved = send(client, item_id, "1", "capability-bounded").json()
    with session_factory.begin() as db:
        original = db.get(QuestionAttempt, UUID(saved["attempt_id"]))
        for i in range(count):
            db.add(QuestionAttempt(practice_item_id=original.practice_item_id,
                question_id=original.question_id, kp_id=original.kp_id, raw_answer="1",
                objective_result="right", submitted_at=clock.now, result_state=original.result_state,
                reason_code=original.reason_code, grading_evidence=deepcopy(original.grading_evidence),
                idempotency_key=f"capability-extra-{i}"))
    result = read(client, session_factory, item_id)
    assert result["history_truncated"] and dim(result)["recent_attempt_count"] == 100
    assert result["confirmation_lookup_truncated"] == (count == 201)
    assert dim(result)["independent_question_count"] == (0 if count == 201 else 1)
