import json
from types import SimpleNamespace
from uuid import UUID,uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from backend.errors import AppError
from backend.models.learning import KnowledgePoint,KpState,Question,QuestionVersion,PracticeItem,DailyPlan
from backend.models.personal_generation import PersonalGenerationBatch
from backend.services.personal_generation_intent import generation_intent
from backend.services.personal_question_service import run_generation
from backend.api.routes.personal_questions import router as personal_router
from backend.api.deps import get_time_provider
from tests.integration.test_personal_general_generation import general_bank,request,NOW
from tests.integration.test_generation_confirmation_recovery import generation_fixture,application,events


class CountModel:
    simulation=True
    model='fixed-count-and-quality-no-network'
    def __init__(self,faults=None,offset=0):self.calls=0;self.requests=[];self.faults=faults or {};self.offset=offset
    def complete(self,messages,**kwargs):
        self.calls+=1;payload=json.loads(messages[-1]['content']);self.requests.append(payload)
        fault=self.faults.get(self.calls)
        if fault=='truncated':raise AppError('answer_truncated',retryable=False)
        if fault=='timeout':raise TimeoutError('synthetic timeout')
        if fault=='network':
            import socket
            import httpx
            from backend.chat.service import _provider_error
            try:
                try: raise socket.gaierror(-2,'DO_NOT_PERSIST_DNS_DETAILS')
                except socket.gaierror as cause: raise httpx.ConnectError('DO_NOT_PERSIST_NETWORK_DETAILS') from cause
            except httpx.ConnectError as exc: raise _provider_error('complete',exc) from exc
        if fault=='format':return '{"stem":',None
        k=self.calls+2+self.offset;answer=str(k*2)
        data={'stem':f'首项为{k}、公比为1/2的等比级数，求其和并说明收敛条件。',
            'question_type':payload['question_type'],'options':None,'correct_answer':answer,
            'explanation':f'公比绝对值小于1，故级数收敛。由求和公式{k}/(1-1/2)={answer}可得结论。',
            'final_value':answer,'steps':[]}
        if payload['question_type']=='single_choice':data.update(options={'A':answer,'B':str(k),'C':str(k+10),'D':str(k+20)},correct_answer='A')
        if fault=='answer':data['final_value']='999'
        if fault=='difficulty':data['difficulty_assessment']={'estimated_level':'basic','relative_change':'easier',
            'reason':'减少了原题需要的逐项求导步骤，仅使用等比级数求和公式。','mechanisms':['reasoning_steps']}
        return json.dumps(data,ensure_ascii=False),{'prompt_tokens':100,'completion_tokens':150,'total_tokens':250}


