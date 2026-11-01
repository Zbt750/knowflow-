"""Frozen provider only. Graduation is earned by the unchanged state machine."""
import json
import pytest
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import UUID,uuid4
from sqlalchemy import select,func
from backend.models.learning import KnowledgePoint,KpState,KpMasteryPolicy,Question,QuestionAttempt,LearningEvent,PracticeItem
from backend.schemas.personal_questions import PersonalGenerationRequest,GenerationTarget
from backend.services.personal_question_service import run_generation,append_personal,bank_rows
from backend.services.answer_submission_service import submit_answer,record_answer_reveal
from backend.services.post_graduation_service import read_post_practice
from backend.services.question_eligibility import question_eligibility
from scripts.run_question_repair_pilot import isolated_factory
from scripts.replay_phase45i_agent_close import frozen_rows,OUTPUT
from tests.integration.test_learning_loop import mark_isolated_question_trusted
from tests.integration.test_phase45e_current_graduation import fixture_submission

DAY=datetime(2026,10,1,2,tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def private_frozen_assets_available():
    from scripts.replay_phase45i_agent_close import SOURCE
    if not (SOURCE/'provider-calls.jsonl').is_file() or not Path('storage/quality-audits/phase45d-20261009/diagnosis/inventory-snapshot.json').is_file():
        pytest.skip('Private frozen response/policy assets are not part of the public repository')


class FrozenProvider:
    simulation=True
    model='FROZEN_DEEPSEEK_NO_NETWORK'
    def __init__(self,rows):self.rows=iter(rows);self.calls=0
    def complete(self,messages,*,attempt=1):
        from backend.errors import AppError
        assert attempt==1
        self.calls+=1;row=next(self.rows)
        if row.get('finish_reason')=='length':raise AppError('answer_truncated')
        return row['response_content'],None  # historical usage is not new billing


def generate(f,kp,rows,kind='single_choice',now=DAY):
    provider=FrozenProvider(rows)
    body=PersonalGenerationRequest(request_key=uuid4(),surface='study',generation_mode='ai_generated',
        targets=[GenerationTarget(kp_id=kp,count=len(rows),question_type=kind,difficulty='basic')])
    result=run_generation(f,body,provider,now=now)
    assert provider.calls==len(rows)
    return result


def submit(f,kp,qid,day,right=True,reveal=False):
    added=append_personal(f,question_ids=[qid],now=day)
    with f.begin() as db:
        q=db.get(Question,qid)
        item=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==UUID(added['plan_id']),PracticeItem.question_id==qid))
        if reveal:record_answer_reveal(db,item_id=item.id,now=day)
        answer=q.correct_answer if right else next(k for k in q.options if k!=q.correct_answer) if q.options else '999'
        return submit_answer(db,item_id=item.id,raw_answer=answer if not q.options else None,
            selected_option=answer if q.options else None,idempotency_key='TEST_FIXTURE-close-'+uuid4().hex,now=day)


def projection(f,kp,day):
    with f() as db:return read_post_practice(db,db.get(KnowledgePoint,kp),now=day)


def restore_policy_fixture(db,code):
    """Copy an existing v2 policy unchanged into a fresh assessable TEST_FIXTURE leaf.

    Synthetic verification stamps represent test inputs only. No real-source or
    human-review claim is made about these synthetic public exam-role questions.
    The previous reference-only live target is never edited or used as a shortcut.
    """
    asset=Path('storage/quality-audits/phase45d-20261009/diagnosis/inventory-snapshot.json')
    raw=json.loads(asset.read_text(encoding='utf-8'))
    node_row=next(n for n in raw['knowledge_points'] if n['code']==code)
    policy_row=next(p for p in raw['kp_mastery_policies'] if p['kp_id']==node_row['id'])
    node=KnowledgePoint(code=code,name=node_row['name'],subject=node_row['subject'],
        is_active=True,is_assessable=True,is_reference_only=False)
    db.add(node);db.flush();db.add(KpState(kp_id=node.id))
    fields={key:value for key,value in policy_row.items() if key not in {'kp_id','created_at','updated_at'}}
    policy=KpMasteryPolicy(kp_id=node.id,**fields);db.add(policy)
    qs=[]
    for index in range(max(policy.min_confirmations,policy.min_real_questions)):
        if 'de439' in code:
            coefficient=index+2;expected=2*coefficient
            stem=f"TEST_FIXTURE exam-role: 设函数f(x)={coefficient}x^2，求f'(1)。"
        else:
            expected=-(1<<(index+3));stem=f'TEST_FIXTURE exam-role: {index+4}位补码最小值是多少？'
        q=Question(kp_id=node.id,question_type='single_choice',stem=stem,
            options={'A':str(expected),'B':str(expected+1),'C':str(expected+2),'D':str(expected+3)},correct_answer='A',
            explanation='TEST_FIXTURE: independently computed basic formula; no actual exam-source claim.',
            skill_tags=list(policy.required_skill_tags),bank_scope='public',grading_config={'verified':True,'method':'single_choice'})
        db.add(q);db.flush();mark_isolated_question_trusted(q,db=db)
        q.question_provenance='real_exam';q.source_status='verified';qs.append(q)
    db.flush()
    assert all(getattr(policy,k)==v for k,v in fields.items())
    assert all(question_eligibility(q,node).practice_eligible for q in qs)
    return node,policy,qs,fields


