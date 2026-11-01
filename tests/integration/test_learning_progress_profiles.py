"""Isolated PG only: progress reads must preserve the strict learning chain."""
from copy import deepcopy
from backend.services.learning_task_context import expand_records
from uuid import UUID
from sqlalchemy import select
from backend.models.learning import PracticeItem, QuestionAttempt, Question, KpState, LearningEvent, KpMasteryPolicy, DailyPlan
from backend.services.learning_task_tools import TaskTools
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from tests.integration.test_answer_submissions import cleanup_answer_records, item_id
from tests.integration.test_attempt_sequence import send
from tests.integration.test_learning_tasks import clean_tasks


def progress(client, factory, item):
    with factory() as db:
        kp = db.get(PracticeItem, UUID(item)).kp_id
    response = client.get(f"/api/knowledge/{kp}")
    assert response.status_code == 200
    return response.json()["capability_profile"]["learning_progress"], kp


def test_api_agent_same_progress_without_changing_strict_state(client, session_factory, item_id, clock):
    first = send(client, item_id, "3", "progress-first-wrong").json()
    assert progress(client, session_factory, item_id)[0]["status"] == "NEEDS_CONSOLIDATION"
    rejected = send(client, item_id, "1", "progress-self-correct", first["attempt_id"])
    assert rejected.status_code == 409
    p, kp = progress(client, session_factory, item_id)
    assert p["status"] == "NEEDS_CONSOLIDATION" and p["distinct_question_count"] == 1
    with session_factory() as db:
        state = db.get(KpState, kp)
        before = deepcopy((state.state, state.evidence_window, state.pending_review_question_ids))
        policy = deepcopy(db.get(KpMasteryPolicy, kp).__dict__)
        tools = TaskTools(session_factory, budget_minutes=20, now=clock.now, goal="复测洛必达法则")
        tools.nodes.add(kp)
        result = tools.execute("get_learning_state", {"kp_ids": [str(kp)]})["states"][0]
        assert result["learning_progress"] == p and "稍后" in result["next_step"]
        db.expire_all()
        state = db.get(KpState, kp)
        assert (state.state, state.evidence_window, state.pending_review_question_ids) == before
        assert state.evidence_window == []  # Self-correction did not become graduation credit.
        assert {k:v for k,v in db.get(KpMasteryPolicy, kp).__dict__.items() if k != "_sa_instance_state"} == {k:v for k,v in policy.items() if k != "_sa_instance_state"}


def test_solution_correct_shows_retest_and_never_stable(client, session_factory, item_id):
    client.post(f"/api/practice-items/{item_id}/answer-reveal")
    send(client, item_id, "1", "progress-solution")
    p, _ = progress(client, session_factory, item_id)
    assert p["status"] == "RETEST_RECOMMENDED" and p["assisted_correct_question_count"] == 1


def test_old_wrong_is_observation_not_reclassified_by_current_verified_key(client, session_factory, item_id):
    send(client, item_id, "3", "progress-old-record")
    with session_factory.begin() as db:
        row = db.scalar(select(QuestionAttempt))
        row.grading_evidence = {"version": 3, "method": "exact_numeric_v1"}
    p, _ = progress(client, session_factory, item_id)
    assert p["status"] == "PRACTICING" and p["reliable_wrong_count"] == 0
    assert p["reference_wrong_count"] == 1


def test_no_practice_inventory_is_not_failure(client, session_factory, item_id):
    _, kp = progress(client, session_factory, item_id)
    with session_factory.begin() as db:
        for q in db.scalars(select(Question).where(Question.kp_id == kp)):
            q.is_active = False
    p, _ = progress(client, session_factory, item_id)
    assert p["status"] == "NOT_STARTED" and p["next_action"] == "read_lesson"
    assert "缺少可用练习" in str(p["limitations"])


def test_unknown_does_not_mark_wrong(client, session_factory, item_id):
    send(client, item_id, "sqrt(1)", "progress-unsupported")
    p, _ = progress(client, session_factory, item_id)
    assert p["status"] == "PRACTICING" and p["unknown_count"] == 1
    assert p["reliable_wrong_count"] == p["reference_wrong_count"] == 0


