import json
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from sqlalchemy import delete, select, func
import pytest

from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from backend.models.learning_task import LearningTask
from backend.models.learning import Question, KnowledgePoint, DailyPlan, PracticeItem, QuestionAttempt, LearningEvent, KpState
from backend.models.chat import ChatSession
from backend.schemas.learning_task import CreateTask, TaskInput
from backend.services.learning_task_service import create_task, run_task, get_task, cancel_task, modify_task
from backend.services.learning_task_tools import TaskTools
from backend.services.learning_task_service import confirm_task
from backend.schemas.learning_task import ConfirmTask
from backend.errors import AppError
from zoneinfo import ZoneInfo


def test_confirmation_creates_plan_once_and_receipt_survives_replay(session_factory):
    ready = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    body = ConfirmTask(draft_version=ready.draft_version)
    first = confirm_task(session_factory, ready.task_id, body)
    second = confirm_task(session_factory, ready.task_id, body)
    assert first.metrics["commit"] == second.metrics["commit"]
    assert first.metrics["commit"]["added_count"] == 1
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == 1
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 1
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 0
    with pytest.raises(AppError): cancel_task(session_factory, ready.task_id)
    with pytest.raises(AppError): modify_task(session_factory, ready.task_id, TaskInput(goal="换基础题", budget_minutes=30))


def test_pending_review_is_prioritized_before_candidate_limit_and_respects_type(session_factory):
    tools, questions = prepared_tools(session_factory)
    kp_id = UUID(questions[0]["kp_id"])
    with session_factory.begin() as db:
        for index in range(20):
            db.add(Question(kp_id=kp_id, question_type="single_choice", stem=f"隔离短题{index}",
                            correct_answer="A", explanation="隔离解析", estimated_minutes=1))
        pending = Question(kp_id=kp_id, question_type="calculation", stem="隔离待复测长题",
                           correct_answer="1", explanation="隔离解析", estimated_minutes=60)
        db.add(pending); db.flush(); pending_id = str(pending.id)
        db.get(KpState, kp_id).pending_review_question_ids = [pending_id, "damaged-id", None]
        db.get(KpState, kp_id).assessment_basis = "objective_v1"
    candidates = tools.execute("find_questions", {"kp_ids": [str(kp_id)]})["questions"]
    assert len(candidates) == 16
    assert candidates[0]["question_id"] == pending_id and candidates[0]["pending_review"]
    choices = tools.execute("find_questions", {"kp_ids": [str(kp_id)], "question_type": "single_choice"})["questions"]
    assert all(q["question_type"] == "single_choice" and not q["pending_review"] for q in choices)
    result = tools.execute("validate_plan", {"question_ids": [pending_id]})
    assert result["valid"]
    assert result["draft"]["questions"][0]["question_version"]
    assert tools.execute("find_questions", {"kp_ids": [str(kp_id)]})["candidate_list_complete"] is False


def test_committed_receipt_remains_idempotent_after_question_revision(session_factory):
    ready = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    body = ConfirmTask(draft_version=ready.draft_version)
    committed = confirm_task(session_factory, ready.task_id, body)
    with session_factory.begin() as db:
        db.get(Question, UUID(ready.draft["questions"][0]["question_id"])).stem += "修订"
    assert confirm_task(session_factory, ready.task_id, body).metrics["commit"] == committed.metrics["commit"]


@pytest.mark.parametrize("change", ["inactive", "budget", "stale", "cancelled", "duplicate", "stem", "answer", "explanation", "options", "grading", "difficulty"])
def test_confirmation_rechecks_changed_draft_and_rolls_back(session_factory, change):
    ready = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    body = ConfirmTask(draft_version=ready.draft_version)
    qid = UUID(ready.draft["questions"][0]["question_id"])
    with session_factory.begin() as db:
        if change == "inactive": db.get(Question, qid).is_active = False
        if change == "budget": db.get(Question, qid).estimated_minutes = 241
        if change == "stem": db.get(Question, qid).stem += "（修订）"
        if change == "answer": db.get(Question, qid).correct_answer = "修订答案"
        if change == "explanation": db.get(Question, qid).explanation = "修订解析"
        if change == "options": db.get(Question, qid).options = ["修订选项"]
        if change == "grading": db.get(Question, qid).grading_config = {"version": "changed"}
        if change == "difficulty": db.get(Question, qid).difficulty = "advanced"
        if change == "duplicate":
            p = DailyPlan(study_date=datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(), status="active")
            db.add(p); db.flush()
            db.add(PracticeItem(plan_id=p.id, question_id=qid, kp_id=db.get(Question, qid).kp_id, ordinal=1))
    if change == "stale": modify_task(session_factory, ready.task_id, TaskInput(goal="换基础题", budget_minutes=30))
    if change == "cancelled": cancel_task(session_factory, ready.task_id)
    with pytest.raises(AppError): confirm_task(session_factory, ready.task_id, body)
    with session_factory() as db:
        assert not db.get(LearningTask, ready.task_id).metrics.get("commit")
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == (1 if change == "duplicate" else 0)


