"""V32 adapter of reviewed V31 fixed/offline runtime, retained DB, new epoch.

Clock override uses the existing FastAPI dependency, not DB edits/system clock.
No new API routes, paid clients or altered handoff policies.
"""
from pathlib import Path
import os,sys,time,json,secrets,subprocess
from datetime import datetime,timezone,date
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_v32_audit import OUT,read,sha
from scripts import naiwa_v31_runtime as base
API=63245;WEB=63246;EPOCH=int(os.environ.get('NAIWA_V32_EPOCH','1'));RUN=OUT/f'runtime-{EPOCH}'
base.OUT=OUT;base.RUN=RUN;base.API=API;base.WEB=WEB
original_sources=base.sources
def sources():
    return {**original_sources(),'scripts/naiwa_v32_runtime.py':sha(Path(__file__)),
        'scripts/naiwa_v32_faults.py':sha(ROOT/'scripts/naiwa_v32_faults.py')}
base.sources=sources
def clock_value():
    day=date.fromisoformat(os.environ.get('NAIWA_V32_STUDY_DATE',f'2040-02-{2+EPOCH:02}'))
    assert day.year==2040,'isolated simulated study date only'
    return datetime(day.year,day.month,day.day,1,0,tzinfo=timezone.utc)
def app():
    application=base.app()
    from backend.api.deps import get_time_provider
    test_now=clock_value()
    application.dependency_overrides[get_time_provider]=lambda:lambda:test_now
    from scripts.naiwa_v32_faults import install
    install(application,RUN)
    return application
def serve():
    import socket
    from scripts.restore_naiwa_experience_20261020 import existing_manager,database_url
    from scripts.naiwa_freeze_gate_20261021 import process_started
    from desktop.postgres import _run
    pg=existing_manager();identity=pg._identity()
    if identity:
        try:process_started(identity[0])
        except ProcessLookupError:pass
        else:raise RuntimeError('original owned supervisor must stop first')
    for port in (API,WEB):
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    RUN.mkdir();(RUN/'writes').mkdir();pg.lock.acquire()
    result=_run([pg.binary('pg_ctl'),'-D',str(pg.cluster),'-l',str(RUN/'postgres.log'),'-o','-p 63044 -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic','-w','-t','30','start'],timeout=45,capture=False)
    identity=pg._identity();assert result.returncode==0 and identity;pg._owned_identity=identity
    base.put(RUN/'epoch.json',{'epoch':EPOCH,'source_sha256':sources(),'pg_identity':list(identity),'test_clock':clock_value().isoformat()})
    base.put(RUN/'sessions.json',{})
    base.put(RUN/'window.json',{'epoch':EPOCH,'enabled':True,'nonce':secrets.token_hex(24),'expires_at':time.time()+3600,'paid_enabled':False})
    env={**os.environ,'APP_ENV':'test','DATABASE_URL':database_url(pg).render_as_string(hide_password=False),'TEST_DATABASE_URL':database_url(pg).render_as_string(hide_password=False),
        'KAOYAN_OWNED_TEST_PORT':'63044','LLM_API_KEY':'offline-only','LLM_MODEL':'FIXED-OFFLINE-NO-PAID-MODEL','LLM_BASE_URL':'http://127.0.0.1:9',
        'MODEL_SETTINGS_PATH':str(RUN/'offline-settings.bin'),'UPLOAD_DIR':str(base.HOME/'uploads'),'CHROMA_DIR':str(base.HOME/'chroma'),
        'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','ANONYMIZED_TELEMETRY':'False','DO_NOT_TRACK':'1','OTEL_SDK_DISABLED':'true','PYTHONIOENCODING':'utf-8',
        'ALLOWED_WEB_ORIGINS':json.dumps([f'http://127.0.0.1:{WEB}']),'VITE_API_PROXY_TARGET':f'http://127.0.0.1:{API}'}
    commands=[[sys.executable,'-m','uvicorn','scripts.naiwa_v32_runtime:app','--factory','--host','127.0.0.1','--port',str(API)],
              [r'D:\应用安装包\node.exe','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',str(WEB),'--strictPort']]
    children=[];logs=[]
    try:
        for label,cmd,cwd in zip(('api','web'),commands,(ROOT,ROOT/'frontend')):
            f=(RUN/f'{label}.log').open('x',encoding='utf-8');logs.append(f)
            children.append(subprocess.Popen(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
        base.put(RUN/'processes.json',{'supervisor':os.getpid(),'api':children[0].pid,'web':children[1].pid,'pg':identity[0],'commands':commands,'paid_enabled':False})
        while not (RUN/'stop.request').exists():
            if any(p.poll() is not None for p in children):raise RuntimeError('v32_child_exited')
            time.sleep(1)
    finally:
        from scripts.naiwa_v31_handoff_policy import close_window
        close_window(RUN/'window.json')
        for p in reversed(children):
            if p.poll() is None:p.terminate();p.wait(timeout=20)
        for f in logs:f.close()
        pg.stop()
if __name__=='__main__':
    if sys.argv[1]=='serve':serve()
    elif sys.argv[1]=='stop':(RUN/'stop.request').touch()
    elif sys.argv[1]=='close':
        from scripts.naiwa_v31_handoff_policy import close_window
        close_window(RUN/'window.json')
