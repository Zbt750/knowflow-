"""Explicit, hash-bound answer verification; never invokes a language model."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.learning import Question, QuestionAnswerVerificationEvent


class AnswerReferenceMetadata(BaseModel):
    """Narrow reference record; declaring it is still a human assertion."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["official_answer_key", "official_solution", "authoritative_publication"]
    identifier: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    locator: str = Field(min_length=1, max_length=500)
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def answer_version_sha256(question: Question) -> str:
    """Hash the exact answer-bearing item identity, independent of DB identity."""
    content = {
        "question_type": question.question_type,
        "stem": question.stem,
        "options": question.options,
        "kp_id": str(question.kp_id) if question.kp_id else None,
        "correct_answer": question.correct_answer,
    }
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def current_answer_verification(question: Question) -> QuestionAnswerVerificationEvent | None:
    """Return only a matching active stamp; stale/manual legacy fields fail closed."""
    event_id = getattr(question, "answer_verification_event_id", None)
    if event_id is None:
        return None
    try:
        event = question.current_answer_verification
    except Exception:
        # A detached object without an eagerly loaded relationship cannot
        # establish trust; callers must load it through their Session.
        return None
    if event is None or event.id != event_id:
        return None
    try:
        if event.verification_type == "verified_reference":
            AnswerReferenceMetadata.model_validate(event.source_metadata)
        elif event.source_metadata.get("kind") != "human_review":
            return None
    except (AttributeError, ValidationError):
        return None
    if (event.event_type != "verified"
            or event.question_id != question.id
            or event.verification_type != question.answer_provenance
            or event.answer_sha256 != answer_version_sha256(question)
            or question.answer_reliability != "verified"
            or question.answer_reviewed_by != event.verifier
            or question.answer_reviewed_at is None
            or question.answer_reviewed_at != event.created_at):
        return None
    return event


def has_current_answer_verification(question: Question) -> bool:
    return current_answer_verification(question) is not None


def _previous_state(question: Question) -> dict[str, Any]:
    return {
        "answer_provenance": question.answer_provenance,
        "answer_reliability": question.answer_reliability,
        "answer_reviewed_by": question.answer_reviewed_by,
        "answer_reviewed_at": question.answer_reviewed_at.isoformat() if question.answer_reviewed_at else None,
        "answer_verification_event_id": str(question.answer_verification_event_id) if question.answer_verification_event_id else None,
        "grading_mode": question.grading_mode,
        "grading_config": question.grading_config,
    }


def _event_by_key(db: Session, key: str) -> QuestionAnswerVerificationEvent | None:
    return db.scalar(select(QuestionAnswerVerificationEvent).where(
        QuestionAnswerVerificationEvent.idempotency_key == key))


def _same_request(event: QuestionAnswerVerificationEvent, *, question_id: UUID,
                  event_type: str, verification_type: str, answer_sha256: str,
                  verifier: str, method: str, note: str,
                  source_metadata: dict[str, Any], related_event_id: UUID | None) -> bool:
    return (event.question_id == question_id and event.event_type == event_type
        and event.verification_type == verification_type and event.answer_sha256 == answer_sha256
        and event.verifier == verifier and event.verification_method == method and event.note == note
        and event.source_metadata == source_metadata and event.related_event_id == related_event_id)


def verify_answer(db: Session, *, question_id: UUID, verification_type: str,
                  verifier: str, method: str, note: str, idempotency_key: str,
                  expected_answer_sha256: str, source_metadata: dict[str, Any] | None = None,
                  now: datetime | None = None) -> QuestionAnswerVerificationEvent:
    """Append a human-declared verification and bind it to the locked answer.

    This command records who asserted the review; it does not authenticate that
    person or prove the cited source is authoritative.
    """
    if verification_type not in {"human_verified", "verified_reference"}:
        raise ValueError("unsupported_answer_verification_type")
    verifier = verifier.strip() if isinstance(verifier, str) else ""
    method = method.strip() if isinstance(method, str) else ""
    note = note.strip() if isinstance(note, str) else ""
    idempotency_key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
    if not verifier or len(verifier) > 100:
        raise ValueError("answer_verifier_required")
    if not method or len(method) > 120:
        raise ValueError("answer_verification_method_required")
    if len(note) < 5:
        raise ValueError("answer_verification_note_required")
    if not idempotency_key or len(idempotency_key) > 160:
        raise ValueError("answer_verification_idempotency_key_invalid")
    try:
        metadata = (AnswerReferenceMetadata.model_validate(source_metadata).model_dump(mode="json")
            if verification_type == "verified_reference" else
            {"kind": "human_review", **(source_metadata or {})})
    except ValidationError as exc:
        raise ValueError("authoritative_answer_source_required") from exc
    if verification_type == "human_verified" and source_metadata and source_metadata.get("kind") not in {None, "human_review"}:
        raise ValueError("human_verification_source_metadata_invalid")

    # Preserve intentional caller edits before a locked refresh; maintenance
    # workflows may have just changed the exact content being reviewed.
    db.flush()
    question = db.scalar(select(Question).where(Question.id == question_id)
        .with_for_update().execution_options(populate_existing=True))
    if question is None:
        raise ValueError("question_not_found")
    actual_sha = answer_version_sha256(question)
    if expected_answer_sha256 != actual_sha:
        raise ValueError("answer_version_changed")
    replay = _event_by_key(db, idempotency_key)
    if replay is not None:
        if _same_request(replay, question_id=question_id, event_type="verified",
            verification_type=verification_type, answer_sha256=expected_answer_sha256,
            verifier=verifier, method=method, note=note, source_metadata=metadata,
            related_event_id=None):
            return replay
        raise ValueError("answer_verification_idempotency_conflict")
    if not question.correct_answer or not question.correct_answer.strip():
        raise ValueError("answer_missing")
    if question.question_provenance == "ai_generated_practice" and verification_type == "verified_reference":
        raise ValueError("generated_practice_cannot_claim_authoritative_exam_reference")

    event = QuestionAnswerVerificationEvent(
        id=uuid4(), question_id=question.id, event_type="verified",
        verification_type=verification_type, answer_sha256=actual_sha,
        verification_method=method, verifier=verifier, source_metadata=metadata,
        note=note, previous_state=_previous_state(question), idempotency_key=idempotency_key,
        created_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc),
    )
    db.add(event)
    # Break the Question <-> event FK cycle explicitly: persist the immutable
    # event first, then point the mutable Question projection at it.
    db.flush()
    question.answer_provenance = verification_type
    question.answer_reliability = "verified"
    question.answer_reviewed_by = verifier
    question.answer_reviewed_at = event.created_at
    question.current_answer_verification = event
    question.answer_verification_event_id = event.id
    db.flush()
    return event


