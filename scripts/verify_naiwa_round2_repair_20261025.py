"""Developer evidence only; not a browser acceptance or simulated student attempt."""
from pathlib import Path
import hashlib,json,os,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/naiwa-ui-round2-repair-20261025'
DATA=ROOT/'storage/manual-experience/naiwa-student-ui-acceptance-20261024-round2fix1'

def main():
    import httpx
    from psycopg import sql
    from desktop.postgres import ManagedPostgres,APP_USER
    from desktop.runtime_paths import RuntimePaths
    config=json.loads((OUT/'station-config.json').read_text(encoding='utf-8-sig'))
    runtime=json.loads((DATA/'runtime.json').read_text(encoding='utf-8'))
    assert runtime['database']==config['database']=='naiwa_student_ui_20261024_round2fix1_test'
    assert runtime['paid_enabled'] is False and runtime['real_model_requests']==0
    allowed={config[k] for k in ('postgres','api','web')}
    def guard(event,args):
        if event=='socket.getaddrinfo' and str(args[0]) not in {'127.0.0.1','::1'}:raise RuntimeError('external DNS forbidden')
        if event=='socket.connect':
            address=args[1]
            if address[0]!='127.0.0.1' or address[1] not in allowed:raise RuntimeError('non-test socket forbidden')
    sys.addaudithook(guard)
    pg=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=DATA/'owned-pg'),Path('C:/Program Files/PostgreSQL/18/bin'),port=config['postgres'])
    pg._load_owner();pg._load_passwords()
    assert pg.owner['cluster_id']==runtime['database_identity']['cluster_id'] and pg._identity() is not None
    def snapshot():
        with pg._connect(user=APP_USER,database=config['database']) as db:
            db.execute('BEGIN READ ONLY')
            identity=db.execute('SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()').fetchone()
            assert identity==(config['database'],APP_USER,'127.0.0.1',config['postgres'])
            names=db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
            result={}
            for (name,) in names:
                rows=db.execute(sql.SQL('SELECT to_jsonb(t) FROM public.{} t').format(sql.Identifier(name))).fetchall()
                canonical=sorted(json.dumps(r[0],ensure_ascii=False,sort_keys=True,default=str) for r in rows)
                result[name]={'count':len(rows),'rows_sha256':[hashlib.sha256(r.encode()).hexdigest() for r in canonical]}
            db.rollback()
            return {'identity':identity,'tables':result}
    def save(name,data):
        with (OUT/name).open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2,default=str)
    before=snapshot();save('station-database-before.json',before)
    api=f"http://127.0.0.1:{config['api']}";web=f"http://127.0.0.1:{config['web']}"
    checks={}
    marker=DATA/'fault-builtin-materials-500.flag'
    assert not marker.exists()
    with httpx.Client(trust_env=False,timeout=15) as client:
        loaded=client.get(api+'/__test/runtime');loaded.raise_for_status();loaded=loaded.json()
        assert loaded['database']==config['database'] and loaded['paid_enabled'] is False
        for path,digest in loaded['source_sha256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest,path
        save('actual-loaded-code.json',loaded)
        for path in ['/study','/chat']:
            response=client.get(web+path);assert response.status_code==200 and '<html' in response.text.lower()
            checks[path]={'status':response.status_code,'response_sha256':hashlib.sha256(response.content).hexdigest(),'evidence_level':'HTTP only, not UI'}
        checks['health']=client.get(web+'/api/health').json()
        materials='/api/materials?limit=1&offset=0&status=ready&source_type=builtin'
        assert client.get(web+materials).status_code==200
        try:
            marker.write_text('SYNTHETIC temporary read-only fault',encoding='utf-8')
            response=client.get(web+materials);assert response.status_code==500 and response.headers.get('x-test-fault')=='builtin-materials-500'
            checks['fault']={'status':response.status_code,'body':response.json()}
            assert client.get(web+'/api/chat/sessions?purpose=qa').status_code==200
        finally:
            marker.unlink(missing_ok=True)
        assert client.get(web+materials).status_code==200
        rejected=client.post(web+'/api/chat/sessions',headers={'Origin':'http://unapproved.invalid'},json={'mode':'builtin','title':'NEGATIVE_AUTH_ONLY'})
        assert rejected.status_code==403
        checks['cross_origin_rejected']=rejected.status_code
        assert snapshot()==before,'GET/fault/denied POST unexpectedly changed rows'
        accepted=client.post(web+'/api/chat/sessions',headers={'Origin':web},json={'mode':'builtin','title':'SYNTHETIC_DEVELOPER_AUTH_PROBE_NOT_UI'})
        assert accepted.status_code==201,accepted.text
        checks['same_origin_session_create']={'status':accepted.status_code,'session_id':accepted.json()['session_id'],'evidence_level':'API authorization probe only; no student messages or attempts'}
    after=snapshot();save('station-database-after.json',after)
    diff={k:{'before':v['count'],'after':after['tables'][k]['count']} for k,v in before['tables'].items() if v!=after['tables'][k]}
    assert set(diff)=={'chat_sessions'} and after['tables']['chat_sessions']['count']==before['tables']['chat_sessions']['count']+1,diff
    assert all(set(v['rows_sha256']).issubset(set(after['tables'][k]['rows_sha256'])) for k,v in before['tables'].items())
    save('station-database-diff.json',diff)
    save('station-verification.json',{'checks':checks,'database_identity':runtime['database_identity'],'real_model_requests':0,
        'paid_enabled':False,'fault_restored':not marker.exists(),'external_network_allowed':False,'browser_ui_executed':False,'captured_at':time.time()})
    print(json.dumps({'url':web+'/study','checks':'passed','browser_ui_executed':False,'diff':diff}))

if __name__=='__main__':main()
