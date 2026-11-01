"""TEST_FIXTURE graduation actually earned through receipts; no dev DB or models."""
from datetime import timedelta
from uuid import UUID,uuid4
from copy import deepcopy
from backend.services.learning_task_context import expand_records
import pytest
from sqlalchemy import select,func
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import get_settings
from backend.api.deps import get_time_provider
from backend.models.learning import KpState,Question,QuestionAttempt,LearningEvent,KnowledgePoint,PracticeItem
from backend.services.post_graduation_service import read_post_practice
from backend.services.personal_question_service import run_generation,append_personal
from backend.schemas.personal_questions import PersonalGenerationRequest,GenerationTarget
from backend.services.answer_submission_service import submit_answer,record_answer_reveal
from backend.services.learning_task_tools import TaskTools
from tests.integration.test_policy_origin_semantics import make_origin_slice,DAY
from tests.integration.test_phase45e_current_graduation import fixture_submission
from scripts.run_question_repair_pilot import isolated_factory


class Model:
    """Varied C7 protocol fixture; this is not real model quality evidence."""
    simulation=True
    calls=0
    def complete(self,messages,*,attempt=1):
        import json
        self.calls+=1;request=json.loads(messages[-1]['content']);n=self.calls
        kind=request['question_type']
        return json.dumps({'stem':f'计算定积分：∫_0^1 {2*n}x dx = ____。',
            'question_type':kind,'options':{'A':str(n),'B':str(n+1),'C':str(n+2),'D':str(n+3)} if kind=='single_choice' else None,
            'correct_answer':'A' if kind=='single_choice' else str(n),
            'explanation':f'原函数为{n}x²。上下限代入得到{n}。',
            'final_value':str(n),'steps':[{'expression':f'{2*n}/2','value':str(n)}]}),None


@pytest.fixture
def graduated(test_database_url):
    with isolated_factory(test_database_url) as (factory,_):
        with factory.begin() as db:
            node,policy,qs=make_origin_slice(db);node.name='定积分的计算';node.code='math.exam.c431f98f817c'
            parent=KnowledgePoint(code='TEST_FIXTURE.root',name='合成数学章节',subject='math2',is_assessable=False,is_active=True)
            db.add(parent);db.flush();node.parent_id=parent.id
            for i,q in enumerate(qs):r=fixture_submission(db,node,q,DAY+timedelta(days=i))
            assert r.state=='mastered';kp=node.id;parent_id=parent.id
            before=deepcopy((db.get(KpState,kp).state,db.get(KpState,kp).evidence_window,db.get(KpState,kp).mastered_at))
        request=PersonalGenerationRequest(request_key=uuid4(),surface='chat',generation_mode='ai_generated',targets=[GenerationTarget(kp_id=kp,count=3),GenerationTarget(kp_id=kp,count=2,question_type='fill_blank')])
        generated=run_generation(factory,request,Model(),now=DAY+timedelta(days=3))
        assert len(generated['question_ids'])==5,generated
        ids=[UUID(q) for q in generated['question_ids']]
        yield factory,kp,ids,before,parent_id


def post(f,kp,day):
    with f() as db:return read_post_practice(db,db.get(KnowledgePoint,kp),now=day)


def submit(f,kp,qid,day,*,right=True,reveal=False):
    appended=append_personal(f,question_ids=[qid],now=day)
    with f.begin() as db:
        item=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==UUID(appended['plan_id']),PracticeItem.question_id==qid))
        if reveal:record_answer_reveal(db,item_id=item.id,now=day)
        q=db.get(Question,qid)
        answer=q.correct_answer if right else 'B' if q.question_type=='single_choice' else '999'
        return submit_answer(db,item_id=item.id,raw_answer=answer if q.question_type!='single_choice' else None,
            selected_option=answer if q.question_type=='single_choice' else None,idempotency_key='TEST_FIXTURE G-'+uuid4().hex,now=day)


def test_real_graduation_risk_recovery_and_history_preserved(graduated):
    f,kp,ids,before,_=graduated
    assert post(f,kp,DAY+timedelta(days=3)).status=='INSUFFICIENT'
    submit(f,kp,ids[0],DAY+timedelta(days=3),right=False)
    assert post(f,kp,DAY+timedelta(days=3)).status=='INSUFFICIENT'
    submit(f,kp,ids[1],DAY+timedelta(days=4),right=False)
    p=post(f,kp,DAY+timedelta(days=4));assert p.status=='CONSOLIDATE' and p.independent_wrong_count==2
    for i,qid in enumerate(ids[2:]):submit(f,kp,qid,DAY+timedelta(days=5+i))
    p=post(f,kp,DAY+timedelta(days=7));assert p.status=='GOOD',p
    assert p.distinct_question_count==5 and p.independent_wrong_count==2
    with f() as db:
        state=db.get(KpState,kp)
        assert (state.state,state.evidence_window,state.mastered_at)==before
        assert db.scalar(select(func.count()).select_from(QuestionAttempt).where(QuestionAttempt.objective_result=='wrong'))==2
        assert all(e.evidence_level=='weak' for e in db.scalars(select(LearningEvent).where(LearningEvent.occurred_at>before[2])))


