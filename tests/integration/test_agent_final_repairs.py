from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json

import pytest
from sqlalchemy import select,func
from backend.models.learning import Question,QuestionAttempt,PracticeItem,DailyPlan,KpState,LearningEvent,KpMasteryPolicy
from backend.services.capability_service import read_capability_profile
from backend.services.auto_question_review import qualify_public_question,question_snapshot_sha256
from backend.services.answer_submission_service import submit_answer,record_answer_reveal
from backend.services.question_versions import question_for_attempt,question_for_practice_item
from backend.services.learning_task_service import run_task
from tests.integration.test_learning_loop import session_factory,clean_database
from tests.integration.test_auto_question_review import _candidate
from tests.integration.test_learning_tasks import PlanningProvider,task

NOW=datetime(2026,1,1,10,tzinfo=timezone.utc)


def setup_formal(factory):
    with factory.begin() as db:
        q,node=_candidate(db)
        db.add(q);db.flush()
        event,result=qualify_public_question(db,question_id=q.id,node_id=node.id,
            expected_snapshot_sha256=question_snapshot_sha256(q),idempotency_key=f"final-repair:{q.id}")
        assert result["status"]=="AUTO_VERIFIED"
        plan=DailyPlan(study_date="2026-01-01",status="active");db.add(plan);db.flush()
        item=PracticeItem(plan_id=plan.id,question_id=q.id,kp_id=node.id,ordinal=1);db.add(item);db.flush()
        return q.id,node.id,item.id


def answer(factory,item_id,*,right,now=NOW,reveal=False):
    with factory.begin() as db:
        item=db.get(PracticeItem,item_id);q=question_for_practice_item(db,item)
        prior=db.scalar(select(QuestionAttempt).where(QuestionAttempt.practice_item_id==item_id)
            .order_by(QuestionAttempt.submitted_at.desc()).limit(1))
        if prior:
            old=item
            day=datetime.fromisoformat(db.get(DailyPlan,old.plan_id).study_date).date()+timedelta(days=1)
            while db.scalar(select(DailyPlan.id).where(DailyPlan.study_date==day.isoformat())):day+=timedelta(days=1)
            plan=DailyPlan(study_date=day.isoformat(),status="active");db.add(plan);db.flush()
            item=PracticeItem(plan_id=plan.id,question_id=old.question_id,kp_id=old.kp_id,
                question_version_id=old.question_version_id,ordinal=1)
            db.add(item);db.flush();item_id=item.id
        if reveal:record_answer_reveal(db,item_id=item_id,now=now-timedelta(seconds=1))
        value=q.correct_answer if right else next((x for x in (q.options or {}) if x!=q.correct_answer),"987654321")
        result=submit_answer(db,item_id=item_id,raw_answer=value if q.question_type!="single_choice" else None,
            selected_option=value if q.question_type=="single_choice" else None,idempotency_key=str(uuid4()),now=now)
        assert result.result==("right" if right else "wrong")
        return result


def test_auto_verified_wrong_remains_reliable_without_changing_history_or_policy(session_factory):
    qid,kp,item=setup_formal(session_factory);answer(session_factory,item,right=False)
    with session_factory() as db:
        state=db.get(KpState,kp);policy=db.get(KpMasteryPolicy,kp)
        before=deepcopy(({c.name:getattr(state,c.name) for c in state.__table__.columns},
            {c.name:getattr(policy,c.name) for c in policy.__table__.columns}))
        a=db.scalar(select(QuestionAttempt).where(QuestionAttempt.question_id==qid));receipt=deepcopy(a.grading_evidence)
        assert receipt["version"]==5 and receipt["evidence_reliability"]=="verified_objective"
        profile=read_capability_profile(db,db.get(Question,qid).kp)
        assert profile.learning_progress.reliable_wrong_count==1
        assert profile.learning_progress.reference_wrong_count==0
        assert profile.learning_progress.status=="NEEDS_CONSOLIDATION"
        from backend.services.post_graduation_service import feedback_bound
        assert feedback_bound(a,question_for_attempt(db,a),db.get(Question,qid).kp)
        assert a.grading_evidence==receipt
        assert before==({c.name:getattr(state,c.name) for c in state.__table__.columns},
            {c.name:getattr(policy,c.name) for c in policy.__table__.columns})