def test_gradient_confirmation_to_saved_personal_versions_does_not_touch_formal_paper(generation_fixture):
    factory,_,kp,sid,_=generation_fixture;model=CountModel()
    context={'surface':'chat','knowledge_node_ids':[str(kp)]}
    with TestClient(application(factory,model)) as client:
        first={'question':'生成三道练习题，由易到难','request_key':str(uuid4()),'study_context':context}
        frames=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=first))
        card=next(d for n,d in frames if n=='personal_generation_confirmation')
        assert card['difficulty_steps']==['基础','中等','综合挑战'] and model.calls==0
        message_id=next(d['message_id'] for n,d in frames if n=='meta')
        confirmed={**first,'request_key':str(uuid4()),'personal_generation_confirmed_kp_id':str(kp),
                   'personal_generation_confirmation_message_id':message_id}
        rejected=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=confirmed))
        assert any(n=='error' and d['code']=='personal_generation_confirmation_invalid' for n,d in rejected)
        assert model.calls==0
        confirmed.pop('personal_generation_confirmed_kp_id')
        confirmed['request_key']=str(uuid4())
        confirmed['personal_generation_confirmed_targets']=[
            {key:target[key] for key in ('kp_id','question_type','count','difficulty')}
            for target in card['proposed_targets']]
        generated=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=confirmed))
        result=next(d for n,d in generated if n=='personal_generation')
        assert result['outcome_summary']['saved_count']==3,result
        assert [r['difficulty_requirement']['target_level'] for r in model.requests]==['basic','medium','challenge']
        replay=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=confirmed))
        assert next(d for n,d in replay if n=='personal_generation')['batch_id']==result['batch_id']
        assert model.calls==3
    with factory() as db:
        batch=db.get(PersonalGenerationBatch,UUID(result['batch_id']))
        assert [t['difficulty'] for t in batch.request['targets']]==['basic','improved','comprehensive']
        for qid in result['question_ids']:
            q=db.get(Question,UUID(qid));version=db.get(QuestionVersion,q.current_version_id)
            assert q.bank_scope=='personal' and version.question_id==q.id
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_multi_knowledge_point_confirmation_saves_exact_allocations_without_formal_append(generation_fixture):
    factory,_,_,sid,_=generation_fixture
    with factory.begin() as db:
        lhopital=KnowledgePoint(code='TEST_FIXTURE.multi_generation.lhopital',name='洛必达法则',
            subject='考研数学',is_active=True,is_assessable=True,is_reference_only=False)
        implicit=KnowledgePoint(code='TEST_FIXTURE.multi_generation.implicit',name='隐函数求导',
            subject='考研数学',is_active=True,is_assessable=True,is_reference_only=False)
        db.add_all([lhopital,implicit]);db.flush()
        db.add_all([KpState(kp_id=lhopital.id),KpState(kp_id=implicit.id)])
        kp_ids=[lhopital.id,implicit.id]
    model=CountModel();context={'surface':'study','knowledge_node_ids':[str(value) for value in kp_ids]}
    question='给我生成三道洛必达法则单选题、两道隐函数求导填空题'
    with TestClient(application(factory,model)) as client:
        first={'question':question,'request_key':str(uuid4()),'study_context':context}
        frames=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=first))
        card=next(data for name,data in frames if name=='personal_generation_confirmation')
        assert card['question_count']==5 and model.calls==0
        allocations=[{key:target[key] for key in ('kp_id','question_type','count','difficulty')}
            for target in card['proposed_targets']]
        assert [(row['kp_id'],row['count'],row['question_type']) for row in allocations]==[
            (str(kp_ids[0]),3,'single_choice'),(str(kp_ids[1]),2,'fill_blank')]
        message_id=next(data['message_id'] for name,data in frames if name=='meta')
        confirmed={**first,'request_key':str(uuid4()),'personal_generation_confirmed_targets':allocations,
            'personal_generation_confirmation_message_id':message_id}
        saved=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=confirmed))
        result=next(data for name,data in saved if name=='personal_generation')
        assert result['outcome_summary']['saved_count']==5 and model.calls==5
        replay=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=confirmed))
        assert next(data for name,data in replay if name=='personal_generation')['batch_id']==result['batch_id']
        assert model.calls==5
    with factory() as db:
        rows=[db.get(Question,UUID(value)) for value in result['question_ids']]
        assert [row.kp_id for row in rows]==[kp_ids[0]]*3+[kp_ids[1]]*2
        assert [row.question_type for row in rows]==['single_choice']*3+['fill_blank']*2
        assert all(row.bank_scope=='personal' and db.get(QuestionVersion,row.current_version_id).question_id==row.id for row in rows)
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


