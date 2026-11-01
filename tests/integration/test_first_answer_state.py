"""First submissions must not depend on a pre-seeded mastery projection.

These cases use only the runner-owned disposable PostgreSQL database.
"""
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select

from backend.mastery.storage import policy_for_node
from backend.models.learning import (
    DailyPlan, KpMasteryPolicy, KpState, LearningEvent, PracticeItem,
    Question, QuestionAttempt,
)
from tests.integration.test_learning_loop import (
    clean_database, client, clock, session_factory, mark_isolated_question_trusted,
)


def prepare_missing_state(factory, policy_version=None):
    with factory.begin() as db:
        question = db.scalar(select(Question).where(
            Question.stem == "求极限 lim(x->0) (e^x - 1) / x 的值。"))
        kp_id = question.kp_id
        db.execute(delete(KpState).where(KpState.kp_id == kp_id))
        if policy_version != 3:
            db.execute(delete(KpMasteryPolicy).where(KpMasteryPolicy.kp_id == kp_id))
            if policy_version is not None:
                db.add(KpMasteryPolicy(kp_id=kp_id, policy_version=policy_version))
        else:
            from backend.services.graduation_question_set import freeze_graduation_question_set
            freeze_graduation_question_set(db, kp_id=kp_id, question_ids=[question.id],
                reason="SYNTHETIC TEST: protect missing v3 binding guard")
        plan = DailyPlan(study_date="2026-01-01", status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=question.id, kp_id=kp_id, ordinal=1)
        db.add(item)
        db.flush()
        return str(item.id), kp_id


@pytest.mark.parametrize("policy_version", [None, 1, 2])
@pytest.mark.parametrize("answer,reveal,expected", [("1", False, "right"), ("0", False, "wrong"), ("1", True, "right")])
def test_first_answer_initializes_missing_projection_without_changing_policy(
        client, session_factory, clean_database, policy_version, answer, reveal, expected):
    item_id, kp_id = prepare_missing_state(session_factory, policy_version)
    if reveal:
        response = client.post(f"/api/practice-items/{item_id}/answer-reveal", json={})
        assert response.status_code == 200, response.text
    payload = {"idempotency_key": "first-state-answer-0001", "raw_answer": answer}
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json=payload)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["result"] == expected
    assert receipt["assisted"] is reveal
    assert client.post(f"/api/practice-items/{item_id}/answer-submissions", json=payload).json() == receipt
    with session_factory() as db:
        state = db.get(KpState, kp_id)
        assert state is not None and state.mastered_at is None and state.state != "mastered"
        assert state.graduation_set_version is None
        assert state.graduation_set_binding_status == "unstarted"
        policy = db.get(KpMasteryPolicy, kp_id)
        assert (policy.policy_version if policy else None) == policy_version
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1
        event = db.scalar(select(LearningEvent).where(LearningEvent.event_type == "answer_submitted"))
        assert event is not None
        assert event.payload["assisted"] is reveal
        assert db.get(PracticeItem, UUID(item_id)).completed_at is not None
        if reveal or expected == "wrong":
            assert receipt["effective_confirmation_count"] == 0


def test_read_only_policy_resolution_does_not_create_projection(session_factory, clean_database):
    _, kp_id = prepare_missing_state(session_factory)
    with session_factory.begin() as db:
        assert policy_for_node(db, kp_id).policy_version == 1
    with session_factory() as db:
        assert db.get(KpState, kp_id) is None
        assert db.get(KpMasteryPolicy, kp_id) is None


