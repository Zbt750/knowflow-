"""真实API/PG跨模块闭环；模型为协议替身，避免用收费推理测试事务。"""
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, func

from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_answer_submissions import cleanup_answer_records
from backend.models.learning import Question, KnowledgePoint, DailyPlan, PracticeItem, QuestionAttempt, LearningEvent, KpState
from backend.services.learning_task_tools import TaskTools


class JourneyPlanner:
    def __init__(self): self.turn = 0; self.nodes = []; self.budget = 0; self.kind = None
    def tool_turn(self, messages, tools, *, timeout):
        self.turn += 1
        if self.turn == 1:
            body = json.loads(messages[1]["content"])
            self.budget = body["budget_minutes"]
            self.kind = "fill_blank" if "填空题" in body["goal"] else None
            actions = [("search_knowledge", {"query": "洛必达"})]
        elif self.turn == 2:
            self.nodes = [n["kp_id"] for n in json.loads(messages[-1]["content"])["nodes"]]
            actions = [("get_learning_state", {"kp_ids": self.nodes}), ("find_questions", {"kp_ids": self.nodes, "question_type": self.kind})]
        elif self.turn == 3:
            qs = json.loads(messages[-1]["content"])["questions"]
            candidates = [q for q in qs if not q["in_today_plan"] and q["minutes"] <= self.budget]
            actions = [("validate_plan", {"question_ids": [candidates[0]["question_id"]], "rationale": "隔离闭环测试：按修改后的题型和时间选择"})]
        else:
            return {"message": {"content": json.dumps({"message": "已校验草案，尚未加入今日学习", "needs_clarification": False})}}
        return {"message": {"tool_calls": [{"id": f"j{self.turn}-{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(actions)]}}


@pytest.fixture
def journey(client, clock, session_factory, monkeypatch):
    import backend.services.learning_task_service as service
    import backend.api.routes.learning_tasks as routes
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None): return clock.now if tz else clock.now.replace(tzinfo=None)
    monkeypatch.setattr(service, "datetime", ClockDateTime)
    monkeypatch.setattr(routes, "provider_from_settings", lambda _: JourneyPlanner())
    with session_factory.begin() as db:
        kp = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == "math.calculus.limit.lhopital"))
        other = db.scalar(select(Question).where(Question.question_type == "single_choice", Question.kp_id != kp.id))
        plan = DailyPlan(study_date=clock.now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(), status="active")
        db.add(plan); db.flush()
        old = PracticeItem(plan_id=plan.id, question_id=other.id, kp_id=other.kp_id, ordinal=1)
        db.add(old); db.flush()
        old_id, plan_id, kp_id, expected = str(old.id), str(plan.id), str(kp.id), other.correct_answer
    first = client.post(f"/api/practice-items/{old_id}/answer-submissions", json={"selected_option": expected, "confidence": "certain", "idempotency_key": "journey-existing-answer"})
    assert first.status_code == 200 and first.json()["result"] == "right"
    before = client.get("/api/plans/today").json()
    assert before["status"] == "completed" and before["total_count"] == 1
    created = client.post("/api/learning-tasks", json={"goal": "洛必达法则比较弱，安排本次学习", "budget_minutes": 30, "mode": "builtin"}).json()
    tid = created["task_id"]
    initial = client.post(f"/api/learning-tasks/{tid}/run").json()
    assert initial["status"] == "ready"
    modified = client.patch(f"/api/learning-tasks/{tid}", json={"goal": "少一点，只做填空题，不超过5分钟", "budget_minutes": 5})
    assert modified.status_code == 200
    ready = client.post(f"/api/learning-tasks/{tid}/run").json()
    assert ready["status"] == "ready" and ready["draft"]["total_minutes"] == 5
    assert client.get("/api/plans/today").json() == before
    # 旧版本不能抢先确认新草案。
    assert client.post(f"/api/learning-tasks/{tid}/confirm", json={"draft_version": initial["draft_version"]}).status_code == 409
    receipt = client.post(f"/api/learning-tasks/{tid}/confirm", json={"draft_version": ready["draft_version"]})
    assert receipt.status_code == 200
    assert receipt.json()["metrics"]["commit"]["plan_id"] == plan_id
    assert client.post(f"/api/learning-tasks/{tid}/confirm", json={"draft_version": ready["draft_version"]}).json() == receipt.json()
    after = client.get("/api/plans/today").json()
    assert after["status"] == "active" and after["total_count"] == 2
    assert after["items"][0] == before["items"][0]
    appended = after["items"][-1]
    assert appended["ordinal"] == 2 and appended["question_type"] == "fill_blank"
    return {"task_id": tid, "item_id": appended["id"], "question_id": appended["question_id"], "kp_id": kp_id, "old_item": before["items"][0]}


@pytest.mark.parametrize("answer,confidence,reveal,result,count", [
    ("2/2", "certain", False, "right", 1),
    ("3", "certain", False, "wrong", 0),
    ("1", "certain", True, "right", 0),
    ("1", "guess", False, "right", 0),
    ("", None, False, "unknown", 0),
    ("sqrt(1)", None, False, "unknown", 0),
])
def test_complete_journey_preserves_paper_and_drives_next_day_recommendation(journey, client, session_factory, clock, answer, confidence, reveal, result, count):
    item_id = journey["item_id"]
    if reveal:
        assert client.post(f"/api/practice-items/{item_id}/answer-reveal").status_code == 200
    payload = {"raw_answer": answer, "confidence": confidence, "idempotency_key": "journey-new-answer"}
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json=payload)
    assert response.status_code == 200
    outcome = response.json()
    assert outcome["result"] == result and outcome["effective_confirmation_count"] == count
    assert client.post(f"/api/practice-items/{item_id}/answer-submissions", json=payload).json() == outcome
    assert client.post(f"/api/practice-items/{item_id}/answer-submissions", json={**payload, "raw_answer": "99"}).status_code == 409
    today = client.get("/api/plans/today").json()
    assert today["status"] == "completed" and today["items"][0] == journey["old_item"]
    assert today["items"][-1]["answer_submission"]["attempt_id"] == outcome["attempt_id"]
    assert client.post(f"/api/learning-tasks/{journey['task_id']}/cancel").status_code == 409
    detail = client.get(f"/api/knowledge/{journey['kp_id']}").json()
    # 无法可靠判定的提交仅记历史，不强行切换掌握口径。
    assert detail["node"]["assessment_basis"] == ("legacy_self_reported" if result == "unknown" else "objective_v1")
    assert detail["node"]["pending_review_count"] == (1 if result == "wrong" else 0)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 2
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 2
        assert db.get(KpState, UUID(journey["kp_id"])).state != "mastered"
    # 下一次安排可读取刚才的真实结果，不把自评或解析辅助当作客观掌握。
    tools = TaskTools(session_factory, budget_minutes=15, now=clock.now, goal="洛必达法则")
    found = tools.execute("search_knowledge", {"query": "洛必达"})
    state = tools.execute("get_learning_state", {"kp_ids": [n["kp_id"] for n in found["nodes"]]})["states"][0]
    assert state["history_available"] and state["recent_attempts"][0]["result"] == result
    assert "raw_answer" not in state["recent_attempts"][0]
    assert state["recent_attempts"][0]["submitted_at"]
    candidates = tools.execute("find_questions", {"kp_ids": [journey["kp_id"]]})["questions"]
    selected = next(q for q in candidates if q["question_id"] == journey["question_id"])
    assert selected["pending_review"] == (result == "wrong")
    assert selected["in_today_plan"]
    if result == "wrong":
        assert candidates[0]["question_id"] == journey["question_id"]
        assert "优先复测" in state["next_step"]
    clock.now += timedelta(days=1)
    tomorrow = client.get("/api/plans/today").json()
    assert tomorrow["status"] == "setup"
    recommendation = next(r for r in tomorrow["recommendations"] if r["kp_id"] == journey["kp_id"])
    if result == "wrong": assert recommendation["reason"] == "objective_review"
    if count: assert recommendation["reason"] == "insufficient_evidence"
    assert recommendation["reason"] != "consolidating"
