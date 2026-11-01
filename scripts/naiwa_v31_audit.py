"""V3.1 read-only baselines. Never migrates, seeds or constructs a Provider."""
from pathlib import Path
import hashlib,json,sys,subprocess,os
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/naiwa-v31-20261022'
HOME=ROOT/'storage/manual-experience/naiwa-real-20261020'
V2=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021'
V3=V2.parent/'naiwa-v3-20261022'

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,data):
    target=OUT/name;target.parent.mkdir(exist_ok=True,parents=True)
    with target.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2,default=str)
def protected():
    names=read(ROOT/'storage/quality-audits/naiwa-v3-stage0-20261022-103246-868529/protected-after.json')
    paths={ROOT/name for name in names}
    paths|={p for d in (V2,V3) for p in d.rglob('*') if p.is_file()}
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths)}

def snapshot(label):
    from scripts.restore_naiwa_experience_20261020 import existing_manager,database_url
    from scripts.naiwa_freeze_gate_20261021 import process_started
    from sqlalchemy import create_engine,text,inspect
    pg=existing_manager();runtime=read(HOME/'restored-offline-20261020/runtime.json')
    if os.environ.get('NAIWA_V31_EPOCH'):
        from scripts.naiwa_v31_runtime import RUN,sources
        running=read(RUN/'processes.json');loaded=read(RUN/'loaded-code.json')
        assert loaded['source_sha256']==sources(),'V31 loaded/workspace mismatch STOP'
        runtime={'postgres_pid':running['pg'],'backend_pid':running['api'],'frontend_pid':running['web']}
    assert pg.owner['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    for key in ('postgres_pid','backend_pid','frontend_pid'):process_started(runtime[key])
    assert pg._identity()[0]==runtime['postgres_pid']
    engine=create_engine(database_url(pg),connect_args={'connect_timeout':5},isolation_level='REPEATABLE READ')
    try:
        with engine.connect() as c:
            c.execute(text('SET TRANSACTION READ ONLY'))
            identity=dict(c.execute(text("SELECT current_database() db,current_user role,current_setting('port') port,current_setting('transaction_isolation') isolation,current_setting('transaction_read_only') read_only")).one()._mapping)
            assert identity['db']=='naiwa_experience_test' and identity['port']=='63044' and identity['read_only']=='on'
            schema=inspect(c);tables=set(schema.get_table_names(schema='public'))
            wanted={'practice_requests','learning_tasks','daily_plans','practice_items','questions','question_versions',
                'question_attempts','learning_events','chat_sessions','chat_messages','personal_generation_batches',
                'knowledge_points','materials','document_chunks','message_citations','kp_states'}
            wanted|={name for name in tables if name.startswith('learning_task')}
            assert wanted<=tables,wanted-tables
            rows={};contract={}
            for name in sorted(wanted):
                rows[name]=[dict(r._mapping) for r in c.execute(text('SELECT * FROM public."'+name+'"'))]
                contract[name]={'columns':[{'name':v['name'],'type':str(v['type']),'nullable':v['nullable']} for v in schema.get_columns(name)],
                    'primary_key':schema.get_pk_constraint(name),'foreign_keys':schema.get_foreign_keys(name)}
        clean=json.loads(json.dumps(rows,ensure_ascii=False,default=str))
        hashes={t:{'count':len(rs),'rows':sorted(hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False).encode()).hexdigest() for r in rs)} for t,rs in clean.items()}
        save(f'database-{label}.json',{'time_utc':datetime.now(timezone.utc).isoformat(),'cluster_id':pg.owner['cluster_id'],
            'identity':identity,'schema':contract,'rows':clean,'row_sha256':hashes})
        return clean
    finally:engine.dispose()

def preflight():
    assert not OUT.exists(),'never overwrite prior V3.1 run'
    OUT.mkdir()
    before=protected();save('protected-before.json',before)
    runtime=read(HOME/'restored-offline-20261020/runtime.json')
    loaded=read(HOME/'restored-offline-20261020/loaded-code.json')
    assert loaded['pid']==runtime['backend_pid']
    assert all(sha(ROOT/name)==value for name,value in loaded['source_sha256'].items()),'loaded/workspace mismatch STOP'
    import httpx
    with httpx.Client(trust_env=False,timeout=5) as c:
        for port in (63045,63046):
            r=c.get(f'http://127.0.0.1:{port}/api/health');assert r.status_code==200
            assert r.headers['x-naiwa-backend-pid']==str(runtime['backend_pid'])
    assert loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL'
    assert loaded['physical_gate']['preparation_permanently_closed']
    save('runtime-before.json',{'runtime':runtime,'loaded':loaded})
    snapshot('before')
    paths=[ROOT/'storage/quality-audits/naiwa-real-20261020/provider-ledger.json',
        ROOT/'storage/quality-audits/naiwa-real-retest-20261020-budget7/provider-ledger.json',
        V2.parent/'round5/provider-ledger.json',V2/'provider-ledger.json']
    ledgers=[{'path':str(p),'sha256':sha(p),'reservations':len(read(p)['requests']),
        'unfinished':sum(not r.get('finished',False) for r in read(p)['requests'])} for p in paths]
    assert len(read(paths[-1])['requests'])==1 and sha(paths[-1])==sha(V2/'A1-ledger-original.json')
    save('ledgers-before.json',ledgers)
    incident=read(V2/'history-preservation-incident.json')
    for row in incident['files']:
        assert sha(ROOT/row['path'])==row['current_sha256']
        row.update(original_recovered=False,current_matches_original=False,
            original_recovery_status='unrecoverable_from_previously_checked_copies_not_claimed_recovered')
    save('historical-incident.json',incident)
    drift=read(V2/'historical-evidence-drift.json');save('historical-drift-reference.json',drift)
    candidates=V2/'overwritten-legacy-diagnostics-current-copy'
    save('candidate-copies.json',{p.name:sha(p) for p in candidates.iterdir() if p.is_file()})
    status=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,encoding='utf-8',errors='replace')
    with (OUT/'worktree-before.txt').open('x',encoding='utf-8') as f:f.write(status)
    assert protected()==before
    save('preflight.json',{'status':'PASS','time_utc':datetime.now(timezone.utc).isoformat(),
        'real_model_requests':0,'paid_enabled':False,'protected_count':len(before),
        'historical_incident':'recorded_not_recovered','no_service_restart':True})
    print('V3.1 READ-ONLY BASELINE PASS; full schema/rows including practice_requests saved; exit CLOSED')

if __name__=='__main__':
    if sys.argv[1]=='preflight':preflight()
    elif sys.argv[1]=='snapshot':snapshot(sys.argv[2]);print('read-only snapshot saved')
