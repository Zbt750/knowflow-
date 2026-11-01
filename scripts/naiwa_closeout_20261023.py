"""Read-only inventory and isolated sidecar. Never adopts the incident cluster."""
from pathlib import Path
import json,sys,hashlib,os
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
HOME=ROOT/'storage/manual-experience/naiwa-clean-20261023'
BASEOUT=ROOT/'storage/quality-audits/naiwa-v33-closeout-20261023'
OUT=Path(os.environ.get('NAIWA_CLOSEOUT_OUT',str(BASEOUT/'revision2')))
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(name,value):
    OUT.mkdir(exist_ok=True)
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,default=str)
def owned():
    from desktop.postgres import ManagedPostgres
    from desktop.runtime_paths import RuntimePaths
    from sqlalchemy.engine import make_url
    i=read(HOME/'identity.json')
    pg=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=HOME/'owned-pg'),Path('C:/Program Files/PostgreSQL/18/bin'),port=i['pg_port'])
    pg.preflight();pg._load_owner();pg._load_passwords()
    assert pg.owner['cluster_id']==i['cluster_id']=='29d19ef862fd401494af347f93c09aec'
    candidates=[BASEOUT/'resume-pg.json',BASEOUT/'revision2/resume-pg.json',BASEOUT/'revision3/resume-pg.json',BASEOUT/'revision4/resume-pg.json',OUT/'resume-pg.json']
    known=[read(p) for p in candidates if p.is_file()]
    assert any(pg._identity()[0]==row['pid'] and row['cluster_id']==i['cluster_id'] for row in known), 'unrecognized_owned_postgres_pid_STOP'
    return pg,make_url(pg.database_url).set(database='naiwa_clean_test').render_as_string(hide_password=False)
def snapshot(label):
    from sqlalchemy import create_engine,text,inspect
    _,url=owned();engine=create_engine(url)
    with engine.connect() as c:
        c.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        identity=dict(c.execute(text("SELECT current_database() db,current_user role,current_setting('port') port")).one()._mapping)
        assert identity['db']=='naiwa_clean_test' and identity['port']=='55220'
        rows={t:[dict(r._mapping) for r in c.execute(text('SELECT * FROM public."'+t+'"'))] for t in inspect(c).get_table_names(schema='public')}
    engine.dispose();data=json.loads(json.dumps(rows,default=str))
    result={'identity':identity,'cluster_id':read(HOME/'identity.json')['cluster_id'],'rows':data,
      'hashes':{t:sorted(hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False).encode()).hexdigest() for r in rs) for t,rs in data.items()}}
    save('database-'+label+'.json',result);return result
def app():
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    _,expected=owned();assert make_url(str(get_settings().active_database_url))==make_url(expected)
    def guard(event,args):
        if event=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','::1','localhost'}:raise RuntimeError('closeout_external_dns_closed')
        if event=='socket.connect' and not (isinstance(args[1],tuple) and args[1][:2] in [('127.0.0.1',55220),('::1',55220)]):raise RuntimeError('closeout_external_socket_closed')
    sys.addaudithook(guard)
    from scripts.manual_naiwa_experience import FixedProvider
    from backend.chat import service
    service.Provider=FixedProvider
    from backend.app import create_app
    from backend.services.learning_task_tools import TaskTools
    original_find=TaskTools.find_questions
    def controlled_find(self,*args,**kwargs):
        flag=OUT/'query-fault.json'
        if flag.exists() and read(flag).get('enabled'):
            raise RuntimeError('OFFLINE_TEST_ONLY_read_dependency_unavailable')
        return original_find(self,*args,**kwargs)
    TaskTools.find_questions=controlled_find
    from backend.api.deps import get_time_provider
    from datetime import datetime,timezone
    application=create_app();application.state.personal_generation_provider=FixedProvider(structured_generation=True)
    application.dependency_overrides[get_time_provider]=lambda:lambda:datetime(2040,4,3,1,tzinfo=timezone.utc)
    save('resume-loaded.json',{'pid':os.getpid(),'provider':'FIXED_OFFLINE','paid_enabled':False,
      'source_hashes':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'backend').rglob('*.py')},'database':read(HOME/'identity.json')})
    return application