def test_generate_then_first_answer_without_seeded_state_or_policy(client, session_factory, clean_database):
    with session_factory.begin() as db:
        question = db.scalar(select(Question).where(
            Question.stem == "求极限 lim(x->0) (e^x - 1) / x 的值。"))
        kp_id = question.kp_id
        db.execute(delete(KpState).where(KpState.kp_id == kp_id))
        db.execute(delete(KpMasteryPolicy).where(KpMasteryPolicy.kp_id == kp_id))
    response = client.post("/api/plans/today/generate", json={"selected_kp_ids": [str(kp_id)]})
    assert response.status_code == 201, response.text
    item = response.json()["items"][0]
    with session_factory() as db:
        assert db.get(KpState, kp_id) is not None
        assert db.get(KpMasteryPolicy, kp_id) is None
        question = db.get(Question, UUID(item["question_id"]))
        answer = {"selected_option": question.correct_answer} if question.options else {"raw_answer": question.correct_answer}
    response = client.post(f"/api/practice-items/{item['id']}/answer-submissions", json={
        "idempotency_key": "new-plan-first-answer-0001", **answer})
    assert response.status_code == 200, response.text
    assert response.json()["result"] == "right"
    assert response.json()["question_version_id"] == item["question_version_id"]


def test_reported_lnx_single_choice_without_state_saves_exact_version_once(client, session_factory, clean_database):
    """Replay the supplied A/0 selection through the real route, in a fresh DB."""
    with session_factory.begin() as db:
        kp_id = db.scalar(select(Question.kp_id).where(
            Question.stem == "求极限 lim(x->0) (e^x - 1) / x 的值。"))
        db.execute(delete(KpState).where(KpState.kp_id == kp_id))
        db.execute(delete(KpMasteryPolicy).where(KpMasteryPolicy.kp_id == kp_id))
        question = Question(kp_id=kp_id, question_type="single_choice", question_role="typical",
            grading_mode="auto", grading_config={"verified": True, "method": "single_choice"},
            difficulty="intermediate", estimated_minutes=5, is_variant=False,
            stem="【SYNTHETIC 隔离练习】求极限 lim(x→∞) ln(x)/x。",
            options={"A": "0", "B": "1", "C": "∞", "D": "不存在"}, correct_answer="A",
            explanation="【合成题解析】导数之比为 1/x，极限为0；不是历年真题。")
        mark_isolated_question_trusted(question, db=db)
        version_id = str(question.current_version_id)
        plan = DailyPlan(study_date="2026-01-01", status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=question.id, kp_id=kp_id, ordinal=1)
        db.add(item)
        db.flush()
        item_id = str(item.id)
    payload = {"idempotency_key": "reported-lnx-option-a-0001", "selected_option": "A", "raw_answer": None}
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json=payload)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["result"] == "right" and receipt["assisted"] is False
    assert receipt["question_version_id"] == version_id
    for _ in range(4):
        replay = client.post(f"/api/practice-items/{item_id}/answer-submissions", json=payload)
        assert replay.status_code == 200 and replay.json() == receipt
    history = client.get(f"/api/practice-items/{item_id}/answer-submissions").json()
    assert len(history["items"]) == 1 and history["items"][0]["attempt_id"] == receipt["attempt_id"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 1


def test_concurrent_first_submissions_share_one_projection(session_factory, clock, clean_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from backend.services.answer_submission_service import submit_answer
    first, kp_id = prepare_missing_state(session_factory)
    with session_factory.begin() as db:
        original = db.get(PracticeItem, UUID(first))
        plan = DailyPlan(study_date="2026-01-02", status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=original.question_id, kp_id=kp_id, ordinal=1)
        db.add(item)
        db.flush()
        second = str(item.id)
    barrier = Barrier(2)
    def answer(target):
        with session_factory.begin() as db:
            barrier.wait(timeout=5)
            return submit_answer(db, item_id=UUID(target), raw_answer="1", selected_option=None,
                idempotency_key=f"first-concurrent-{target}", now=clock())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(answer, target) for target in (first, second)]
        assert all(f.result(timeout=15).result == "right" for f in futures)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(KpState).where(KpState.kp_id == kp_id)) == 1
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 2
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 2


def test_missing_v3_binding_is_not_silently_invented_for_existing_practice(client, session_factory, clean_database):
    item_id, kp_id = prepare_missing_state(session_factory, policy_version=3)
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json={
        "idempotency_key": "missing-v3-binding-0001", "raw_answer": "1"})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "graduation_set_binding_missing_for_started_learner"
    with session_factory() as db:
        assert db.get(KpState, kp_id) is None  # failed transaction rolled back initialization
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 0