@pytest.mark.parametrize("field,value",[("version",3),("auto_review_event_id",None),
    ("auto_review_snapshot_sha256","bad"),("answer_version_sha256","bad"),("bank_scope","personal")])
def test_new_current_qualification_cannot_upgrade_missing_or_mismatched_receipt(session_factory,field,value):
    qid,kp,item=setup_formal(session_factory);answer(session_factory,item,right=False)
    with session_factory.begin() as db:
        row=db.scalar(select(QuestionAttempt).where(QuestionAttempt.question_id==qid))
        row.grading_evidence={**row.grading_evidence,field:value}
    with session_factory() as db:
        p=read_capability_profile(db,db.get(Question,qid).kp).learning_progress
        assert p.reliable_wrong_count==0 and p.reference_wrong_count==1


def test_assisted_correction_then_later_independent_answer_is_read_separately(session_factory):
    qid,kp,item=setup_formal(session_factory)
    answer(session_factory,item,right=False)
    answer(session_factory,item,right=True,reveal=True,now=NOW+timedelta(days=1))
    with session_factory() as db:
        p=read_capability_profile(db,db.get(Question,qid).kp).learning_progress
        assert p.assisted_correct_question_count==1 and p.status=="RETEST_RECOMMENDED"
    with session_factory.begin() as db:
        plan=DailyPlan(study_date="2026-01-03",status="active");db.add(plan);db.flush()
        new=PracticeItem(plan_id=plan.id,question_id=qid,kp_id=kp,ordinal=1);db.add(new);db.flush();new_id=new.id
    answer(session_factory,new_id,right=True,now=NOW+timedelta(days=2))
    with session_factory() as db:
        p=read_capability_profile(db,db.get(Question,qid).kp)
        assert p.learning_progress.assisted_correct_question_count==0
        assert p.learning_progress.reference_wrong_count==0 and p.learning_progress.status!="RETEST_RECOMMENDED"
        assert any(d.independent_question_count>=1 for d in p.dimensions)


def test_history_keeps_old_version_evidence_when_current_question_changes(session_factory):
    qid,kp,item=setup_formal(session_factory);answer(session_factory,item,right=False)
    with session_factory.begin() as db:
        q=db.get(Question,qid);old=q.current_version_id;q.stem += "（新的独立版本）";db.flush()
        assert q.current_version_id!=old
    with session_factory() as db:
        a=db.scalar(select(QuestionAttempt).where(QuestionAttempt.question_id==qid))
        bound=question_for_attempt(db,a)
        assert a.question_version_id==old and not bound.stem.endswith("（新的独立版本）")
        p=read_capability_profile(db,db.get(Question,qid).kp).learning_progress
        assert p.reliable_wrong_count==1 and p.distinct_question_count==1


@pytest.mark.parametrize("needs_clarification",[False,True])
def test_source_correction_preserves_valid_draft_budget_and_confirmation(session_factory,needs_clarification):
    class Provider(PlanningProvider):
        def tool_turn(self,messages,tools,*,timeout):
            if self.calls<3:return super().tool_turn(messages,tools,timeout=timeout)
            self.calls+=1
            return {"message":{"content":json.dumps({"message":"所有候选题全部为AI生成，没有真题。","needs_clarification":needs_clarification})}}
    result=run_task(session_factory,task(session_factory,budget=20).task_id,Provider())
    assert result.status=="ready" and result.draft is not None
    assert result.draft["total_minutes"]<=20
    assert "服务端已校验方案" in result.message and "不超过20分钟预算" in result.message
    assert "只有你确认后" in result.message and "尚未加入今日学习" in result.message
    assert "所有候选题全部为AI生成" not in result.message
    assert "仍需校验方案" not in result.message
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0