@pytest.mark.parametrize('text,count',[
    ('帮我生成一道更难的类似题',1),('帮我出一道类似题',1),('再来一题',1),
    ('生成两道类似题',2),('生成三道题，难度高一点',3),('帮我生成练习题',1),
    ('帮我生成比这题还难的题',1),('再来一道更难的',1),('给我出个更难的',1),
    ('生成两道更难的题',2),('生成 3 道题',3),
])
def test_instruction_to_actual_calls_saved_versions_and_report(general_bank,text,count):
    factory,kp=general_bank
    with factory() as db:
        body=generation_intent(db,text,SimpleNamespace(knowledge_node_ids=[kp],question_id=None,surface='chat',daily_plan_id=None),uuid4(),confirmed_kp_id=kp)
    model=CountModel();app=application(factory,model)
    app.include_router(personal_router,prefix='/api')
    app.dependency_overrides[get_time_provider]=lambda:lambda:NOW
    with TestClient(app) as client:
        response=client.post('/api/personal-questions/generate',json=body.model_dump(mode='json'))
        assert response.status_code==200,response.text
        result=response.json()
        assert client.get(f'/api/personal-questions/batches/{body.request_key}').json()['outcome_summary']==result['outcome_summary']
    summary=result['outcome_summary']
    assert sum(t.count for t in body.targets)==count
    assert model.calls==summary['provider_calls']==summary['requested_count']==summary['saved_count']==count,result
    assert summary['failed_count']==summary['not_attempted_count']==summary['unresolved_count']==0
    assert f'你请求了{count}道' in result['message']
    with TestClient(app) as client:
        again=client.post('/api/personal-questions/generate',json=body.model_dump(mode='json')).json()
    assert again['replayed'] and again['outcome_summary']==summary and model.calls==count
    with factory() as db:
        for qid in result['question_ids']:
            q=db.get(Question,UUID(qid));version=db.get(QuestionVersion,q.current_version_id)
            assert q.kp_id==kp and version.question_id==q.id
        assert db.scalar(select(func.count()).select_from(QuestionVersion))==count
        for table in (PracticeItem,DailyPlan):assert db.scalar(select(func.count()).select_from(table))==0


@pytest.mark.parametrize('count,faults,saved,failed,idle,quality',[
    (1,{1:'answer'},0,1,0,1),(1,{1:'truncated'},0,1,0,0),
    (1,{1:'difficulty'},0,1,0,1),(2,{2:'answer'},1,1,0,1),
    (2,{},2,0,0,0),(3,{1:'timeout'},0,1,2,0),(1,{1:'format'},0,1,0,0),
    (1,{1:'network'},0,1,0,0),(3,{1:'network'},0,1,2,0),
])
def test_real_failure_records_never_become_extra_calls_or_fake_success(general_bank,count,faults,saved,failed,idle,quality):
    factory,kp=general_bank;body=request(kp);body.targets[0].count=count
    body.user_requirement='比原题更难';body.reference_text='当|x|<1时，求级数sum nx^n的和。'
    model=CountModel(faults);result=run_generation(factory,body,model,now=NOW);summary=result['outcome_summary']
    assert summary['requested_count']==count
    assert summary['saved_count']==saved and summary['failed_count']==failed
    assert summary['not_attempted_count']==idle and summary['quality_rejected_count']==quality
    assert summary['not_executed_count']==idle and summary['attempted_count']==model.calls
    assert summary['network_failed_count']==int('network' in faults.values())
    if 'network' in faults.values():
        assert result['diagnostics'][0]['code']=='personal_generation_provider_network'
        assert result['diagnostics'][0]['network_cause']=='dns_resolution_failed'
        assert result['calls'][0]['failure_reason']=='network_ConnectError'
        assert 'DO_NOT_PERSIST' not in json.dumps(result)
    assert model.calls==count-idle and summary['provider_calls']==model.calls
    assert len(result['question_ids'])==saved
    assert '未通过检查或未生成' not in result['message']
    replay=run_generation(factory,body,model,now=NOW)
    assert replay['outcome_summary']==summary and model.calls==count-idle
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Question))==saved
        assert db.scalar(select(func.count()).select_from(QuestionVersion))==saved
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_actual_two_then_one_harder_conversation_does_not_inherit_old_count(generation_fixture):
    factory,_,kp,sid,_=generation_fixture;model=CountModel()
    with factory.begin() as db:
        parent=Question(kp_id=kp,stem='当|x|<1时，求级数sum nx^n的和，并说明逐项求导的条件。',
            question_type='single_choice',options={'A':'2','B':'3','C':'4','D':'5'},correct_answer='A',
            explanation='收敛区间内部可以逐项求导，代入指定条件得到结果。',is_active=True)
        db.add(parent);db.flush();qid=parent.id
    context={'surface':'chat','knowledge_node_ids':[str(kp)],'question_id':str(qid)}
    with TestClient(application(factory,model)) as client:
        first={'question':'那给我再生成2道都是中等的题目','request_key':str(uuid4()),'study_context':context}
        frames=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=first))
        card=next(d['message_id'] for n,d in frames if n=='meta')
        confirmed={**first,'request_key':str(uuid4()),'personal_generation_confirmed_kp_id':str(kp),'personal_generation_confirmation_message_id':card}
        generated=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=confirmed))
        old=next(d for n,d in generated if n=='personal_generation')
        assert old['outcome_summary']['saved_count']==2 and model.calls==2
        second={'question':'你帮我生成一道比这道更难的题','request_key':str(uuid4()),'study_context':context}
        frames=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=second))
        current=next(d for n,d in frames if n=='personal_generation')
        assert current['requested']==current['outcome_summary']['provider_calls']==len(current['question_ids'])==1,frames
        assert model.calls==3 and parent.stem in model.requests[-1]['reference']['statement']
        assert model.requests[-1]['reference']['source']['question_version_id']
        assert model.requests[-1]['difficulty_requirement']['relative_change']=='harder'
        history=client.get(f'/api/chat/sessions/{sid}/messages').json()
        assert history[-1]['personal_generation']['outcome_summary']==current['outcome_summary']
        with factory() as db:
            batch=db.get(PersonalGenerationBatch,UUID(current['batch_id']))
            assert batch.request['targets'][0]['count']==1


