"""New V32 failures, unchanged original utterances. Only retained test PG rollback."""
import importlib.util
from pathlib import Path
from uuid import UUID
import pytest
from sqlalchemy import select
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message
from backend.models.chat import ChatMessage
from backend.models.learning import Question
from backend.services.question_availability import question_source_category

spec=importlib.util.spec_from_file_location('v32_rollback_support',Path(__file__).with_name('test_v31_postgres_flow.py'))
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
factory=support.factory

@pytest.mark.parametrize('text,capability,intent',[
 ('其中选择题有多少道？','data_query','inventory'),
 ('给我讲讲导数计算，不要安排题目。','qa','qa'),
 ('先不管之前的安排，讲讲幂级数。','qa','qa'),
 ('先选一道洛必达让我看看，不要加入。','planner','plan'),
 ('找一道洛必达题，但不要现在加入。','planner','plan'),
 ('那里面哪些做错了？','data_query','history'),
 ('我改变主意了，取消刚才的安排。','qa','practice_request_cancel'),
 ('只加入一道洛必达题，不要多加。','planner','plan'),
])
def test_original_route_failure(text,capability,intent):
    result=route_message(text,StudyContext(surface='chat'))
    assert (result.capability,result.intent)==(capability,intent)

def evidence(factory,sid):
    with factory() as db:
        row=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,ChatMessage.role=='assistant').order_by(ChatMessage.seq.desc()).limit(1))
        return row.metadata_['read_only_data_query']

def test_choice_history_chain_really_filters_and_keeps_scope(factory):
    sid=support.session(factory)
    for text in ['我题库里有多少道数学二的可练题？','那其中洛必达法则的题有多少道？','其中选择题有多少道？','这些题我做过几道？','那里面哪些做错了？']:
        frames=support.talk(factory,sid,text)
        assert not any(e in {'practice_request','planner'} for e,d in frames)
        state=evidence(factory,sid)
        assert state['query_status']=='executed'
    state=evidence(factory,sid)
    assert state['query_state']['subject']=='考研数学'
    assert state['query_state']['question_types']==['single_choice','multiple_choice']
    assert len(state['scope_node_ids'])==1 and state['result_filter']=='wrong'

def test_public_only_excludes_personal_in_real_sql_result(factory):
    sid=support.session(factory)
    support.talk(factory,sid,'洛必达法则的可练题有多少道？')
    support.talk(factory,sid,'不要个人 AI 生成题，只要已有公共题库题。')
    state=evidence(factory,sid);condition=state['query_state']
    assert condition['excluded_source_categories']==['personal_ai_practice','personal_practice']
    from backend.services.assistant_data_queries import _questions_for_conditions
    with factory() as db:
        qs=_questions_for_conditions(db,condition,{UUID(v) for v in state['scope_node_ids']})
        assert all(not question_source_category(q).startswith('personal') for q in qs)
        assert state['question_count']==len(qs)

def test_source_only_question_keeps_last_scope_but_new_session_is_global(factory):
    sid=support.session(factory)
    support.talk(factory,sid,'洛必达法则的可练题有多少道？')
    original=evidence(factory,sid)['scope_node_ids']
    support.talk(factory,sid,'有没有历年真题？')
    state=evidence(factory,sid)
    assert state['scope_node_ids']==original and state['query_state']['source_categories']==['exam_curated']
    new=support.session(factory);support.talk(factory,new,'有没有历年真题？')
    assert evidence(factory,new)['scope_node_ids']==[]

def test_denied_arrangement_never_creates_request(factory):
    before=support.counts(factory);sid=support.session(factory)
    for text in ['给我讲讲导数计算，不要安排题目。','先不管之前的安排，讲讲幂级数。']:
        frames=support.talk(factory,sid,text)
        assert not any(e in {'practice_request','planner'} for e,d in frames)
    assert support.counts(factory)==before

def test_cancel_utterance_uses_same_session_resource_no_plan(factory):
    from backend.models.practice_request import PracticeRequest
    sid=support.session(factory)
    frames=support.talk(factory,sid,'给我安排一道洛必达题。')
    rid=UUID(next(d for e,d in frames if e=='practice_request')['id'])
    before=support.counts(factory)
    frames=support.talk(factory,sid,'我改变主意了，取消刚才的安排。')
    assert not any(e in {'practice_request','planner'} for e,d in frames)
    with factory() as db:assert db.get(PracticeRequest,rid).status=='declined'
    assert support.counts(factory)==before

def test_study_and_qa_bank_selection_share_public_only_constraint(factory):
    from backend.services.learning_assistant_service import planner_handoff
    from backend.services.study_context_service import validate_study_context
    target=support.session(factory,'study')
    with factory() as db:
        ctx=validate_study_context(db,session_id=target,context=StudyContext(surface='study'),now=support.TEST_NOW)
    handoff=planner_handoff(factory,ctx=ctx,user_id=UUID(int=1),message='讲讲洛必达法则，再从题库挑一道加入今日卷。',
        route=route_message('讲讲洛必达法则，再从题库挑一道加入今日卷。',ctx),now=support.TEST_NOW)
    assert handoff.constraints['existing_bank_only'] is True

def test_parallel_server_created_session_registration_does_not_lose_ownership(tmp_path):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from scripts.naiwa_v31_handoff_policy import register_session
    p=tmp_path/'sessions.json';p.write_text('{}',encoding='utf-8')
    owner={'epoch':4,'purpose':'qa','principal':'controlled-test'}
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda i:register_session(p,str(i),owner),range(20)))
    assert len(json.loads(p.read_text(encoding='utf-8')))==20
    with pytest.raises(RuntimeError,match='owner_collision'):
        register_session(p,'0',{**owner,'principal':'forged-other-owner'})

@pytest.mark.parametrize('kind,code',[('closed','provider_egress_closed'),('network','provider_network'),('timeout','provider_timeout')])
@pytest.mark.parametrize('after_delta',[False,True])
def test_actual_stream_queue_classifies_failure_without_retry(kind,code,after_delta):
    import asyncio,httpx
    from backend.chat.service import _stream_deltas
    from backend.errors import AppError
    from scripts.phase5_eval_meter import BudgetStop
    class Provider:
        model='OFFLINE TEST';timeout=1;calls=0
        async def stream(self,*args,**kwargs):
            self.calls+=1
            if after_delta:yield '中文 $\\frac{1}{2}$'
            if kind=='closed':raise BudgetStop('paid_exit_closed')
            if kind=='network':raise httpx.RemoteProtocolError('offline simulation')
            raise httpx.ReadTimeout('offline simulation')
    class Request:
        async def is_disconnected(self):await asyncio.sleep(.01);return False
    provider=Provider();parts=[]
    async def collect():
        return [v async for v in _stream_deltas(provider,[],parts,Request(),{'disconnected':False},'讲一个例子')]
    with pytest.raises(AppError) as caught:asyncio.run(collect())
    assert caught.value.code==code and caught.value.retryable is False
    assert provider.calls==1
    assert bool(parts)==after_delta
