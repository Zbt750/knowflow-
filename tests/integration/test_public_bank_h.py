"""Isolated H publication/supply/source guards and E/F/G compatibility."""
from copy import deepcopy
from datetime import timedelta
from uuid import UUID,uuid4
from pathlib import Path
from sqlalchemy import select,func,text
import pytest
from backend.models.learning import Question,KnowledgePoint,KpState,KpMasteryPolicy,QuestionAttempt
from backend.services.question_generation import assess_output,generate,Budget,promote
from backend.services.public_practice_release import publish_bounded_public,release_hash,release_is_current
from backend.services.question_eligibility import question_eligibility
from backend.services.public_bank_supply import supply_for_node
from backend.mastery.storage import policy_from_storage
from backend.services.question_answer_revision import revise_transcription_content
from scripts.run_question_generation_pilot import FixtureModel
from scripts.run_question_repair_pilot import isolated_factory,clone_inventory
from tests.integration.test_personal_question_bank import bank,body,Model,NOW
from backend.services.personal_question_service import run_generation
from tests.integration.test_policy_origin_semantics import DAY
from tests.integration.test_phase45e_current_graduation import fixture_submission


def original(db,kp,request='TEST_FIXTURE public H'):
    node=db.get(KnowledgePoint,kp)
    out,trace=generate(FixtureModel(),{'family':'power_integral','question_type':'single_choice','sample':1},Budget())
    c=assess_output(out,node,request_id=request,mode='original',family='power_integral',trace=trace)
    assert c['status']=='AUTO_PASS';q,_=promote(db,c,node);db.flush()
    return q,node


def test_legacy_bounded_public_release_cannot_bypass_formal_admission(bank):
    from backend.models.learning import DailyPlan,PracticeItem,LearningEvent
    from backend.services.answer_submission_service import submit_answer
    f,kp=bank
    with f.begin() as db:
        q,node=original(db,kp);before=deepcopy(db.get(KpState,kp).evidence_window)
        h=release_hash(q);publish_bounded_public(db,q,node,expected_hash=h,apply=True)
        assert publish_bounded_public(db,q,node,expected_hash=h,apply=True)['status']=='NOOP'
        e=question_eligibility(q,node)
        assert not e.practice_eligible and e.evidence_capability=='archive_only'
        plan=DailyPlan(study_date=NOW.date().isoformat(),status='active');db.add(plan);db.flush()
        item=PracticeItem(plan_id=plan.id,kp_id=kp,question_id=q.id,ordinal=1);db.add(item);db.flush()
        r=submit_answer(db,item_id=item.id,raw_answer=None,selected_option=q.correct_answer,idempotency_key='TEST_FIXTURE H answer',now=NOW)
        assert r.result=='unknown' and r.reason=='question_not_practice_eligible'
        assert db.get(KpState,kp).evidence_window==before
        assert db.scalar(select(LearningEvent)).evidence_level=='weak'
        assert db.scalar(select(QuestionAttempt)).grading_evidence['evidence_reliability']=='ungradable'
        q.explanation+=' changed'
        assert not release_is_current(q,node) and not question_eligibility(q,node).practice_eligible


def test_personal_and_forged_authority_rejected_without_mutation(bank):
    f,kp=bank;r=run_generation(f,body(kp,1,surface='chat'),Model(),now=NOW)
    with f.begin() as db:
        q=db.get(Question,UUID(r['question_ids'][0]));node=db.get(KnowledgePoint,kp);before=release_hash(q)
        with pytest.raises(ValueError,match='Personal'):publish_bounded_public(db,q,node,expected_hash=before,apply=True)
        with pytest.raises(ValueError,match='Personal'):revise_transcription_content(db,q.id,'0'*64,{'options':q.options},basis='TEST_FIXTURE no personal repair',proposed_source_pack_sha256='a'*64,proposed_pack_version='test',apply=True)
        assert release_hash(q)==before
        public,node=original(db,kp,'TEST_FIXTURE false-source');public.question_provenance='real_exam';public.content_trust='verified'
        with pytest.raises(ValueError):publish_bounded_public(db,public,node,expected_hash=release_hash(public),apply=True)


def test_bad_answer_options_explanation_and_wrong_mapping_no_publication(bank):
    f,kp=bank
    for fault in ('wrong_answer','duplicate_options','bad_explanation','unsupported_proof'):
        with f.begin() as db:
            node=db.get(KnowledgePoint,kp)
            out,trace=generate(FixtureModel(),{'family':'power_integral','question_type':'single_choice','fault':fault},Budget())
            c=assess_output(out,node,request_id='TEST_FIXTURE reject '+fault,mode='original',family='power_integral',trace=trace)
            assert c['status']!='AUTO_PASS'
    with f.begin() as db:
        q,node=original(db,kp,'TEST_FIXTURE mapping');node.name='完全不相关的知识点'
        with pytest.raises(ValueError):publish_bounded_public(db,q,node,expected_hash=release_hash(q),apply=True)


@pytest.mark.parametrize('code',['math.exam.fd2f9e3739d9','cs408.ds.topic.ee1ca2a45d19'])
def test_captured_real_content_with_test_only_review_reaches_unchanged_policy(test_database_url,code):
    from scripts.run_public_bank_h import read_frozen,ROOT
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    raw,_=read_frozen(ROOT/'storage/quality-audits/phase45d-20261009/diagnosis')
    with isolated_factory(test_database_url) as (f,_):
        clone_inventory(f,raw)
        with f.begin() as db:
            n=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==code));p=db.get(KpMasteryPolicy,n.id)
            policy_before={c.name:deepcopy(getattr(p,c.name)) for c in KpMasteryPolicy.__table__.columns}
            qs=list(db.scalars(select(Question).where(Question.kp_id==n.id,Question.question_provenance=='real_exam').order_by(Question.id)))[:3]
            assert len(qs)==3
            before=supply_for_node(qs,n,policy_from_storage(p));assert before['status']=='INSUFFICIENT'
            # TEST_FIXTURE stamps validate the mechanism, not source authenticity,
            # solution quality or actual human review. No production adoption.
            for q in qs:
                q.grading_config={**q.grading_config,'verified':True,'method':'single_choice' if q.question_type=='single_choice' else 'numeric_final'}
                mark_isolated_question_trusted(q,db=db);q.question_provenance='real_exam';q.source_status='verified';db.flush();db.refresh(q)
            supply=supply_for_node(qs,n,policy_from_storage(p));assert supply['status']=='CONDITIONAL_FUTURE_SUBMISSIONS',supply
            for i,q in enumerate(qs):
                # Helper supports selected options; numeric question path is
                # exercised separately by the standard answer-submission tests.
                if q.question_type=='single_choice':r=fixture_submission(db,n,q,DAY+timedelta(days=i),answer=q.correct_answer)
                else:
                    from backend.models.learning import DailyPlan,PracticeItem
                    from backend.services.answer_submission_service import submit_answer
                    plan=DailyPlan(study_date=(DAY+timedelta(days=i)).date().isoformat(),status='active');db.add(plan);db.flush()
                    item=PracticeItem(plan_id=plan.id,kp_id=n.id,question_id=q.id,ordinal=1);db.add(item);db.flush()
                    r=submit_answer(db,item_id=item.id,raw_answer=q.correct_answer,selected_option=None,idempotency_key='TEST_FIXTURE H numeric '+uuid4().hex,now=DAY+timedelta(days=i))
            assert r.state=='mastered'
            assert {c.name:getattr(p,c.name) for c in KpMasteryPolicy.__table__.columns}==policy_before
