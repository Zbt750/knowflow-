"""Live clean-site HTTP reads with full-row snapshots; no business writes."""
from pathlib import Path
import json,sys,hashlib
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/naiwa-v33-continue-20261023';HOME=ROOT/'storage/manual-experience/naiwa-clean-20261023'
def main():
    from desktop.postgres import ManagedPostgres
    from desktop.runtime_paths import RuntimePaths
    from sqlalchemy import create_engine,text,inspect
    from sqlalchemy.engine import make_url
    import httpx
    from scripts.naiwa_v33_final_audit import protect
    protect()
    identity=json.loads((HOME/'identity.json').read_text(encoding='utf-8'))
    proc=json.loads((OUT/'clean-processes.json').read_text(encoding='utf-8'))
    pg=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=HOME/'owned-pg'),Path('C:/Program Files/PostgreSQL/18/bin'),port=identity['pg_port'])
    pg.preflight();pg._load_owner();pg._load_passwords()
    assert pg.owner['cluster_id']==identity['cluster_id']!='eb3800c77c3c40f6ac12eb21112df36c'
    assert pg._identity()[0]==proc['pg']
    engine=create_engine(make_url(pg.database_url).set(database='naiwa_clean_test'))
    def save(name,value):
        with (OUT/name).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,default=str)
    def snap():
        with engine.connect() as c:
            c.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            actual=dict(c.execute(text("SELECT current_database() db,current_user role,current_setting('port') port")).one()._mapping)
            assert actual['db']=='naiwa_clean_test' and int(actual['port'])==identity['pg_port']
            rows={t:[dict(r._mapping) for r in c.execute(text('SELECT * FROM public."'+t+'"'))] for t in inspect(c).get_table_names(schema='public')}
        clean=json.loads(json.dumps(rows,default=str));return {'identity':actual,'cluster_id':identity['cluster_id'],'rows':clean,
            'hashes':{t:sorted(hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False).encode()).hexdigest() for r in rs) for t,rs in clean.items()}}
    before=snap();save('live-get-before.json',before)
    urls=['/api/practice-requests','/api/chat/sessions?purpose=qa','/api/plans/today']
    urls += ['/api/practice-requests/'+r['id'] for r in before['rows']['practice_requests']]
    urls += ['/api/learning-tasks/'+r['id'] for r in before['rows']['learning_tasks']]
    with httpx.Client(base_url=f"http://127.0.0.1:{identity['api_port']}",trust_env=False,timeout=15) as client:
        with ThreadPoolExecutor(max_workers=6) as pool:statuses=list(pool.map(lambda p:client.get(p).status_code,urls*3))
        health=client.get('/api/health');assert health.status_code==200
    after=snap();save('live-get-after.json',after);assert all(x==200 for x in statuses);assert before['hashes']==after['hashes']
    protect();save('live-get-result.json',{'status':'PASS','requests':len(statuses),'concurrency':6,'full_rows_equal':True,'historical_files_unchanged':True,'real_model_requests':0,'paid_enabled':False})
    engine.dispose();print('LIVE_GET_FULL_ROWS_PASS',len(statuses))
if __name__=='__main__':main()
