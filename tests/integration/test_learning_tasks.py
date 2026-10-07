import json
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from sqlalchemy import delete, select, func
import pytest

from tests.integration.test_learning_loop import session_factory, clean_database, client, clock, mark_isolated_question_trusted
from backend.models.learning_task import LearningTask
from backend.models.learning import Question, KnowledgePoint, DailyPlan, PracticeItem, QuestionAttempt, LearningEvent, KpState, ExamQuestionReference
from backend.models.chat import ChatSession
from backend.schemas.learning_task import CreateTask, TaskInput
from backend.services.learning_task_service import create_task, run_task, get_task, cancel_task, modify_task
from backend.services.learning_task_tools import TaskTools, classify_task_intent, tool_definitions
from backend.services.question_availability import question_availability
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


def test_confirmation_uses_node_before_question_lock_order(session_factory):
    from sqlalchemy import event
    ready = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    statements = []
    engine = session_factory.kw["bind"]

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        confirm_task(session_factory, ready.task_id, ConfirmTask(draft_version=ready.draft_version))
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    nodes = [i for i, sql in enumerate(statements) if "FROM knowledge_points" in sql]
    questions = [i for i, sql in enumerate(statements) if "FROM questions" in sql]
    assert nodes and questions and min(nodes) < min(questions)
    assert "ORDER BY knowledge_points.code" in statements[min(nodes)]


def test_pending_review_is_prioritized_before_candidate_limit_and_respects_type(session_factory):
    tools, questions = prepared_tools(session_factory)
    kp_id = UUID(questions[0]["kp_id"])
    with session_factory.begin() as db:
        for index in range(20):
            db.add(mark_isolated_question_trusted(Question(kp_id=kp_id, question_type="single_choice", stem=f"隔离短题{index}",
                            correct_answer="A", explanation="隔离解析", estimated_minutes=1,
                            options={"A": "选项甲", "B": "选项乙"},
                            grading_config={"verified": True, "method": "single_choice"})))
        pending = Question(kp_id=kp_id, question_type="calculation", stem="隔离待复测长题",
                           correct_answer="1", explanation="隔离解析", estimated_minutes=60)
        mark_isolated_question_trusted(pending)
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