def test_same_question_repeats_assisted_and_long_gap(graduated):
    f,kp,ids,before,_=graduated
    for i in range(3):submit(f,kp,ids[0],DAY+timedelta(days=3+i))
    p=post(f,kp,DAY+timedelta(days=6));assert p.status=='INSUFFICIENT' and p.distinct_question_count==1
    submit(f,kp,ids[1],DAY+timedelta(days=7),reveal=True)
    p=post(f,kp,DAY+timedelta(days=8));assert p.status=='REVIEW' and p.assisted_correct_count==1
    count=p.observed_attempt_count
    p=post(f,kp,DAY+timedelta(days=90));assert p.status=='REVIEW' and '不证明' in p.reason
    with f() as db:assert db.scalar(select(func.count()).select_from(QuestionAttempt))==3+count


def test_real_api_tree_parent_and_agent_use_same_evidence_without_model(graduated):
    f,kp,ids,_,parent=graduated
    submit(f,kp,ids[0],DAY+timedelta(days=3),right=False);submit(f,kp,ids[1],DAY+timedelta(days=4),right=False)
    now=DAY+timedelta(days=5)
    app=create_app();app.state.session_factory=f;app.state.settings=get_settings()
    app.dependency_overrides[get_time_provider]=lambda:lambda:now
    c=TestClient(app,base_url='http://127.0.0.1:8003')
    detail=c.get(f'/api/knowledge/{kp}');assert detail.status_code==200,detail.text
    data=detail.json();assert data['node']['state']=='mastered' and data['node']['post_graduation']['status']=='CONSOLIDATE'
    assert data['capability_profile']['post_graduation']==data['node']['post_graduation']
    tree=c.get('/api/knowledge/tree').json()['nodes'][0]
    assert tree['id']==str(parent) and tree['state'] is None and tree['post_graduation_review_count']==1
    assert c.get(f'/api/knowledge/{parent}').json()['node']['post_graduation_review_count']==1
    needs=c.get('/api/learning-review-needs').json();assert needs['total']==1
    tools=TaskTools(f,budget_minutes=30,now=now,goal='帮我安排今天的复习')
    result=tools.execute('list_review_needs',{})
    assert result['nodes'][0]['kp_id']==str(kp)
    facts=tools.execute('get_learning_state',{'kp_ids':[str(kp)]})['states'][0]
    assert facts['post_graduation']==data['node']['post_graduation']
    stock=tools.execute('find_questions',{'kp_ids':[str(kp)]})['questions']
    assert stock and stock[0]['question_id'] in {str(q) for q in ids[2:]}
    valid=tools.execute('validate_plan',{'question_ids':[stock[0]['question_id']],'review_kp_ids':[],'review_minutes':0,'rationale':'TEST_FIXTURE 换题复测'})
    assert valid['valid'],valid
    with f() as db:
        # Validation produced a draft, not a new practice item.
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==5


def test_not_graduated_and_revoked_trust_are_not_post_graduation(graduated):
    from backend.services.answer_verification import revoke_answer_verification,answer_version_sha256
    f,kp,ids,_,_=graduated
    with f.begin() as db:
        q=db.scalar(select(Question).where(Question.kp_id==kp,Question.bank_scope=='public'))
        revoke_answer_verification(db,question_id=q.id,expected_event_id=q.answer_verification_event_id,
            expected_answer_sha256=answer_version_sha256(q),verifier='TEST_FIXTURE',method='TEST_FIXTURE revoke',note='isolated only',idempotency_key='TEST_FIXTURE '+uuid4().hex)
    p=post(f,kp,DAY+timedelta(days=4));assert not p.applicable and p.status=='NOT_APPLICABLE'
    with f() as db:assert db.get(KpState,kp).state=='mastered'  # historical unchanged, current projection not graduated