def test_bootstrap_relocks_committed_state_without_overwriting_concurrent_change(client, session_factory, monkeypatch, clean_database):
    from backend.services import answer_submission_service as service
    item_id, kp_id = prepare_missing_state(session_factory)
    original = service.policy_for_node
    captured = []
    applied = []
    original_apply = service.apply_snapshot
    def resolve(db, target, **kwargs):
        if not captured:
            # Another creator commits after submit's first empty row-lock query.
            with session_factory.begin() as other:
                other.add(KpState(kp_id=kp_id))
            captured.append(db.get(KpState, kp_id))
            # Keep the cached ORM row alive, then commit a real concurrent update.
            with session_factory.begin() as other:
                other.get(KpState, kp_id).node_self_grade = "partial"
        return original(db, target, **kwargs)
    monkeypatch.setattr(service, "policy_for_node", resolve)
    def apply(state, snapshot):
        applied.append(snapshot.node_self_grade.value if snapshot.node_self_grade else None)
        return original_apply(state, snapshot)
    monkeypatch.setattr(service, "apply_snapshot", apply)
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json={
        "idempotency_key": "bootstrap-concurrent-update-0001", "raw_answer": "1"})
    assert response.status_code == 200, response.text
    assert applied == ["partial"]
    with session_factory() as db:
        assert db.get(KpState, kp_id).node_self_grade == "partial"
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1


def test_exception_after_initialization_rolls_back_projection_and_answer(client, session_factory, monkeypatch, clean_database):
    from backend.services import answer_submission_service as service
    item_id, kp_id = prepare_missing_state(session_factory)
    def fail(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_TEST_FAILURE_AFTER_STATE_INITIALIZATION")
    monkeypatch.setattr(service, "apply_snapshot", fail)
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json={
        "idempotency_key": "bootstrap-rollback-0001", "raw_answer": "1"})
    assert response.status_code == 500
    with session_factory() as db:
        assert db.get(KpState, kp_id) is None
        assert db.get(PracticeItem, UUID(item_id)).completed_at is None
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 0


def test_handoff_provider_reports_actual_tool_receipts_without_planning_writes(client, session_factory, clock, clean_database):
    import json
    from scripts.naiwa_answer_handoff_provider import HandoffEvidenceProvider
    from backend.services.learning_task_tools import TaskTools, tool_definitions
    item_id, kp_id = prepare_missing_state(session_factory)
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json={
        "idempotency_key":"handoff-evidence-test-0001", "raw_answer":"1"})
    assert response.status_code == 200, response.text
    provider = HandoffEvidenceProvider()
    tools = TaskTools(session_factory, budget_minutes=90, now=clock(), goal="只给洛必达复习建议，不创建计划")
    tools.nodes.add(kp_id)
    messages = [{"role":"user","content":json.dumps({"structured_handoff":{
        "constraints":{"resolved_scope_node_ids":[str(kp_id)]}}})}]
    trace=[]
    turn = provider.tool_turn(messages, tool_definitions("recommend"), timeout=10)
    calls = turn["message"]["tool_calls"]
    assert {call["function"]["name"] for call in calls} == {
        "get_learning_state", "get_question_availability", "find_questions"}
    for call in calls:
        function = call["function"]
        result = tools.execute(function["name"], json.loads(function["arguments"]))
        trace.append({"tool":function["name"],"status":"completed","result":result})
        messages.append({"role":"tool","content":json.dumps(result,ensure_ascii=False)})
    from backend.services.learning_task_service import _finalization_messages
    finalization = _finalization_messages("只给洛必达复习建议，不创建计划",90,
        {"kind":"recommend"},trace,tools,planner_factual_summary=tools.planner_factual_summary())
    assert not any(message.get("role")=="tool" for message in finalization)
    final = provider.tool_turn(finalization, [], timeout=10)
    message = json.loads(final["message"]["content"])["message"]
    assert "独立答对1条" in message and "独立答错0条" in message and "看解析后答对0条" in message
    assert "固定模拟Provider" in message and "没有创建或追加正式计划" in message
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == 1
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 1
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 1