def test_read_failed_batch_is_free_and_new_user_request_has_its_own_calls(general_bank):
    factory,kp=general_bank;body=request(kp);body.targets[0].count=1
    model=CountModel({1:'network'})
    failed=run_generation(factory,body,model,now=NOW)
    assert failed['outcome_summary']['network_failed_count']==1 and model.calls==1
    assert not failed['calls'][0]['usage_observed']  # unknown billing is not zero usage
    replay=run_generation(factory,body,model,now=NOW)
    assert replay['replayed'] and model.calls==1
    new_request=body.model_copy(update={'request_key':uuid4()},deep=True)
    saved=run_generation(factory,new_request,model,now=NOW)
    assert saved['batch_id']!=failed['batch_id'] and model.calls==2
    assert saved['outcome_summary']['attempted_count']==saved['outcome_summary']['saved_count']==1
    assert saved['calls'][0]['usage_observed'] and saved['calls'][0]['usage']['total_tokens']==250
    run_generation(factory,new_request,model,now=NOW)
    assert model.calls==2
    with factory() as db:
        for table in (Question,QuestionVersion):assert db.scalar(select(func.count()).select_from(table))==1
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==2
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_new_default_request_supersedes_old_three_question_confirmation(generation_fixture):
    factory,_,kp,sid,_=generation_fixture;model=CountModel()
    context={'surface':'chat','knowledge_node_ids':[str(kp)]}
    with TestClient(application(factory,model)) as client:
        for text,count in [('生成 3 道题',3),('帮我生成比这题还难的题。原题：当|x|<1时求级数sum nx^n的和。',1)]:
            payload={'question':text,'request_key':str(uuid4()),'study_context':context}
            frames=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=payload))
            card=next(data for name,data in frames if name=='personal_generation_confirmation')
            assert card['question_count']==count and model.calls==0
        card_id=next(data['message_id'] for name,data in frames if name=='meta')
        confirmed={**payload,'request_key':str(uuid4()),'personal_generation_confirmed_kp_id':str(kp),
            'personal_generation_confirmation_message_id':card_id}
        saved=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=confirmed))
        result=next(data for name,data in saved if name=='personal_generation')
        assert result['outcome_summary']['requested_count']==result['outcome_summary']['saved_count']==1
        assert model.calls==1