def launch():
    import subprocess,socket,time
    from scripts.naiwa_v33_final_audit import protect
    protect()
    for port in (55221,55222):
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    # Prior supervisor has stopped its own children and PG gracefully. Restart
    # the SAME persistent cluster; never initdb/migrate/seed on this path.
    from desktop.postgres import ManagedPostgres
    from desktop.runtime_paths import RuntimePaths
    from sqlalchemy.engine import make_url
    i=read(HOME/'identity.json')
    pg=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=HOME/'owned-pg'),Path('C:/Program Files/PostgreSQL/18/bin'),port=55220)
    pg.preflight();pg._load_owner();pg._load_passwords()
    assert pg.owner['cluster_id']==i['cluster_id']=='29d19ef862fd401494af347f93c09aec'
    live=pg._identity()
    if live:
        candidate_paths=[BASEOUT/'resume-pg.json',BASEOUT/'revision2/resume-pg.json',BASEOUT/'revision3/resume-pg.json',BASEOUT/'revision4/resume-pg.json',OUT/'resume-pg.json']
        candidates=[read(p) for p in candidate_paths if p.is_file()]
        assert any(live[0]==saved['pid'] and saved['cluster_id']==pg.owner['cluster_id'] for saved in candidates), 'unexpected_postgres_instance_STOP'
        pg._owned_identity=live
    else:
        pg.start()
    url=make_url(pg.database_url).set(database='naiwa_clean_test').render_as_string(hide_password=False)
    save('resume-pg.json',{'pid':pg._identity()[0],'cluster_id':pg.owner['cluster_id']})
    current=snapshot('resume-after-restart')
    assert current['hashes']==read(OUT/'database-before.json')['hashes'],'data_changed_during_owned_restart_STOP'
    env={**os.environ,'APP_ENV':'test','DATABASE_URL':url,'TEST_DATABASE_URL':url,'KAOYAN_OWNED_TEST_PORT':'55220',
      'LLM_API_KEY':'offline-only','LLM_BASE_URL':'http://127.0.0.1:9','LLM_MODEL':'FIXED_OFFLINE',
      'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','ANONYMIZED_TELEMETRY':'False',
      'MODEL_SETTINGS_PATH':str(HOME/'offline-settings.bin'),'UPLOAD_DIR':str(HOME/'uploads'),'CHROMA_DIR':str(HOME/'chroma'),
      'ALLOWED_WEB_ORIGINS':json.dumps(['http://127.0.0.1:55222']),'VITE_API_PROXY_TARGET':'http://127.0.0.1:55221','PYTHONIOENCODING':'utf-8'}
    cmds=[[sys.executable,'-m','uvicorn','scripts.naiwa_closeout_20261023:app','--factory','--host','127.0.0.1','--port','55221'],[r'D:\应用安装包\node.exe','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','55222','--strictPort']]
    logs=[];children=[]
    try:
        for label,cmd,cwd in zip(('api','web'),cmds,(ROOT,ROOT/'frontend')):
            f=(OUT/('resume-'+label+'.log')).open('x',encoding='utf-8');logs.append(f)
            children.append(subprocess.Popen(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
        save('resume-processes.json',{'supervisor':os.getpid(),'children':[p.pid for p in children],'commands':cmds,'same_persistent_cluster':True})
        while not (OUT/'stop-sidecar.request').exists():
            if any(p.poll() is not None for p in children):raise RuntimeError('sidecar_child_exited')
            time.sleep(1)
    finally:
        for p in reversed(children):
            if p.poll() is None:p.terminate();p.wait(timeout=20)
        for f in logs:f.close()
        pg.stop()
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='snapshot':snapshot('before')
    else:launch()