@pytest.fixture(autouse=True)
def clean_tasks(session_factory, clean_database):
    with session_factory.begin() as db:
        db.execute(delete(LearningTask))
    yield
    with session_factory.begin() as db:
        db.execute(delete(LearningTask))


class PlanningProvider:
    """协议级替身，按真实工具结果决策；不调用收费端点。"""
    def __init__(self): self.calls = 0; self.nodes = []; self.questions = []

    def tool_turn(self, messages, tools, *, timeout):
        self.calls += 1
        assert 0 < timeout <= 12
        if self.calls == 1:
            actions = [("search_knowledge", {"query": "洛必达"})]
        elif self.calls == 2:
            result = json.loads(messages[-1]["content"])
            self.nodes = [n["kp_id"] for n in result["nodes"]]
            actions = [("get_learning_state", {"kp_ids": self.nodes}), ("find_questions", {"kp_ids": self.nodes})]
        elif self.calls == 3:
            result = json.loads(messages[-1]["content"])
            self.questions = [q for q in result["questions"] if not q["in_today_plan"]]
            actions = [("validate_plan", {"question_ids": [self.questions[0]["question_id"]], "rationale": "无历史时先做基础题。"})]
        else:
            return {"message": {"content": json.dumps({"message": "没有近期作答，先从基础练习开始；尚未加入今日学习。", "needs_clarification": False})}, "model": "test-tool-model"}
        return {"message": {"tool_calls": [{"id": f"t{self.calls}-{i}", "type": "function",
            "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(actions)]},
            "usage": {"total_tokens": 10}, "model": "test-tool-model"}


def task(factory, goal="洛必达比较弱，安排学习", budget=90):
    return create_task(factory, CreateTask(goal=goal, budget_minutes=budget))


def test_confirmation_appends_to_existing_completed_plan_without_reordering(session_factory):
    ready = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    qid = UUID(ready.draft["questions"][0]["question_id"])
    with session_factory.begin() as db:
        other = db.scalar(select(Question).where(Question.id != qid))
        plan = DailyPlan(study_date=datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(), status="completed")
        db.add(plan); db.flush(); pid = plan.id
        db.add(PracticeItem(plan_id=pid, question_id=other.id, kp_id=other.kp_id, ordinal=5, latest_self_grade="mastered"))
    result = confirm_task(session_factory, ready.task_id, ConfirmTask(draft_version=ready.draft_version))
    assert result.metrics["commit"]["plan_id"] == str(pid)
    with session_factory() as db:
        items = db.scalars(select(PracticeItem).where(PracticeItem.plan_id == pid).order_by(PracticeItem.ordinal)).all()
        assert [i.ordinal for i in items] == [5, 6]
        assert items[0].latest_self_grade == "mastered"
        assert db.get(DailyPlan, pid).status == "active"


def test_concurrent_confirmation_is_idempotent(session_factory):
    from concurrent.futures import ThreadPoolExecutor
    ready = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    body = ConfirmTask(draft_version=ready.draft_version)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm_task(session_factory, ready.task_id, body), range(2)))
    assert results[0].metrics["commit"] == results[1].metrics["commit"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 1


def test_confirmation_api_uses_study_clock_and_rejects_missing_version(session_factory, client, clock):
    ready = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    url = f"/api/learning-tasks/{ready.task_id}/confirm"
    assert client.post(url, json={}).status_code == 422
    response = client.post(url, json={"draft_version": ready.draft_version})
    assert response.status_code == 200
    assert response.json()["metrics"]["commit"]["study_date"] == clock.now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    assert client.post(url, json={"draft_version": ready.draft_version}).json()["metrics"]["commit"] == response.json()["metrics"]["commit"]


def prepared_tools(factory, *, budget=90, goal=""):
    tools = TaskTools(factory, budget_minutes=budget, now=datetime(2026, 1, 1, tzinfo=timezone.utc), goal=goal)
    found = tools.execute("search_knowledge", {"query": "洛必达"})
    ids = [n["kp_id"] for n in found["nodes"]]
    tools.execute("get_learning_state", {"kp_ids": ids})
    questions = tools.execute("find_questions", {"kp_ids": ids})["questions"]
    return tools, questions


def test_agent_loop_creates_only_validated_draft_and_replay_does_not_call_model(session_factory):
    provider = PlanningProvider()
    created = task(session_factory)
    result = run_task(session_factory, created.task_id, provider)
    assert result.status == "ready"
    assert result.draft["total_minutes"] <= 90 and result.draft["can_commit"] is True
    assert [t["tool"] for t in result.trace] == ["search_knowledge", "get_learning_state", "find_questions", "validate_plan"]
    assert result.metrics["calls"][-1]["usage_observed"] is False
    assert run_task(session_factory, created.task_id, provider).model_dump() == result.model_dump()
    assert provider.calls == 4
    with session_factory() as db:
        for model in [DailyPlan, PracticeItem, QuestionAttempt, LearningEvent]:
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert all(s.state == "unseen" for s in db.scalars(select(KpState)))


def test_unknown_question_and_wrong_scope_are_rejected(session_factory):
    tools, questions = prepared_tools(session_factory)
    result = tools.execute("validate_plan", {"question_ids": [str(uuid4())]})
    assert not result["valid"] and "questions_not_observed" in result["errors"]
    assert tools.execute("delete_everything", {}) == {"error": "tool_not_allowed"}
    with pytest.raises(ValueError): tools.execute("get_learning_state", {"kp_ids": [str(uuid4())]})


@pytest.mark.parametrize("case", ["duplicate", "over_budget", "missing_state", "wrong_type", "wrong_difficulty"])
def test_program_rejects_invalid_plans(session_factory, case):
    tools, questions = prepared_tools(session_factory, budget=5 if case == "over_budget" else 90,
                                     goal="只做填空题" if case == "wrong_type" else "换基础题" if case == "wrong_difficulty" else "")
    q = next(q for q in questions if q["minutes"] > 5) if case == "over_budget" else questions[0]
    if case == "wrong_difficulty": q = next(q for q in questions if q["difficulty"] == "advanced")
    if case == "missing_state": tools.state_read.clear()
    ids = [q["question_id"]] * (2 if case == "duplicate" else 1)
    result = tools.execute("validate_plan", {"question_ids": ids})
    assert not result["valid"] and tools.draft is None


def test_existing_today_questions_are_not_added_twice(session_factory):
    tools, questions = prepared_tools(session_factory)
    with session_factory.begin() as db:
        q = db.get(Question, UUID(questions[0]["question_id"]))
        p = DailyPlan(study_date="2026-01-01", status="active")
        db.add(p); db.flush()
        db.add(PracticeItem(plan_id=p.id, question_id=q.id, kp_id=q.kp_id, ordinal=1))
    result = tools.execute("validate_plan", {"question_ids": [questions[0]["question_id"]]})
    assert "already_in_today_plan" in result["errors"]


def test_lecture_and_questions_do_not_export_standard_answers(session_factory):
    tools, questions = prepared_tools(session_factory)
    assert all("correct_answer" not in q and "explanation" not in q for q in questions)
    result = tools.execute("read_lesson", {"kp_id": questions[0]["kp_id"]})
    assert result["available"] and len(result["markdown"]) <= 4000


def test_self_report_and_objective_basis_are_separate(session_factory):
    tools, questions = prepared_tools(session_factory)
    kp_id = UUID(questions[0]["kp_id"])
    with session_factory.begin() as db:
        state = db.get(KpState, kp_id)
        state.node_self_grade = "mastered"
        state.assessment_basis = "objective_v1"
    result = tools.execute("get_learning_state", {"kp_ids": [str(kp_id)]})["states"][0]
    assert result["basis"] == "objective_v1" and result["self_report"] == "mastered"
    assert result["history_available"] is False


def test_cancellation_during_model_round_cannot_publish_draft(session_factory):
    created = task(session_factory)
    class CancelProvider:
        def tool_turn(self, *args, **kwargs):
            cancel_task(session_factory, created.task_id)
            return {"message": {"tool_calls": [{"id": "a", "function": {"name": "search_knowledge", "arguments": '{"query":"洛必达"}'}}]}}
    result = run_task(session_factory, created.task_id, CancelProvider())
    assert result.status == "cancelled" and result.draft is None


def test_crash_recovery_marks_expired_task_retryable(session_factory):
    created = task(session_factory)
    with session_factory.begin() as db:
        row = db.get(LearningTask, created.task_id)
        row.status, row.run_token = "running", "old-token"
        row.started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    restored = get_task(session_factory, created.task_id)
    assert restored.status == "failed" and restored.error_code == "interrupted"
    assert run_task(session_factory, created.task_id, PlanningProvider()).status == "ready"


def test_modify_retains_prior_goal_and_uses_new_budget(session_factory):
    created = task(session_factory)
    first = run_task(session_factory, created.task_id, PlanningProvider())
    updated = modify_task(session_factory, created.task_id, TaskInput(goal="少一点，只做选择题", budget_minutes=5))
    assert updated.status == "created" and updated.draft is None
    with session_factory() as db:
        row = db.get(LearningTask, created.task_id)
        assert row.context["previous_draft"] == first.draft
    assert run_task(session_factory, created.task_id, PlanningProvider()).draft["total_minutes"] <= 5


def test_final_unvalidated_answer_is_not_presented_as_plan(session_factory):
    class FictionProvider:
        def tool_turn(self, *args, **kwargs):
            return {"message": {"content": '{"message":"已加入10道题","needs_clarification":false}'}}
    result = run_task(session_factory, task(session_factory).task_id, FictionProvider())
    assert result.status == "needs_info" and result.draft is None
    assert "已加入" not in result.message


def test_tool_budget_and_bad_model_output_fail_closed(session_factory, monkeypatch):
    import backend.services.learning_task_service as service
    monkeypatch.setattr(service, "MAX_TOOL_CALLS", 0)
    result = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    assert result.status == "failed" and result.draft is None


def test_api_mode_validation_and_task_persistence(client, session_factory):
    assert client.post("/api/learning-tasks", json={"goal": "学习积分", "budget_minutes": 90, "mode": "user"}).status_code == 422
    assert client.post("/api/learning-tasks", json={"goal": "学习积分", "budget_minutes": 0}).status_code == 422
    with session_factory.begin() as db:
        s = ChatSession(title="用户资料", mode="user"); db.add(s); db.flush(); sid = str(s.id)
    assert client.post("/api/learning-tasks", json={"goal": "学习积分", "budget_minutes": 90, "session_id": sid}).status_code == 403
    created = client.post("/api/learning-tasks", json={"goal": "学习积分", "budget_minutes": 90})
    assert created.status_code == 201
    identifier = created.json()["task_id"]
    assert client.get(f"/api/learning-tasks/{identifier}").json()["status"] == "created"
    assert client.post(f"/api/learning-tasks/{identifier}/cancel", json={}).json()["status"] == "cancelled"
    assert client.get(f"/api/learning-tasks/{uuid4()}").status_code == 404


def test_model_replans_after_tool_reports_over_budget(session_factory):
    class AdaptiveProvider(PlanningProvider):
        def tool_turn(self, messages, tools, *, timeout):
            if self.calls < 2:
                return super().tool_turn(messages, tools, timeout=timeout)
            self.calls += 1
            if self.calls == 3:
                self.questions = json.loads(messages[-1]["content"])["questions"]
                chosen = max(self.questions, key=lambda q: q["minutes"])
            elif self.calls == 4:
                assert "time_budget_exceeded" in json.loads(messages[-1]["content"])["errors"]
                chosen = min(self.questions, key=lambda q: q["minutes"])
            else:
                return {"message": {"content": '{"message":"已根据时长调整草案，尚未加入今日学习。"}'}}
            return {"message": {"tool_calls": [{"id": f"fix-{self.calls}", "function": {"name": "validate_plan",
                "arguments": json.dumps({"question_ids": [chosen["question_id"]]})}}]}}
    result = run_task(session_factory, task(session_factory, budget=5).task_id, AdaptiveProvider())
    assert result.status == "ready" and result.draft["total_minutes"] <= 5
    assert result.metrics["rounds"] == 5


def test_deactivated_node_cannot_produce_question_draft(session_factory):
    tools, questions = prepared_tools(session_factory)
    with session_factory.begin() as db:
        db.get(KnowledgePoint, UUID(questions[0]["kp_id"])).is_active = False
    result = tools.execute("validate_plan", {"question_ids": [questions[0]["question_id"]]})
    assert not result["valid"]


def test_readonly_review_plan_reports_question_shortage(session_factory):
    tools, questions = prepared_tools(session_factory)
    result = tools.execute("validate_plan", {"review_kp_ids": [questions[0]["kp_id"]], "review_minutes": 15})
    assert result["valid"] and result["draft"]["warnings"]
    assert result["draft"]["questions"] == []


def test_run_round_limit_is_enforced(session_factory, monkeypatch):
    import backend.services.learning_task_service as service
    monkeypatch.setattr(service, "MAX_ROUNDS", 1)
    result = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    assert result.status == "failed" and result.error_code == "round_limit"


def test_failed_model_call_is_recorded_without_assuming_zero_cost(session_factory):
    class FailingProvider:
        model = "synthetic-model"
        def tool_turn(self, *args, **kwargs):
            raise AppError("generation_failed", retryable=True)
    result = run_task(session_factory, task(session_factory).task_id, FailingProvider())
    assert result.status == "failed"
    assert result.metrics["rounds"] == 1
    assert result.metrics["model_calls"] == 2
    assert result.metrics["failed_calls"] == 2
    assert result.metrics["successful_calls"] == 0
    call = result.metrics["calls"][0]
    assert call["status"] == "error" and call["usage"] is None
    assert call["usage_observed"] is False and call["prompt_chars"] > 0
    assert "prompt" not in call and call["error_code"] == "generation_failed"


def test_agent_recovers_one_transient_connection_failure_with_shared_deadline(session_factory):
    class TransientProvider(PlanningProvider):
        def __init__(self): super().__init__(); self.failed = False; self.timeouts = []
        def tool_turn(self, messages, tools, *, timeout):
            self.timeouts.append(timeout)
            if not self.failed:
                self.failed = True
                raise AppError("generation_failed", retryable=True)
            return super().tool_turn(messages, tools, timeout=timeout)
    provider = TransientProvider()
    result = run_task(session_factory, task(session_factory).task_id, provider)
    assert result.status == "ready"
    assert result.metrics["model_calls"] == 5 and result.metrics["rounds"] == 4
    assert result.metrics["failed_calls"] == 1 and result.metrics["successful_calls"] == 4
    assert result.metrics["calls"][0]["attempt"] == 1 and result.metrics["calls"][1]["attempt"] == 2
    assert provider.timeouts[1] <= provider.timeouts[0] <= 12


def test_scope_initialization_failure_does_not_leave_task_running(session_factory, monkeypatch):
    import backend.services.learning_task_service as service
    class BrokenTools:
        def __init__(self, *args, **kwargs): raise RuntimeError("synthetic initialization failure")
    monkeypatch.setattr(service, "TaskTools", BrokenTools)
    result = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    assert result.status == "failed" and result.error_code == "internal_error"
    assert result.metrics["model_calls"] == 0 and result.draft is None


@pytest.mark.parametrize("invalid", ["inactive", "zero_minutes"])
def test_changed_question_is_revalidated_before_delivery(session_factory, invalid):
    tools, questions = prepared_tools(session_factory)
    with session_factory.begin() as db:
        q = db.get(Question, UUID(questions[0]["question_id"]))
        if invalid == "inactive": q.is_active = False
        else: q.estimated_minutes = 0
    result = tools.execute("validate_plan", {"question_ids": [questions[0]["question_id"]]})
    assert not result["valid"] and tools.draft is None


def test_tool_validation_feedback_is_actionable_without_echoing_input(session_factory):
    class CorrectingProvider(PlanningProvider):
        def tool_turn(self, messages, tools, *, timeout):
            response = super().tool_turn(messages, tools, timeout=timeout)
            if self.calls == 3:
                action = response["message"]["tool_calls"][0]["function"]
                args = json.loads(action["arguments"])
                args["rationale"] = "PRIVATE_SENTINEL" * 40
                action["arguments"] = json.dumps(args)
            if self.calls == 4:
                feedback = json.loads(messages[-1]["content"])
                assert feedback["error"] == "invalid_tool_arguments"
                assert {"field": ["rationale"], "type": "string_too_long"} in feedback["fields"]
                assert "PRIVATE_SENTINEL" not in json.dumps(feedback)
                return {"message": {"tool_calls": [{"id": "corrected", "type": "function", "function": {
                    "name": "validate_plan", "arguments": json.dumps({"question_ids": [self.questions[0]["question_id"]], "rationale": "已缩短说明。"})}}]}}
            return response
    result = run_task(session_factory, task(session_factory).task_id, CorrectingProvider())
    assert result.status == "ready"
    assert "PRIVATE_SENTINEL" not in json.dumps(result.trace)


def test_two_relative_modifications_keep_original_scope_anchor(session_factory):
    from backend.services.learning_task_service import _task_constraints
    created = task(session_factory, goal="洛必达法则比较弱", budget=30)
    modify_task(session_factory, created.task_id, TaskInput(goal="只做填空题", budget_minutes=5))
    modify_task(session_factory, created.task_id, TaskInput(goal="还是这个知识点，只做选择题", budget_minutes=5))
    with session_factory() as db:
        row = db.get(LearningTask, created.task_id)
        constraints = _task_constraints(row.goal, row.context)
    tools = TaskTools(session_factory, budget_minutes=5, now=datetime.now(timezone.utc), goal=constraints)
    assert tools.required_type == "single_choice"
    assert [n["name"] for n in tools.execute("search_knowledge", {"query": "洛必达"})["nodes"]] == ["洛必达法则"]
    assert tools.execute("search_knowledge", {"query": "隐函数"})["nodes"] == []


def test_releasing_question_type_keeps_knowledge_scope(session_factory):
    from backend.services.learning_task_service import _task_constraints
    constraints = _task_constraints("还是这个知识点，不限题型", {"original_goal": "洛必达法则只做填空题"})
    tools = TaskTools(session_factory, budget_minutes=30, now=datetime.now(timezone.utc), goal=constraints)
    assert tools.required_type is None
    assert tools.execute("search_knowledge", {"query": "隐函数"})["nodes"] == []
    assert tools.execute("search_knowledge", {"query": "洛必达"})["nodes"]


@pytest.mark.parametrize("goal,expected", [("必须有3道不同的题", 3), ("恰好三道题", 3), ("只做2道填空题", 2), ("推荐三道题", None), ("做三到五道题", None)])
def test_explicit_question_count_is_not_confused_with_soft_preferences(session_factory, goal, expected):
    tools = TaskTools(session_factory, budget_minutes=30, now=datetime.now(timezone.utc), goal="洛必达法则，" + goal)
    assert tools.required_count == expected


@pytest.mark.parametrize("fenced", [True, False])
def test_final_json_format_recovers_without_rebuilding_valid_draft(session_factory, fenced):
    class FormattingProvider(PlanningProvider):
        def tool_turn(self, messages, tools, *, timeout):
            response = super().tool_turn(messages, tools, timeout=timeout)
            if self.calls == 4:
                if fenced:
                    response["message"]["content"] = "```json\n" + response["message"]["content"] + "\n```"
                else:
                    response["message"]["content"] = json.dumps({"message": "正常说明", "needs_clarification": False, "PRIVATE_FIELD": "PRIVATE_VALUE"})
            return response
    result = run_task(session_factory, task(session_factory).task_id, FormattingProvider())
    assert result.status == "ready" and len(result.draft["questions"]) == 1
    assert result.metrics["model_calls"] == (4 if fenced else 5)
    assert sum(t["tool"] == "validate_plan" for t in result.trace) == 1
    assert "PRIVATE" not in json.dumps(result.metrics["conclusion_errors"])


def test_repeated_invalid_conclusions_stop_at_original_round_limit(session_factory):
    class InvalidFinalProvider(PlanningProvider):
        def tool_turn(self, messages, tools, *, timeout):
            response = super().tool_turn(messages, tools, timeout=timeout)
            if self.calls >= 4:
                response["message"]["content"] = "PRIVATE_NOT_JSON"
            return response
    result = run_task(session_factory, task(session_factory).task_id, InvalidFinalProvider())
    assert result.status == "failed" and result.error_code == "invalid_model_response"
    assert result.metrics["model_calls"] == 6 and len(result.metrics["conclusion_errors"]) == 3
    assert result.draft is None and "无需修改学习目标" in result.message
    assert "PRIVATE" not in json.dumps(result.metrics)
