"""Explicitly isolated TEST_FIXTURE data; production flag remains off."""
from copy import deepcopy
from uuid import UUID
import pytest
from sqlalchemy import select
from backend.config import get_settings
from backend.models.learning import PracticeItem, QuestionAttempt, KpState, KpMasteryPolicy, DailyPlan
from backend.services.question_attestation import question_content_sha256
from backend.services.answer_consistency import answer_attestation_result_hash
from tests.integration.test_learning_loop import session_factory,clean_database,client,clock
from tests.integration.test_answer_submissions import item_id,cleanup_answer_records,submit


@pytest.mark.parametrize("independent",[True,False])
def test_enabled_feedback_never_creates_strict_confirmation(client,session_factory,item_id,monkeypatch,independent):
    monkeypatch.setattr(get_settings(),"teaching_practice_enabled",True)
    with session_factory.begin() as db:
        item=db.get(PracticeItem,UUID(item_id)); q=item.question; kp=item.kp_id
        q.stem="Compute 1/2+1/2." if independent else "TEST_FIXTURE: state the limit value for this exercise."
        q.question_provenance="real_exam"; q.content_trust="source_attested"; q.source_status="traceable"
        q.answer_provenance="ai_generated"; q.answer_reliability="ai_generated_consistent"
        q.current_answer_verification=None; q.answer_verification_event_id=None
        q.grading_config={"verified":False,"practice_method":"numeric_final", "provenance":{
            "content_status":"source_transcribed","source":{"source_type":"exam","subject":"math2","year":2020,"question_number":1}}}
        q.source_attestation_key="TEST_FIXTURE_SOURCE"; q.source_attestation_sha256=question_content_sha256(q)
        q.answer_attestation_key="TEST_FIXTURE_ANSWER"; q.answer_attestation_sha256=answer_attestation_result_hash(q)
        # Existing items keep their bound immutable version. Exercise the
        # modified, unverified public content through a fresh practice item.
        plan=DailyPlan(study_date="2026-01-02",status="active")
        db.add(plan);db.flush()
        current_item=PracticeItem(plan_id=plan.id,question_id=q.id,kp_id=kp,ordinal=1)
        db.add(current_item);db.flush()
        current_item_id=str(current_item.id)
        policies={str(p.kp_id):{c.name:deepcopy(getattr(p,c.name)) for c in KpMasteryPolicy.__table__.columns}
                  for p in db.scalars(select(KpMasteryPolicy))}
    response=submit(client,current_item_id,"2",key="test-teaching-b2-submission")
    assert response.status_code==200,response.text
    result=response.json()
    assert result["result"]=="unknown"
    assert result["reason"]=="question_not_practice_eligible"
    assert result["reference_result"] is None
    assert result["effective_confirmation_count"]==0 and result["feedback_notice"] is None
    with session_factory() as db:
        a=db.scalar(select(QuestionAttempt))
        assert a.grading_evidence["evidence_reliability"]=="ungradable"
        assert a.grading_evidence["evidence_capability"]!="verified_objective"
        state=db.get(KpState,kp)
        assert state.evidence_window==[] and state.mastered_at is None
        assert {str(p.kp_id):{c.name:getattr(p,c.name) for c in KpMasteryPolicy.__table__.columns}
                for p in db.scalars(select(KpMasteryPolicy))}==policies
    # Repeated idempotent submission cannot add evidence or attempts.
    assert submit(client,current_item_id,"2",key="test-teaching-b2-submission").json()==result
