"""Real PostgreSQL regression; never replace this group with mock persistence."""
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select, func
from tests.integration.test_student_uiv2_repairs import session_factory, clean_database, clean_tasks, conversations, setup, NOW
from backend.models.learning import PracticeItem, QuestionAttempt, LearningEvent
from backend.schemas.paper_adjustment import PaperAdjustmentRequest, PaperAdjustmentConfirmation
from backend.services.paper_adjustment_service import propose_adjustment, confirm_adjustment
from backend.services.practice_activity_service import record_activity
from backend.errors import AppError


@pytest.mark.parametrize('kind',[None,'viewed','started','skipped'])
def test_remove_preserves_item_and_events_and_requires_protection(session_factory,kind):
    sid,ctx,_=setup(session_factory)
    if kind:
        with session_factory.begin() as db:
            record_activity(db,item_id=ctx.practice_item_id,kind=kind,idempotency_key=str(uuid4()),now=NOW)
    request=PaperAdjustmentRequest(session_id=sid,plan_id=ctx.daily_plan_id,
        remove_item_ids=[ctx.practice_item_id],budget_minutes=60)
    if kind in {'started','skipped'}:
        with pytest.raises(AppError):propose_adjustment(session_factory,request,now=NOW)
        return
    proposal=propose_adjustment(session_factory,request,now=NOW)
    confirmation=PaperAdjustmentConfirmation(session_id=sid,draft_version=proposal['draft_version'])
    if kind=='viewed':
        with pytest.raises(AppError):confirm_adjustment(session_factory,UUID(proposal['task_id']),confirmation,now=NOW)
        confirmation.confirm_viewed=True
    receipt=confirm_adjustment(session_factory,UUID(proposal['task_id']),confirmation,now=NOW)
    assert receipt['total_count']==0
    assert confirm_adjustment(session_factory,UUID(proposal['task_id']),confirmation,now=NOW)==receipt
    with session_factory() as db:
        item=db.get(PracticeItem,ctx.practice_item_id)
        assert item is not None and item.removed_at==NOW
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.source_id==item.id,LearningEvent.event_type=='paper_item_removed'))==1
        if kind:
            assert db.scalar(select(func.count()).select_from(LearningEvent).where(
                LearningEvent.source_id==item.id,LearningEvent.event_type=='scheduler_activity'))==1