def test_ai_consistency_only_public_question_is_not_admitted_to_new_practice(client, session_factory, item_id):
    from backend.services.question_attestation import question_content_sha256
    from backend.services.answer_consistency import answer_attestation_result_hash
    with session_factory.begin() as db:
        old_item = db.get(PracticeItem, UUID(item_id))
        q = old_item.question
        q.question_provenance = "real_exam"
        q.content_trust = "source_attested"
        q.source_status = "traceable"
        q.answer_provenance = "ai_generated"
        q.answer_reliability = "ai_generated_consistent"
        q.current_answer_verification = None
        q.answer_verification_event_id = None
        q.grading_mode = "self_assessed"
        q.grading_config = {"verified": False, "method": None, "practice_method": "numeric_final",
            "provenance": {"content_status": "source_transcribed", "source": {"source_type": "exam"}}}
        q.source_attestation_key = "SIMULATED_TEST_SOURCE_BINDING"
        q.source_attestation_sha256 = question_content_sha256(q)
        q.answer_attestation_key = "SIMULATED_TEST_ANSWER_BINDING"
        q.answer_attestation_sha256 = answer_attestation_result_hash(q)
        # The existing item stays bound to its prior immutable content/trust
        # snapshot. Use a fresh item to test the newly simulated reference-only
        # version rather than mutating history in place.
        db.flush()
        current_plan = DailyPlan(study_date="2026-01-02", status="active")
        db.add(current_plan)
        db.flush()
        current_item = PracticeItem(plan_id=current_plan.id, question_id=q.id,
            kp_id=q.kp_id, ordinal=1)
        db.add(current_item)
        db.flush()
        current_item_id = str(current_item.id)
    result = send(client, current_item_id, "3", "progress-ai-reference-wrong").json()
    # Public questions require the current formal review path. AI answer
    # consistency by itself cannot make a public question practice-eligible.
    assert result["result"] == "unknown"
    assert result["reason"] == "question_not_practice_eligible"
    assert result["effective_confirmation_count"] == 0
    with session_factory() as db:
        receipt = db.get(QuestionAttempt, UUID(result["attempt_id"])).grading_evidence
        assert receipt["evidence_reliability"] == "ungradable"
        assert receipt["reason"] == "question_not_practice_eligible"
    p, _ = progress(client, session_factory, current_item_id)
    assert p["status"] == "PRACTICING" and p["unknown_count"] == 1
    assert p["reliable_wrong_count"] == p["reference_wrong_count"] == 0


def test_offline_agent_reads_progress_then_proposes_review_and_appends_only_after_confirmation(
        client, session_factory, item_id, clock):
    import json
    from sqlalchemy import func
    from backend.schemas.learning_task import CreateTask
    from backend.services.learning_task_service import create_task, run_task
    first = send(client, item_id, "3", "progress-agent-wrong").json()
    rejected = send(client, item_id, "1", "progress-agent-corrected", first["attempt_id"])
    assert rejected.status_code == 409
    class ProgressProvider:
        """Protocol double driven by real isolated DB tool results, not a live LLM."""
        def __init__(self):
            self.calls, self.nodes, self.questions, self.progress = 0, [], [], None
        def tool_turn(self, messages, tools, *, timeout):
            self.calls += 1
            if self.calls == 1:
                actions = [("search_knowledge", {"query": "洛必达"})]
            elif self.calls == 2:
                self.nodes = [n["kp_id"] for n in expand_records(json.loads(messages[-1]["content"]))["nodes"]]
                actions = [("get_learning_state", {"kp_ids": self.nodes}), ("find_questions", {"kp_ids": self.nodes})]
            elif self.calls == 3:
                values = [expand_records(json.loads(m["content"])) for m in messages if m.get("role") == "tool"]
                states = next(v["states"] for v in values if "states" in v)
                self.progress = states[0]["learning_progress"]
                assert self.progress["status"] == "NEEDS_CONSOLIDATION"
                assert states[0]["effective_confirmation_count"] == 0
                self.questions = [q for q in values[-1]["questions"] if not q["in_today_plan"]]
                actions = [("read_lesson", {"kp_id": self.nodes[0]})]
            elif self.calls == 4:
                actions = [("validate_plan", {"question_ids": [self.questions[0]["question_id"]],
                    "review_kp_ids": [self.nodes[0]], "review_minutes": 5,
                    "rationale": self.progress["next_step"]})]
            else:
                return {"message": {"content": json.dumps({"message": "纠错体现学习过程，建议复习后独立验证；方案等你确认。", "needs_clarification": False})}}
            return {"message": {"tool_calls": [{"id": f"p-{self.calls}-{i}", "type": "function",
                "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(actions)]}}
    created = create_task(session_factory, CreateTask(goal="洛必达的题已经纠错，安排下一次学习", budget_minutes=30), now=clock.now)
    with session_factory() as db:
        before_items = db.scalar(select(func.count()).select_from(PracticeItem))
        before_attempts = db.scalar(select(func.count()).select_from(QuestionAttempt))
    provider = ProgressProvider()
    result = run_task(session_factory, created.task_id, provider, now=clock.now)
    assert result.status == "ready", result.message
    assert result.draft["review_minutes"] == 5
    assert any(t["tool"] == "get_learning_state" for t in result.trace)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == before_items
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == before_attempts
    response = client.post(f"/api/learning-tasks/{created.task_id}/confirm", json={"draft_version": result.draft_version})
    assert response.status_code == 200, response.text
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == before_items + 1
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == before_attempts
