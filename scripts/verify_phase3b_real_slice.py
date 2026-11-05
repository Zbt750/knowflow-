"""Exercise the real Phase 3B question/planner/attempt path and roll it back.

Uses only the approved development Question IDs. No model call is made, no user
history is modified, and all practice/task writes are enclosed in an outer
PostgreSQL transaction that is explicitly rolled back after assertions.
Reports contain identifiers and outcome metadata only, never question text.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import (
    DailyPlan, KpState, KnowledgePoint, LearningEvent, PracticeItem,
    Question, QuestionAttempt,
)
from backend.models.learning_task import LearningTask
from backend.schemas.learning_task import (
    ConfirmTask, CreateTask, FindQuestions, NodeIds,
    QuestionAvailabilityQuery, SearchKnowledge, ValidatePlan,
)
from backend.services.answer_submission_service import record_answer_reveal, submit_answer
from backend.services.learning_task_service import confirm_task, create_task, get_task
from backend.services.learning_task_tools import TaskTools
from backend.services.practice_service import append_questions_to_plan
from backend.services.question_eligibility import question_eligibility

SHANGHAI = ZoneInfo("Asia/Shanghai")
MATH_NODE_CODE = "math.exam.fd2f9e3739d9"
BINARY_TREE_NODE_CODE = "cs408.ds.topic.1efaf3d00b50"
MATH_QUESTION_IDS = (
    "90566e9d-9681-40d0-9168-b2cc1770b5a4",  # Math II 2022 Q05
    "d1691564-0c42-43c0-8ab2-b011fd88ac65",  # Math II 2023 Q06
)
BINARY_TREE_QUESTION_IDS = (
    "e4225412-c705-4439-97b0-593278e28da3",  # 408 2018 Q04
    "6d277fd3-10af-4693-8a53-9f66ddbfb453",  # 408 2019 Q02
)


def _count(db, model) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _state_summary(db, kp_id: UUID) -> dict:
    state = db.get(KpState, kp_id)
    if state is None:
        return {"exists": False, "state": None, "assessment_basis": None,
                "evidence_window_count": 0, "pending_review_count": 0,
                "manual_credit_count": 0}
    return {"exists": True, "state": state.state,
            "assessment_basis": state.assessment_basis,
            "evidence_window_count": len(state.evidence_window or []),
            "pending_review_count": len(state.pending_review_question_ids or []),
            "manual_credit_count": state.manual_credit_count}


def _submit(db, item: PracticeItem, question: Question, *, answer: str | None,
            option: str | None, now: datetime, previous_attempt_id=None) -> dict:
    result = submit_answer(db, item_id=item.id, raw_answer=answer,
        selected_option=option, idempotency_key=str(uuid4()), now=now,
        expected_previous_attempt_id=previous_attempt_id)
    event = db.scalar(select(LearningEvent).where(
        LearningEvent.source_id == result.attempt_id,
        LearningEvent.event_type == "answer_submitted"))
    state_after = _state_summary(db, item.kp_id)
    expected_correct = (question.correct_answer or "").strip().upper()
    selected = (option or answer or "").strip().upper()
    return {"question_id": str(question.id), "practice_item_id": str(item.id),
        "result_vs_ai_reference": result.result,
        "matches_ai_reference": bool(expected_correct and selected == expected_correct),
        "assistance_level": result.assistance_level,
        "sequence_category": result.sequence_category,
        "assessment_basis": result.assessment_basis,
        "evidence_reliability": (event.payload or {}).get("evidence_reliability") if event else None,
        "evidence_level": event.evidence_level if event else None,
        "mastery_reason": result.mastery_reason,
        "state_after": state_after,
        "effective_confirmation_count": result.effective_confirmation_count,
        "attempt_id": str(result.attempt_id)}


def _planner_preview_and_commit(factory, *, now: datetime, goal: str,
                                budget: int, search_terms: list[str],
                                node_codes: list[str],
                                expected_question_ids: list[str]) -> dict:
    task = create_task(factory, CreateTask(goal=goal, budget_minutes=budget), now=now)
    with factory() as db:
        task_row = db.get(LearningTask, task.task_id)
        current_plan = (task_row.context or {}).get("current_plan", {})
        node_by_code = {node.code: node for node in db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.code.in_(node_codes)))}
        if set(node_by_code) != set(node_codes):
            raise AssertionError("golden node missing")
        node_ids = [node_by_code[code].id for code in node_codes]
        questions_by_id = {q.id: q for q in db.scalars(select(Question).where(
            Question.id.in_([UUID(value) for value in expected_question_ids])))}
        if len(questions_by_id) != len(expected_question_ids):
            raise AssertionError("golden question missing")
        if any(not question_eligibility(q, node_by_code[next(
                code for code, node in node_by_code.items() if node.id == q.kp_id)]).practice_eligible
               for q in questions_by_id.values()):
            raise AssertionError("golden question is not Practice Eligible")
        goal_nodes = [{"code": n.code, "name": n.name, "subject": n.subject,
                       "is_reference_only": n.is_reference_only} for n in node_by_code.values()]

    tools = TaskTools(factory, budget_minutes=budget, now=now, goal=goal,
                      current_plan=current_plan)
    with factory() as db:
        search_results = [tools.search_knowledge(db, SearchKnowledge(query=term))
                          for term in search_terms]
        state_result = tools.get_learning_state(db, NodeIds(kp_ids=node_ids))
        availability = tools.get_question_availability(
            db, QuestionAvailabilityQuery(kp_ids=node_ids))
        found = tools.find_questions(db, FindQuestions(kp_ids=node_ids))
        found_ids = [UUID(item["question_id"]) for item in found["questions"]]
        expected_ids = [UUID(value) for value in expected_question_ids]
        if set(found_ids) != set(expected_ids):
            raise AssertionError("live find_questions inventory differs from approved golden IDs")
        validation = tools.validate_plan(db, ValidatePlan(
            question_ids=expected_ids, review_kp_ids=[], review_minutes=0,
            rationale="Phase 3B real inventory preview; no user-facing rationale."))
    if not validation.get("valid") or not tools.draft:
        raise AssertionError(f"real planner validation failed: {validation.get('errors')}")

    with factory.begin() as db:
        task_row = db.get(LearningTask, task.task_id)
        task_row.status = "ready"
        task_row.draft = tools.draft
        task_row.message = "Phase 3B isolated transactional preview"
        task_row.metrics = {**(task_row.metrics or {}), "intent": "plan",
                            "phase3b_local_real_inventory_preview": True}
    ready = get_task(factory, task.task_id)
    first = confirm_task(factory, task.task_id,
        ConfirmTask(draft_version=ready.draft_version), now=now)
    second = confirm_task(factory, task.task_id,
        ConfirmTask(draft_version=ready.draft_version), now=now)
    if first.metrics["commit"] != second.metrics["commit"]:
        raise AssertionError("idempotent second confirmation changed commit receipt")
    return {"task_id": str(task.task_id), "goal_scope": goal_nodes,
        "search_hits": [len(item.get("nodes", [])) for item in search_results],
        "learning_state_nodes_read": len(state_result.get("states", [])),
        "availability_active_questions": availability["active_question_count"],
        "availability_practice_eligible": availability["practice_eligible_count"],
        "find_questions_eligible": found["practice_eligible_count"],
        "preview_valid": validation["valid"],
        "preview_question_ids": [str(value) for value in expected_ids],
        "first_confirm_added_count": first.metrics["commit"]["added_count"],
        "second_confirm_idempotent": second.metrics["commit"] == first.metrics["commit"],
        "plan_id": first.metrics["commit"]["plan_id"],
        "draft_version_present": bool(ready.draft_version)}


def run() -> dict:
    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    if (url.database or "").lower().endswith("_test") or (url.database or "").lower() == "test":
        raise ValueError("refuse to run Phase 3B real slice against a test database")
    engine = create_db_engine(str(settings.active_database_url))
    normal_factory = create_session_factory(engine)
    base_date = date(2099, 1, 1)
    with normal_factory() as db:
        occupied_dates = set(db.scalars(select(DailyPlan.study_date)))
        while base_date.isoformat() in occupied_dates or (base_date + timedelta(days=1)).isoformat() in occupied_dates:
            base_date += timedelta(days=2)
        math_node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == MATH_NODE_CODE))
        binary_node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == BINARY_TREE_NODE_CODE))
        if math_node is None or binary_node is None:
            raise ValueError("Phase 3B golden node missing")
        math_node_id, math_node_code = math_node.id, math_node.code
        math_node_name, math_subject = math_node.name, math_node.subject
        binary_node_id, binary_node_code = binary_node.id, binary_node.code
        binary_node_name, binary_subject = binary_node.name, binary_node.subject
        math_qs = {str(q.id): q for q in db.scalars(select(Question).where(
            Question.id.in_([UUID(value) for value in MATH_QUESTION_IDS])))}
        binary_qs = {str(q.id): q for q in db.scalars(select(Question).where(
            Question.id.in_([UUID(value) for value in BINARY_TREE_QUESTION_IDS])))}
        if set(math_qs) != set(MATH_QUESTION_IDS) or set(binary_qs) != set(BINARY_TREE_QUESTION_IDS):
            raise ValueError("Phase 3B golden questions missing")
        golden = {"math2": {"node_code": math_node_code, "node_name": math_node_name,
                            "subject": math_subject, "question_ids": list(MATH_QUESTION_IDS)},
                  "408": {"node_code": binary_node_code, "node_name": binary_node_name,
                          "subject": binary_subject, "question_ids": list(BINARY_TREE_QUESTION_IDS)}}

    now = datetime.combine(base_date, time(12, 0), tzinfo=SHANGHAI).astimezone(timezone.utc)
    connection = engine.connect()
    outer = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, autoflush=False,
                           join_transaction_mode="create_savepoint")
    report = {"schema_version": "phase3b-real-slice-transactional-v1",
        "database": url.database, "model_calls": 0, "business_writes_committed": False,
        "transactional_date": base_date.isoformat(), "golden": golden,
        "planner": {}, "attempts": [], "rollback_verification": {}}
    task_ids: list[str] = []
    item_ids: list[str] = []
    attempt_ids: list[str] = []
    plan_dates = [base_date.isoformat(), (base_date + timedelta(days=1)).isoformat()]
    try:
        # Evidence-pool shortage remains distinct from this temporary learner journey.
        math_probe_goal = f"请恰好3道积分题，范围 {math_node_name} {math_node_code}"
        probe = TaskTools(factory, budget_minutes=60, now=now, goal=math_probe_goal)
        with factory() as db:
            probe.search_knowledge(db, SearchKnowledge(query=math_node_name))
            probe.get_learning_state(db, NodeIds(kp_ids=[math_node_id]))
            math_availability = probe.get_question_availability(db,
                QuestionAvailabilityQuery(kp_ids=[math_node_id]))
            math_found = probe.find_questions(db, FindQuestions(kp_ids=[math_node_id]))
            rejected = probe.validate_plan(db, ValidatePlan(
                question_ids=[UUID(row["question_id"]) for row in math_found["questions"]],
                review_kp_ids=[], review_minutes=0, rationale="check exact-count insufficiency"))
        report["planner"]["math_three_when_two_exist"] = {
            "required_count": 3, "availability_count": math_availability["practice_eligible_count"],
            "find_count": math_found["practice_eligible_count"],
            "validation_rejected": rejected.get("valid") is False,
            "rejection_codes": rejected.get("errors", []),
            "no_plan_written": True}

        math_plan = _planner_preview_and_commit(factory, now=now,
            goal=f"请恰好2道积分题，范围 {math_node_name} {math_node_code}",
            budget=60, search_terms=[math_node_name], node_codes=[math_node_code],
            expected_question_ids=list(MATH_QUESTION_IDS))
        task_ids.append(math_plan["task_id"])
        report["planner"]["math_exact_two"] = math_plan

        binary_plan = _planner_preview_and_commit(factory, now=now,
            goal=f"请恰好2道二叉树题，范围 {binary_node_name} {binary_node_code}",
            budget=60, search_terms=[binary_node_name], node_codes=[binary_node_code],
            expected_question_ids=list(BINARY_TREE_QUESTION_IDS))
        task_ids.append(binary_plan["task_id"])
        report["planner"]["408_binary_tree_exact_two"] = binary_plan

        # Create an isolated fresh state only if the real node has never been projected.
        with factory.begin() as db:
            for kp_id in (math_node_id, binary_node_id):
                if db.get(KpState, kp_id) is None:
                    db.add(KpState(kp_id=kp_id))
            db.flush()
            before_states = {str(kp_id): _state_summary(db, kp_id)
                             for kp_id in (math_node_id, binary_node_id)}
            items = {str(item.question_id): item for item in db.scalars(select(PracticeItem)
                .where(PracticeItem.plan_id.in_([UUID(math_plan["plan_id"]), UUID(binary_plan["plan_id"])])))
                if item.question_id}
            wanted = set(MATH_QUESTION_IDS) | set(BINARY_TREE_QUESTION_IDS)
            items = {qid: item for qid, item in items.items() if qid in wanted}
            if set(items) != wanted:
                raise AssertionError("confirmed real IDs not present in temporary practice plan")
            item_ids.extend(str(item.id) for item in items.values())

            math1 = math_qs[MATH_QUESTION_IDS[0]]
            wrong_option = next(key for key in math1.options if key.upper() != math1.correct_answer.strip().upper())
            first = _submit(db, items[MATH_QUESTION_IDS[0]], math1, answer=None,
                option=wrong_option, now=now + timedelta(minutes=1))
            attempt_ids.append(first.pop("attempt_id"))
            correction = _submit(db, items[MATH_QUESTION_IDS[0]], math1, answer=None,
                option=math1.correct_answer, now=now + timedelta(minutes=2),
                previous_attempt_id=UUID(attempt_ids[-1]))
            attempt_ids.append(correction.pop("attempt_id"))
            report["attempts"].extend([{"scenario": "AI-answer comparison wrong; no learner-failure promotion", **first},
                                       {"scenario": "same-item correction", **correction}])

            math2 = math_qs[MATH_QUESTION_IDS[1]]
            record_answer_reveal(db, item_id=items[MATH_QUESTION_IDS[1]].id,
                                 now=now + timedelta(minutes=3))
            assisted = _submit(db, items[MATH_QUESTION_IDS[1]], math2, answer=None,
                option=math2.correct_answer, now=now + timedelta(minutes=4))
            attempt_ids.append(assisted.pop("attempt_id"))
            report["attempts"].append({"scenario": "solution-viewed then submitted", **assisted})

            binary1 = binary_qs[BINARY_TREE_QUESTION_IDS[0]]
            independent = _submit(db, items[BINARY_TREE_QUESTION_IDS[0]], binary1,
                answer=None, option=binary1.correct_answer, now=now + timedelta(minutes=5))
            attempt_ids.append(independent.pop("attempt_id"))
            report["attempts"].append({"scenario": "distinct 408 binary-tree question", **independent})

            binary2 = binary_qs[BINARY_TREE_QUESTION_IDS[1]]
            wrong_binary_option = next(key for key in binary2.options
                if key.upper() != binary2.correct_answer.strip().upper())
            wrong_408 = _submit(db, items[BINARY_TREE_QUESTION_IDS[1]], binary2,
                answer=None, option=wrong_binary_option, now=now + timedelta(minutes=6))
            attempt_ids.append(wrong_408.pop("attempt_id"))
            report["attempts"].append({"scenario": "distinct 408 binary-tree wrong answer", **wrong_408})

            # Repeating the same real question in another plan remains non-confirming.
            repeat_plan = DailyPlan(study_date=plan_dates[1], status="active")
            db.add(repeat_plan)
            db.flush()
            append_questions_to_plan(db, plan_id=repeat_plan.id,
                question_ids=[UUID(MATH_QUESTION_IDS[0])])
            db.flush()
            repeated_item = db.scalar(select(PracticeItem).where(
                PracticeItem.plan_id == repeat_plan.id,
                PracticeItem.question_id == UUID(MATH_QUESTION_IDS[0])))
            item_ids.append(str(repeated_item.id))
            repeated = _submit(db, repeated_item, math1, answer=None,
                option=math1.correct_answer, now=now + timedelta(days=1, minutes=1))
            attempt_ids.append(repeated.pop("attempt_id"))
            report["attempts"].append({"scenario": "same question on next study date", **repeated})

            after_states = {str(kp_id): _state_summary(db, kp_id)
                            for kp_id in (math_node_id, binary_node_id)}
            report["knowledge_state"] = {"before": before_states, "after": after_states,
                "changed_by_ai_consistent_attempts": before_states != after_states,
                "expected_policy": "AI-consistent final-answer comparisons record weak evidence and do not advance mastery/graduation."}

        # Capture the transient write counts and ensure all six submitted attempts
        # reached the normal tables before rolling the outer transaction back.
        with factory() as db:
            report["transactional_write_counts"] = {
                "temporary_plans": int(db.scalar(select(func.count()).select_from(DailyPlan)
                    .where(DailyPlan.study_date.in_(plan_dates))) or 0),
                "temporary_items": int(db.scalar(select(func.count()).select_from(PracticeItem)
                    .where(PracticeItem.id.in_([UUID(i) for i in item_ids]))) or 0),
                "temporary_attempts": int(db.scalar(select(func.count()).select_from(QuestionAttempt)
                    .where(QuestionAttempt.id.in_([UUID(i) for i in attempt_ids]))) or 0),
                "temporary_tasks": int(db.scalar(select(func.count()).select_from(LearningTask)
                    .where(LearningTask.id.in_([UUID(i) for i in task_ids]))) or 0),
            }
        if report["transactional_write_counts"]["temporary_attempts"] != len(attempt_ids):
            raise AssertionError("not every real submission reached the transaction")
    finally:
        outer.rollback()
        connection.close()

    with normal_factory() as db:
        report["rollback_verification"] = {
            "temporary_plans_remaining": int(db.scalar(select(func.count()).select_from(DailyPlan)
                .where(DailyPlan.study_date.in_(plan_dates))) or 0),
            "temporary_items_remaining": int(db.scalar(select(func.count()).select_from(PracticeItem)
                .where(PracticeItem.id.in_([UUID(i) for i in item_ids]))) or 0),
            "temporary_attempts_remaining": int(db.scalar(select(func.count()).select_from(QuestionAttempt)
                .where(QuestionAttempt.id.in_([UUID(i) for i in attempt_ids]))) or 0),
            "temporary_tasks_remaining": int(db.scalar(select(func.count()).select_from(LearningTask)
                .where(LearningTask.id.in_([UUID(i) for i in task_ids]))) or 0),
        }
    report["rollback_verification"]["passed"] = all(value == 0 for key, value in report["rollback_verification"].items()
        if key.endswith("_remaining"))
    report["business_writes_committed"] = not report["rollback_verification"]["passed"]
    engine.dispose()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
        default=ROOT / "tmp" / "phase3b_20261006" / "real-slice-transactional.json")
    args = parser.parse_args()
    output = args.output.resolve()
    if not any(output.is_relative_to(ROOT / folder) for folder in ("tmp", "eval/reports")):
        parser.error("report output must stay under tmp/ or eval/reports/")
    if output.exists():
        parser.error("refuse to overwrite an existing report")
    report = run()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"database": report["database"], "model_calls": report["model_calls"],
        "planner": report["planner"], "attempt_scenarios": len(report["attempts"]),
        "rollback_verification": report["rollback_verification"],
        "business_writes_committed": report["business_writes_committed"]}, ensure_ascii=False, indent=2))
    print(f"report={output}")
    return 0 if report["rollback_verification"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