def test_all_twenty_frozen_responses_save_without_implicit_today_append(test_database_url):
    calls,turns=frozen_rows()
    with isolated_factory(test_database_url) as (f,_):
        with f.begin() as db:
            for t in {t['knowledge_node_id']:t for t in turns}.values():
                node=KnowledgePoint(id=UUID(t['knowledge_node_id']),code=t['knowledge_node_code'],name=t['knowledge_node_name'],
                    subject='408' if t['subject']=='408' else '考研数学',is_active=True,is_assessable=True,is_reference_only=True)
                db.add(node);db.add(KpState(kp_id=node.id))
        results=[]
        for row,t in zip(calls,turns):
            results.append(generate(f,UUID(t['knowledge_node_id']),[row],kind=t['question_type']))
        saved=sum(len(r['question_ids']) for r in results)
        assert saved==16,results
        # Generation saves a personal question; it is not consent to add it
        # to today's paper. The user must take a separate append action.
        assert sum(len(r.get('appended_question_ids',[])) for r in results)==0
        with f() as db:
            assert bank_rows(db,scope='public')['total']==0
            assert bank_rows(db,scope='personal')['total']==16
            assert db.scalar(select(func.count()).select_from(QuestionAttempt))==0
            assert db.scalar(select(func.count()).select_from(PracticeItem))==0
            assert db.scalar(select(func.count()).select_from(KpMasteryPolicy))==0
            for q in db.scalars(select(Question)):
                assert question_eligibility(q,db.get(KnowledgePoint,q.kp_id)).evidence_capability=='personal_practice_only'
        OUTPUT.mkdir(parents=True,exist_ok=True)
        (OUTPUT/'service-replay.json').write_text(json.dumps({'paid_requests':0,'saved':saved,'appended':0,'results':results},
            ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def test_earned_graduation_frozen_ai_risk_recovery_assistance_and_no_backfill(test_database_url):
    calls,_=frozen_rows()
    older=json.loads(Path('storage/quality-audits/phase45i-real-20261009/actual-run/provider-calls.jsonl').read_text(encoding='utf-8').splitlines()[0])
    with isolated_factory(test_database_url) as (f,_):
        with f.begin() as db:
            node,policy,qs,fields=restore_policy_fixture(db,'math.exam.de439863790e');kp=node.id
            public_ids=[q.id for q in qs]
        first=generate(f,kp,[calls[0],older]);fill=generate(f,kp,[calls[1]],kind='fill_blank')
        ids=[UUID(q) for q in first['question_ids']+fill['question_ids']]
        assert len(ids)==3
        pre=submit(f,kp,ids[0],DAY)
        assert pre.effective_confirmation_count==0 and not projection(f,kp,DAY).applicable
        with f.begin() as db:
            node=db.get(KnowledgePoint,kp)
            for i,qid in enumerate(public_ids):
                result=fixture_submission(db,node,db.get(Question,qid),DAY+timedelta(days=i+1))
            assert result.state=='mastered' and result.effective_confirmation_count==3
            state=db.get(KpState,kp);foundation=deepcopy((state.state,state.mastered_at,state.evidence_window))
        assert projection(f,kp,DAY+timedelta(days=3,minutes=1)).observed_attempt_count==0
        submit(f,kp,ids[0],DAY+timedelta(days=4),right=False)
        submit(f,kp,ids[1],DAY+timedelta(days=5),right=False)
        risk=projection(f,kp,DAY+timedelta(days=5));assert risk.status=='CONSOLIDATE'
        for i,qid in enumerate(ids):submit(f,kp,qid,DAY+timedelta(days=6+i))
        good=projection(f,kp,DAY+timedelta(days=8));assert good.status=='GOOD',good
        submit(f,kp,ids[2],DAY+timedelta(days=9),reveal=True)
        assisted=projection(f,kp,DAY+timedelta(days=9));assert assisted.status=='REVIEW' and assisted.assisted_correct_count==1
        with f() as db:
            state=db.get(KpState,kp);assert (state.state,state.mastered_at,state.evidence_window)==foundation
            assert all(getattr(db.get(KpMasteryPolicy,kp),k)==v for k,v in fields.items())
            events=list(db.scalars(select(LearningEvent).where(LearningEvent.occurred_at>foundation[1])))
            assert all(e.evidence_level=='weak' for e in events)
            hidden=db.get(Question,ids[0]);hidden.is_hidden=True;db.commit()
            assert db.scalar(select(func.count()).select_from(QuestionAttempt).where(QuestionAttempt.question_id==ids[0]))==3
        (OUTPUT/'graduation-closeout.json').write_text(json.dumps({'fixture_only':True,'policy_restored_without_changes':fields,
            'pre_graduation_confirmations':pre.effective_confirmation_count,'no_pre_graduation_backfill':True,
            'risk':risk.model_dump(),'good':good.model_dump(),'assisted':assisted.model_dump(),'foundation_unchanged':True},
            ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def test_frozen_range_answer_after_earned_graduation_is_reliable(test_database_url):
    calls,_=frozen_rows()
    with isolated_factory(test_database_url) as (f,_):
        with f.begin() as db:
            node,policy,qs,_=restore_policy_fixture(db,'cs408.co.topic.324b03e7b481');kp=node.id
            for i,q in enumerate(qs):result=fixture_submission(db,node,q,DAY+timedelta(days=i))
            assert result.state=='mastered'
        generated=generate(f,kp,[calls[13]],kind='fill_blank',now=DAY+timedelta(days=10))
        assert len(generated['question_ids'])==1,generated
        submit(f,kp,UUID(generated['question_ids'][0]),DAY+timedelta(days=10))
        p=projection(f,kp,DAY+timedelta(days=10));assert p.reliable_attempt_count==1,p


def test_reference_only_mapping_guard_is_preserved(test_database_url):
    with isolated_factory(test_database_url) as (f,_):
        with f.begin() as db:
            node,policy,qs,_=restore_policy_fixture(db,'math.exam.de439863790e')
            node.is_reference_only=True
            q=qs[0];db.flush()
            assert not question_eligibility(q,node).practice_eligible
            result=fixture_submission(db,node,q,DAY)
            assert result.result=='unknown' and result.effective_confirmation_count==0
            assert result.state!='mastered'


def test_wrong_requested_type_is_rejected_without_regeneration(test_database_url):
    calls,_=frozen_rows()
    with isolated_factory(test_database_url) as (f,_):
        with f.begin() as db:
            node,_,_,_=restore_policy_fixture(db,'math.exam.de439863790e');kp=node.id
        result=generate(f,kp,[calls[1]],kind='single_choice')
        assert not result['question_ids'] and result['model_calls']==1
        assert result['failures'][0]['reason']=='requested_type_not_followed'


def test_truncated_item_does_not_retry_or_stop_other_budgeted_items(test_database_url):
    calls,_=frozen_rows()
    older=json.loads(Path('storage/quality-audits/phase45i-real-20261009/actual-run/provider-calls.jsonl').read_text(encoding='utf-8').splitlines()[0])
    with isolated_factory(test_database_url) as (f,_):
        with f.begin() as db:
            node,_,_,_=restore_policy_fixture(db,'math.exam.de439863790e');kp=node.id
        result=generate(f,kp,[calls[0],calls[17],older])
        assert result['model_calls']==3 and len(result['question_ids'])==2,result
        assert result['status']=='partial'
        assert result['failures'][0]['review_status']=='OUTPUT_TRUNCATED'
