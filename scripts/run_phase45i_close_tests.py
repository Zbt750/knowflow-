"""Zero-paid-call acceptance in new databases inside the identified test cluster."""
import argparse,json,os,socket,subprocess,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--browser',action='store_true');parser.add_argument('--pytest-file',action='append',default=[])
    args=parser.parse_args();output=args.output_dir.resolve()
    if not output.is_relative_to(ROOT/'storage/quality-audits'):raise ValueError('Private audit output required')
    output.mkdir(parents=True,exist_ok=False)
    from scripts import run_phase45i_agent_real as owner
    _,cluster,port=owner.load_existing_owner()
    if port!=59227 or port==5433:raise ValueError('Unexpected owned test port')
    started=owner.start_owned_database(cluster,port);server=None
    results={'new_paid_calls':0,'development_5433_touched':False,'checks':[],'owned_port':port}
    def execute(name,cmd,env,cwd=ROOT):
        with (output/(name+'.log')).open('w',encoding='utf-8') as log:
            r=subprocess.run(cmd,env=env,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
        results['checks'].append({'name':name,'exit_code':r.returncode,'log':name+'.log'})
        print(name+': '+str(r.returncode),flush=True);return r.returncode
    try:
        identity=owner.verify_database(cluster,port,expected_revision='f49d10c2a703')
        results['source_test_identity']={k:identity[k] for k in ('port','database','system_identifier','revision')}
        from psycopg import connect,sql
        def new_db(tag):
            name='phase45i_close_'+tag+'_'+uuid4().hex[:8]+'_test'
            with connect(host='127.0.0.1',port=port,user='postgres',dbname='postgres',autocommit=True,connect_timeout=5) as c:
                if str(c.execute('SELECT system_identifier FROM pg_control_system()').fetchone()[0])!='7694698872540080852':
                    raise ValueError('Owned cluster identity mismatch')
                c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
            return name
        def environment(name):
            url=f'postgresql+psycopg://postgres@127.0.0.1:{port}/{name}'
            return {**os.environ,'APP_ENV':'test','DATABASE_URL':url,'TEST_DATABASE_URL':url,
                'KAOYAN_OWNED_TEST_PORT':str(port),'PHASE45I_CLOSE_OFFLINE':'1','PYTHONIOENCODING':'utf-8',
                'PHASE45I_CLOSE_OUTPUT':str(output),
                'LLM_API_KEY':'','LLM_BASE_URL':'http://127.0.0.1:9','LLM_MODEL':'offline-test-fixture',
                'UPLOAD_DIR':str(output/'uploads'),'CHROMA_DIR':str(output/'chroma'),
                'MODEL_CACHE_DIR':str(ROOT/'storage/model-cache'),'MODEL_SETTINGS_PATH':str(output/'model-settings.bin'),
                'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
        name=new_db('backend');env=environment(name);results['backend_database']=name
        execute('pytest',[sys.executable,'-m','pytest',*args.pytest_file,'-q','-o','addopts=','--basetemp',str(output/'pytest-temp')],env)
        if args.browser:
            name=new_db('browser');env=environment(name);results['browser_database']=name
            if execute('browser-migration',[sys.executable,'-m','alembic','upgrade','head'],env):raise ValueError('Browser schema failed')
            api_port=free_port();web_port=free_port()
            env.update(E2E_API_BASE=f'http://127.0.0.1:{api_port}',E2E_WEB_BASE=f'http://127.0.0.1:{web_port}',
                ALLOWED_WEB_ORIGINS=json.dumps([f'http://127.0.0.1:{web_port}']),
                PHASE45I_CLOSE_WEB_PORT=str(web_port),PHASE45I_CLOSE_OUTPUT=str(output),PHASE45I_CLOSE_BROWSER='1',
                PLAYWRIGHT_JSON_OUTPUT_NAME=str(output/'playwright.json'))
            log=(output/'browser-backend.log').open('w',encoding='utf-8')
            server=subprocess.Popen([sys.executable,'-m','uvicorn','scripts.phase45i_close_browser_backend:create_app',
                '--factory','--host','127.0.0.1','--port',str(api_port)],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            import httpx
            deadline=time.monotonic()+90;ready=False
            while time.monotonic()<deadline and server.poll() is None:
                try:
                    if httpx.get(env['E2E_API_BASE']+'/_phase45i/stats',timeout=2,trust_env=False).status_code==200:
                        ready=True;break
                except Exception:pass
                time.sleep(.5)
            if not ready:raise ValueError('Frozen browser backend not ready')
            execute('playwright',['npx.cmd','playwright','test','--config','playwright.phase45i-close.config.ts',
                '--output='+str(output/'browser-artifacts'),'--reporter=list,json'],env,ROOT/'frontend')
            results['browser_final_stats']=httpx.get(env['E2E_API_BASE']+'/_phase45i/stats',timeout=5,trust_env=False).json()
            server.terminate();server.wait(timeout=20);server=None;log.close()
        after=owner.verify_database(cluster,port,expected_revision='f49d10c2a703')
        results['original_isolated_ledger_unchanged']=after['counts']==identity['counts'] and after['daily_reserved_calls']==identity['daily_reserved_calls']
        from backend.db import create_db_engine
        from backend.models.learning import Question,KnowledgePoint
        from backend.services.question_generation import current_generation_binding
        from sqlalchemy import inspect,select,text
        from sqlalchemy.orm import Session
        historical_engine=create_db_engine(f'postgresql+psycopg://postgres@127.0.0.1:{port}/kaoyan_test')
        try:
            # This reused Phase45I source ledger intentionally remains at f49,
            # before immutable QuestionVersion columns exist. Do not load its
            # rows through today's ORM model (which selects current_version_id
            # and fails on that historical schema); report the capability
            # boundary explicitly while retaining the read-only count check.
            with historical_engine.connect() as connection:
                connection.execute(text('SET TRANSACTION READ ONLY'))
                total=int(connection.execute(text('SELECT count(*) FROM questions')).scalar_one())
                has_versions='current_version_id' in {column['name'] for column in inspect(connection).get_columns('questions')}
                if not has_versions:
                    results['old_c7_bindings']={'total':total,'current':None,
                        'status':'NOT_APPLICABLE_SOURCE_SCHEMA_PRE_QUESTION_VERSION'}
                else:
                    with Session(bind=connection) as db:
                        qs=list(db.scalars(select(Question)))
                        results['old_c7_bindings']={'total':len(qs),'current':sum(current_generation_binding(q,db.get(KnowledgePoint,q.kp_id)) for q in qs),
                            'status':'CHECKED'}
        finally:historical_engine.dispose()
    finally:
        if server is not None:server.terminate();server.wait(timeout=20)
        if started:
            stopped=owner.command([str(owner.PG_BIN/'pg_ctl.exe'),'-D',str(cluster),'-m','fast','-w','-t','30','stop'],timeout=40,check=False)
            results['owned_test_cluster_stopped']=stopped.returncode==0
        (output/'run-summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False));return int(any(c['exit_code'] for c in results['checks']))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
