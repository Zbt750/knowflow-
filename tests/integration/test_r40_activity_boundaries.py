from uuid import UUID
import pytest
from tests.integration.test_learning_assistant import session_factory, clean_database, conversations, setup, NOW
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_complex_intent_current import protected_rows
from backend.services.paper_adjustment_service import propose_adjustment, confirm_adjustment
from backend.schemas.paper_adjustment import PaperAdjustmentRequest, PaperAdjustmentConfirmation
from backend.services.learning_task_service import create_task
from backend.schemas.learning_task import CreateTask
from backend.errors import AppError
from backend.models.learning import PracticeItem


def test_soft_removing_last_item_does_not_turn_formal_paper_into_a_new_draft(session_factory):
    sid,ctx,_=setup(session_factory)
    proposal=propose_adjustment(session_factory,PaperAdjustmentRequest(
        session_id=sid,plan_id=ctx.daily_plan_id,remove_item_ids=[ctx.practice_item_id],budget_minutes=60),now=NOW)
    receipt=confirm_adjustment(session_factory,UUID(proposal['task_id']),PaperAdjustmentConfirmation(
        session_id=sid,draft_version=proposal['draft_version']),now=NOW)
    assert receipt['total_count']==0
    before=protected_rows(session_factory)
    body=CreateTask(goal='重新生成数学今日卷',budget_minutes=60,session_id=sid,current_plan_id=ctx.daily_plan_id)
    with pytest.raises(AppError) as error:
        create_task(session_factory,body,now=NOW)
    assert error.value.code=='plan_already_generated'
    assert protected_rows(session_factory)==before
    query=create_task(session_factory,body,now=NOW,read_only=True)
    assert query.task_id
    after=protected_rows(session_factory)
    assert {k:v for k,v in after.items() if k!='learning_tasks'}=={
        k:v for k,v in before.items() if k!='learning_tasks'}
    with session_factory() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is not None
