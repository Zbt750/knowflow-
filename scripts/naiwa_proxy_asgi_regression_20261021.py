"""Real existing ASGI/SSE routes + retained PG; fixed error Providers only.

No lifespan/migrations/second listening backend. All writes are new marked
sessions/messages/tasks; no fixture seeding or cleanup, no external socket.
"""
from pathlib import Path
import os,sys,json,asyncio
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_proxy_zero_20261021 import OUT,read
from scripts.restore_naiwa_experience_20261020 import existing_manager,database_url,save
from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate,ROUND

url=database_url(existing_manager()).render_as_string(hide_password=False)
os.environ.update(APP_ENV='test',DATABASE_URL=url,TEST_DATABASE_URL=url,KAOYAN_OWNED_TEST_PORT='63044',
    LLM_API_KEY='zero-network-not-a-key',LLM_BASE_URL='http://127.0.0.1:9',LLM_MODEL='FIXED-ERROR-REGRESSION',
    MODEL_SETTINGS_PATH=str(OUT/'no-model-settings.bin'))
guard=FinalRoundGate(ROUND.parent/'proxy-asgi-network-guard',simulated=True,preparation=True)
sys.addaudithook(guard.socket_guard)

import httpx
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from backend.config import get_settings
get_settings.cache_clear()
from backend.app import create_app
from backend.api.routes import chat as chat_routes
from backend.errors import AppError
from backend.services.model_failure import MESSAGES
from scripts.phase5_eval_meter import BudgetStop
from uuid import uuid4

cases=[('proxy','proxy_not_allowed','provider_proxy_policy_blocked'),
       ('retry','transport_retries_not_allowed','provider_transport_retry_blocked'),
       ('budget','global_cap5','provider_budget_exhausted'),
       ('scene','paid_exit_closed_or_scene_unapproved','provider_scene_not_authorized'),
       ('closed','phase1_real_model_exit_permanently_closed','provider_egress_closed'),
       ('unknown','unfinished_send_state_unknown_reservation_retained','provider_request_state_unknown'),
       ('network',None,'provider_network'),('timeout',None,'provider_timeout'),('auth',None,'provider_auth_failed')]
engine=create_engine(url);factory=sessionmaker(engine)
with engine.connect() as connection:
    assert connection.execute(text('SELECT current_database(),current_user,current_setting(\'port\')')).one()==('naiwa_experience_test','kaoyan_app','63044')
application=create_app()
application.state.settings=get_settings();application.state.session_factory=factory
application.state.retrieval_stack=None
client=TestClient(application)
original=chat_routes.provider_from_settings
results=[]
try:
    for case,reason,code in cases:
        class FixedError:
            model='FIXED-ERROR-REGRESSION'
            def tool_turn(self,*args,**kwargs):
                if reason:
                    raise BudgetStop(reason,diagnostic={'source':'final_round_gate','stage':'pre_send',
                        'physical_request_attempts':0,'model_request_sent':False})
                if case=='network':error=httpx.RemoteProtocolError('fixture connection interrupted')
                elif case=='timeout':error=httpx.ReadTimeout('fixture timeout')
                else:error=httpx.HTTPStatusError('fixture auth failed',request=httpx.Request('POST','https://api.deepseek.com/chat/completions'),response=httpx.Response(401))
                try:raise error
                except Exception as cause:raise AppError('generation_failed',retryable=case!='auth') from cause
        chat_routes.provider_from_settings=lambda settings:FixedError()
        created=client.post('/api/chat/sessions',json={'title':'零付费代理诊断回归·'+case,'mode':'builtin','purpose':'study'})
        assert created.status_code==201,created.text
        session=created.json()['session_id']
        # Deliberately not the previous failed user input. These are labelled
        # engineering stimuli and not claimed to be student/model evaluation.
        body={'question':f'【零付费错误归因回归 {case}】给出30分钟数学二复习建议，只给建议，不创建计划。',
            'request_key':str(uuid4()),'study_context':{'surface':'study','conversation_id':session,
                'subject':'考研数学','knowledge_node_ids':['32a29e1e-8ae3-41fc-9322-43f727596819']}}
        response=client.post(f'/api/chat/sessions/{session}/assistant:stream',json=body)
        assert response.status_code==200,response.text
        (OUT/f'{case}.sse').write_text(response.text,encoding='utf-8')
        frames=[]
        for block in response.text.strip().split('\n\n'):
            lines=block.splitlines();event=next((l[6:].strip() for l in lines if l.startswith('event:')),None)
            data=next((json.loads(l[5:]) for l in lines if l.startswith('data:')),None)
            frames.append({'event':event,'data':data})
        error=next(f['data'] for f in frames if f['event']=='error')
        task=next(f['data'] for f in frames if f['event']=='planner')
        assert error['code']==task['error_code']==code
        assert error['message']==task['message']==MESSAGES[code]
        assert task['status']=='failed' and task['metrics']['provider_call_attempts']==1
        assert task['metrics']['physical_request_attempts']==(0 if reason else None)
        assert ('预算上限' in task['message'])==(case=='budget')
        if case=='proxy':assert '尚未发送' in task['message'] and error['retryable'] is False
        history=client.get(f'/api/chat/sessions/{session}/messages').json()
        again=client.get(f'/api/chat/sessions/{session}/messages').json()
        assert history==again and history[-1]['content']==task['message']
        assert history[-1]['assistant_error_code']==code and history[-1]['retryable']==error['retryable']
        persisted=client.get(f'/api/learning-tasks/{task["task_id"]}').json()
        assert persisted['metrics']==task['metrics']
        results.append({'case':case,'status':'PASS','session_id':session,'task_id':task['task_id'],'request':body,
            'error_event':error,'task':persisted,'history':history,'history_restored_identical':True,
            'method':'TestClient real ASGI/SSE routes and real PostgreSQL, FixedError Provider, no listening test API'})
        save(OUT/'asgi-regression.json',{'cases':results,'real_requests':0})
finally:
    chat_routes.provider_from_settings=original
    client.close();engine.dispose()
print(json.dumps({'asgi_sse_cases':'PASS','passed':len(results),'real_model_requests':0,'new_marked_sessions':len(results)}))
