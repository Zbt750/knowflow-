"""Versioned origin evidence and guarded policy changes in kaoyan_test only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from sqlalchemy import func, select, text

from backend.models.learning import (KnowledgePoint, KpMasteryPolicy, KpState, Question,
    QuestionAttempt, PracticeItem, DailyPlan, LearningEvent, ExamQuestionReference)
from backend.mastery.policy import MasteryPolicy, LEGACY_POLICY_FIELDS
from backend.services.answer_submission_service import submit_answer
from backend.services.answer_verification import verify_answer, revoke_answer_verification, answer_version_sha256
from backend.services.policy_evidence_service import current_policy_snapshot
from scripts.migrate_graduation_policy_semantics import plan, apply_conversion, recover_policies, protected_data_comparison
from tests.integration.test_learning_loop import clean_database, session_factory, mark_isolated_question_trusted

DAY = datetime(2026,1,1,2,tzinfo=timezone.utc)


def make_origin_slice(db, *, qtype="single_choice"):
    node=KnowledgePoint(code="synthetic.origin."+uuid4().hex,name="Synthetic origin topic",subject="math2",
        is_active=True,is_assessable=True,is_reference_only=False,ordinal=1)
    db.add(node); db.flush()
    state=KpState(kp_id=node.id); db.add(state)
    policy=KpMasteryPolicy(kp_id=node.id,policy_version=2,required_question_origins={"real_exam":3},
        required_question_types={},min_confirmations=3,min_real_questions=3,
        required_variant_count=0,required_skill_tags=["topic"],min_day_span=2)
    db.add(policy)
    questions=[]
    for i in range(3):
        q=Question(kp_id=node.id,question_type=qtype,stem=f"Synthetic isolated question {i}",
            options={"A":"Synthetic A","B":"Synthetic B"} if qtype=="single_choice" else None,
            correct_answer="A" if qtype=="single_choice" else "Synthetic process answer",
            explanation="Synthetic fixture only",skill_tags=["topic"],
            grading_config={"verified":True,"method":"single_choice"} if qtype=="single_choice" else {"verified":False})
        db.add(q); db.flush(); mark_isolated_question_trusted(q,db=db)
        # A public, non-exam practice item is sufficient when its answer and
        # objective grader are verified; the old real_exam quota is ignored.
        q.question_provenance="trusted_practice"; q.source_status="not_applicable"
        questions.append(q)
    db.flush()
    return node,policy,questions


def attempt(db,node,q,day,*,assisted=False,key=None):
    plan_row=DailyPlan(study_date=day.date().isoformat(),status="active")
    db.add(plan_row); db.flush()
    item=PracticeItem(plan_id=plan_row.id,kp_id=node.id,question_id=q.id,ordinal=1,
        answer_revealed_at=day-timedelta(minutes=1) if assisted else None)
    db.add(item); db.flush()
    return submit_answer(db,item_id=item.id,raw_answer=None,selected_option="A" if q.question_type=="single_choice" else None,
        idempotency_key=key or "synthetic-origin-"+uuid4().hex,now=day)


def test_three_future_verified_non_exam_answers_graduate_without_source_quota(session_factory,clean_database):
    with session_factory() as db:
        node,policy,qs=make_origin_slice(db)
        for i,q in enumerate(qs):
            result=attempt(db,node,q,DAY+timedelta(days=i))
            assert result.result=="right" and result.effective_confirmation_count==i+1
        assert result.state=="mastered"
        receipt=db.scalar(select(QuestionAttempt).where(QuestionAttempt.id==result.attempt_id))
        assert receipt.grading_evidence["policy_version"]==2
        assert receipt.grading_evidence["question_provenance"]=="trusted_practice"
        assert receipt.grading_evidence["answer_version_sha256"]==answer_version_sha256(qs[-1])
        snapshot=current_policy_snapshot(db,db.get(KpState,node.id),MasteryPolicy(policy_version=2,required_question_origins={"real_exam":3}))
        assert len(snapshot.evidence_window)==3
        assert all(e.confirmation_facts["attempt_id"] for e in snapshot.evidence_window)
        db.rollback()


def test_solution_and_ai_consistent_answers_never_grant_origin_confirmations(session_factory,clean_database):
    with session_factory() as db:
        node,policy,qs=make_origin_slice(db)
        result=attempt(db,node,qs[0],DAY,assisted=True)
        assert result.result=="right" and result.effective_confirmation_count==0
        qs[1].answer_provenance="ai_generated"; qs[1].answer_reliability="ai_generated_consistent"
        qs[1].answer_verification_event_id=None; qs[1].current_answer_verification=None
        qs[1].grading_config={"verified":False,"practice_method":"single_choice"}; db.flush()
        result=attempt(db,node,qs[1],DAY+timedelta(days=1))
        assert result.effective_confirmation_count==0
        assert db.get(KpState,node.id).state!="mastered"
        db.rollback()


def test_revocation_and_new_review_do_not_recertify_an_old_receipt_or_write_state(session_factory,clean_database):
    with session_factory() as db:
        node,policy,qs=make_origin_slice(db)
        result=attempt(db,node,qs[0],DAY)
        state=db.get(KpState,node.id); before=deepcopy(state.evidence_window)
        q=qs[0]
        revoke_answer_verification(db,question_id=q.id,expected_event_id=q.answer_verification_event_id,
            expected_answer_sha256=answer_version_sha256(q),verifier="synthetic-test-only",
            method="synthetic withdrawal",note="Isolated test withdrawal, no production review.",
            idempotency_key="synthetic-revoke-"+uuid4().hex)
        p=MasteryPolicy(policy_version=2)
        assert current_policy_snapshot(db,state,p).evidence_window==()
        assert state.evidence_window==before
        q.grading_config={"verified":True,"method":"single_choice"}
        verify_answer(db,question_id=q.id,verification_type="human_verified",verifier="synthetic-test-only",
            method="synthetic new review",note="Isolated fixture only, not production approval.",
            idempotency_key="synthetic-new-review-"+uuid4().hex,expected_answer_sha256=answer_version_sha256(q))
        assert current_policy_snapshot(db,state,p).evidence_window==()
        assert state.evidence_window==before
        assert db.get(QuestionAttempt,result.attempt_id).grading_evidence["answer_verification_event_id"]!=str(q.answer_verification_event_id)
        db.rollback()


def test_policy_change_never_backfills_v1_evidence(session_factory,clean_database):
    with session_factory() as db:
        node,policy,qs=make_origin_slice(db)
        policy.policy_version=1; policy.required_question_origins={}; db.flush()
        result=attempt(db,node,qs[0],DAY)
        state=db.get(KpState,node.id); before=deepcopy(state.evidence_window)
        policy.policy_version=2; policy.required_question_origins={}; db.flush()
        assert current_policy_snapshot(db,state,MasteryPolicy(policy_version=2)).evidence_window==()
        assert state.evidence_window==before
        assert db.get(QuestionAttempt,result.attempt_id).grading_evidence["policy_version"]==1
        db.rollback()


@pytest.mark.parametrize("qtype", ["proof","discussion","program"])
def test_archived_difficult_public_question_process_record_never_becomes_formal(qtype,session_factory,clean_database):
    with session_factory() as db:
        node,policy,qs=make_origin_slice(db,qtype=qtype)
        from backend.services.question_eligibility import question_eligibility
        assert not question_eligibility(qs[0],node).practice_eligible
        plan_row=DailyPlan(study_date=DAY.date().isoformat(),status="active")
        db.add(plan_row); db.flush()
        item=PracticeItem(plan_id=plan_row.id,kp_id=node.id,question_id=qs[0].id,ordinal=1)
        db.add(item); db.flush()
        db.add(LearningEvent(kp_id=node.id,source_id=item.id,event_type="ai_process_reviewed",
            evidence_level="weak",payload={"synthetic_test_only":True},occurred_at=DAY))
        db.flush()
        result=submit_answer(db,item_id=item.id,raw_answer="Synthetic learner process",selected_option=None,
            idempotency_key="synthetic-process-"+uuid4().hex,now=DAY)
        assert result.result=="unknown" and result.effective_confirmation_count==0
        receipt=db.get(QuestionAttempt,result.attempt_id).grading_evidence
        # An old persisted item can retain its process history, but the new
        # single formal public bank does not admit unsupported proof grading.
        assert receipt["evidence_reliability"]=="ungradable"
        assert receipt["assistance_level"]=="process_review"
        assert db.get(KpState,node.id).evidence_window==[]
        db.rollback()


def _synthetic_proposal(db):
    node=KnowledgePoint(code="synthetic.migration."+uuid4().hex,name="Synthetic migration topic",subject="math2",
        is_active=True,is_assessable=True,is_reference_only=True,ordinal=1)
    db.add(node); db.flush()
    audit_time=datetime.now(timezone.utc)+timedelta(seconds=2)
    policy=KpMasteryPolicy(kp_id=node.id,policy_version=1,required_question_origins={},
        required_question_types={"external_exam":3},min_confirmations=3,min_real_questions=3,
        required_skill_tags=[node.name],required_variant_count=0,min_day_span=2,
        note="历年真题索引策略：Synthetic isolated fixture",updated_at=audit_time-timedelta(days=1))
    db.add(policy)
    for number in range(1,7):
        db.add(ExamQuestionReference(subject="math2",year=2018,question_number=number,
            knowledge_point_id=node.id,topic_label=node.name,source_topic_label=node.name,
            local_folder="synthetic-test-only",source_note="Synthetic test, not an actual source"))
    db.flush()
    entry={"node_id":str(node.id),"node_code":node.code,"node_name":node.name,"subject":node.subject,
        "node_active":True,"reference_only":True,"reference_count":6,"matches_reference_seed_formula":True,
        "before_policy":{k:deepcopy(getattr(policy,k)) for k in LEGACY_POLICY_FIELDS}}
    return {"format":"graduation-policy-compatibility-proposal-v1","created_at":audit_time.isoformat(),
        "proposal_status":"NOT_APPROVED_NOT_APPLIED","affected_policies":[entry]},node.id


def test_guarded_apply_noop_and_recovery_preserve_every_other_table(session_factory,clean_database):
    with session_factory() as db:
        proposal,node_id=_synthetic_proposal(db)
        c=db.connection(); before=plan(c,proposal)
        saved={"before":before,"proposal":proposal}
        result=apply_conversion(c,proposal,saved)
        assert result["policy_mutations"]==1 and result["protected_data"]["passed"]
        assert result["policy_preservation_passed"]
        assert apply_conversion(c,proposal,saved)["policy_mutations"]==0
        recovery=recover_policies(c,saved,apply=True)
        assert recovery["status_counts"]=={"RESTORABLE":1}
        after=plan(c,proposal)
        assert protected_data_comparison(before,after)["passed"]
        assert after["tables"]["kp_mastery_policies"]==before["tables"]["kp_mastery_policies"]
        db.rollback()


def test_changed_policy_is_safely_skipped_by_apply(session_factory,clean_database):
    with session_factory() as db:
        proposal,node_id=_synthetic_proposal(db)
        c=db.connection()
        db.get(KpMasteryPolicy,node_id).min_day_span=4; db.flush()
        before=plan(c,proposal); saved={"before":before,"proposal":proposal}
        result=apply_conversion(c,proposal,saved)
        assert result["policy_mutations"]==0
        assert result["status_counts"]=={"POLICY_CHANGED_SINCE_AUDIT":1}
        assert db.scalar(select(KpMasteryPolicy.min_day_span).where(KpMasteryPolicy.kp_id==node_id))==4
        db.rollback()
