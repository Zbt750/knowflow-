"""Conditional protocol planner + real API/PG. NOT a real-model quality evaluation.

Golden content verification is simulated only in the test database.
"""
import json
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from backend.models.learning import Question, KpState, QuestionAttempt
from backend.services.learning_task_tools import TaskTools
from scripts.run_learning_agent_eval import snapshot
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_answer_submissions import cleanup_answer_records
from tests.integration.test_golden_learning_slice import slice_questions
from scripts.run_agent_evidence_journey import EvidencePlanner


@pytest.fixture
def adaptive(slice_questions, session_factory, client, clock, monkeypatch):
    import backend.services.learning_task_service as service
    import backend.api.routes.learning_tasks as routes
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now if tz else clock.now.replace(tzinfo=None)
    monkeypatch.setattr(service, "datetime", ClockDateTime)
    monkeypatch.setattr(routes, "provider_from_settings", lambda _: EvidencePlanner())
    return slice_questions


def arrange(client, factory, goal, budget=10):
    before = snapshot(factory)
    created = client.post("/api/learning-tasks", json={"goal": goal, "budget_minutes": budget, "mode": "builtin"})
    assert created.status_code == 201, created.text
    tid = created.json()["task_id"]
    response = client.post(f"/api/learning-tasks/{tid}/run")
    assert response.status_code == 200, response.text
    result = response.json()
    assert snapshot(factory) == before  # Tasks may persist, learning business must not change.
    return tid, result


def confirm(client, tid, result):
    body = {"draft_version": result["draft_version"]}
    first = client.post(f"/api/learning-tasks/{tid}/confirm", json=body)
    assert first.status_code == 200, first.text
    assert client.post(f"/api/learning-tasks/{tid}/confirm", json=body).json() == first.json()
    return client.get("/api/plans/today").json()["items"][-1]


@pytest.mark.parametrize("subject", ["math2", "408"])
@pytest.mark.parametrize("outcome", ["independent", "wrong", "corrected", "solution", "guess", "unknown"])
def test_second_agent_run_reads_new_evidence_and_adapts(adaptive, session_factory, client, clock, subject, outcome):
    asset, ids = adaptive
    topic = next(t for t in asset.topics if t.subject == subject)
    # Bound this protocol experiment to two numeric questions per subject.
    kept = ["M01", "M03"] if subject == "math2" else ["T01", "T02"]
    with session_factory.begin() as db:
        kp = db.get(Question, UUID(ids[kept[0]])).kp_id
        for q in db.scalars(select(Question).where(Question.kp_id == kp)):
            q.is_active = str(q.id) in {ids[s] for s in kept}
    tid, first = arrange(client, session_factory, topic.name)
    assert first["status"] == "ready"
    item = confirm(client, tid, first)
    with session_factory() as db: expected = db.get(Question, UUID(item["question_id"])).correct_answer
    if outcome == "solution":
        assert client.post(f"/api/practice-items/{item['id']}/answer-reveal").status_code == 200
    payload = {"raw_answer": "999" if outcome in {"wrong", "corrected"} else "sqrt(1)" if outcome == "unknown" else expected,
               "confidence": "guess" if outcome == "guess" else "certain", "idempotency_key": "p5-first"}
    answer = client.post(f"/api/practice-items/{item['id']}/answer-submissions", json=payload).json()
    if outcome == "corrected":
        answer = client.post(f"/api/practice-items/{item['id']}/answer-submissions", json={
            **payload, "raw_answer": expected, "idempotency_key": "p5-corrected", "expected_previous_attempt_id": answer["attempt_id"]}).json()
        assert answer["sequence_category"] == "self_corrected"
    old = client.get("/api/plans/today").json()
    clock.now += timedelta(days=1)
    tid2, second = arrange(client, session_factory, topic.name)
    assert second["status"] == "ready"
    prior_candidate = next(q for t in second["trace"] if t["tool"] == "find_questions"
                           for q in t["result"]["questions"] if q["question_id"] == item["question_id"])
    assert prior_candidate["can_repractice_in_new_item"] and not prior_candidate["in_today_plan"]
    assert prior_candidate["pending_review"] == (outcome in {"wrong", "corrected"})
    chosen = second["draft"]["questions"][0]["question_id"]
    assert (chosen != item["question_id"]) == (outcome == "independent")
    state = next(t["result"]["states"][0] for t in second["trace"] if t["tool"] == "get_learning_state")
    assert state["recent_attempts"][0]["sequence_category"] == answer["sequence_category"]
    dim = next(d for d in state["capability_profile"]["dimensions"] if d["key"] == "final_result")
    assert dim["independent_question_count"] == (1 if outcome == "independent" else 0)
    assert bool(state["pending_review_question_ids"]) == (outcome in {"wrong", "corrected"})
    assert "raw_answer" not in json.dumps(state)
    assert all(d["independent_question_count"] == 0 for d in state["capability_profile"]["dimensions"] if d["key"] in {"reasoning_process", "algorithm_process"})
    retest = confirm(client, tid2, second)
    if outcome in {"wrong", "corrected"}:
        passed = client.post(f"/api/practice-items/{retest['id']}/answer-submissions", json={
            "raw_answer": expected, "confidence": "certain", "idempotency_key": "p5-independent-retest"}).json()
        assert passed["result"] == "right" and not passed["assisted"]
        clock.now += timedelta(days=1)
        _, third = arrange(client, session_factory, topic.name)
        assert third["status"] == "ready" and third["draft"]["questions"][0]["question_id"] != item["question_id"]
        state3 = next(t["result"]["states"][0] for t in third["trace"] if t["tool"] == "get_learning_state")
        assert not state3["pending_review_question_ids"]
    assert client.get(f"/api/plans/{old['plan_id']}/items").json() == old