def test_availability_separates_ai_questions_plan_attempts_references_and_exclusions(session_factory):
    now = datetime(2026, 1, 1, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    with session_factory.begin() as db:
        base = db.scalar(select(Question).where(Question.question_type == "single_choice"))
        node = db.get(KnowledgePoint, base.kp_id)
        ai_question = mark_isolated_question_trusted(Question(kp_id=node.id,
            question_type="single_choice", stem="隔离 AI 答案练习题，选择正确项。",
            options={"A": "甲", "B": "乙"}, correct_answer="A", explanation="隔离 AI 参考解析。",
            grading_config={"verified": False, "practice_method": "single_choice"}))
        ai_question.answer_provenance = "ai_generated"
        ai_question.answer_reliability = "model_generated"
        ai_question.answer_reviewed_by = None
        ai_question.answer_reviewed_at = None
        db.add(ai_question)

        plan = DailyPlan(study_date="2026-01-01", status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=base.id, kp_id=node.id, ordinal=1)
        db.add(item)
        db.flush()
        db.add(QuestionAttempt(practice_item_id=item.id, question_id=base.id, kp_id=node.id,
            objective_result="right", submitted_at=now, idempotency_key="availability-fixture-attempt",
            result_state="unseen", reason_code="synthetic_test"))

        reference_node = KnowledgePoint(code="synthetic.reference-only", subject=node.subject,
            name="隔离仅原卷引用", is_active=True, is_assessable=True, is_reference_only=True)
        db.add(reference_node)
        db.flush()
        db.add(ExamQuestionReference(subject="数学二", year=2024, question_number=1,
            knowledge_point_id=reference_node.id, topic_label="合成引用", source_topic_label="合成来源",
            local_folder="synthetic-only", source_note="隔离测试，不是真题"))
        base_id, ai_id, node_id, reference_node_id, plan_id = base.id, ai_question.id, node.id, reference_node.id, plan.id

    with session_factory() as db:
        inventory = question_availability(db, now=now, kp_ids=[node_id], plan_id=plan_id)
    assert inventory["practice_eligible_count"] >= 2
    assert inventory["already_in_plan_count"] == 1
    assert inventory["available_to_append_count"] == inventory["practice_eligible_count"] - 1
    assert inventory["previously_attempted_count"] == 1
    assert inventory["answer_provenance_counts"]["ai_generated"] == 1
    assert inventory["candidate_count"] is None and inventory["candidate_inventory_status"] == "not_indexed"
    with session_factory() as db:
        without_base = question_availability(db, now=now, kp_ids=[node_id],
            exclude_question_ids=[base_id], plan_id=plan_id)
    assert without_base["active_question_count"] == inventory["active_question_count"] - 1
    assert str(base_id) in without_base["excluded_question_ids"]

    with session_factory() as db:
        references_only = question_availability(db, now=now, kp_ids=[reference_node_id], plan_id=plan_id)
    assert references_only["reference_count"] == 1
    assert references_only["practice_eligible_count"] == 0
    assert references_only["candidate_count"] is None


@pytest.mark.parametrize("goal", [
    "除了洛必达还有哪些章节有题？", "除洛必达外还有哪些章节有题？",
    "洛必达以外还有哪些章节有题？", "除了洛必达之外还有哪些章节有题？",
    "不要洛必达，哪些章节有题？", "不练洛必达，哪些章节有题？",
    "排除洛必达，哪些章节有题？", "避开洛必达，哪些章节有题？",
])
def test_exclusion_query_does_not_reuse_previous_positive_scope(session_factory, goal):
    combined = "上一轮：洛必达给我两道题。\n" + goal
    assert classify_task_intent(combined) == "query"
    tools = TaskTools(session_factory, budget_minutes=30,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc), goal=combined)
    availability = tools.execute("get_question_availability", {})
    assert availability["candidate_count"] is None
    assert availability["excluded_node_ids"]
    assert all(row["code"] != "math.calculus.limit.lhopital" for row in availability["eligible_nodes"])
    assert "validate_plan" not in {item["function"]["name"] for item in tool_definitions("query")}


def test_append_defaults_to_current_plan_and_query_only_never_validates_plan(session_factory):
    with session_factory() as db:
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == "math.calculus.limit.lhopital"))
        node_id = node.id
    tools = TaskTools(session_factory, budget_minutes=30, now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        goal="再补两道题", current_plan={"knowledge_point_ids": [str(node_id)], "unstarted_question_ids": []})
    found = tools.execute("find_questions", {})
    assert found["requested_kp_ids"] == [str(node_id)]
    query_tools = TaskTools(session_factory, budget_minutes=30,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc), goal="哪些章节有题？")
    assert query_tools.intent == "query"
    assert query_tools.execute("validate_plan", {"question_ids": []}) == {"error": "tool_not_allowed"}


def test_modify_intent_is_reported_as_unsupported_not_as_append(session_factory):
    goal = "把没做的难题换简单"
    assert classify_task_intent(goal) == "modify"
    tools = TaskTools(session_factory, budget_minutes=30,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc), goal=goal)
    assert tools.execute("validate_plan", {"question_ids": []}) == {"error": "unsupported_operation"}


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


def task(factory, goal="洛必达比较弱，安排学习", budget=90, *, now=None):
    return create_task(factory, CreateTask(goal=goal, budget_minutes=budget), now=now)