def test_changed_current_personal_answer_does_not_rewrite_old_attempt_version(graduated):
    f,kp,ids,_,_=graduated;submit(f,kp,ids[0],DAY+timedelta(days=3),right=False)
    with f.begin() as db:
        q=db.get(Question,ids[0]);old_version=q.current_version_id;q.correct_answer='B'
    p=post(f,kp,DAY+timedelta(days=4))
    assert p.reliable_attempt_count==1 and p.excluded_attempt_count==0
    with f() as db:
        attempt=db.scalar(select(QuestionAttempt).where(QuestionAttempt.question_id==ids[0]))
        question=db.get(Question,ids[0])
        assert attempt.question_version_id==old_version
        assert question.current_version_id!=old_version


def test_ungraduated_personal_correct_does_not_enable_post_model(test_database_url):
    with isolated_factory(test_database_url) as (f,_):
        with f.begin() as db:
            n,_,_=make_origin_slice(db);n.name='定积分的计算';n.code='math.exam.c431f98f817c';kp=n.id
        body=PersonalGenerationRequest(request_key=uuid4(),surface='chat',generation_mode='ai_generated',targets=[GenerationTarget(kp_id=kp,count=3)])
        ids=run_generation(f,body,Model(),now=DAY)['question_ids']
        for i,q in enumerate(ids):submit(f,kp,UUID(q),DAY+timedelta(days=i))
        assert not post(f,kp,DAY+timedelta(days=3)).applicable
        with f() as db:assert db.get(KpState,kp).state=='unseen'


def test_formal_verified_error_still_uses_original_graduation_algorithm(graduated):
    f,kp,_,_,_=graduated
    with f.begin() as db:
        n=db.get(KnowledgePoint,kp);q=db.scalar(select(Question).where(Question.kp_id==kp,Question.bank_scope=='public'))
        result=fixture_submission(db,n,q,DAY+timedelta(days=4),answer='B')
        assert result.state=='stuck'
    assert not post(f,kp,DAY+timedelta(days=5)).applicable


def test_wrong_solution_correct_is_not_independent_recovery(graduated):
    f,kp,ids,_,_=graduated;day=DAY+timedelta(days=3)
    r=submit(f,kp,ids[0],day,right=False)
    # 同一练习已锁定；后一天新练习看解析后完成也不能成为独立恢复证据。
    submit(f,kp,ids[0],day+timedelta(days=1),right=True,reveal=True)
    p=post(f,kp,day+timedelta(days=1,minutes=3))
    assert p.status=='REVIEW' and p.independent_correct_count==0 and p.independent_wrong_count==1


def test_planner_real_tool_cycle_confirm_only_then_preserves_foundation(graduated):
    import json
    from backend.services.learning_task_service import create_task,run_task,confirm_task
    from backend.schemas.learning_task import CreateTask,ConfirmTask
    f,kp,ids,before,_=graduated;now=DAY+timedelta(days=5)
    submit(f,kp,ids[0],DAY+timedelta(days=3),right=False);submit(f,kp,ids[1],DAY+timedelta(days=4),right=False)
    class ReviewProvider:
        calls=0
        def tool_turn(self,messages,tools,*,timeout):
            self.calls+=1
            if self.calls==1:actions=[('list_review_needs',{})]
            elif self.calls==2:actions=[('get_learning_state',{'kp_ids':[str(kp)]}),('find_questions',{'kp_ids':[str(kp)]})]
            elif self.calls==3:
                stock=expand_records(json.loads(messages[-1]['content']))['questions'];qid=next(q['question_id'] for q in stock if not q['in_today_plan'])
                actions=[('validate_plan',{'question_ids':[qid],'review_kp_ids':[],'review_minutes':0,'rationale':'根据近期不同题可靠错误，换题复测'})]
            else:return {'message':{'content':json.dumps({'message':'建议换一道题复习，尚未加入。','needs_clarification':False})},'model':'TEST_FIXTURE G'}
            return {'message':{'tool_calls':[{'id':f'g-{self.calls}-{i}','type':'function','function':{'name':n,'arguments':json.dumps(a)}} for i,(n,a) in enumerate(actions)]},'model':'TEST_FIXTURE G'}
    t=create_task(f,CreateTask(goal='帮我安排今天的复习',budget_minutes=30),now=now)
    result=run_task(f,t.task_id,ReviewProvider(),now=now)
    assert result.status=='ready',result
    with f() as db:assert db.scalar(select(func.count()).select_from(PracticeItem))==5
    confirmed=confirm_task(f,t.task_id,ConfirmTask(draft_version=result.draft_version),now=now)
    assert confirmed.metrics['commit']
    confirm_task(f,t.task_id,ConfirmTask(draft_version=result.draft_version),now=now)
    with f() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem))==6
        assert (db.get(KpState,kp).state,db.get(KpState,kp).evidence_window,db.get(KpState,kp).mastered_at)==before