def test_legacy_pending_flags_are_not_objective_tool_evidence(adaptive, session_factory, clock):
    asset, ids = adaptive
    with session_factory.begin() as db:
        kp = db.get(Question, UUID(ids["M01"])).kp_id
        state = db.get(KpState, kp)
        state.assessment_basis = "legacy_self_reported"
        state.pending_review_question_ids = [ids["M01"]]
    tools = TaskTools(session_factory, budget_minutes=10, now=clock.now, goal=asset.topics[0].name)
    tools.execute("search_knowledge", {"query": asset.topics[0].name})
    state = tools.execute("get_learning_state", {"kp_ids": [str(kp)]})["states"][0]
    assert state["pending_review_question_ids"] == [] and "优先复测之前答错" not in state["next_step"]
    candidate = next(q for q in tools.execute("find_questions", {"kp_ids": [str(kp)]})["questions"] if q["question_id"] == ids["M01"])
    assert not candidate["pending_review"]
    with session_factory() as db: assert db.get(KpState, kp).pending_review_question_ids == [ids["M01"]]


def test_too_short_budget_stops_without_business_writes(adaptive, session_factory, client):
    with session_factory.begin() as db:
        kp = db.get(Question, UUID(adaptive[1]["M01"])).kp_id
        for q in db.scalars(select(Question).where(Question.kp_id == kp)):
            q.estimated_minutes = 10
    _, result = arrange(client, session_factory, adaptive[0].topics[0].name, budget=5)
    assert result["status"] == "needs_info" and not result["draft"]


def test_malformed_legacy_sequence_number_does_not_break_state_tool(adaptive, session_factory, client, clock):
    asset, _ = adaptive
    tid, ready = arrange(client, session_factory, asset.topics[0].name)
    item = confirm(client, tid, ready)
    response = client.post(f"/api/practice-items/{item['id']}/answer-submissions", json={
        "raw_answer": "999", "idempotency_key": "p5-malformed-history"})
    assert response.status_code == 200
    with session_factory.begin() as db:
        row = db.get(QuestionAttempt, UUID(response.json()["attempt_id"]))
        row.grading_evidence = {**row.grading_evidence, "attempt_number": "not-an-integer"}
    tools = TaskTools(session_factory, budget_minutes=10, now=clock.now, goal=asset.topics[0].name)
    tools.execute("search_knowledge", {"query": asset.topics[0].name})
    state = tools.execute("get_learning_state", {"kp_ids": [item["kp_id"]]})["states"][0]
    assert state["history_available"] and state["recent_attempts"][0]["result"] == response.json()["result"]