def test_confirmation_appends_to_existing_completed_plan_without_reordering(session_factory):
    with session_factory.begin() as db:
        questions = db.scalars(select(Question).order_by(Question.estimated_minutes.desc(), Question.id.desc())).all()
        other = questions[0]
        plan = DailyPlan(study_date=datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(), status="completed")
        db.add(plan); db.flush(); pid = plan.id
        db.add(PracticeItem(plan_id=pid, question_id=other.id, kp_id=other.kp_id, ordinal=5, latest_self_grade="mastered"))
    ready = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    assert ready.draft["questions"][0]["question_id"] != str(other.id)
    result = confirm_task(session_factory, ready.task_id, ConfirmTask(draft_version=ready.draft_version))
    assert result.metrics["commit"]["plan_id"] == str(pid)
    with session_factory() as db:
        items = db.scalars(select(PracticeItem).where(PracticeItem.plan_id == pid).order_by(PracticeItem.ordinal)).all()
        assert [i.ordinal for i in items] == [5, 6]
        assert items[0].latest_self_grade == "mastered"
        assert db.get(DailyPlan, pid).status == "active"


def test_confirmation_rejects_plan_created_after_preview(session_factory):
    ready = run_task(session_factory, task(session_factory).task_id, PlanningProvider())
    with session_factory.begin() as db:
        question = db.scalar(select(Question))
        plan = DailyPlan(study_date=datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(), status="active")
        db.add(plan); db.flush()
        db.add(PracticeItem(plan_id=plan.id, question_id=question.id, kp_id=question.kp_id, ordinal=1))
    with pytest.raises(AppError) as error:
        confirm_task(session_factory, ready.task_id, ConfirmTask(draft_version=ready.draft_version))
    assert error.value.code == "learning_task_stale_draft"


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
    ready = run_task(session_factory, task(session_factory, now=clock.now).task_id,
        PlanningProvider(), now=clock.now)
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


def test_isolated_seed_questions_have_explicit_synthetic_trust_only_in_test_fixture(session_factory):
    with session_factory() as db:
        questions = db.scalars(select(Question)).all()
    assert questions
    assert all(q.question_provenance == "trusted_practice" and q.content_trust == "verified"
        and q.answer_provenance == "verified_reference" for q in questions), [
            (q.question_provenance, q.content_trust, q.answer_provenance) for q in questions]


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
                                     goal="只做填空题" if case == "wrong_type" else "安排基础题" if case == "wrong_difficulty" else "")
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