def revoke_answer_verification(db: Session, *, question_id: UUID,
                               expected_event_id: UUID, verifier: str,
                               method: str, note: str, idempotency_key: str,
                               expected_answer_sha256: str,
                               now: datetime | None = None) -> QuestionAnswerVerificationEvent:
    """Append a revocation; preserve the old event and restore its prior trust."""
    verifier = verifier.strip() if isinstance(verifier, str) else ""
    method = method.strip() if isinstance(method, str) else ""
    note = note.strip() if isinstance(note, str) else ""
    idempotency_key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
    if not verifier or len(verifier) > 100:
        raise ValueError("answer_verifier_required")
    if not method or len(method) > 120:
        raise ValueError("answer_verification_method_required")
    if len(note) < 5:
        raise ValueError("answer_verification_note_required")
    if not idempotency_key or len(idempotency_key) > 160:
        raise ValueError("answer_verification_idempotency_key_invalid")
    db.flush()
    question = db.scalar(select(Question).where(Question.id == question_id)
        .with_for_update().execution_options(populate_existing=True))
    if question is None:
        raise ValueError("question_not_found")
    current_hash = answer_version_sha256(question)
    if current_hash != expected_answer_sha256:
        raise ValueError("answer_version_changed")
    original = db.get(QuestionAnswerVerificationEvent, expected_event_id)
    replay = _event_by_key(db, idempotency_key)
    if replay is not None:
        if (original and _same_request(replay, question_id=question_id,
            event_type="revoked", verification_type=original.verification_type,
            answer_sha256=original.answer_sha256, verifier=verifier, method=method,
            note=note, source_metadata={}, related_event_id=expected_event_id)
            and (replay.previous_state or {}).get("revocation_current_answer_sha256") == current_hash):
            return replay
        raise ValueError("answer_verification_idempotency_conflict")
    if (original is None or original.question_id != question.id or original.event_type != "verified"
            or question.answer_verification_event_id != original.id):
        raise ValueError("answer_verification_not_current")
    event = QuestionAnswerVerificationEvent(
        id=uuid4(), question_id=question.id, event_type="revoked",
        verification_type=original.verification_type, answer_sha256=original.answer_sha256,
        verification_method=method, verifier=verifier, source_metadata={}, note=note,
        previous_state={**_previous_state(question), "revocation_current_answer_sha256": current_hash},
        related_event_id=original.id,
        idempotency_key=idempotency_key,
        created_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc),
    )
    db.add(event)
    db.flush()
    previous = original.previous_state or {}
    question.answer_provenance = previous.get("answer_provenance", "unknown")
    question.answer_reliability = previous.get("answer_reliability", "unknown")
    question.answer_reviewed_by = previous.get("answer_reviewed_by")
    reviewed_at = previous.get("answer_reviewed_at")
    question.answer_reviewed_at = datetime.fromisoformat(reviewed_at) if reviewed_at else None
    prior_id = previous.get("answer_verification_event_id")
    prior = db.get(QuestionAnswerVerificationEvent, UUID(prior_id)) if prior_id else None
    if prior is not None and prior.event_type == "verified" and prior.answer_sha256 == answer_version_sha256(question):
        question.grading_mode = previous.get("grading_mode", question.grading_mode)
        question.grading_config = previous.get("grading_config")
        question.current_answer_verification = prior
        question.answer_verification_event_id = prior.id
    else:
        # A stamp cannot be revoked while leaving its deterministic grader active.
        # Preserve the old configuration in the immutable revoke event, but
        # disable its trusted method until a new answer review is recorded.
        config = previous.get("grading_config")
        question.grading_config = {**(config if isinstance(config, dict) else {}),
            "verified": False, "method": None}
        question.grading_mode = "self_assessed"
        question.current_answer_verification = None
        question.answer_verification_event_id = None
    db.flush()
    return event
