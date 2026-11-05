"""Current-baseline-only final5 acceptance. No legacy stage2 factory use."""
from pathlib import Path
import sys,os,json,time,hashlib,secrets,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_naiwa_experience_20261020 import RUN,HOME,MODULES,save,snapshot,existing_manager,database_url
from scripts.naiwa_freeze_gate_20261021 import ROUND,FinalRoundGate,SCENE,disable_provider_retries,BudgetStop
BASE=ROOT/'storage/quality-audits/naiwa-final-zero-precheck-20261021/retest-baseline.json'
OUT=ROOT/'storage/quality-audits/naiwa-current-baseline-real5-20261021'
A='根据最近错题和薄弱点，给出90分钟数学二复习建议，未经确认不要创建计划。'
B='这道题不错，帮我生成一道更难的类似题。'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def current():return json.loads(json.dumps(snapshot('current-baseline-integrity-'+str(time.time_ns())),default=str))

def verify(scene=None,request=None):
    baseline=read(BASE)
    assert all(sha(ROOT/p)==h for p,h in baseline['expected_source_hashes'].items()),'current_baseline_source_mismatch'
    if OUT.exists() and (OUT/'authorization.json').exists():
        auth=read(OUT/'authorization.json')
        assert auth['baseline_sha256']==sha(BASE)
        assert sha(Path(__file__))==auth['runtime_sha256'],'runtime_source_changed'
    for p,h in baseline['ledger_sha256'].items():
        if str(ROOT/p)!=baseline['ledger_path']:assert sha(ROOT/p)==h,'old_ledger_changed'
    pg=existing_manager();assert pg.owner['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    now=current();assert now['identity']==baseline['database']['identity']
    for table,rows in baseline['database'].items():
        if not isinstance(rows,list):continue
        key=lambda r:str(r.get('id',r.get('kp_id')))
        actual={key(r):r for r in now[table]}
        assert all(actual.get(key(r))==r for r in rows),'historical_row_changed:'+table
        new=set(actual)-{key(r) for r in rows}
        allowed={'chat_sessions','chat_messages','learning_tasks'}|({'questions','question_versions','personal_generation_batches'} if scene=='GENERATE' else set())
        assert not new or table in allowed,'unapproved_new_rows:'+table
    return now

def prepare():
    assert not OUT.exists()
    before=verify()
    assert before==read(BASE)['database'],'database_drift_before_test'
    assert sha(ROUND/'provider-ledger.json')==read(BASE)['ledger_sha256'][str((ROUND/'provider-ledger.json').relative_to(ROOT))]
    ledger=read(ROUND/'provider-ledger.json');assert ledger['requests']==[] and not ledger.get('stop_reason')
    assert not read(ROUND/'control.json')['paid_enabled']
    loaded=read(RUN/'loaded-code.json');runtime=read(RUN/'runtime.json')
    assert loaded['pid']==runtime['backend_pid'] and loaded['physical_gate']['preparation_permanently_closed']
    assert all(sha(ROOT/p)==h for p,h in loaded['source_sha256'].items())
    assert not [t for t in before['learning_tasks'] if t['status'] in {'running','pending','generating','executing'}]
    assert not [m for m in before['chat_messages'] if m.get('status') in {'generating','pending','streaming'}]
    ps="$l=Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 63044,63045,63046; @($l | ForEach-Object { $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.OwningProcess); [pscustomobject]@{port=$_.LocalPort;pid=$p.ProcessId;command=$p.CommandLine;executable=$p.ExecutablePath} }) | ConvertTo-Json"
    processes=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',ps],encoding='utf-8-sig'))
    for port,key in [(63044,'postgres_pid'),(63045,'backend_pid'),(63046,'frontend_pid')]:
        rows=[p for p in processes if p['port']==port];assert len(rows)==1 and rows[0]['pid']==runtime[key]
    assert 'restore_naiwa_experience_20261020:sealed_app' in next(p['command'] for p in processes if p['port']==63045)
    OUT.mkdir()
    save(OUT/'database-before.json',before);save(OUT/'processes-before.json',processes)
    save(OUT/'authorization.json',{'explicit_user_authorized':True,'total':5,'AGENT':4,'GENERATE':1,
        'baseline_sha256':sha(BASE),'runtime_sha256':sha(Path(__file__)),'inputs':{'AGENT':A,'GENERATE':B},
        'source':'current human message: final stage2 max5, Agent pass prerequisite for generation','paid_enabled_on_start':False})
    shutil.copy2(BASE,OUT/'retest-baseline.json');shutil.copy2(ROUND/'provider-ledger.json',OUT/'ledger-before.json')
    for name in ['loaded-code.json','runtime.json','backend.log','supervisor.log']:shutil.copy2(RUN/name,OUT/('before-'+name))
    (OUT/'browser-nonce.txt').write_text(secrets.token_urlsafe(32),encoding='utf-8')
    save(OUT/'sessions.json',{})
    print('PASS current baseline, actual process identity, retained history, new ledger0 and closed exit')

def real_app():
    from backend.config import get_settings
    from sqlalchemy.engine import make_url
    from backend.chat.http_clients import configure_isolated_provider_http,policy
    settings=get_settings();u=make_url(str(settings.active_database_url))
    assert (u.host,u.port,u.database)==('127.0.0.1',63044,'naiwa_experience_test')
    assert settings.app_env=='test' and settings.llm_model=='deepseek-flash' and settings.llm_base_url.rstrip('/')=='https://api.deepseek.com'
    verify();configure_isolated_provider_http(settings)
    gate=FinalRoundGate(preparation=False);gate.seal('current_runtime_loaded_waiting_for_scoped_browser')
    gate.before_send=verify;gate.install();sys.addaudithook(gate.socket_guard)
    try:sys.audit('socket.connect',None,('192.0.2.1',80))
    except BudgetStop:pass
    else:raise AssertionError('socket_guard_failed')
    from backend.chat.service import Provider
    disable_provider_retries(Provider)
    from backend.app import create_app
    application=create_app();application.state.final_round_gate=gate
    loaded={}
    import importlib
    for name in MODULES:
        p=Path(importlib.import_module(name).__file__).resolve();assert p.is_relative_to(ROOT)
        loaded[str(p.relative_to(ROOT)).replace('\\','/')]=sha(p)
    loaded[str(Path(__file__).relative_to(ROOT)).replace('\\','/')]=sha(Path(__file__))
    save(RUN/'loaded-code.json',{'pid':os.getpid(),'workspace':str(ROOT),'python':sys.executable,
        'source_sha256':loaded,'provider':'real-deepseek-current-baseline-final5-initially-closed',
        'baseline_sha256':sha(BASE),'http_policy':policy(),'guard_self_check_passed':True,
        'physical_gate':{'installed':True,'global_limit':5,'scene_limits':{'AGENT':4,'GENERATE':1},'preparation_permanently_closed':False},'loaded_at':time.time()})
    class Scoped:
        async def __call__(self,scope,receive,send):
            from starlette.responses import JSONResponse
            import hmac,re
            headers=dict(scope.get('headers',[]));scene=headers.get(b'x-naiwa-final-scene',b'').decode();nonce=headers.get(b'x-naiwa-final-nonce',b'').decode()
            valid=bool(nonce) and hmac.compare_digest(nonce,(OUT/'browser-nonce.txt').read_text().strip())
            method,path=scope.get('method','GET'),scope.get('path','')
            if scene=='GENERATE' and not (OUT/'agent-quality-pass.json').exists():valid=False
            if method not in {'GET','HEAD','OPTIONS'}:
                match=re.fullmatch(r'/api/chat/sessions/([0-9a-f-]+)/assistant(?::|%3A)stream',path)
                allowed=valid and scene in {'AGENT','GENERATE'} and (method=='POST' and path=='/api/chat/sessions' or method=='POST' and match and read(OUT/'sessions.json').get(scene)==match[1])
                if not allowed:return await JSONResponse({'error':{'code':'current_retest_write_not_authorized','message':'只允许本轮明确授权的会话与操作。'}},status_code=403)(scope,receive,send)
            token=SCENE.set(scene if valid and scene in {'AGENT','GENERATE'} else None)
            async def labeled(message):
                if message['type']=='http.response.start':message.setdefault('headers',[]).extend([(b'x-naiwa-experience',b'current-baseline-real5'),(b'x-naiwa-backend-pid',str(os.getpid()).encode())])
                await send(message)
            try:await application(scope,receive,labeled)
            finally:SCENE.reset(token)
    return Scoped()

def serve():
    from desktop.postgres import _run
    import httpx,socket
    baseline=read(BASE)
    assert all(sha(ROOT/p)==h for p,h in baseline['expected_source_hashes'].items())
    assert sha(Path(__file__))==read(OUT/'authorization.json')['runtime_sha256']
    pg=existing_manager();children=[];handles=[];runtime=None
    for port in (63044,63045,63046):
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    pg.lock.acquire()
    try:
        assert _run([pg.binary('pg_ctl'),'-D',str(pg.cluster),'-l',str(OUT/'postgres.log'),'-o','-p 63044 -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic','-w','-t','30','start'],timeout=45,capture=False).returncode==0
        identity=pg._identity();assert identity;pg._owned_identity=identity
        verify()
        from backend.config import get_settings
        from backend.services.model_settings_service import load_local_settings
        effective=load_local_settings(get_settings());assert effective.llm_api_key and effective.llm_model=='deepseek-flash' and effective.llm_base_url.rstrip('/')=='https://api.deepseek.com'
        key=effective.llm_api_key;key=key.get_secret_value() if hasattr(key,'get_secret_value') else str(key)
        env={**os.environ,'APP_ENV':'test','DATABASE_URL':database_url(pg).render_as_string(hide_password=False),'TEST_DATABASE_URL':database_url(pg).render_as_string(hide_password=False),
            'KAOYAN_OWNED_TEST_PORT':'63044','LLM_API_KEY':key,'LLM_BASE_URL':effective.llm_base_url,'LLM_MODEL':effective.llm_model,
            'LLM_STREAM_INCLUDE_USAGE':'true','MODEL_SETTINGS_PATH':str(OUT/'isolated-settings.bin'),'UPLOAD_DIR':str(HOME/'uploads'),'CHROMA_DIR':str(HOME/'chroma'),
            'MODEL_CACHE_DIR':str(ROOT/'storage/models'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','ANONYMIZED_TELEMETRY':'False','DO_NOT_TRACK':'1','OTEL_SDK_DISABLED':'true',
            'PYTHONIOENCODING':'utf-8','ALLOWED_WEB_ORIGINS':'["http://127.0.0.1:63046"]','VITE_API_PROXY_TARGET':'http://127.0.0.1:63045',
            'NAIWA_REAL_RETEST_BUDGET7':'0','NAIWA_FINAL_ROUND_STAGE2':'0'}
        commands=[[sys.executable,'-m','uvicorn','scripts.naiwa_stage2_current_20261021:real_app','--factory','--host','127.0.0.1','--port','63045'],
            [r'D:\应用安装包\node.exe','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','63046','--strictPort']]
        for name,command,cwd in zip(('backend','frontend'),commands,(ROOT,ROOT/'frontend')):
            h=(OUT/(name+'.log')).open('a',encoding='utf-8');handles.append(h)
            children.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
        runtime={'workspace':str(ROOT),'cluster_id':pg.owner['cluster_id'],'database':current()['identity'],'supervisor_pid':os.getpid(),
            'postgres_pid':identity[0],'backend_pid':children[0].pid,'frontend_pid':children[1].pid,'commands':commands,'status':'starting','paid_enabled_on_start':False}
        save(OUT/'runtime.json',runtime)
        with httpx.Client(trust_env=False,timeout=3) as client:
            for _ in range(80):
                assert all(c.poll() is None for c in children),'child_exited'
                try:
                    r=client.get('http://127.0.0.1:63046/api/health')
                    if r.status_code==200:
                        assert r.headers['x-naiwa-experience']=='current-baseline-real5' and r.json()['database']=='connected'
                        runtime.update(status='running',health=r.json());save(OUT/'runtime.json',runtime);break
                except httpx.HTTPError:pass
                time.sleep(1)
            else:raise RuntimeError('startup_timeout')
        while not (OUT/'stop.request').exists():
            assert all(c.poll() is None for c in children),'child_exited';time.sleep(1)
    finally:
        FinalRoundGate(preparation=True).seal('current_retest_shutdown')
        for c in reversed(children):
            if c.poll() is None:c.terminate();c.wait(timeout=25)
        for h in handles:h.close()
        pg.stop()
        if runtime:runtime['status']='stopped';save(OUT/'runtime.json',runtime)

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    elif sys.argv[1]=='serve':serve()
    elif sys.argv[1]=='close':FinalRoundGate(preparation=True).seal('current_retest_explicitly_closed');print('paid exit closed')
    elif sys.argv[1]=='bind-runtime':
        baseline=read(BASE)
        assert current()==baseline['database']
        assert all(sha(ROOT/p)==h for p,h in baseline['expected_source_hashes'].items())
        assert all(sha(ROOT/p)==h for p,h in baseline['ledger_sha256'].items())
        assert read(ROUND/'provider-ledger.json')['requests']==[] and not read(ROUND/'control.json')['paid_enabled']
        auth=read(OUT/'authorization.json');save(OUT/'authorization-before-wrapper-startup-fix.json',auth)
        auth['runtime_sha256']=sha(Path(__file__));save(OUT/'authorization.json',auth)
        print('Runtime hash bound before activation; baseline checks unchanged')
