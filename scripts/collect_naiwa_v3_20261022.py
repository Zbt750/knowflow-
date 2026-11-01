"""V3 read-only closeout; no model or business write endpoints."""
import json
import sys
import time
from pathlib import Path
from sqlalchemy import create_engine,text
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_v3_runtime_20261022 import OUT,RUN,LEDGER,LEDGER_DIR,STAGE0,read,sha,save,bind,old


def collect(label):
    bind()
    if label=='fixed':
        runtime=read(old.OLD_RUN/'runtime.json')
        from scripts.naiwa_freeze_gate_20261021 import process_started
        for key in ('supervisor_pid','postgres_pid','backend_pid','frontend_pid'):process_started(runtime[key])
        pg=old.existing_manager();identity=pg._identity()
    else:
        runtime=read(OUT/'runtime-v2.json')
        pg=old.existing_manager();identity=pg._identity()
    assert identity[0]==runtime['postgres_pid']
    data=old.snapshot_database(OUT/f'database-{label}.json',allow_live_identity=identity)
    engine=create_engine(old.database_url(pg),connect_args={'connect_timeout':5})
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            requests=[dict(r._mapping) for r in conn.execute(text('SELECT * FROM public.practice_requests'))]
        save(OUT/f'practice-requests-{label}.json',requests)
    finally:engine.dispose()
    before=read(OUT/'database-before.json')
    registry=read(RUN/'session-registry.json')['sessions']
    diff=old.compare_snapshot(before,data,mutable_session_ids=[s['session_id'] for s in registry])
    assert diff['preexisting_rows_preserved'],'old business rows changed STOP'
    save(OUT/f'database-diff-{label}.json',diff)
    ids={s['session_id'] for s in registry}
    messages=[r for r in data['chat_messages'] if r['session_id'] in ids]
    save(OUT/f'chat-records-{label}.json',{'sessions':[s for s in data['chat_sessions'] if s['id'] in ids],
        'messages':messages,'practice_requests':[r for r in requests if str(r['source_conversation_id']) in ids]})
    lines=['# V3 实际Vue对话：本次均为确定性业务回复，未新增真实模型调用','']
    for sid in sorted(ids):
        lines.extend(['## 会话 '+sid,''])
        for row in sorted([m for m in messages if m['session_id']==sid],key=lambda m:m['created_at']):
            lines.extend(['### '+row['role'],row['content'],''])
    target=OUT/f'transcript-{label}.md'
    with target.open('x',encoding='utf-8') as f:f.write('\n'.join(lines))
    expected=read(STAGE0/'protected-after.json')
    current={name:sha(ROOT/name) for name in expected}
    changed=[name for name in expected if expected[name]!=current[name]]
    save(OUT/f'history-hashes-{label}.json',{'files':current,'changed':changed})
    assert not changed,'historical artifact change STOP'
    ledger=read(LEDGER)
    assert len(ledger['requests'])==1 and sha(LEDGER)==sha(LEDGER_DIR/'A1-ledger-original.json')
    assert not read(OUT/'control.json')['paid_enabled']
    # Retrieve structured query evidence actually persisted, not test presets.
    save(OUT/f'persisted-tool-evidence-{label}.json',[
        {'id':m['id'],'session_id':m['session_id'],'metadata':m.get('metadata',m.get('metadata_',{}))}
        for m in messages if m['role']=='assistant'])
    result={'time':time.time(),'stage':'V3_FIRST_UI_BATCH_STOPPED_ON_HARNESS_ROUTE_GAP',
        'ledger_total':1,'v3_physical_requests':0,'unused_global_ceiling':39,
        'paid_enabled':False,'historical_hashes_preserved':True,'preexisting_business_rows_preserved':True,
        'new_sessions':len(ids),'new_messages':len(messages),'database_diff':diff,
        'practice_requests_had_no_pre_batch_baseline':True,
        'runtime':runtime,'not_a_real_model_quality_pass':True}
    if label=='fixed':
        import httpx
        loaded=read(old.OLD_RUN/'loaded-code.json')
        assert loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL'
        assert loaded['physical_gate']['preparation_permanently_closed']
        assert all(sha(ROOT/name)==value for name,value in loaded['source_sha256'].items())
        health={}
        for port in (63045,63046):
            r=httpx.get(f'http://127.0.0.1:{port}/api/health',trust_env=False,timeout=5)
            assert r.status_code==200 and r.headers['x-naiwa-backend-pid']==str(runtime['backend_pid'])
            health[str(port)]={'status':r.status_code,'body':r.json()}
        result.update(fixed_provider_restored=True,health=health,loaded_source_hashes_match=True)
        assert data==read(OUT/'database-closed.json')
        assert json.loads(json.dumps(requests,default=str))==read(OUT/'practice-requests-closed.json')
    save(OUT/f'final-verification-{label}.json',result)
    print(json.dumps({'stage':label,'physical_requests':0,'new_messages':len(messages),
        'old_rows_preserved':True,'history_artifact_changes':changed},ensure_ascii=False))


if __name__=='__main__':collect(sys.argv[1])
