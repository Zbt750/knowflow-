"""Real PostgreSQL regression; never replace this group with mock persistence."""
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select, func
from tests.integration.test_student_uiv2_repairs import session_factory, clean_database, clean_tasks, conversations, setup, NOW
from backend.models.learning import PracticeItem, Question, QuestionAttempt, LearningEvent, KpState
from backend.schemas.paper_adjustment import PaperAdjustmentRequest, PaperAdjustmentConfirmation
from backend.services.paper_adjustment_service import propose_adjustment, confirm_adjustment
from backend.services.practice_activity_service import record_activity
from backend.errors import AppError


@pytest.mark.parametrize('kind',[None,'viewed','started','submitted','completed','skipped'])
def test_remove_preserves_item_and_events_and_requires_protection(session_factory,kind):
    sid,ctx,correct=setup(session_factory)
    if kind:
        if kind in {'submitted','completed'}:
            from backend.services.answer_submission_service import submit_answer
            with session_factory.begin() as db:
                submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=correct,
                    idempotency_key='paper-adjustment-completed-protection',now=NOW)
                if kind == 'submitted':
                    # Preserve the attempt while modeling legacy rows that have
                    # the receipt but lack the completion timestamp.
                    db.get(PracticeItem,ctx.practice_item_id).completed_at=None
        else:
            with session_factory.begin() as db:
                record_activity(db,item_id=ctx.practice_item_id,kind=kind,idempotency_key=str(uuid4()),now=NOW)
    request=PaperAdjustmentRequest(session_id=sid,plan_id=ctx.daily_plan_id,
        remove_item_ids=[ctx.practice_item_id],budget_minutes=60)
    if kind in {'started','submitted','completed','skipped'}:
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


def test_soft_removal_preserves_real_graduation_evidence(session_factory):
    """Removing another planned item must leave a real objective receipt intact."""
    from backend.services.answer_submission_service import submit_answer

    sid,ctx,correct=setup(session_factory)
    with session_factory.begin() as db:
        original=db.get(PracticeItem,ctx.practice_item_id)
        candidate=db.scalar(select(Question).where(
            Question.kp_id==original.kp_id,Question.id!=original.question_id,
            Question.question_type=='single_choice',Question.is_active.is_(True)
        ).order_by(Question.id))
        assert candidate is not None
        removable=PracticeItem(plan_id=ctx.daily_plan_id,question_id=candidate.id,
            question_version_id=candidate.current_version_id,kp_id=candidate.kp_id,ordinal=2)
        db.add(removable);db.flush()
        removable_id=removable.id
        submitted=submit_answer(db,item_id=original.id,raw_answer=None,selected_option=correct,
            idempotency_key='paper-adjustment-graduation-evidence',now=NOW)
        assert submitted.result=='right'
        state=db.get(KpState,original.kp_id)
        assert state is not None and state.assessment_basis=='objective_v1'
        assert len(state.evidence_window)==1
        evidence_before=[dict(row) for row in state.evidence_window]
        state_before=(state.state,state.assessment_basis,evidence_before,state.mastered_at,
            list(state.pending_review_question_ids),state.graduation_set_version,
            state.graduation_set_binding_status)
        attempt=db.get(QuestionAttempt,submitted.attempt_id)
        attempt_before=(attempt.id,attempt.practice_item_id,attempt.question_id,
            attempt.question_version_id,dict(attempt.grading_evidence),attempt.objective_result,
            attempt.next_review_at)
        event_before=[(event.id,event.source_id,event.question_version_id,event.event_type,
            event.evidence_level,event.payload,event.idempotency_key)
            for event in db.scalars(select(LearningEvent).where(
                LearningEvent.event_type!='paper_item_removed').order_by(LearningEvent.id))]

    request=PaperAdjustmentRequest(session_id=sid,plan_id=ctx.daily_plan_id,
        remove_item_ids=[removable_id],budget_minutes=60)
    proposal=propose_adjustment(session_factory,request,now=NOW)
    receipt=confirm_adjustment(session_factory,UUID(proposal['task_id']),
        PaperAdjustmentConfirmation(session_id=sid,draft_version=proposal['draft_version']),now=NOW)
    assert receipt['removed_item_ids']==[str(removable_id)]
    with session_factory() as db:
        state=db.get(KpState,ctx.knowledge_node_ids[0])
        assert (state.state,state.assessment_basis,state.evidence_window,state.mastered_at,
            state.pending_review_question_ids,state.graduation_set_version,
            state.graduation_set_binding_status)==state_before
        attempt=db.get(QuestionAttempt,attempt_before[0])
        assert (attempt.id,attempt.practice_item_id,attempt.question_id,attempt.question_version_id,
            attempt.grading_evidence,attempt.objective_result,attempt.next_review_at)==attempt_before
        assert db.get(PracticeItem,removable_id).removed_at==NOW
        assert db.get(Question,ctx.question_id) is not None
        assert db.get(Question,attempt.question_id) is not None
        assert db.get(QuestionAttempt,attempt.id) is not None
        event_after=[(event.id,event.source_id,event.question_version_id,event.event_type,
            event.evidence_level,event.payload,event.idempotency_key)
            for event in db.scalars(select(LearningEvent).where(
                LearningEvent.event_type!='paper_item_removed').order_by(LearningEvent.id))]
        assert event_after==event_before
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.source_id==removable_id,LearningEvent.event_type=='paper_item_removed'))==1
