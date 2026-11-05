"""Independent, persisted personal practice lifecycle.

This service deliberately does not create DailyPlan/PracticeItem/QuestionAttempt or
LearningEvent rows. Training answers are personal observations, not formal mastery
evidence. All question identity is pinned to an immutable QuestionVersion.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.models.chat import ChatSession
from backend.models.learning import KnowledgePoint, Question, QuestionAttempt, QuestionVersion
from backend.models.personal_training import (
    PersonalTraining,
    PersonalTrainingAction,
    PersonalTrainingAttempt,
    PersonalTrainingItem,
)
from backend.services.answer_grading import grade_practice_final_answer, validate_submission_input
from backend.services.question_eligibility import question_eligibility
from backend.services.question_versions import question_for_version


class PersonalTrainingError(ValueError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


MAX_TRAINING_QUESTIONS = 30
MAX_RECENT_ERROR_RECORDS = 200


def _fail(code: str, status: int = 409):
    raise PersonalTrainingError(code, status)


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def _owner(db: Session, owner_session_id: UUID, *, lock: bool = False) -> ChatSession:
    query = select(ChatSession).where(ChatSession.id == owner_session_id)
    if lock:
        query = query.with_for_update()
    session = db.scalar(query)
    if (session is None or session.mode != "builtin" or session.purpose not in {"study", "qa"}
            or session.archived_at is not None):
        _fail("personal_training_session_forbidden", 404)
    return session


def _locked_training(db: Session, training_id: UUID, owner_session_id: UUID) -> PersonalTraining:
    row = db.scalar(select(PersonalTraining).where(
        PersonalTraining.id == training_id,
        PersonalTraining.owner_session_id == owner_session_id,
    ).with_for_update())
    if row is None:
        _fail("personal_training_not_found", 404)
    return row


def _recent_mistakes(
    db: Session, selected_ids: list[UUID], *, owner_session_id: UUID,
) -> tuple[list[UUID], set[UUID], Counter[UUID]]:
    rows = list(db.scalars(select(QuestionAttempt).where(
        QuestionAttempt.objective_result == "wrong",
        *([QuestionAttempt.kp_id.in_(selected_ids)] if selected_ids else []),
    ).order_by(QuestionAttempt.submitted_at.desc().nulls_last(), QuestionAttempt.id.desc())
      .limit(MAX_RECENT_ERROR_RECORDS)))
    personal_rows = list(db.scalars(select(PersonalTrainingAttempt).join(
        PersonalTrainingItem, PersonalTrainingItem.id == PersonalTrainingAttempt.training_item_id
    ).join(PersonalTraining, PersonalTraining.id == PersonalTrainingItem.training_id).where(
        PersonalTraining.owner_session_id == owner_session_id,
        PersonalTrainingAttempt.result == "wrong",
        *([PersonalTrainingAttempt.kp_id.in_(selected_ids)] if selected_ids else []),
    ).order_by(PersonalTrainingAttempt.submitted_at.desc(), PersonalTrainingAttempt.id.desc())
      .limit(MAX_RECENT_ERROR_RECORDS)))
    scored: Counter[UUID] = Counter()
    excluded: set[UUID] = set()
    chronology: list[tuple[datetime, UUID, UUID]] = []
    for attempt in rows:
        if attempt.question_id:
            excluded.add(attempt.question_id)
        if attempt.question_id is not None and attempt.kp_id is not None and attempt.submitted_at is not None:
            chronology.append((attempt.submitted_at, attempt.kp_id, attempt.question_id))
    for attempt in personal_rows:
        excluded.add(attempt.question_id)
        chronology.append((attempt.submitted_at, attempt.kp_id, attempt.question_id))
    chronology.sort(key=lambda row: row[0], reverse=True)
    ordered_kps: list[UUID] = []
    for _, kp_id, _ in chronology:
        scored[kp_id] += 1
        if kp_id not in ordered_kps:
            ordered_kps.append(kp_id)
    return ordered_kps, excluded, scored


def _assessable_nodes(db: Session, ids: list[UUID]) -> dict[UUID, KnowledgePoint]:
    unique = list(dict.fromkeys(ids))
    if not unique:
        _fail("personal_training_knowledge_point_required", 422)
    rows = list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(unique))))
    mapping = {row.id: row for row in rows}
    if len(mapping) != len(unique):
        _fail("knowledge_point_not_found", 404)
    if any(not row.is_active or not row.is_assessable or row.is_reference_only for row in rows):
        _fail("personal_training_node_not_assessable", 422)
    return mapping


def _candidate_rows(
    db: Session,
    *,
    kp_ids: list[UUID],
    difficulty: str,
    question_type: str | None,
    excluded_ids: set[UUID],
) -> list[tuple[Question, QuestionVersion]]:
    nodes = _assessable_nodes(db, kp_ids)
    query = select(Question).where(
        Question.kp_id.in_(list(nodes)),
        Question.is_active.is_(True),
        Question.is_hidden.is_(False),
        Question.current_version_id.is_not(None),
    ).order_by(Question.kp_id, Question.id)
    selected: list[tuple[Question, QuestionVersion]] = []
    for question in db.scalars(query):
        if question.id in excluded_ids:
            continue
        if question_type and question.question_type != question_type:
            continue
        if difficulty != "any" and question.difficulty != difficulty:
            continue
        version = db.get(QuestionVersion, question.current_version_id)
        if version is None or version.question_id != question.id or not version.is_active or version.kp_id != question.kp_id:
            continue
        if question_eligibility(question, nodes[question.kp_id]).practice_eligible:
            from backend.services.question_admission import formal_use_allowed
            if not formal_use_allowed(question, version):
                continue
            selected.append((question, version))
    return selected


def _choose(
    db: Session,
    *,
    kp_ids: list[UUID],
    difficulty: str,
    question_type: str | None,
    selection_basis: str,
    requested_count: int | None,
    target_minutes: int,
    exclude_ids: set[UUID] | None = None,
    owner_session_id: UUID,
) -> tuple[list[tuple[Question, QuestionVersion]], list[UUID], set[UUID]]:
    resolved = list(dict.fromkeys(kp_ids))
    mistake_ids: set[UUID] = set(exclude_ids or ())
    wrong_kps: list[UUID] = []
    if selection_basis == "recent_mistakes":
        wrong_kps, wrong_question_ids, _ = _recent_mistakes(
            db, resolved, owner_session_id=owner_session_id)
        if not resolved:
            resolved = wrong_kps[:8]
        if not resolved:
            _fail("personal_training_recent_mistakes_unavailable", 422)
        if not wrong_kps:
            _fail("personal_training_recent_mistakes_unavailable", 422)
        mistake_ids.update(wrong_question_ids)
        # Order the final tie break by the observed weak-node ranking.
        kp_order = {kp: index for index, kp in enumerate(wrong_kps)}
    else:
        _assessable_nodes(db, resolved)
        kp_order = {kp: index for index, kp in enumerate(resolved)}
    rows = _candidate_rows(db, kp_ids=resolved, difficulty=difficulty,
        question_type=question_type, excluded_ids=mistake_ids)
    rows.sort(key=lambda pair: (
        kp_order.get(pair[0].kp_id, len(kp_order)),
        pair[0].estimated_minutes,
        str(pair[0].id),
    ))
    if requested_count is not None:
        limit = requested_count
    else:
        limit = MAX_TRAINING_QUESTIONS
    picked: list[tuple[Question, QuestionVersion]] = []
    minutes = 0
    for pair in rows:
        if len(picked) >= limit:
            break
        picked.append(pair)
        minutes += max(1, pair[1].estimated_minutes)
        if requested_count is None and minutes >= target_minutes:
            break
    return picked, resolved, mistake_ids


def _item_view(db: Session, item: PersonalTrainingItem) -> dict[str, Any]:
    version = db.get(QuestionVersion, item.question_version_id)
    if version is None or version.question_id != item.question_id:
        _fail("personal_training_question_version_missing", 409)
    snapshot = version.snapshot_json or {}
    latest = db.scalar(select(PersonalTrainingAttempt).where(
        PersonalTrainingAttempt.training_item_id == item.id
    ).order_by(PersonalTrainingAttempt.submitted_at.desc(), PersonalTrainingAttempt.id.desc()).limit(1))
    return {
        "item_id": str(item.id), "ordinal": item.ordinal,
        "question_id": str(item.question_id), "question_version_id": str(item.question_version_id),
        "kp_id": str(item.kp_id), "question_type": version.question_type,
        "difficulty": version.difficulty, "estimated_minutes": version.estimated_minutes,
        "stem": snapshot.get("stem", version.stem), "options": snapshot.get("options", version.options),
        "completed": item.completed_at is not None,
        "draft_answer": item.draft_answer,
        "draft_selected_option": item.draft_selected_option,
        "draft_revision": item.draft_revision,
        "draft_saved_at": item.draft_saved_at.isoformat() if item.draft_saved_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "latest_result": latest.result if latest else None,
    }


def training_view(db: Session, row: PersonalTraining) -> dict[str, Any]:
    items = list(db.scalars(select(PersonalTrainingItem).where(
        PersonalTrainingItem.training_id == row.id
    ).order_by(PersonalTrainingItem.ordinal)))
    minutes = sum((db.get(QuestionVersion, item.question_version_id).estimated_minutes or 0) for item in items)
    completed = sum(item.completed_at is not None for item in items)
    return {
        "training_id": str(row.id), "owner_session_id": str(row.owner_session_id),
        "request_key": row.request_key, "title": row.title, "status": row.status,
        "version": row.version, "knowledge_point_ids": list(row.selected_kp_ids or []),
        "difficulty": row.difficulty, "question_type": row.question_type,
        "selection_basis": row.selection_basis, "requested_count": row.requested_count,
        "target_minutes": row.target_minutes, "actual_minutes": minutes,
        "inventory_shortfall": max(0, (row.requested_count or len(items)) - len(items)),
        "minutes_shortfall": max(0, row.target_minutes - minutes),
        "item_count": len(items), "completed_count": completed,
        "remaining_count": len(items) - completed,
        "progress_percent": round(completed / len(items) * 100) if items else 0,
        "started_at": row.started_at.isoformat(),
        "paused_at": row.paused_at.isoformat() if row.paused_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "adapted_from_training_id": str(row.adapted_from_training_id) if row.adapted_from_training_id else None,
        "context": dict(row.context or {}),
        "items": [_item_view(db, item) for item in items],
    }


def create_training(
    db: Session,
    *,
    owner_session_id: UUID,
    request_key: str,
    title: str,
    kp_ids: list[UUID],
    question_count: int | None,
    target_minutes: int,
    difficulty: str,
    question_type: str | None,
    selection_basis: str,
    now: datetime,
    question_ids: list[UUID] | None = None,
    adapted_from_training_id: UUID | None = None,
    exclude_question_ids: set[UUID] | None = None,
) -> dict[str, Any]:
    payload = {
        "owner_session_id": str(owner_session_id), "title": title, "kp_ids": [str(k) for k in kp_ids],
        "question_count": question_count, "target_minutes": target_minutes,
        "difficulty": difficulty, "question_type": question_type,
        "selection_basis": selection_basis,
        "question_ids": sorted(str(value) for value in (question_ids or [])),
        "adapted_from_training_id": str(adapted_from_training_id) if adapted_from_training_id else None,
        "exclude_question_ids": sorted(str(value) for value in (exclude_question_ids or set())),
    }
    fingerprint = _fingerprint(payload)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"), {"key": "training:create:" + request_key})
    _owner(db, owner_session_id)
    old = db.scalar(select(PersonalTraining).where(PersonalTraining.request_key == request_key).with_for_update())
    if old is not None:
        if old.owner_session_id != owner_session_id or old.input_sha256 != fingerprint:
            _fail("personal_training_idempotency_conflict", 409)
        return training_view(db, old)
    if not 5 <= target_minutes <= 240 or question_count is not None and not 1 <= question_count <= MAX_TRAINING_QUESTIONS:
        _fail("personal_training_request_invalid", 422)
    picked, resolved_kps, excluded = _choose(db, kp_ids=kp_ids, difficulty=difficulty,
        question_type=question_type, selection_basis=selection_basis,
        requested_count=question_count, target_minutes=target_minutes,
        exclude_ids=exclude_question_ids, owner_session_id=owner_session_id)
    if question_ids:
        requested = list(dict.fromkeys(question_ids))
        rows = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(requested)))}
        nodes = {n.id: n for n in db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.id.in_({q.kp_id for q in rows.values()} or {UUID(int=0)})))}
        explicit: list[tuple[Question, QuestionVersion]] = []
        from backend.services.question_admission import formal_use_allowed
        for question_id in requested:
            question = rows.get(question_id)
            version = db.get(QuestionVersion, question.current_version_id) if question else None
            if (question is None or version is None or version.question_id != question.id
                    or not version.is_active or question.is_hidden or not question.is_active):
                _fail("personal_training_question_unavailable", 422)
            if not question_eligibility(question, nodes[question.kp_id]).practice_eligible:
                _fail("personal_training_question_ineligible", 422)
            if not formal_use_allowed(question, version):
                _fail("personal_training_question_needs_review", 422)
            explicit.append((question, version))
        picked = explicit[:question_count or len(explicit)]
        resolved_kps = list(dict.fromkeys([q.kp_id for q, _ in picked])) or resolved_kps
    if not picked:
        _fail("personal_training_questions_unavailable", 409)
    row = PersonalTraining(id=uuid4(), owner_session_id=owner_session_id,
        request_key=request_key, input_sha256=fingerprint, title=title,
        status="active", selected_kp_ids=[str(k) for k in resolved_kps],
        selection_basis=selection_basis, requested_count=question_count,
        target_minutes=target_minutes, difficulty=difficulty, question_type=question_type,
        adapted_from_training_id=adapted_from_training_id, version=1, started_at=now,
        context={"excluded_wrong_question_count": len(excluded), "source": "eligible_question_bank"})
    db.add(row)
    db.flush()
    for ordinal, (question, version) in enumerate(picked, start=1):
        db.add(PersonalTrainingItem(training_id=row.id, ordinal=ordinal,
            question_id=question.id, question_version_id=version.id, kp_id=question.kp_id))
    db.flush()
    return training_view(db, row)


def list_trainings(db: Session, *, owner_session_id: UUID) -> list[dict[str, Any]]:
    _owner(db, owner_session_id)
    rows = list(db.scalars(select(PersonalTraining).where(
        PersonalTraining.owner_session_id == owner_session_id
    ).order_by(PersonalTraining.updated_at.desc(), PersonalTraining.id.desc()).limit(100)))
    return [training_view(db, row) for row in rows]


def read_training(db: Session, *, training_id: UUID, owner_session_id: UUID) -> dict[str, Any]:
    _owner(db, owner_session_id)
    row = db.scalar(select(PersonalTraining).where(
        PersonalTraining.id == training_id,
        PersonalTraining.owner_session_id == owner_session_id,
    ))
    if row is None:
        _fail("personal_training_not_found", 404)
    return training_view(db, row)


def _existing_action(db: Session, request_key: str, *, training_id: UUID, action: str, fingerprint: str):
    old = db.scalar(select(PersonalTrainingAction).where(
        PersonalTrainingAction.request_key == request_key
    ).with_for_update())
    if old is None:
        return None
    if old.training_id != training_id or old.action != action or old.input_sha256 != fingerprint:
        _fail("personal_training_idempotency_conflict", 409)
    return dict(old.result)


def _save_action(db: Session, row: PersonalTraining, *, request_key: str, action: str,
                 payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    result = training_view(db, row)
    db.add(PersonalTrainingAction(training_id=row.id, request_key=request_key, action=action,
        input_sha256=_fingerprint(payload), result=result, created_at=now))
    db.flush()
    return result


def transition_training(
    db: Session,
    *,
    training_id: UUID,
    owner_session_id: UUID,
    request_key: str,
    expected_version: int,
    action: str,
    now: datetime,
) -> dict[str, Any]:
    _owner(db, owner_session_id)
    payload = {"owner_session_id": str(owner_session_id), "expected_version": expected_version}
    fingerprint = _fingerprint(payload)
    replay = _existing_action(db, request_key, training_id=training_id, action=action, fingerprint=fingerprint)
    if replay is not None:
        return replay
    row = _locked_training(db, training_id, owner_session_id)
    # A concurrent identical request may have waited on the row lock while the
    # first request committed its idempotency receipt.
    replay = _existing_action(db, request_key, training_id=training_id, action=action, fingerprint=fingerprint)
    if replay is not None:
        return replay
    if row.version != expected_version:
        _fail("personal_training_version_conflict", 409)
    if action == "increase_difficulty":
        if row.status != "active":
            _fail("personal_training_state_conflict", 409)
        next_level = {"any": "improved", "basic": "improved", "improved": "comprehensive",
            "comprehensive": "comprehensive"}.get(row.difficulty)
        if next_level is None:
            _fail("personal_training_action_invalid", 422)
        if row.difficulty != next_level:
            row.difficulty = next_level
            row.version += 1
            db.flush()
        return _save_action(db, row, request_key=request_key, action=action, payload=payload, now=now)
    transitions = {
        "pause": ("active", "paused"),
        "resume": ("paused", "active"),
        "finish": ({"active", "paused"}, "completed"),
    }
    if action not in transitions:
        _fail("personal_training_action_invalid", 422)
    source, target = transitions[action]
    allowed = source if isinstance(source, set) else {source}
    if row.status == target:
        return _save_action(db, row, request_key=request_key, action=action, payload=payload, now=now)
    if row.status not in allowed:
        _fail("personal_training_state_conflict", 409)
    row.status = target
    row.version += 1
    if action == "pause":
        row.paused_at = now
    elif action == "resume":
        row.paused_at = None
    else:
        row.finished_at = now
    db.flush()
    return _save_action(db, row, request_key=request_key, action=action, payload=payload, now=now)


def append_training_questions(
    db: Session,
    *,
    training_id: UUID,
    owner_session_id: UUID,
    request_key: str,
    expected_version: int,
    question_count: int,
    now: datetime,
    question_refs: list[dict] | None = None,
) -> dict[str, Any]:
    _owner(db, owner_session_id)
    payload = {"owner_session_id": str(owner_session_id), "expected_version": expected_version,
        "question_count": question_count}
    fingerprint = _fingerprint(payload)
    replay = _existing_action(db, request_key, training_id=training_id, action="append", fingerprint=fingerprint)
    if replay is not None:
        return replay
    row = _locked_training(db, training_id, owner_session_id)
    replay = _existing_action(db, request_key, training_id=training_id, action="append", fingerprint=fingerprint)
    if replay is not None:
        return replay
    if row.version != expected_version:
        _fail("personal_training_version_conflict", 409)
    if row.status != "active":
        _fail("personal_training_state_conflict", 409)
    if not 1 <= question_count <= MAX_TRAINING_QUESTIONS:
        _fail("personal_training_request_invalid", 422)
    items = list(db.scalars(select(PersonalTrainingItem).where(
        PersonalTrainingItem.training_id == row.id
    ).order_by(PersonalTrainingItem.ordinal)))
    existing_ids = {item.question_id for item in items}
    if len(existing_ids) + question_count > MAX_TRAINING_QUESTIONS:
        _fail("personal_training_question_limit", 422)
    added_count = skipped_count = rejected_count = 0
    picked = []
    if question_refs:
        from backend.models.learning import KnowledgePoint, Question, QuestionVersion
        from backend.services.question_eligibility import question_eligibility
        from backend.services.question_versions import question_version_reference
        for ref in question_refs:
            try:
                question = db.get(Question, UUID(str(ref["question_id"])))
                version = db.get(QuestionVersion, UUID(str(ref.get("question_version") or ref.get("question_version_id"))))
            except (KeyError, TypeError, ValueError):
                rejected_count += 1
                continue
            if not question or not version or version.question_id != question.id:
                rejected_count += 1
                continue
            if question.id in existing_ids:
                skipped_count += 1
                continue
            if question_version_reference(question) != str(version.id):
                rejected_count += 1
                continue
            node = db.get(KnowledgePoint, question.kp_id)
            assessment = question_eligibility(question, node) if node else None
            from backend.services.question_admission import formal_use_allowed
            if (not assessment or not assessment.practice_eligible
                    or not formal_use_allowed(question)):
                rejected_count += 1
                continue
            picked.append((question, version))
            existing_ids.add(question.id)
            added_count += 1
        if not picked:
            view = read_training(db, training_id=row.id, owner_session_id=owner_session_id)
            view.update({"added_count": 0, "skipped_duplicate_count": skipped_count,
                         "rejected_count": rejected_count,
                         "final_item_count": view.get("item_count")})
            return view
    else:
        kp_ids = [UUID(value) for value in (row.selected_kp_ids or [])]
        picked, _, _ = _choose(db, kp_ids=kp_ids, difficulty=row.difficulty,
            question_type=row.question_type, selection_basis=row.selection_basis,
            requested_count=question_count, target_minutes=row.target_minutes,
            exclude_ids=existing_ids, owner_session_id=owner_session_id)
        added_count = len(picked)
    if not picked:
        _fail("personal_training_questions_unavailable", 409)
    next_ordinal = max((item.ordinal for item in items), default=0) + 1
    for ordinal, (question, version) in enumerate(picked, start=next_ordinal):
        db.add(PersonalTrainingItem(training_id=row.id, ordinal=ordinal,
            question_id=question.id, question_version_id=version.id, kp_id=question.kp_id))
    if row.requested_count is not None:
        row.requested_count += len(picked)
    row.version += 1
    db.flush()
    result = _save_action(db, row, request_key=request_key, action="append", payload=payload, now=now)
    if isinstance(result, dict):
        result.update({"added_count": added_count, "skipped_duplicate_count": skipped_count,
                       "rejected_count": rejected_count,
                       "final_item_count": result.get("item_count")})
    return result


def submit_training_answer(
    db: Session,
    *,
    training_id: UUID,
    item_id: UUID,
    owner_session_id: UUID,
    idempotency_key: str,
    expected_version: int,
    raw_answer: str | None,
    selected_option: str | None,
    now: datetime,
) -> dict[str, Any]:
    _owner(db, owner_session_id)
    normalized = raw_answer.strip() if raw_answer and raw_answer.strip() else None
    payload = {"training_id": str(training_id), "item_id": str(item_id),
        "owner_session_id": str(owner_session_id), "expected_version": expected_version,
        "raw_answer": normalized, "selected_option": selected_option}
    fingerprint = _fingerprint(payload)
    old = db.scalar(select(PersonalTrainingAttempt).where(
        PersonalTrainingAttempt.idempotency_key == idempotency_key).with_for_update())
    if old is not None:
        if old.training_item_id != item_id or old.grading_evidence.get("input_sha256") != fingerprint:
            _fail("personal_training_idempotency_conflict", 409)
        return read_training(db, training_id=training_id, owner_session_id=owner_session_id)
    row = _locked_training(db, training_id, owner_session_id)
    old = db.scalar(select(PersonalTrainingAttempt).where(
        PersonalTrainingAttempt.idempotency_key == idempotency_key).with_for_update())
    if old is not None:
        if old.training_item_id != item_id or old.grading_evidence.get("input_sha256") != fingerprint:
            _fail("personal_training_idempotency_conflict", 409)
        return training_view(db, row)
    if row.version != expected_version:
        _fail("personal_training_version_conflict", 409)
    if row.status != "active":
        _fail("personal_training_state_conflict", 409)
    item = db.scalar(select(PersonalTrainingItem).where(
        PersonalTrainingItem.id == item_id, PersonalTrainingItem.training_id == row.id
    ).with_for_update())
    if item is None:
        _fail("personal_training_item_not_found", 404)
    if item.completed_at is not None:
        _fail("personal_training_item_already_answered", 409)
    version = db.get(QuestionVersion, item.question_version_id)
    if version is None or version.question_id != item.question_id:
        _fail("personal_training_question_version_missing", 409)
    question = question_for_version(db, version.id)
    node = db.get(KnowledgePoint, item.kp_id)
    if question is None or node is None or not question_eligibility(question, node).practice_eligible:
        _fail("personal_training_question_no_longer_eligible", 409)
    validate_submission_input(question_type=version.question_type, selected_option=selected_option,
        options=version.options if isinstance(version.options, dict) else None)
    if version.question_type != "single_choice" and selected_option is not None:
        _fail("personal_training_answer_format_invalid", 422)
    if version.question_type != "single_choice" and normalized is None:
        _fail("personal_training_answer_required", 422)
    verdict = grade_practice_final_answer(
        question_type=version.question_type, config=version.grading_config,
        answer=normalized, selected_option=selected_option, expected=version.correct_answer,
        options=version.options if isinstance(version.options, dict) else None,
        answer_provenance=version.answer_provenance, content_trust=version.content_trust,
        answer_reliability=version.answer_reliability)
    db.add(PersonalTrainingAttempt(
        training_item_id=item.id, idempotency_key=idempotency_key,
        question_id=item.question_id, question_version_id=item.question_version_id,
        kp_id=item.kp_id, raw_answer=normalized, selected_option=selected_option,
        result=verdict.result, reason=verdict.reason, method=verdict.method,
        grading_evidence={"input_sha256": fingerprint, "scope": "personal_training_only"},
        submitted_at=now))
    item.completed_at = now
    item.draft_answer = None
    item.draft_selected_option = None
    item.draft_saved_at = None
    item.draft_revision += 1
    row.version += 1
    db.flush()
    return training_view(db, row)


def save_training_draft(
    db: Session,
    *,
    training_id: UUID,
    item_id: UUID,
    owner_session_id: UUID,
    expected_draft_revision: int,
    draft_answer: str | None,
    draft_selected_option: str | None,
    now: datetime,
) -> dict[str, Any]:
    """Persist editable input without creating a submitted attempt or mastery evidence."""
    _owner(db, owner_session_id)
    row = _locked_training(db, training_id, owner_session_id)
    if row.status != "active":
        _fail("personal_training_state_conflict", 409)
    item = db.scalar(select(PersonalTrainingItem).where(
        PersonalTrainingItem.id == item_id,
        PersonalTrainingItem.training_id == row.id,
    ).with_for_update())
    if item is None:
        _fail("personal_training_item_not_found", 404)
    if item.completed_at is not None:
        _fail("personal_training_item_already_answered", 409)
    if item.draft_revision != expected_draft_revision:
        _fail("personal_training_draft_revision_conflict", 409)
    answer = draft_answer.strip() if draft_answer and draft_answer.strip() else None
    option = draft_selected_option.strip() if draft_selected_option and draft_selected_option.strip() else None
    if answer is not None and option is not None:
        _fail("personal_training_answer_format_invalid", 422)
    item.draft_answer = answer
    item.draft_selected_option = option
    item.draft_revision += 1
    item.draft_saved_at = now if answer is not None or option is not None else None
    db.flush()
    return training_view(db, row)


def _personal_question_bindings(db: Session, *, question_ids: list[UUID], batch_id: UUID,
                                 allowed_kp_ids: set[UUID]) -> list[tuple[Question, QuestionVersion]]:
    if not question_ids or len(question_ids) != len(set(question_ids)):
        _fail("personal_training_generated_question_invalid", 409)
    output: list[tuple[Question, QuestionVersion]] = []
    for question_id in question_ids:
        question = db.get(Question, question_id)
        version = db.get(QuestionVersion, question.current_version_id) if question else None
        node = db.get(KnowledgePoint, question.kp_id) if question else None
        if (question is None or version is None or version.question_id != question.id
                or version.id != question.current_version_id or not version.is_active
                or question.bank_scope != "personal" or question.generation_batch_id != batch_id
                or question.kp_id not in allowed_kp_ids or version.kp_id != question.kp_id
                or node is None or not question_eligibility(question, node).practice_eligible):
            _fail("personal_training_generated_question_invalid", 409)
        output.append((question, version))
    return output


def create_training_from_personal_questions(
    db: Session, *, owner_session_id: UUID, request_key: str, title: str,
    question_ids: list[UUID], generation_batch_id: UUID, now: datetime,
    target_minutes: int, difficulty: str, question_type: str | None,
    expected_kp_ids: set[UUID],
) -> dict[str, Any]:
    """Bind verified AI personal-bank versions to a separate training object."""
    _owner(db, owner_session_id)
    payload = {"owner_session_id": str(owner_session_id), "question_ids": [str(q) for q in question_ids],
        "generation_batch_id": str(generation_batch_id), "title": title, "target_minutes": target_minutes,
        "difficulty": difficulty, "question_type": question_type}
    fingerprint = _fingerprint(payload)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"), {"key": "training:create-ai:" + request_key})
    old = db.scalar(select(PersonalTraining).where(PersonalTraining.request_key == request_key).with_for_update())
    if old:
        if old.owner_session_id != owner_session_id or old.input_sha256 != fingerprint:
            _fail("personal_training_idempotency_conflict", 409)
        return training_view(db, old)
    if len(question_ids) > MAX_TRAINING_QUESTIONS:
        _fail("personal_training_request_invalid", 422)
    bindings = _personal_question_bindings(db, question_ids=question_ids,
        batch_id=generation_batch_id, allowed_kp_ids=expected_kp_ids)
    if any(question.kp_id not in expected_kp_ids for question, _ in bindings):
        _fail("personal_training_generated_question_invalid", 409)
    minutes = sum(max(1, version.estimated_minutes) for _, version in bindings)
    row = PersonalTraining(id=uuid4(), owner_session_id=owner_session_id, request_key=request_key,
        input_sha256=fingerprint, title=title, status="active",
        selected_kp_ids=[str(kp) for kp in dict.fromkeys(q.kp_id for q, _ in bindings)],
        selection_basis="personal_ai_generation", requested_count=len(bindings),
        target_minutes=max(5, min(240, target_minutes or minutes)), difficulty=difficulty,
        question_type=question_type, version=1, started_at=now,
        context={"source": "personal_ai_generation", "generation_batch_id": str(generation_batch_id)})
    db.add(row); db.flush()
    for ordinal, (question, version) in enumerate(bindings, start=1):
        db.add(PersonalTrainingItem(training_id=row.id, ordinal=ordinal,
            question_id=question.id, question_version_id=version.id, kp_id=question.kp_id))
    db.flush()
    return training_view(db, row)


def append_personal_questions_to_training(
    db: Session, *, training_id: UUID, owner_session_id: UUID, request_key: str,
    expected_version: int, question_ids: list[UUID], generation_batch_id: UUID, now: datetime,
    allowed_kp_ids: set[UUID] | None = None,
) -> dict[str, Any]:
    _owner(db, owner_session_id)
    payload = {"owner_session_id": str(owner_session_id), "expected_version": expected_version,
        "question_ids": [str(q) for q in question_ids], "generation_batch_id": str(generation_batch_id)}
    fingerprint = _fingerprint(payload)
    replay = _existing_action(db, request_key, training_id=training_id, action="ai_append", fingerprint=fingerprint)
    if replay is not None:
        return replay
    row = _locked_training(db, training_id, owner_session_id)
    replay = _existing_action(db, request_key, training_id=training_id, action="ai_append", fingerprint=fingerprint)
    if replay is not None:
        return replay
    if row.version != expected_version:
        _fail("personal_training_version_conflict", 409)
    if row.status != "active":
        _fail("personal_training_state_conflict", 409)
    items = list(db.scalars(select(PersonalTrainingItem).where(
        PersonalTrainingItem.training_id == row.id).order_by(PersonalTrainingItem.ordinal)))
    existing_ids = {item.question_id for item in items}
    if existing_ids.intersection(question_ids):
        _fail("personal_training_generated_question_duplicate", 409)
    if len(existing_ids) + len(question_ids) > MAX_TRAINING_QUESTIONS:
        _fail("personal_training_question_limit", 422)
    existing_kps = {UUID(str(value)) for value in (row.selected_kp_ids or [])}
    requested_kps = set(allowed_kp_ids or existing_kps)
    if not existing_kps.issubset(requested_kps):
        _fail("personal_training_generated_question_invalid", 409)
    # A new, explicitly parsed knowledge point can extend a training. The
    # persisted scope is the union; it is never narrowed by an append.
    authorized_kps = _assessable_nodes(db, list(requested_kps))
    bindings = _personal_question_bindings(db, question_ids=question_ids,
        batch_id=generation_batch_id, allowed_kp_ids=set(authorized_kps))
    row.selected_kp_ids = [str(kp) for kp in dict.fromkeys([
        *[UUID(str(value)) for value in (row.selected_kp_ids or [])],
        *[question.kp_id for question, _ in bindings],
    ])]
    next_ordinal = max((item.ordinal for item in items), default=0) + 1
    for ordinal, (question, version) in enumerate(bindings, start=next_ordinal):
        db.add(PersonalTrainingItem(training_id=row.id, ordinal=ordinal,
            question_id=question.id, question_version_id=version.id, kp_id=question.kp_id))
    if row.requested_count is not None:
        row.requested_count += len(bindings)
    row.context = {**(row.context or {}), "last_generation_batch_id": str(generation_batch_id)}
    row.version += 1
    db.flush()
    return _save_action(db, row, request_key=request_key, action="ai_append", payload=payload, now=now)


def training_report(db: Session, *, training_id: UUID, owner_session_id: UUID) -> dict[str, Any]:
    _owner(db, owner_session_id)
    row = db.scalar(select(PersonalTraining).where(
        PersonalTraining.id == training_id,
        PersonalTraining.owner_session_id == owner_session_id,
    ))
    if row is None:
        _fail("personal_training_not_found", 404)
    attempts = list(db.scalars(select(PersonalTrainingAttempt).join(
        PersonalTrainingItem, PersonalTrainingItem.id == PersonalTrainingAttempt.training_item_id
    ).where(PersonalTrainingItem.training_id == row.id).order_by(
        PersonalTrainingAttempt.submitted_at, PersonalTrainingAttempt.id)))
    by_kp: Counter[UUID] = Counter()
    for attempt in attempts:
        if attempt.result == "wrong":
            by_kp[attempt.kp_id] += 1
    weaknesses = []
    for kp_id, count in by_kp.most_common():
        kp = db.get(KnowledgePoint, kp_id)
        weaknesses.append({"kp_id": str(kp_id), "name": kp.name if kp else "未知知识点", "wrong_count": count})
    counts = Counter(attempt.result for attempt in attempts)
    return {"training_id": str(row.id), "status": row.status,
        "question_count": len(list(row.items)), "submitted_count": len(attempts),
        "right_count": counts["right"], "wrong_count": counts["wrong"],
        "unknown_count": counts["unknown"], "wrong_knowledge_points": weaknesses,
        "next_round_recommendation": ({"knowledge_point_ids": [item["kp_id"] for item in weaknesses[:5]],
            "question_count": min(5, max(1, counts["wrong"]))} if weaknesses else None),
        "evidence_scope": "personal_training_only_not_formal_mastery"}


def create_next_training(
    db: Session,
    *,
    training_id: UUID,
    owner_session_id: UUID,
    request_key: str,
    now: datetime,
    question_count: int | None = None,
    target_minutes: int | None = None,
) -> dict[str, Any]:
    _owner(db, owner_session_id)
    source = _locked_training(db, training_id, owner_session_id)
    if source.status != "completed":
        _fail("personal_training_state_conflict", 409)
    report = training_report(db, training_id=training_id, owner_session_id=owner_session_id)
    recommendation = report.get("next_round_recommendation")
    if recommendation is None:
        _fail("personal_training_no_error_evidence", 409)
    source_chain: list[PersonalTraining] = []
    seen: set[UUID] = set()
    cursor: PersonalTraining | None = source
    while cursor is not None and cursor.id not in seen:
        seen.add(cursor.id)
        source_chain.append(cursor)
        cursor = db.get(PersonalTraining, cursor.adapted_from_training_id) if cursor.adapted_from_training_id else None
    prior_training_ids = [row.id for row in source_chain]
    excluded_question_ids = set(db.scalars(select(PersonalTrainingItem.question_id).where(
        PersonalTrainingItem.training_id.in_(prior_training_ids)
    )))
    return create_training(db, owner_session_id=owner_session_id, request_key=request_key,
        title=f"{source.title}·下一轮", kp_ids=[UUID(k) for k in recommendation["knowledge_point_ids"]],
        question_count=question_count or recommendation["question_count"],
        target_minutes=target_minutes or source.target_minutes, difficulty=source.difficulty,
        question_type=source.question_type, selection_basis="selected", now=now,
        adapted_from_training_id=source.id,
        exclude_question_ids=excluded_question_ids)
