"""Explicit, idempotent, standalone retry; never rewrite a paper or old attempt."""
from uuid import UUID
from datetime import datetime
from sqlalchemy import select
from backend.models.learning import PracticeItem, PracticeRetryRequest
from backend.services.practice_lock import lock_practice_item
from backend.services.answer_submission_service import item_attempts

def create_retry(db, *, source_id: UUID, key: str, now: datetime):
    source = lock_practice_item(db, source_id)
    request = db.get(PracticeRetryRequest, key)
    if request:
        if request.source_id != source_id: raise ValueError('idempotency_key_conflict')
        return db.get(PracticeItem, request.retry_id)
    previous = db.scalar(select(PracticeItem).where(PracticeItem.retry_key == key))
    if previous:
        if previous.retry_source_id != source_id: raise ValueError('idempotency_key_conflict')
        return previous
    # Historical receipts/keys still replay above; only new nested instances are refused.
    if source.retry_source_id is not None:
        raise ValueError('practice_retry_nested_not_allowed')
    attempts = item_attempts(db, source.id)
    if not attempts or attempts[-1].objective_result != 'wrong' or source.question_id is None:
        raise ValueError('practice_retry_not_available')
    # Serialised by source lock; a lost response or second tab resumes the same pending retry.
    active = db.scalar(select(PracticeItem).where(PracticeItem.retry_source_id == source_id,
        PracticeItem.completed_at.is_(None)))
    if active:
        db.add(PracticeRetryRequest(idempotency_key=key,source_id=source_id,retry_id=active.id))
        db.flush()
        return active
    revealed_at = source.answer_revealed_at
    assisted = bool((attempts[-1].grading_evidence or {}).get('assisted'))
    # A later sibling retry must retain help seen in an earlier retry of this
    # exact original instance, even if the original itself was never revealed.
    family = list(db.scalars(select(PracticeItem).where(PracticeItem.retry_source_id == source_id)))
    for previous_item in family:
        revealed_at = revealed_at or previous_item.answer_revealed_at
        assisted = assisted or any((a.grading_evidence or {}).get('assisted') for a in item_attempts(db, previous_item.id))
    retry = PracticeItem(plan_id=None, retry_source_id=source_id, retry_key=key,
        question_id=source.question_id, question_version_id=source.question_version_id,
        kp_id=source.kp_id, ordinal=source.ordinal,
        # A known answer (or any earlier assistance) must never become fresh independent evidence.
        answer_revealed_at=(revealed_at or now if revealed_at or assisted else None))
    db.add(retry); db.flush()
    db.add(PracticeRetryRequest(idempotency_key=key,source_id=source_id,retry_id=retry.id)); db.flush()
    return retry
