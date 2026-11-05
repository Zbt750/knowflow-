"""Read-only adapter over existing learner attempt facts (single learner DB).

No new truth store, no schema migration, no historical evidence updates.
"""
from sqlalchemy import select
from backend.models.learning import QuestionAttempt, LearningEvent
from backend.services.adaptive_scheduler import Observation, replay


def read_projection(db, now, kp_ids):
    attempts = db.scalars(select(QuestionAttempt).where(
        QuestionAttempt.kp_id.in_(kp_ids), QuestionAttempt.submitted_at <= now,
        QuestionAttempt.question_id.is_not(None),
        QuestionAttempt.question_version_id.is_not(None),
    ).order_by(QuestionAttempt.submitted_at, QuestionAttempt.id)).all()
    observations = []
    for a in attempts:
        evidence = a.grading_evidence or {}
        result = a.objective_result
        rating = None
        if result == 'wrong':
            rating = 'again'
        elif result == 'right':
            rating = 'hard' if evidence.get('confidence') in {'uncertain','guess'} else 'good'
        else:
            rating = {'not_mastered':'again','partial':'hard','mastered':'good'}.get(a.self_grade)
        observations.append(Observation(str(a.id), str(a.question_id),
            str(a.question_version_id), str(a.kp_id), a.submitted_at,
            result if result in {'right','wrong'} else 'unknown',
            reliable=evidence.get('evidence_capability') == 'verified_objective',
            assisted=bool(evidence.get('assisted')) or evidence.get('confidence') == 'guess',
            error_kind=evidence.get('error_kind', 'unclassified'), rating=rating))
    skips = db.scalars(select(LearningEvent).where(LearningEvent.kp_id.in_(kp_ids),
        LearningEvent.event_type=='scheduler_activity',LearningEvent.occurred_at<=now)).all()
    for event in skips:
        payload=event.payload or {}
        if payload.get('kind')=='skipped':
            observations.append(Observation('activity:'+str(event.id),
                payload.get('question_id') or '',str(event.question_version_id or ''),
                str(event.kp_id),event.occurred_at,'skipped',reliable=False))
    return replay(observations, now)
