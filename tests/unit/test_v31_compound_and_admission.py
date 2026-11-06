from types import SimpleNamespace
from copy import deepcopy
import pytest
from backend.services.assistant_router import route_message
from scripts.naiwa_v31_handoff_policy import admit_handoff

@pytest.mark.parametrize('text,capability,intent,explanation',[
 ('洛必达法则是怎么样的，帮我从题库里面拿出一道放进今日卷。','planner','plan',True),
 ('讲讲洛必达法则，再从题库挑一道加入今日卷。','planner','plan',True),
 ('洛必达法则是什么？先给我讲清楚，题目可以先选好但不要加入。','qa','qa',True),
 ('帮我找一道洛必达的题，先给我看看。','data_query','find',False),
 ('给我安排一道洛必达题。','planner','plan',False),
 ('先别加题，只解释洛必达法则。','qa','qa',True),
 ('没有合格题也没关系，你先讲解。','qa','qa',True),
 ('先讲知识点，再问我是否要安排题目。','qa','qa',True),
 ('我说的是题库已有的题，不要生成新题。','qa','qa',False),
])
def test_independent_goals(text,capability,intent,explanation):
    r=route_message(text,SimpleNamespace(question_id=None,knowledge_node_ids=[]))
    assert (r.capability,r.intent)==(capability,intent)
    assert bool(r.explanation_request) is explanation

RID='00000000-0000-0000-0000-000000000001'
SOURCE='qa';TARGET='study'
def data():
    return dict(method='POST',path=f'/api/practice-requests/{RID}/send',
        body={'source_conversation_id':SOURCE,'target_study_session_id':TARGET},
        resource={'id':RID,'source_conversation_id':SOURCE,'status':'draft','expires_at':200,'confirmation_a':False},
        sessions={SOURCE:{'purpose':'qa','epoch':2,'principal':'local'},TARGET:{'purpose':'study','epoch':2,'principal':'local'}},
        window={'enabled':True,'expires_at':200,'epoch':2},epoch=2,principal='local',now=100)

def test_exact_matching_route_enters_business():assert admit_handoff(**data())==(True,'exact_owned_handoff')

@pytest.mark.parametrize('case',['source','target','sent','expired','path','method','epoch','principal','closed','draft_expired','task_owner'])
def test_rejection_before_writes_or_budget(case):
    d=data()
    if case=='source':d['body']['source_conversation_id']='other'
    if case=='target':d['body']['target_study_session_id']='other'
    if case=='sent':d['resource']['status']='pending'
    if case=='expired':d['window']['expires_at']=99
    if case=='path':d['path']='/api/anything'
    if case=='method':d['method']='DELETE'
    if case=='epoch':d['sessions'][SOURCE]['epoch']=1
    if case=='principal':d['sessions'][SOURCE]['principal']='another'
    if case=='closed':d['window']['enabled']=False
    if case=='draft_expired':d['resource']['expires_at']=99
    if case=='task_owner':d['resource']['task_session_id']='other'
    before=deepcopy(d)
    assert admit_handoff(**d)[0] is False
    assert d==before  # no mutation, persistence, client construction or reservation

def test_plan_requires_the_bound_owned_study_session():
    d=data();d['path']=d['path'].replace('/send','/plan')
    d['resource'].update(status='pending',confirmation_a=True,target_study_session_id=TARGET)
    d['body']={'study_session_id':TARGET}
    assert admit_handoff(**d)[0]
    d['body']['study_session_id']='different'
    assert not admit_handoff(**d)[0]

def test_single_consumption_and_close_have_shared_atomic_boundary(tmp_path):
    from scripts.naiwa_v31_handoff_policy import consume_permit,close_window
    import json
    import concurrent.futures
    p=tmp_path/'window.json';p.write_text(json.dumps({'enabled':True,'epoch':2,'nonce':'trusted','expires_at':200}))
    def attempt(_):return consume_permit(window_path=p,claim_path=tmp_path/'claims'/'id.json',grant={'epoch':2},nonce='trusted',now=100)[0]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:assert sum(pool.map(attempt,range(10)))==1
    close_window(p)
    assert not consume_permit(window_path=p,claim_path=tmp_path/'claims'/'another.json',grant={'epoch':2},nonce='trusted',now=100)[0]
    assert not (tmp_path/'claims'/'another.json').exists()