def test_recommendation_uses_server_facts_when_plan_has_pending_items_and_no_new_inventory(session_factory):
    from backend.services.learning_task_service import create_task as create_learning_task
    from backend.services.learning_task_service import _daily_plan_snapshot

    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    with session_factory.begin() as db:
        node = db.scalar(select(KnowledgePoint).where(
            KnowledgePoint.code == "math.calculus.limit.lhopital"))
        assert node is not None
        for old in db.scalars(select(Question).where(Question.kp_id == node.id)):
            old.is_active = False
        plan = DailyPlan(study_date="2026-01-01", status="active")
        db.add(plan); db.flush()
        questions = []
        for index in range(6):
            question = Question(kp_id=node.id, question_type="single_choice",
                grading_mode="objective", grading_config={"verified": False, "practice_method": "single_choice"},
                stem=f"隔离 Planner 事实测试第{index + 1}题，选择正确选项。",
                options={"A": "选项甲", "B": "选项乙"}, correct_answer="A",
                explanation="隔离测试解析。", estimated_minutes=4, difficulty="medium")
            mark_isolated_question_trusted(question)
            question.answer_provenance = "ai_generated"
            question.answer_reliability = "ai_generated_consistent"
            question.grading_config = {"verified": False, "practice_method": "single_choice"}
            db.add(question); questions.append(question)
        db.flush()
        items = []
        for index, question in enumerate(questions):
            item = PracticeItem(plan_id=plan.id, question_id=question.id, kp_id=node.id,
                ordinal=index + 1,
                completed_at=now if index < 4 else None)
            db.add(item); items.append(item)
        db.flush()
        attempt_rows = [
            (0, "right", "none", False, 1),
            (1, "wrong", "none", False, 1),
            (1, "right", "hint_1", True, 2),
            (2, "right", "solution", True, 1),
            (3, "wrong", "hint_1", True, 1),
        ]
        for index, (question_index, result, assistance, assisted, number) in enumerate(attempt_rows):
            db.add(QuestionAttempt(practice_item_id=items[question_index].id,
                question_id=questions[question_index].id, kp_id=node.id,
                objective_result=result,
                grading_evidence={"assisted": assisted, "assistance_level": assistance,
                    "attempt_number": number, "evidence_reliability": "ai_consistent_objective",
                    "sequence_category": "ai_consistent_correct_nonconfirming" if result == "right" else "ai_consistent_wrong_nonconfirming"},
                submitted_at=now, idempotency_key=f"planner-facts-attempt-{index}",
                result_state="unseen", reason_code="answer_recorded_only"))
        db.flush()
        plan_id, node_id = str(plan.id), str(node.id)

    class BadNarrativeProvider:
        calls = 0
        def tool_turn(self, messages, tools, *, timeout):
            self.calls += 1
            assert 0 < timeout <= 12
            if self.calls == 1:
                return {"message": {"tool_calls": [
                    {"id": "facts-state", "type": "function", "function": {
                        "name": "get_learning_state", "arguments": json.dumps({"kp_ids": [node_id]})}},
                    {"id": "facts-inventory", "type": "function", "function": {
                        "name": "find_questions", "arguments": json.dumps({"kp_ids": [node_id]})}},
                ]}, "model": "test-facts-model"}
            assert any("AUTHORITATIVE_PLANNER_FACTUAL_SUMMARY" in str(message.get("content"))
                for message in messages)
            return {"message": {"content": json.dumps({
                "message": "正确答案全部来自提示和解析，请重新完成已经做过的二叉树题，共需12分钟。",
                "needs_clarification": True})}, "model": "test-facts-model"}

    created = create_learning_task(session_factory, CreateTask(
        goal="根据我今天实际学习情况，接下来应该练什么？", budget_minutes=90,
        current_plan_id=UUID(plan_id)), now=now)
    with session_factory.begin() as db:
        row = db.get(LearningTask, created.task_id)
        row.context = {**row.context, "planner_handoff": {
            "version": "planner-handoff-v1", "request_type": "recommend",
            "target_knowledge_node_ids": [node_id],
            "constraints": {"scope_origin": "today_evidence_scope"},
        }}
        before_attempts = db.scalar(select(func.count()).select_from(QuestionAttempt))
        before_items = db.scalar(select(func.count()).select_from(PracticeItem))

    provider = BadNarrativeProvider()
    result = run_task(session_factory, created.task_id, provider, now=now)
    summary = result.metrics["planner_factual_summary"]
    assert result.status == "answered"
    assert result.metrics["deterministic_response_override"] == "current_plan_pending_no_additional_inventory"
    assert provider.calls == 2 and result.metrics["model_calls"] == 2
    assert summary["today_plan"]["total_items"] == 6
    assert summary["today_plan"]["completed_items"] == 4
    assert summary["today_plan"]["pending_items"] == 2
    assert summary["today_plan"]["remaining_minutes"] == 8
    assert summary["observations"]["unassisted_correct_observation_count"] == 1
    assert summary["observations"]["hint_assisted_correct_observation_count"] == 1
    assert summary["observations"]["solution_assisted_correct_observation_count"] == 1
    assert summary["observations"]["incorrect_observation_count"] == 2
    assert summary["evidence"]["effective_confirmation_count"] == 0
    assert summary["evidence"]["verified_objective_confirmation_count"] == 0
    assert summary["answer_reliability"]["counts"] == {"ai_generated_consistent": 6}
    assert summary["inventory"]["additional_eligible_count"] == 0
    assert "正确答案全部来自提示和解析" not in result.message
    assert "无辅助答对观察1次" in result.message
    assert "共6题，已完成4题，还有2题待完成，预计还需约8分钟" in result.message
    assert "没有额外可追加的合格在线题（0道）" in result.message
    assert "二叉树" not in result.message
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == before_attempts
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == before_items == 6
        fresh_plan, _ = _daily_plan_snapshot(db, now=now)
        assert fresh_plan["completed_count"] == 4 and fresh_plan["pending_count"] == 2


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
