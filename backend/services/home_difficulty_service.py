"""整卷难度调整：用真实候选题替换，绝不修改 difficulty 字段。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from backend.errors import AppError
from backend.mastery.rules import SHANGHAI
from backend.models.learning import KnowledgePoint, Question, QuestionVersion
from backend.models.learning_task import LearningTask
from backend.services.home_recommendation_service import (
    _reject_materialized_daily_plan_mutation,
    _serialize_daily_plan_mutation,
    _session,
    _preview_view,
)
from backend.services.learning_task_service import _draft_version
from backend.services.question_eligibility import question_eligibility
from backend.services.question_versions import _json_value, question_version_reference

DIFFICULTY_ORDER = {"basic": 0, "medium": 1, "advanced": 2}
DIFFICULTY_NAME = {0: "basic", 1: "medium", 2: "advanced"}


def _target_difficulty(current: str | None, direction: str) -> str | None:
    level = DIFFICULTY_ORDER.get(current or "")
    if level is None:
        return None
    target = level + (1 if direction == "harder" else -1)
    return DIFFICULTY_NAME.get(target)


def _candidate(db: Session, *, kp_id: UUID, question_type: str | None, target: str,
               excluded: set[str]):
    query = select(Question).where(
        Question.kp_id == kp_id,
        Question.is_active.is_(True),
        Question.is_hidden.is_(False),
        Question.current_version_id.is_not(None),
        Question.difficulty == target,
    )
    if question_type:
        query = query.where(Question.question_type == question_type)
    if excluded:
        query = query.where(Question.id.notin_([UUID(value) for value in excluded]))
    node = db.get(KnowledgePoint, kp_id)
    if node is None:
        return None
    for question in db.scalars(query.order_by(Question.id)):
        version = db.get(QuestionVersion, question.current_version_id)
        if (version is None or not version.is_active or version.question_id != question.id
                or version.kp_id != kp_id):
            continue
        if not question_eligibility(question, node).practice_eligible:
            continue
        return question, version
    return None


def _paper_total(questions: list[dict]) -> int:
    return sum(int(q.get("minutes") or 0) for q in questions)


def adjust_paper_difficulty(
    db: Session,
    *,
    task_id: UUID,
    session_id: UUID,
    direction: str,
    request_key: str,
    now: datetime,
) -> dict:
    """按方向替换真实题目；候选不足或约束冲突时整卷不变。"""
    if direction not in {"harder", "easier"}:
        raise AppError("validation_failed", status_code=422)
    _serialize_daily_plan_mutation(db)
    _reject_materialized_daily_plan_mutation(db, now)
    session = _session(db, session_id)
    row = db.get(LearningTask, task_id, with_for_update=True)
    if row is None or row.session_id != session.id or not (row.context or {}).get("home_recommendation"):
        raise AppError("learning_task_not_found", status_code=404)
    if row.status != "ready" or (row.metrics or {}).get("commit") or not row.draft:
        raise AppError("learning_task_stale_draft", status_code=409)
    context = dict(row.context or {})
    today = now.astimezone(SHANGHAI).date().isoformat()
    try:
        expires_at = datetime.fromisoformat(context["expires_at"])
    except (KeyError, ValueError):
        raise AppError("learning_task_stale_draft", status_code=409) from None
    if context.get("study_date") != today or expires_at <= now:
        raise AppError("learning_task_stale_draft", status_code=409)

    actions = dict(context.get("difficulty_actions") or {})
    if request_key in actions:
        return {**_preview_view(db, row), "difficulty_changes": actions[request_key]["changes"], "replayed": True}

    paper = deepcopy(row.draft)
    old_questions = list(paper.get("questions") or [])
    if not old_questions:
        raise AppError("learning_task_stale_draft", status_code=409)
    used = {str(q["question_id"]) for q in old_questions}
    budget = int(paper.get("budget_minutes") or row.budget_minutes or 0)
    total = _paper_total(old_questions)
    new_questions: list[dict] = []
    changes: list[dict] = []
    for item in old_questions:
        current = item.get("difficulty")
        target = _target_difficulty(current, direction)
        if target is None:
            new_questions.append(item)
            continue
        old_version = db.get(QuestionVersion, UUID(item["question_version_id"]))
        question_type = old_version.question_type if old_version is not None else None
        candidate = _candidate(db, kp_id=UUID(item["kp_id"]), question_type=question_type,
                               target=target, excluded=used)
        if candidate is None:
            new_questions.append(item)
            continue
        question, version = candidate
        node = db.get(KnowledgePoint, question.kp_id)
        minutes = max(1, int(version.estimated_minutes or 1))
        projected = total - int(item.get("minutes") or 0) + minutes
        if budget and projected > budget:
            new_questions.append(item)
            continue
        total = projected
        used.add(str(question.id))
        new_questions.append({
            "question_id": str(question.id),
            "question_version_id": str(version.id),
            "version": question_version_reference(question),
            "kp_id": str(question.kp_id),
            "kp_name": node.name if node else item.get("kp_name"),
            "stem": question.stem,
            "options": question.options,
            "difficulty": question.difficulty,
            "minutes": minutes,
            "reason": f"难度{'提高' if direction == 'harder' else '降低'}：{current}→{question.difficulty}",
            "eligibility": question_eligibility(question, node).public_dict() if node else item.get("eligibility"),
        })
        changes.append({
            "ordinal": len(new_questions),
            "old_question_id": item["question_id"],
            "old_question_version_id": item["question_version_id"],
            "old_difficulty": current,
            "new_question_id": str(question.id),
            "new_question_version_id": str(version.id),
            "new_difficulty": question.difficulty,
        })
    if not changes:
        raise AppError("home_difficulty_candidates_insufficient", status_code=409)

    # 硬约束：题量、知识点覆盖、无重复、版本配对、预算。
    if len(new_questions) != len(old_questions):
        raise AppError("home_difficulty_constraint_failed", status_code=409)
    if len({q["question_id"] for q in new_questions}) != len(new_questions):
        raise AppError("home_difficulty_duplicate_question", status_code=409)
    if {q["kp_id"] for q in new_questions} != {q["kp_id"] for q in old_questions}:
        raise AppError("home_difficulty_kp_coverage_changed", status_code=409)
    if budget and _paper_total(new_questions) > budget:
        raise AppError("home_difficulty_budget_exceeded", status_code=409)

    paper["questions"] = new_questions
    paper["total_minutes"] = _paper_total(new_questions)
    paper["candidate_question_ids"] = [q["question_id"] for q in new_questions]
    paper["allocation_kp_ids"] = [str(k) for k in (paper.get("allocation_kp_ids") or paper["selected_kp_ids"])]
    undo_stack = list(context.get("home_undo_stack") or [])
    undo_stack.append({"snapshot": _json_value(deepcopy(row.draft)), "difficulty_snapshot": True})
    actions[request_key] = {"changes": changes, "at": now.isoformat()}
    context.update({
        "home_undo_stack": undo_stack[-30:],
        "home_redo_stack": [],
        "difficulty_actions": actions,
        "difficulty_adjusted": True,
    })
    row.draft = _json_value(paper)
    row.context = _json_value(context)
    row.message = (f"已按真实候选题{'提高' if direction == 'harder' else '降低'}难度，替换 {len(changes)} 道题；"
                   f"题量、知识点覆盖与时间预算保持不变。")
    flag_modified(row, "draft")
    flag_modified(row, "context")
    db.flush()
    return {**_preview_view(db, row), "difficulty_changes": changes, "draft_version": _draft_version(row)}
