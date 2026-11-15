"""Real PostgreSQL activity replay; no provider or browser claims."""
from sqlalchemy import select, func
from tests.integration.test_student_uiv2_repairs import session_factory, clean_database, clean_tasks, setup, NOW
from backend.models.learning import QuestionAttempt, KpState, LearningEvent
from backend.services.practice_activity_service import record_activity


def test_skip_with_distinct_request_keys_is_one_fact_and_no_mastery_change(session_factory):
    _sid, ctx, _ = setup(session_factory)
    with session_factory() as db:
        state=db.get(KpState,ctx.knowledge_node_ids[0])
        before={c.name:getattr(state,c.name) for c in KpState.__table__.columns}
        attempts=db.scalar(select(func.count()).select_from(QuestionAttempt))
    with session_factory.begin() as db:
        first=record_activity(db,item_id=ctx.practice_item_id,kind='skipped',idempotency_key='final-skip-first',now=NOW)
        first_id=first.id
    with session_factory.begin() as db:
        second=record_activity(db,item_id=ctx.practice_item_id,kind='skipped',idempotency_key='final-skip-reload',now=NOW)
        assert second.id == first_id
    with session_factory() as db:
        state=db.get(KpState,ctx.knowledge_node_ids[0])
        assert {c.name:getattr(state,c.name) for c in KpState.__table__.columns} == before
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == attempts
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.source_id==ctx.practice_item_id,
            LearningEvent.payload['kind'].as_string()=='skipped')) == 1
