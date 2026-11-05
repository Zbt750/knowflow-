"""Explicit final5 runtime; all paid operations still require scoped browser gate.

No enable-on-start. No migrations/fixtures/cleanup. Older ledgers are read-only.
"""
from pathlib import Path
import sys,os,json,time,hashlib,shutil,secrets
from uuid import UUID,uuid4
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_naiwa_experience_20261020 import RUN,MODULES,snapshot,save,existing_manager,database_url
from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate,ROUND,SCENE,disable_provider_retries,BudgetStop
OUT=ROOT/'storage/quality-audits/naiwa-final-real-retest-20261021'
OLD=[ROOT/'storage/quality-audits/naiwa-real-20261020/provider-ledger.json',
     ROOT/'storage/quality-audits/naiwa-real-retest-20261020-budget7/provider-ledger.json']
A='根据最近错题和薄弱点，给出90分钟数学二复习建议，未经确认不要创建计划。'
B='这道题不错，帮我生成一道更难的类似题。'

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def sources():
    return [ROOT/(name.replace('.','/')+'.py') for name in MODULES]+[
        ROOT/'scripts/restore_naiwa_experience_20261020.py',ROOT/'scripts/naiwa_freeze_gate_20261021.py',Path(__file__).resolve()]

def prepare():
    OUT.mkdir(exist_ok=False,parents=True)
    before=json.loads(json.dumps(snapshot('final5-before'),default=str))
    assert before['identity']=={'db':'naiwa_experience_test','role':'kaoyan_app','port':'63044'}
    assert read(RUN/'runtime.json')['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    assert read(ROUND/'provider-ledger.json')['requests']==[]
    assert read(ROUND/'control.json')['paid_enabled'] is False
    save(OUT/'database-before.json',before)
    hashes={str(p.relative_to(ROOT)):sha(p) for p in OLD}
    prior=read(ROUND.parent/'stage1-closeout/final-verification.json')
    assert all(hashes[k]==v for k,v in prior['ledger_hashes'].items() if k in hashes)
    save(OUT/'authorization.json',{'explicit_user_authorized':True,'total':5,'AGENT':4,'GENERATE':1,
        'source_attachment_sha256':sha(Path('C:/Users/ZBT/.codex/attachments/73b43f60-3a8d-4af1-906c-4a48bf620ee7/已粘贴的文本.txt')),
        'inputs':{'AGENT':A,'GENERATE':B},'paid_enabled_on_start':False})
    save(OUT/'baseline.json',{'database':before,'old_ledger_hashes':hashes,
        'expected_source_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sources()},
        'round_ledger':str(ROUND/'provider-ledger.json')})
    (OUT/'browser-nonce.txt').write_text(secrets.token_urlsafe(32),encoding='utf-8')
    save(OUT/'sessions.json',{})
    for name in ['runtime.json','loaded-code.json','backend.log','supervisor.log']:
        shutil.copy2(RUN/name,OUT/('before-'+name))
    # Exact input offline scope check; no messages or model request.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.schemas.learning_assistant import StudyContext
    from backend.services.assistant_router import route_message
    from backend.services.learning_assistant_service import planner_handoff
    factory=sessionmaker(create_engine(database_url(existing_manager()),connect_args={'options':'-c default_transaction_read_only=on'}))
    ctx=StudyContext(surface='study',subject='考研数学',knowledge_node_ids=[UUID('32a29e1e-8ae3-41fc-9322-43f727596819')],
        question_id=UUID('9ba9c177-26a2-4918-bf84-b85159f9b002'),question_version_id=UUID('92c57d4d-f0bf-4df2-b9b2-c949a3d43904'),conversation_id=uuid4())
    route=route_message(A,ctx)
    handoff=planner_handoff(factory,ctx=ctx,user_id=uuid4(),message=A,route=route,now=datetime.now(timezone.utc))
    assert route.capability=='planner' and route.intent=='recommend'
    assert handoff.constraints['scope_origin']=='explicit_subject_scope'
    save(OUT/'exact-input-preflight.json',{'route':route.public_dict(),'handoff':handoff.model_dump(mode='json'),'real_calls':0})
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    effective=load_local_settings(get_settings())
    assert effective.llm_api_key and effective.llm_model=='deepseek-flash'
    assert effective.llm_base_url.rstrip('/')=='https://api.deepseek.com'
    save(OUT/'provider-preflight.json',{'configured':True,'model':effective.llm_model,'endpoint':'official DeepSeek',
        'key_logged':False,'real_calls':0})
    print('Final5 baseline and exact input verified; no paid request; runtime switch still closed')

def verify(scene=None,request=None):
    expected=read(OUT/'baseline.json')
    assert all(sha(ROOT/p)==h for p,h in expected['expected_source_hashes'].items()),'source_hash_changed'
    assert all(sha(ROOT/p)==h for p,h in expected['old_ledger_hashes'].items()),'old_ledger_changed'
    now=json.loads(json.dumps(snapshot('final5-integrity-current'),default=str))
    assert now['identity']==expected['database']['identity']
    for table,previous in expected['database'].items():
        if not isinstance(previous,list):continue
        key=lambda r:str(r.get('id',r.get('kp_id')))
        present={key(r):r for r in now[table]}
        assert all(present.get(key(r))==r for r in previous),'historical_row_changed:'+table
    return now

def real_app():
    from backend.config import get_settings
    from sqlalchemy.engine import make_url
    auth=read(OUT/'authorization.json');assert auth['explicit_user_authorized'] and auth['total']==5
    settings=get_settings();url=make_url(str(settings.active_database_url))
    assert (url.host,url.port,url.database)==('127.0.0.1',63044,'naiwa_experience_test')
    assert settings.app_env=='test' and settings.llm_model=='deepseek-flash'
    assert settings.llm_base_url.rstrip('/')=='https://api.deepseek.com'
    from backend.chat.http_clients import configure_isolated_provider_http
    configure_isolated_provider_http(settings)
    verify()
    gate=FinalRoundGate(preparation=False)
    gate.seal('explicit_stage2_runtime_loaded_but_browser_operation_not_enabled')
    gate.before_send=verify
    gate.install()
    sys.addaudithook(gate.socket_guard)
    try:sys.audit('socket.connect',None,('192.0.2.1',80))
    except BudgetStop:pass
    else:raise RuntimeError('non_model_egress_not_blocked')
    from backend.chat.service import Provider
    disable_provider_retries(Provider)
    from backend.app import create_app
    application=create_app()
    application.state.final_round_gate=gate
    hashes={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sources()}
    save(RUN/'loaded-code.json',{'pid':os.getpid(),'workspace':str(ROOT),'python':sys.executable,
        'source_sha256':hashes,'provider':'real-deepseek-final5-scoped-initially-closed',
        'guard_self_check_passed':True,'ledger':str(gate.path),'physical_gate':{'installed':gate.installed,
            'global_limit':5,'scene_limits':{'AGENT':4,'GENERATE':1},'preparation_permanently_closed':False},'loaded_at':time.time()})
    class Scoped:
        async def __call__(self,scope,receive,send):
            from starlette.responses import JSONResponse
            headers=dict(scope.get('headers',[]));nonce=headers.get(b'x-naiwa-final-nonce',b'').decode()
            scene=headers.get(b'x-naiwa-final-scene',b'').decode()
            import hmac,re
            valid=bool(nonce) and hmac.compare_digest(nonce,(OUT/'browser-nonce.txt').read_text(encoding='utf-8').strip())
            method,path=scope.get('method','GET'),scope.get('path','')
            if method not in {'GET','HEAD','OPTIONS'}:
                sessions=read(OUT/'sessions.json')
                match=re.fullmatch(r'/api/chat/sessions/([0-9a-f-]+)/assistant(?::|%3A)stream',path)
                allowed=valid and (method=='POST' and path=='/api/chat/sessions' or
                    method=='POST' and match and sessions.get(scene)==match[1] and scene in {'AGENT','GENERATE'})
                if not allowed:
                    return await JSONResponse({'error':{'code':'final_retest_write_not_authorized','message':'仅允许本轮会话与指定复验操作。'}},status_code=403)(scope,receive,send)
            token=SCENE.set(scene if valid and scene in {'AGENT','GENERATE'} else None)
            async def labeled(message):
                if message['type']=='http.response.start':
                    message.setdefault('headers',[]).extend([(b'x-naiwa-experience',b'final-real-retest5'),
                        (b'x-naiwa-backend-pid',str(os.getpid()).encode())])
                await send(message)
            try:await application(scope,receive,labeled)
            finally:SCENE.reset(token)
    return Scoped()

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    elif sys.argv[1]=='verify':
        verify();print('Historical integrity PASS; no model request')
    elif sys.argv[1]=='close':
        FinalRoundGate(preparation=True).seal('final_real_retest_finished_or_stopped')
        print('Final5 paid exit closed')
