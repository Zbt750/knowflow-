"""Immutable question-content snapshots and bound historical reads."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.learning import (
    LearningEvent, PracticeItem, Question, QuestionAttempt, QuestionVersion,
)


VERSION_FIELDS = (
    "kp_id", "question_type", "grading_mode", "grading_config", "stem", "options",
    "correct_answer", "explanation", "question_role", "skill_tags", "estimated_minutes",
    "is_variant", "variant_group", "difficulty", "is_active", "bank_scope", "is_hidden",
    "generation_batch_id", "question_provenance", "content_trust", "source_status",
    "answer_provenance", "answer_reliability", "content_reviewed_by", "content_reviewed_at",
    "answer_reviewed_by", "answer_reviewed_at", "answer_verification_event_id",
    "auto_review_event_id", "source_attestation_key", "source_attestation_sha256",
    "answer_attestation_key", "answer_attestation_sha256",
)

_DEFAULTS = {
    "grading_mode": "self_assessed", "question_role": "basic", "skill_tags": [],
    "estimated_minutes": 5, "is_variant": False, "is_active": True, "difficulty": "basic",
    "bank_scope": "public", "is_hidden": False, "question_provenance": "legacy_unknown",
    "content_trust": "unreviewed", "source_status": "unknown",
    "answer_provenance": "unknown", "answer_reliability": "unknown",
}


def _json_value(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def question_version_snapshot(question) -> dict:
    return {name: _json_value(getattr(question, name, None)
            if getattr(question, name, None) is not None else _DEFAULTS.get(name))
            for name in VERSION_FIELDS}


def version_snapshot_hash(snapshot: dict) -> str:
    raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def question_version_reference(question) -> str | None:
    """Return the immutable version bound to an ORM question or historical proxy."""
    version_id = getattr(question, "version_id", None)
    if version_id is None:
        version_id = getattr(question, "current_version_id", None)
    return str(version_id) if version_id is not None else None


def _version_row(question, *, version_number: int) -> QuestionVersion:
    if question.id is None:
        question.id = uuid4()
    if getattr(question, "bank_scope", None) == "personal":
        try:
            from backend.services.math_verification import verify_question
            structured = (getattr(question, "grading_config", None) or {}).get("structured_math")
            if structured:
                from backend.services.structured_math import verify_structured
                verification = verify_structured(getattr(question, "stem", ""), structured,
                                                 getattr(question, "options", None),
                                                 getattr(question, "correct_answer", None))
            else:
                verification = verify_question(getattr(question, "stem", ""),
                                               getattr(question, "options", None),
                                               getattr(question, "correct_answer", None))
        except Exception:
            verification = {"status": "needs_review", "engine": "sympy", "reason": "verifier_error"}
        # questions.grading_config 是 questions 行列；必须在生成 snapshot 之前写入。
        config = dict(getattr(question, "grading_config", None) or {})
        config["math_verification"] = verification
        question.grading_config = config
        if verification.get("status") == "rejected":
            import logging
            logging.getLogger(__name__).warning(
                "math_verification_rejected stem=%r options=%r answer=%r verification=%r",
                (question.stem or "")[:300], question.options, question.correct_answer, verification)
            raise ValueError("math_verification_rejected")
    snapshot = question_version_snapshot(question)
    values = {name: getattr(question, name, None) for name in VERSION_FIELDS}
    for name, default in _DEFAULTS.items():
        if values.get(name) is None:
            values[name] = default
    values["id"] = uuid4()
    values["question_id"] = question.id
    values["version_number"] = version_number
    values["snapshot_json"] = snapshot
    values["content_hash"] = version_snapshot_hash(snapshot)
    values["review_status"] = "snapshot_only"
    return QuestionVersion(**values)


def ensure_question_versions_for_flush(session: Session) -> None:
    # The version table is append-only both in the database and ORM unit of work.
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, QuestionVersion):
            raise ValueError("question_version_is_immutable")

    for question in list(session.new):
        if not isinstance(question, Question):
            continue
        if question.current_version is not None or question.current_version_id is not None:
            raise ValueError("new_question_version_pointer_is_managed")
        version = _version_row(question, version_number=1)
        question.current_version = version
        # `post_update=True` makes SQLAlchemy insert Question with a NULL
        # pointer, insert its first QuestionVersion, then set the pointer.
        # Writing the FK column here bypasses that cycle-breaking behavior
        # and violates the immediate FK before the version row exists.
        session.add(version)

    for question in list(session.dirty):
        if not isinstance(question, Question) or question in session.new:
            continue
        state = __import__("sqlalchemy").inspect(question)
        changed = any(state.attrs[name].history.has_changes() for name in VERSION_FIELDS)
        if not changed:
            continue
        current_id = question.current_version_id
        current = question.current_version
        if current is None and current_id is not None:
            current = session.get(QuestionVersion, current_id)
        if current is None:
            raise ValueError("question_current_version_missing")
        snapshot = question_version_snapshot(question)
        digest = version_snapshot_hash(snapshot)
        if digest == current.content_hash:
            continue
        max_number = session.scalar(select(QuestionVersion.version_number)
            .where(QuestionVersion.question_id == question.id)
            .order_by(QuestionVersion.version_number.desc()).limit(1)) or current.version_number
        version = _version_row(question, version_number=max_number + 1)
        question.current_version = version
        question.current_version_id = version.id
        session.add(version)

    # Capture the version at the moment an item/attempt/event is created.
    for item in list(session.new):
        if isinstance(item, PracticeItem) and item.question_id is not None and item.question_version_id is None:
            question = item.question or session.get(Question, item.question_id)
            if question is None or question.current_version is None:
                raise ValueError("practice_item_question_version_missing")
            if question.id != item.question_id:
                raise ValueError("practice_item_question_binding_mismatch")
            item.question_version_id = question.current_version.id

    for attempt in list(session.new):
        if isinstance(attempt, QuestionAttempt) and attempt.question_id is not None and attempt.question_version_id is None:
            item = attempt.practice_item or session.get(PracticeItem, attempt.practice_item_id)
            if item is None or item.question_id != attempt.question_id or item.question_version_id is None:
                raise ValueError("attempt_question_version_binding_missing")
            attempt.question_version_id = item.question_version_id

    for event_row in list(session.new):
        if not isinstance(event_row, LearningEvent) or event_row.question_version_id is not None:
            continue
        kind = event_row.event_type
        source_id = event_row.source_id
        if source_id is None:
            continue
        if kind in {"answer_submitted", "practice_self_reported", "question_self_assessed"}:
            attempt = session.get(QuestionAttempt, source_id)
            if attempt is not None:
                event_row.question_version_id = attempt.question_version_id
        elif kind in {"qa_assistance_used", "ai_process_reviewed"}:
            item = session.get(PracticeItem, source_id)
            if item is not None:
                event_row.question_version_id = item.question_version_id
            else:
                question = session.get(Question, source_id)
                if question is not None:
                    event_row.question_version_id = question.current_version_id


def _proxy_from_version(session: Session, version: QuestionVersion):
    snapshot = dict(version.snapshot_json or {})
    for name in ("kp_id", "generation_batch_id", "answer_verification_event_id", "auto_review_event_id"):
        value = snapshot.get(name)
        if value:
            try:
                snapshot[name] = UUID(str(value))
            except (TypeError, ValueError):
                pass
    for name in ("content_reviewed_at", "answer_reviewed_at"):
        value = snapshot.get(name)
        if value:
            try:
                snapshot[name] = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                pass
    snapshot.update(id=version.question_id, version_id=version.id,
                    version_number=version.version_number, content_hash=version.content_hash)
    proxy = SimpleNamespace(**snapshot)
    proxy.kp = session.get(__import__("backend.models.learning", fromlist=["KnowledgePoint"]).KnowledgePoint,
                           version.kp_id)
    from backend.models.learning import QuestionAnswerVerificationEvent, QuestionAutoReviewEvent
    answer_verification = (session.get(QuestionAnswerVerificationEvent,
        version.answer_verification_event_id) if version.answer_verification_event_id else None)
    # A content snapshot remains immutable, but an explicit answer-verification
    # revocation is a current trust decision and must invalidate receipts bound
    # to that verification event. Do not revive the old stamp merely because a
    # historical QuestionVersion still points to it.
    if answer_verification is not None and session.scalar(select(QuestionAnswerVerificationEvent.id).where(
            QuestionAnswerVerificationEvent.related_event_id == answer_verification.id,
            QuestionAnswerVerificationEvent.event_type == "revoked").limit(1)) is not None:
        answer_verification = None
    proxy.current_answer_verification = answer_verification
    proxy.current_auto_review = (session.get(QuestionAutoReviewEvent,
        version.auto_review_event_id) if version.auto_review_event_id else None)
    return proxy


def question_for_practice_item(session: Session, item: PracticeItem):
    if item.question_id is None:
        return None
    if item.question_version_id is None:
        raise ValueError("practice_item_question_version_missing")
    version = session.get(QuestionVersion, item.question_version_id)
    if version is None or version.question_id != item.question_id:
        raise ValueError("practice_item_question_version_mismatch")
    return _proxy_from_version(session, version)


def question_for_version(session: Session, version_id: UUID):
    """Load one exact immutable question snapshot for assistant explanations."""
    version = session.get(QuestionVersion, version_id)
    if version is None:
        return None
    return _proxy_from_version(session, version)


def question_for_attempt(session: Session, attempt: QuestionAttempt):
    if attempt.question_id is None:
        return None
    if attempt.question_version_id is None:
        raise ValueError("attempt_question_version_missing")
    version = session.get(QuestionVersion, attempt.question_version_id)
    if version is None or version.question_id != attempt.question_id:
        raise ValueError("attempt_question_version_mismatch")
    return _proxy_from_version(session, version)
