"""Local fixed-Provider acceptance host; no paid model client or ledger writes."""
from pathlib import Path
import sys,os,json,time,subprocess,hashlib,secrets,re,threading
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_v31_audit import OUT,HOME,read,sha
RUN=OUT/('runtime-'+os.environ.get('NAIWA_V31_EPOCH','1'))
API=63145;WEB=63146

def put(path,value):
    from scripts.naiwa_freeze_gate_20261021 import atomic_json
    atomic_json(path,value)

def sources():
    paths=list((ROOT/'backend').rglob('*.py'))+list((ROOT/'frontend/src').rglob('*'))+[Path(__file__),
        ROOT/'scripts/naiwa_v31_handoff_policy.py',ROOT/'scripts/manual_naiwa_experience.py']
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths if p.is_file() and '__pycache__' not in str(p)}

def capture(factory):
    from sqlalchemy import text
    result={}
    with factory() as db:
        db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        for table in read(OUT/'database-before.json')['schema']:
            result[table]=[dict(r._mapping) for r in db.execute(text('SELECT * FROM public."'+table+'"'))]
    return json.loads(json.dumps(result,ensure_ascii=False,default=str))

def app():
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    settings=get_settings();u=make_url(str(settings.active_database_url))
    assert (settings.app_env,u.host,u.port,u.database)==('test','127.0.0.1',63044,'naiwa_experience_test')
    epoch=read(RUN/'epoch.json');assert sources()==epoch['source_sha256']
    from scripts import manual_naiwa_experience as fixed
    fixed.HOME=RUN
    def no_external(event,args):
        if event=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','localhost','::1'}:raise RuntimeError('v31_external_dns_closed')
        if event=='socket.connect' and not (isinstance(args[1],tuple) and args[1][:2] in [('127.0.0.1',63044),('::1',63044)]):raise RuntimeError('v31_external_socket_closed')
    sys.addaudithook(no_external)
    from backend.chat import service
    from backend.chat.http_clients import configure_isolated_provider_http
    configure_isolated_provider_http(settings);service.Provider=fixed.FixedProvider
    from backend.app import create_app
    application=create_app();application.state.personal_generation_provider=fixed.FixedProvider(structured_generation=True)
    put(RUN/'loaded-code.json',{'pid':os.getpid(),'epoch':epoch['epoch'],'source_sha256':sources(),
        'provider':'FIXED-OFFLINE-NO-PAID-MODEL','paid_enabled':False,'external_network':'blocked except owned PG63044'})
    lock=threading.Lock()

    @application.middleware('http')
    async def scope(request,call_next):
        from starlette.responses import JSONResponse
        method=request.method;path=request.url.path
        owned=read(RUN/'sessions.json');control=read(RUN/'window.json')
        if method in {'GET','HEAD','OPTIONS'}:response=await call_next(request)
        else:
            body=await request.body()
            try:payload=json.loads(body or b'{}')
            except ValueError:payload={}
            active=(control['enabled'] and control['expires_at']>time.time()
                and control['epoch']==epoch['epoch'] and request.headers.get('x-naiwa-v31')==control['nonce']
                and request.headers.get('origin')==f'http://127.0.0.1:{WEB}')
            create=method=='POST' and path=='/api/chat/sessions' and payload.get('purpose','qa') in {'qa','study'} and payload.get('mode','builtin')=='builtin'
            chat=re.fullmatch(r'/api/chat/sessions/([0-9a-f-]{36})/assistant:stream',path)
            task=re.fullmatch(r'/api/learning-tasks/([0-9a-f-]{36})/(confirm|cancel)',path)
            permitted=bool(create or (method=='POST' and chat and chat[1] in owned))
            handoff=re.fullmatch(r'/api/practice-requests/([0-9a-f-]{36})/(send|plan|decline)',path)
            if handoff and active:
                from uuid import UUID
                from backend.models.practice_request import PracticeRequest
                from backend.models.learning_task import LearningTask
                from scripts.naiwa_v31_handoff_policy import admit_handoff
                with application.state.session_factory() as db:
                    row=db.get(PracticeRequest,UUID(handoff[1]))
                    linked=db.get(LearningTask,row.planner_task_id) if row and row.planner_task_id else None
                    resource=None if not row else {'id':str(row.id),'source_conversation_id':str(row.source_conversation_id),
                        'status':row.status,'expires_at':row.expires_at.timestamp(),
                        'confirmation_a':row.request.get('confirmation_a'),
                        'target_study_session_id':row.request.get('target_study_session_id'),
                        'task_session_id':str(linked.session_id) if linked else None}
                permitted,reason=admit_handoff(method=method,path=path,body=payload,resource=resource,sessions=owned,
                    window=control,epoch=epoch['epoch'],principal='v31-local-test')
                if permitted and handoff[2]=='send':
                    from scripts.naiwa_v31_handoff_policy import consume_permit
                    permitted,reason=consume_permit(window_path=RUN/'window.json',
                        claim_path=RUN/'handoff-claims'/f'{handoff[1]}.json',nonce=request.headers.get('x-naiwa-v31'),
                        grant={'method':method,'path':path,'request_id':handoff[1],
                            'source':resource['source_conversation_id'],'target':payload['target_study_session_id'],
                            'epoch':epoch['epoch'],'principal':'v31-local-test','expires_at':control['expires_at'],
                            'cluster_id':'eb3800c77c3c40f6ac12eb21112df36c','state':'reserved_before_business_write'})
                with (RUN/'handoff-admission.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps({'method':method,'path':path,'source':resource.get('source_conversation_id') if resource else None,
                        'target':payload.get('target_study_session_id',payload.get('study_session_id')),
                        'epoch':epoch['epoch'],'allowed':permitted,'reason':reason,'time':time.time()})+'\n')
            if task and method=='POST':
                from uuid import UUID
                from backend.models.learning_task import LearningTask
                with application.state.session_factory() as db:
                    row=db.get(LearningTask,UUID(task[1]));permitted=bool(row and str(row.session_id) in owned)
            if not(active and permitted):
                response=JSONResponse({'error':{'code':'v31_scoped_write_denied','message':'本轮精确授权尚未覆盖此操作，未执行写入。'}},status_code=403)
                with (RUN/'denied.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'path':path,'method':method,'epoch':epoch['epoch'],'active':active})+'\n')
            else:
                with lock:
                    number=len(list((RUN/'writes').glob('*-before.json')))+1
                    put(RUN/'writes'/f'{number:03}-before.json',capture(application.state.session_factory))
                response=await call_next(request)
                # Buffer only the short session creation response, never SSE.
                if create and response.status_code<300:
                    chunks=[chunk async for chunk in response.body_iterator]
                    raw=b''.join(chunks);result=json.loads(raw)
                    from scripts.naiwa_v31_handoff_policy import register_session
                    register_session(RUN/'sessions.json',result['session_id'],
                        {'purpose':payload.get('purpose','qa'),'epoch':epoch['epoch'],'principal':'v31-local-test'})
                    from starlette.responses import Response
                    response=Response(raw,status_code=response.status_code,headers=dict(response.headers),media_type='application/json')
                if create:put(RUN/'writes'/f'{number:03}-after.json',capture(application.state.session_factory))
                else:
                    original=response.body_iterator
                    async def completed_body():
                        try:
                            async for chunk in original:yield chunk
                        finally:put(RUN/'writes'/f'{number:03}-after.json',capture(application.state.session_factory))
                    response.body_iterator=completed_body()
        response.headers['x-naiwa-backend-pid']=str(os.getpid())
        response.headers['x-naiwa-v31-epoch']=str(epoch['epoch'])
        return response
    return application

def serve():
    import socket,httpx
    from scripts.restore_naiwa_experience_20261020 import existing_manager,database_url
    for port in (API,WEB):
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    pg=existing_manager()
    from scripts.naiwa_freeze_gate_20261021 import process_started
    identity=pg._identity()
    if identity:
        try:process_started(identity[0])
        except ProcessLookupError:pass
        else:raise RuntimeError('stop original isolated supervisor first; never bypass single-backend DB guard')
    RUN.mkdir(exist_ok=True);(RUN/'writes').mkdir(exist_ok=True)
    assert not (RUN/'epoch.json').exists(),'never overwrite epoch'
    pg.lock.acquire()
    from desktop.postgres import _run
    result=_run([pg.binary('pg_ctl'),'-D',str(pg.cluster),'-l',str(RUN/'postgres.log'),'-o',
        '-p 63044 -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic','-w','-t','30','start'],timeout=45,capture=False)
    identity=pg._identity();assert result.returncode==0 and identity
    pg._owned_identity=identity
    put(RUN/'epoch.json',{'epoch':int(os.environ.get('NAIWA_V31_EPOCH','1')),'source_sha256':sources(),'pg_identity':list(identity)})
    put(RUN/'sessions.json',{})
    put(RUN/'window.json',{'epoch':int(os.environ.get('NAIWA_V31_EPOCH','1')),'enabled':True,'nonce':secrets.token_hex(24),'expires_at':time.time()+3600,'paid_enabled':False})
    env={**os.environ,'APP_ENV':'test','DATABASE_URL':database_url(pg).render_as_string(hide_password=False),
        'TEST_DATABASE_URL':database_url(pg).render_as_string(hide_password=False),'KAOYAN_OWNED_TEST_PORT':'63044',
        'LLM_API_KEY':'offline-only','LLM_MODEL':'FIXED-OFFLINE-NO-PAID-MODEL','LLM_BASE_URL':'http://127.0.0.1:9',
        'MODEL_SETTINGS_PATH':str(RUN/'offline-settings.bin'),'UPLOAD_DIR':str(HOME/'uploads'),
        'CHROMA_DIR':str(HOME/'chroma'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
        'ANONYMIZED_TELEMETRY':'False','DO_NOT_TRACK':'1','OTEL_SDK_DISABLED':'true','PYTHONIOENCODING':'utf-8',
        'ALLOWED_WEB_ORIGINS':json.dumps([f'http://127.0.0.1:{WEB}']),'VITE_API_PROXY_TARGET':f'http://127.0.0.1:{API}'}
    commands=[[sys.executable,'-m','uvicorn','scripts.naiwa_v31_runtime:app','--factory','--host','127.0.0.1','--port',str(API)],
        [r'D:\应用安装包\node.exe','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',str(WEB),'--strictPort']]
    children=[];logs=[]
    try:
        for label,cmd,cwd in zip(('api','web'),commands,(ROOT,ROOT/'frontend')):
            log=(RUN/(label+'.log')).open('x',encoding='utf-8');logs.append(log)
            children.append(subprocess.Popen(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
        put(RUN/'processes.json',{'supervisor':os.getpid(),'api':children[0].pid,'web':children[1].pid,'pg':identity[0],'commands':commands,'paid_enabled':False})
        while not (RUN/'stop.request').exists():
            if any(p.poll() is not None for p in children):raise RuntimeError('v31_child_exited')
            time.sleep(1)
    finally:
        window=read(RUN/'window.json');window['enabled']=False;put(RUN/'window.json',window)
        for child in reversed(children):
            if child.poll() is None:child.terminate();child.wait(timeout=20)
        for log in logs:log.close()
        pg.stop()

if __name__=='__main__':
    if sys.argv[1]=='serve':serve()
    elif sys.argv[1]=='stop':(RUN/'stop.request').touch()
    elif sys.argv[1]=='close':
        from scripts.naiwa_v31_handoff_policy import close_window
        close_window(RUN/'window.json')
