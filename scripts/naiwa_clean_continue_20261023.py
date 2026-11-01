"""New owned offline experience; never adopts or repairs the incident cluster."""
from pathlib import Path
import os,sys,json,socket,subprocess,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
HOME=ROOT/'storage/manual-experience/naiwa-clean-20261023'
OUT=ROOT/'storage/quality-audits/naiwa-v33-continue-20261023'
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,default=str)
def app():
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    settings=get_settings();u=make_url(str(settings.active_database_url))
    manifest=json.loads((HOME/'identity.json').read_text(encoding='utf-8'))
    assert (u.host,u.port,u.database)==('127.0.0.1',manifest['pg_port'],'naiwa_clean_test') and settings.app_env=='test'
    def guard(event,args):
        if event=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','::1','localhost'}:raise RuntimeError('clean_external_dns_closed')
        if event=='socket.connect' and not (isinstance(args[1],tuple) and args[1][:2] in [('127.0.0.1',u.port),('::1',u.port)]):raise RuntimeError('clean_external_socket_closed')
    sys.addaudithook(guard)
    from scripts.manual_naiwa_experience import FixedProvider
    from backend.chat import service
    service.Provider=FixedProvider
    from backend.app import create_app
    application=create_app();application.state.personal_generation_provider=FixedProvider(structured_generation=True)
    from backend.api.deps import get_time_provider
    from datetime import datetime,timezone
    application.dependency_overrides[get_time_provider]=lambda:lambda:datetime(2040,4,2,1,tzinfo=timezone.utc)
    import hashlib
    save(OUT/'clean-loaded.json',{'pid':os.getpid(),'provider':'FIXED-OFFLINE-NO-PAID-MODEL','paid_enabled':False,
        'sources':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'backend').rglob('*.py')},'database':manifest})
    return application
def serve():
    from desktop.runtime_paths import RuntimePaths
    from desktop.postgres import ManagedPostgres,APP_USER
    from sqlalchemy.engine import make_url
    from psycopg import sql
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from tests.integration.query_followup_backend import prepare_fixture
    assert not HOME.exists(),'exclusive new environment only'
    HOME.mkdir(parents=True)
    ports=[]
    for _ in range(3):
        with socket.socket() as s:s.bind(('127.0.0.1',0));ports.append(s.getsockname()[1])
    assert len(set(ports))==3 and all(p>18000 and p not in {5433,8000,5173,63044,63245,63246} for p in ports)
    pg=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=HOME/'owned-pg'),Path('C:/Program Files/PostgreSQL/18/bin'),port=ports[0]);pg.start()
    children=[];logs=[]
    try:
        with pg._connect() as c:c.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier('naiwa_clean_test'),sql.Identifier(APP_USER)))
        url=make_url(pg.database_url).set(database='naiwa_clean_test').render_as_string(hide_password=False)
        env={**os.environ,'APP_ENV':'test','DATABASE_URL':url,'TEST_DATABASE_URL':url,'KAOYAN_OWNED_TEST_PORT':str(ports[0]),'LLM_API_KEY':'offline-only','LLM_BASE_URL':'http://127.0.0.1:9','LLM_MODEL':'FIXED-OFFLINE-NO-PAID-MODEL','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','ANONYMIZED_TELEMETRY':'False','MODEL_SETTINGS_PATH':str(HOME/'offline-settings.bin'),'UPLOAD_DIR':str(HOME/'uploads'),'CHROMA_DIR':str(HOME/'chroma'),'ALLOWED_WEB_ORIGINS':json.dumps([f'http://127.0.0.1:{ports[2]}']),'VITE_API_PROXY_TARGET':f'http://127.0.0.1:{ports[1]}','PYTHONIOENCODING':'utf-8'}
        os.environ.update({k:env[k] for k in ('APP_ENV','DATABASE_URL','TEST_DATABASE_URL','KAOYAN_OWNED_TEST_PORT')})
        from backend.config import get_settings
        get_settings.cache_clear()
        cfg=Config(str(ROOT/'alembic.ini'));command.upgrade(cfg,'head')
        engine=create_engine(url);factory=sessionmaker(bind=engine,expire_on_commit=False)
        facts=prepare_fixture(factory)
        # Synthetic lesson scope uses the actual shipped lesson identifier.
        from backend.models.learning import KnowledgePoint
        from uuid import UUID
        with factory.begin() as db:db.get(KnowledgePoint,UUID(facts['lhopital_id'])).code='math.calculus.limit.lhopital'
        engine.dispose();save(OUT/'clean-fixture.json',facts)
        identity={'cluster_id':pg.owner['cluster_id'],'cluster':str(pg.cluster),'pg_port':ports[0],'api_port':ports[1],'web_port':ports[2],'database':'naiwa_clean_test','prior_incident_cluster_touched':False}
        save(HOME/'identity.json',identity)
        commands=[[sys.executable,'-m','uvicorn','scripts.naiwa_clean_continue_20261023:app','--factory','--host','127.0.0.1','--port',str(ports[1])],[r'D:\应用安装包\node.exe','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',str(ports[2]),'--strictPort']]
        for label,cmd,cwd in zip(('api','web'),commands,(ROOT,ROOT/'frontend')):
            f=(OUT/('clean-'+label+'.log')).open('x',encoding='utf-8');logs.append(f)
            children.append(subprocess.Popen(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
        save(OUT/'clean-processes.json',{'supervisor':os.getpid(),'pg':pg._identity()[0],'api':children[0].pid,'web':children[1].pid,'identity':identity,'commands':commands,'paid_enabled':False})
        while not (HOME/'stop.request').exists():
            if any(p.poll() is not None for p in children):raise RuntimeError('owned_clean_child_exited')
            time.sleep(1)
    finally:
        for p in reversed(children):
            if p.poll() is None:p.terminate();p.wait(timeout=20)
        for f in logs:f.close()
        pg.stop()
if __name__=='__main__':serve()
