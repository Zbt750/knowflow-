"""V3.2 full read-only evidence. No Provider creation, migrations or seed."""
from pathlib import Path
import os,sys,json,hashlib,subprocess
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/naiwa-v32-20261022'
from scripts.naiwa_v31_audit import read,sha,protected as older_protected
def save(name,value):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,default=str)
def protected():
    files=older_protected()
    old=ROOT/'storage/quality-audits/naiwa-v31-20261022'
    for p in old.rglob('*'):
        if p.is_file() and not (p.parent.name=='runtime-9' and p.name in {'api.log','web.log','postgres.log','window.json','stop.request','admission.lock'}):
            files[p.relative_to(ROOT).as_posix()]=sha(p)
    return files
def snapshot(label):
    from scripts.restore_naiwa_experience_20261020 import existing_manager,database_url
    from sqlalchemy import create_engine,text,inspect
    pg=existing_manager();identity=pg._identity()
    assert identity and pg.owner['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    engine=create_engine(database_url(pg),isolation_level='REPEATABLE READ',connect_args={'connect_timeout':5})
    try:
        with engine.connect() as c:
            c.execute(text('SET TRANSACTION READ ONLY'))
            info=dict(c.execute(text("SELECT current_database() db,current_user role,current_setting('port') port,current_setting('transaction_read_only') read_only,current_setting('transaction_isolation') isolation")).one()._mapping)
            assert info['db']=='naiwa_experience_test' and info['port']=='63044' and info['read_only']=='on'
            schema={};rows={};ins=inspect(c)
            for t in sorted(ins.get_table_names(schema='public')):
                schema[t]={'columns':[{'name':v['name'],'type':str(v['type']),'nullable':v['nullable']} for v in ins.get_columns(t)],'primary_key':ins.get_pk_constraint(t),'foreign_keys':ins.get_foreign_keys(t)}
                rows[t]=[dict(r._mapping) for r in c.execute(text('SELECT * FROM public."'+t+'"'))]
        clean=json.loads(json.dumps(rows,ensure_ascii=False,default=str))
        hashes={t:sorted(hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False).encode()).hexdigest() for r in rs) for t,rs in clean.items()}
        value={'time':datetime.now(timezone.utc).isoformat(),'cluster_id':pg.owner['cluster_id'],'pg_identity':list(identity),'cluster_path':str(pg.cluster),'identity':info,'schema':schema,'rows':clean,'row_sha256':hashes}
        save('database-'+label+'.json',value);return value
    finally:engine.dispose()
def preflight():
    assert not OUT.exists();OUT.mkdir()
    p=protected();save('protected-before.json',p)
    old=ROOT/'storage/quality-audits/naiwa-v31-20261022'
    loaded=read(old/'runtime-9/loaded-code.json')
    from scripts.naiwa_v31_runtime import sources
    assert loaded['source_sha256']==sources()
    assert not read(old/'runtime-9/window.json')['enabled']
    snapshot('before')
    ledgers=read(old/'ledger-final.json')['ledgers']
    assert all(sha(Path(v['path']))==v['sha256'] for v in ledgers)
    save('ledger-before.json',ledgers)
    status=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,encoding='utf-8',errors='replace')
    (OUT/'worktree-before.txt').write_text(status,encoding='utf-8')
    save('history-incident.json',{'status':'ORIGINAL_10_BYTES_UNRECOVERED','reference':str(old/'historical-incident.json'),'sha256':sha(old/'historical-incident.json')})
    save('preflight.json',{'status':'PASS','original_loaded':loaded,'protected_count':len(p),'paid_enabled':False,'model_requests':0})
    print('V32_FULL_BASELINE_PASS')
if __name__=='__main__':
    if sys.argv[1]=='preflight':preflight()
    elif sys.argv[1]=='snapshot':snapshot(sys.argv[2]);print('SNAPSHOT_SAVED')
