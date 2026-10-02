"""P1 finite learning slice against isolated PG; all review stamps are SIMULATED.

No human content review, model call or development-data import occurs here.
"""
import json
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from backend.models.learning import (
    DailyPlan, KnowledgePoint, KpMasteryPolicy, KpState, LearningEvent,
    PracticeItem, Question, QuestionAttempt,
)
from backend.services.exam_reference_service import build_exam_reference_seed
from backend.services.learning_task_tools import TaskTools
from backend.services.question_pack import import_pack
from backend.services.golden_learning_slice import reviewed_pack
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_answer_submissions import cleanup_answer_records
from tests.unit.test_golden_learning_slice import load_asset, attest_for_test


@pytest.fixture
def slice_questions(session_factory, clean_database):
    """Only test DB receives the simulated reviewed version; tracked asset stays GENERATED."""
    asset = load_asset()
    index, _ = build_exam_reference_seed()
    index = {n["code"]: n for n in index}
    with session_factory.begin() as db:
        def ensure(code):
            node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == code))
            if node: return node
            spec = index[code]
            parent = ensure(spec["parent_code"]) if spec.get("parent_code") else None
            node = KnowledgePoint(code=code, name=spec["name"], subject=spec["subject"],
                parent_id=parent.id if parent else None, ordinal=spec.get("ordinal", 1),
                is_assessable=spec.get("is_assessable", True), is_active=True,
                is_reference_only=spec.get("is_reference_only", True))
            db.add(node); db.flush()
            return node
        for topic in asset.topics:
            node = ensure(topic.kp_code)
            if db.get(KpState, node.id) is None: db.add(KpState(kp_id=node.id))
            if db.get(KpMasteryPolicy, node.id) is None:
                db.add(KpMasteryPolicy(kp_id=node.id, min_confirmations=3, min_real_questions=3,
                    required_variant_count=1, min_day_span=2, note="Isolated golden fixture policy"))
        result = import_pack(db, reviewed_pack(attest_for_test(asset)), apply=True)
        assert result["new"] == 16
        # Production requires a separate explicit online policy review; this fixture
        # deliberately simulates it without touching seed or development nodes.
        for topic in asset.topics: ensure(topic.kp_code).is_reference_only = False
        rows = db.scalars(select(Question).where(
            Question.grading_config["provenance"]["key"].as_string().like(asset.slice_id + ":%"))).all()
        identifiers = {(q.grading_config["provenance"]["key"].split(":")[-1]): str(q.id) for q in rows}
    return asset, identifiers


def make_item(factory, qid, study_date="2026-01-01"):
    with factory.begin() as db:
        question = db.get(Question, UUID(qid))
        plan = DailyPlan(study_date=study_date, status="active")
        db.add(plan); db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=question.id, kp_id=question.kp_id, ordinal=1)
        db.add(item); db.flush()
        return str(item.id), str(question.kp_id)


@pytest.mark.parametrize("source_id", [q.content.source_id for q in load_asset().questions])
def test_all_finite_questions_through_real_answer_api(slice_questions, session_factory, client, source_id):
    asset, ids = slice_questions
    content = next(q.content for q in asset.questions if q.content.source_id == source_id)
    item, kp = make_item(session_factory, ids[source_id])
    payload = {"idempotency_key": "golden-answer-" + source_id,
        ("selected_option" if content.options else "raw_answer"): content.correct_answer}
    response = client.post(f"/api/practice-items/{item}/answer-submissions", json=payload)
    assert response.status_code == 200, response.text
    expected = "right" if content.grading_method else "unknown"
    assert response.json()["result"] == expected
    assert response.json()["effective_confirmation_count"] == (1 if expected == "right" else 0)
    assert client.post(f"/api/practice-items/{item}/answer-submissions", json=payload).json() == response.json()
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1
        assert db.get(KpState, UUID(kp)).state != "mastered"


@pytest.mark.parametrize("source_id", [q.content.source_id for q in load_asset().questions])
def test_generated_content_cannot_add_objective_confirmation(slice_questions, session_factory, client, source_id):
    asset, ids = slice_questions
    content = next(q.content for q in asset.questions if q.content.source_id == source_id)
    with session_factory.begin() as db:
        q = db.get(Question, UUID(ids[source_id]))
        q.grading_config = {"verified": False, "method": content.grading_method}
    item, kp = make_item(session_factory, ids[source_id])
    result = client.post(f"/api/practice-items/{item}/answer-submissions", json={
        "idempotency_key": "golden-unverified-" + source_id,
        ("selected_option" if content.options else "raw_answer"): content.correct_answer}).json()
    assert result["result"] == "unknown" and result["reason"] == "answer_not_verified"
    assert result["effective_confirmation_count"] == 0
    with session_factory() as db:
        assert db.get(KpState, UUID(kp)).assessment_basis == "legacy_self_reported"


