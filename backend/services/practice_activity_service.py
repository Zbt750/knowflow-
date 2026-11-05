"""Append-only activity facts; no QuestionAttempt, mastery or graduation writes."""
from sqlalchemy import select
from backend.models.learning import LearningEvent
from backend.services.practice_lock import lock_practice_item

KINDS = {'viewed', 'started', 'skipped', 'left'}


def record_activity(db, *, item_id, kind, idempotency_key, now):
    if kind not in KINDS or not 8 <= len(idempotency_key) <= 100:
        raise ValueError('invalid_activity_request')
    item = lock_practice_item(db, item_id)
    key = 'activity:' + idempotency_key
    old = db.scalar(select(LearningEvent).where(LearningEvent.idempotency_key==key))
    if old is not None:
        if old.source_id != item.id or (old.payload or {}).get('kind') != kind:
            raise ValueError('idempotency_key_conflict')
        return old
    if item.completed_at is not None and kind in {'started','skipped'}:
        raise ValueError('practice_item_already_assessed')
    row = LearningEvent(kp_id=item.kp_id, source_id=item.id,
        question_version_id=item.question_version_id, event_type='scheduler_activity',
        evidence_level=None, payload={'scheduler_only':True,'kind':kind,
            'question_id':str(item.question_id) if item.question_id else None,
            'plan_id':str(item.plan_id),'changes_mastery':False,'can_graduate':False},
        occurred_at=now,idempotency_key=key)
    db.add(row); db.flush()
    return row