def test_assistant_summary_reads_facts_without_paid_or_generation_provider(graduated):
    from backend.models.chat import ChatSession
    f,kp,ids,_,_=graduated
    submit(f,kp,ids[0],DAY+timedelta(days=3),right=False);submit(f,kp,ids[1],DAY+timedelta(days=4),right=False)
    # The stream's clock defaults to real October; use existing fake-clock
    # projection via current evidence queries for recent test dates instead.
    import asyncio
    from types import SimpleNamespace
    from backend.services.learning_assistant_service import assistant_stream
    from backend.schemas.learning_assistant import AssistantRequest,StudyContext
    with f.begin() as db:
        s=ChatSession(title='TEST_FIXTURE review',mode='builtin',purpose='qa');db.add(s);db.flush();sid=s.id
    async def collect():
        frames=[]
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=get_settings())))
        async for frame in assistant_stream(f,request=request,session_id=sid,body=AssistantRequest(question='我毕业的知识点里，哪些最近需要复习？',study_context=StudyContext(surface='chat'),request_key=uuid4()),stack=None,provider=None,now=DAY+timedelta(days=5)):
            frames.append(frame.decode())
        return ''.join(frames)
    data=asyncio.run(collect());assert '建议巩固' in data and 'event: error' not in data,data


def test_old_missing_receipt_and_unsupported_answers_are_not_errors(graduated):
    f,kp,ids,_,_=graduated;day=DAY+timedelta(days=3)
    submit(f,kp,ids[0],day)
    with f.begin() as db:
        a=db.scalar(select(QuestionAttempt).where(QuestionAttempt.question_id==ids[0]))
        a.grading_evidence={'version':3};a.objective_result='wrong'  # TEST_FIXTURE legacy missing binding
        appended=append_personal(f,question_ids=[ids[1]],now=day+timedelta(days=1))
        item=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==UUID(appended['plan_id'])))
        submit_answer(db,item_id=item.id,raw_answer='unparsed expression',selected_option=None,
            idempotency_key='TEST_FIXTURE unknown',now=day+timedelta(days=1))
    p=post(f,kp,day+timedelta(days=2));assert p.status=='INSUFFICIENT' and p.independent_wrong_count==0 and p.reliable_attempt_count==0


def test_no_outside_inventory_summary_does_not_call_generation(graduated):
    import asyncio
    from types import SimpleNamespace
    from backend.models.chat import ChatSession
    from backend.models.learning import DailyPlan
    from backend.services.learning_assistant_service import assistant_stream
    from backend.schemas.learning_assistant import AssistantRequest,StudyContext
    f,kp,ids,_,_=graduated;day=DAY+timedelta(days=5)
    submit(f,kp,ids[0],DAY+timedelta(days=3),right=False);submit(f,kp,ids[1],DAY+timedelta(days=4),right=False)
    a=append_personal(f,question_ids=ids,now=day)
    with f.begin() as db:
        pub=list(db.scalars(select(Question.id).where(Question.kp_id==kp,Question.bank_scope=='public')))
        # This read-only query fixture models a completed paper containing all
        # eligible items before the freeze boundary; it must not use a runtime
        # append service to mutate an already materialized plan.
        plan=db.get(DailyPlan,UUID(a['plan_id']))
        existing_items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==plan.id)))
        next_ordinal=max((item.ordinal for item in existing_items),default=0)+1
        questions={q.id:q for q in db.scalars(select(Question).where(Question.id.in_(pub)))}
        for question_id in pub:
            if not any(item.question_id==question_id for item in existing_items):
                db.add(PracticeItem(plan_id=plan.id,question_id=question_id,kp_id=questions[question_id].kp_id,ordinal=next_ordinal))
                next_ordinal+=1
        s=ChatSession(title='TEST_FIXTURE no-stock',mode='builtin',purpose='qa');db.add(s);db.flush();sid=s.id
    async def collect():
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=get_settings())))
        return b''.join([frame async for frame in assistant_stream(f,request=request,session_id=sid,
            body=AssistantRequest(question='我毕业的知识点哪些最近需要复习？',study_context=StudyContext(surface='chat'),request_key=uuid4()),
            stack=None,provider=None,now=day)]).decode()
    data=asyncio.run(collect());assert '当前卷外没有合格题' in data and 'event: error' not in data,data