class SlicePlanner:
    """Offline protocol stub uses tool results; it does not prove real model planning quality."""
    def __init__(self, target_question):
        self.target = target_question
        self.turn = 0
        self.nodes = []

    def tool_turn(self, messages, tools, *, timeout):
        self.turn += 1
        if self.turn == 1:
            goal = json.loads(messages[1]["content"])["goal"]
            actions = [("search_knowledge", {"query": goal})]
        elif self.turn == 2:
            self.nodes = [n["kp_id"] for n in json.loads(messages[-1]["content"])["nodes"]]
            actions = [("get_learning_state", {"kp_ids": self.nodes}),
                ("read_lesson", {"kp_id": self.nodes[0]}),
                ("find_questions", {"kp_ids": self.nodes})]
        elif self.turn == 3:
            available = json.loads(messages[-1]["content"])["questions"]
            candidate = next(q for q in available if q["question_id"] == self.target)
            assert not candidate["in_today_plan"]
            actions = [("validate_plan", {"question_ids": [candidate["question_id"]],
                "rationale": "隔离黄金样例：按真实候选与状态安排，不导出标准答案"})]
        else:
            return {"message": {"content": json.dumps({"message": "草案已校验，等待确认", "needs_clarification": False})}}
        return {"message": {"tool_calls": [{"id": f"golden-{self.turn}-{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(actions)]}}


@pytest.mark.parametrize("source_id", ["M01", "T01"])
def test_slice_task_answer_and_next_day_feedback(slice_questions, session_factory, client, clock, monkeypatch, source_id):
    import backend.services.learning_task_service as service
    import backend.api.routes.learning_tasks as routes
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None): return clock.now if tz else clock.now.replace(tzinfo=None)
    monkeypatch.setattr(service, "datetime", ClockDateTime)
    asset, ids = slice_questions
    q = next(q.content for q in asset.questions if q.content.source_id == source_id)
    topic = next(t for t in asset.topics if t.kp_code == q.kp_code)
    monkeypatch.setattr(routes, "provider_from_settings", lambda _: SlicePlanner(ids[source_id]))
    lesson = client.get(f"/api/knowledge/lessons/{topic.kp_code}")
    assert lesson.status_code == 200 and lesson.json()["question_count"] == 8
    assert "例题" in lesson.json()["markdown"]

    def arrange():
        with session_factory() as db:
            before_items = db.scalar(select(func.count()).select_from(PracticeItem))
        created = client.post("/api/learning-tasks", json={"goal": topic.name,
            "budget_minutes": 10, "mode": "builtin"})
        assert created.status_code == 201, created.text
        tid = created.json()["task_id"]
        run = client.post(f"/api/learning-tasks/{tid}/run")
        assert run.status_code == 200 and run.json()["status"] == "ready", run.text
        with session_factory() as db:
            assert db.scalar(select(func.count()).select_from(PracticeItem)) == before_items
        body = {"draft_version": run.json()["draft_version"]}
        committed = client.post(f"/api/learning-tasks/{tid}/confirm", json=body)
        assert committed.status_code == 200, committed.text
        assert client.post(f"/api/learning-tasks/{tid}/confirm", json=body).json() == committed.json()
        today = client.get("/api/plans/today").json()
        assert len(today["items"]) == 1
        return today["items"][0]

    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 0
    first = arrange()
    wrong = client.post(f"/api/practice-items/{first['id']}/answer-submissions", json={
        "raw_answer": "99", "idempotency_key": "golden-first-wrong"}).json()
    assert wrong["result"] == "wrong" and wrong["effective_confirmation_count"] == 0
    clock.now += timedelta(days=1)
    tools = TaskTools(session_factory, budget_minutes=10, now=clock.now, goal=topic.name)
    found = tools.execute("search_knowledge", {"query": topic.name})
    state = tools.execute("get_learning_state", {"kp_ids": [n["kp_id"] for n in found["nodes"]]})["states"][0]
    assert state["recent_attempts"][0]["result"] == "wrong"
    candidates = tools.execute("find_questions", {"kp_ids": [first["kp_id"]]})["questions"]
    assert candidates[0]["question_id"] == ids[source_id] and candidates[0]["pending_review"]
    assert all("correct_answer" not in c for c in candidates)
    second = arrange()
    assert second["id"] != first["id"] and second["question_id"] == first["question_id"]
    # Looking at the solution before correcting must not become independent evidence.
    assert client.post(f"/api/practice-items/{second['id']}/answer-reveal").status_code == 200
    corrected = client.post(f"/api/practice-items/{second['id']}/answer-submissions", json={
        "raw_answer": q.correct_answer, "idempotency_key": "golden-assisted-correct"}).json()
    assert corrected["result"] == "right" and corrected["assisted"]
    assert corrected["effective_confirmation_count"] == 0
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 2
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 2
        assert db.get(QuestionAttempt, UUID(wrong["attempt_id"])).objective_result == "wrong"
        assert db.get(KpState, UUID(first["kp_id"])).state != "mastered"


@pytest.mark.parametrize("source_id", ["M01", "T01"])
def test_slice_budget_and_existing_today_question_constraints(slice_questions, session_factory, clock, source_id):
    asset, ids = slice_questions
    q = next(q.content for q in asset.questions if q.content.source_id == source_id)
    topic = next(t for t in asset.topics if t.kp_code == q.kp_code)
    tools = TaskTools(session_factory, budget_minutes=1, now=clock.now, goal=topic.name)
    nodes = tools.execute("search_knowledge", {"query": topic.name})["nodes"]
    tools.execute("get_learning_state", {"kp_ids": [n["kp_id"] for n in nodes]})
    tools.execute("find_questions", {"kp_ids": [n["kp_id"] for n in nodes]})
    invalid = tools.execute("validate_plan", {"question_ids": [ids[source_id]]})
    assert not invalid["valid"] and "time_budget_exceeded" in invalid["errors"]
    assert tools.draft is None
    make_item(session_factory, ids[source_id])
    tools.budget_minutes = 10
    existing = tools.execute("validate_plan", {"question_ids": [ids[source_id]]})
    assert not existing["valid"] and "already_in_today_plan" in existing["errors"]
    assert tools.draft is None
