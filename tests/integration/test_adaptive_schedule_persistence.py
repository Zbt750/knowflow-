"""FSRS/BKT receipt projection persists beside, not inside, graduation state."""
from uuid import UUID
from sqlalchemy import select
from backend.models.learning import QuestionAttempt, KpState
from tests.integration.test_learning_loop import session_factory, clean_database
from tests.integration.test_policy_origin_semantics import make_origin_slice, attempt, DAY


def test_verified_attempt_persists_schedule_card_and_separate_skill_state(session_factory, clean_database):
    with session_factory() as db:
        node, _policy, questions = make_origin_slice(db)
        result = attempt(db, node, questions[0], DAY)
        receipt = db.scalar(select(QuestionAttempt).where(QuestionAttempt.id==result.attempt_id))
        adaptive = receipt.grading_evidence['adaptive_schedule']
        assert adaptive['algorithm']=='fsrs6.3.2-bkt-tempered-v2'
        assert adaptive['question']['last_review'] is not None
        assert adaptive['question']['due'] is not None
        assert adaptive['question']['stability'] is not None
        assert adaptive['skill']['right']==1
        assert adaptive['skill']['stage']=='learning'
        assert receipt.grading_evidence['evidence_capability']=='verified_objective'
        # The graduation model remains its own projection and one correct answer
        # still does not graduate the node.
        state=db.get(KpState,node.id)
        assert state.state!='mastered'
        attempt_id=receipt.id
        saved=adaptive
        db.commit()
    with session_factory() as other:
        persisted=other.get(QuestionAttempt,attempt_id)
        assert persisted.grading_evidence['adaptive_schedule']==saved
