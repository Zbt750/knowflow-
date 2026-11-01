"""Narrow offline PostgreSQL closeout; preserves existing databases and evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--tag',required=True)
    parser.add_argument('tests',nargs='*',default=['tests/integration/test_differentiated_closeout.py'])
    args=parser.parse_args()
    if not args.tag.replace('-','').isalnum(): raise ValueError('invalid tag')
    out=ROOT/'storage/quality-audits/naiwa-four-item-closeout-20261024'/args.tag
    out.mkdir(parents=True,exist_ok=False)
    from desktop.postgres import ManagedPostgres, APP_USER
    from desktop.runtime_paths import RuntimePaths
    from sqlalchemy.engine import make_url
    from psycopg import sql
    owned=ROOT/'storage/manual-experience/naiwa-differentiated-test-20261024-r8/owned-pg'
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
    if port<=18000 or port in {5433,63044}: raise RuntimeError('unsafe test port')
    pg=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=owned),
        Path('C:/Program Files/PostgreSQL/18/bin'),port=port)
    def save(name,data):
        with (out/name).open('x',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2,default=str)
    protected=[ROOT/'storage/quality-audits/naiwa-differentiated-acceptance-20261024/B-GENERATION-1792822891054804600.json',
        ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-v33-exploratory-r8z/provider-ledger.json']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    started=False
    try:
        pg.start();started=True
        if pg.owner['cluster_id']!='75c291dd1be548158fd57c5f03c37e02':raise RuntimeError('owned cluster mismatch')
        database='naiwa_closeout_'+args.tag.replace('-','_')+'_test'
        with pg._connect() as admin:
            if admin.execute('SELECT 1 FROM pg_database WHERE datname=%s',(database,)).fetchone():raise RuntimeError('database already exists')
            admin.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(database),sql.Identifier(APP_USER)))
            cluster_system=str(admin.execute('SELECT system_identifier FROM pg_control_system()').fetchone()[0])
        with pg._connect(user=APP_USER,database=database) as conn:
            identity=conn.execute('SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()').fetchone()
        assert tuple(identity)==(database,APP_USER,'127.0.0.1',port)
        save('identity-before.json',{'identity':identity,'cluster_id':pg.owner['cluster_id'],
            'system_identifier':cluster_system,'data_directory':str(pg.cluster),'pid':pg._identity(),'protected':hashes})
        url=make_url(pg.database_url).set(database=database).render_as_string(hide_password=False)
        env={**os.environ,'APP_ENV':'test','TEST_DATABASE_URL':url,'DATABASE_URL':url,
            'KAOYAN_OWNED_TEST_PORT':str(port),'PHASE45E_OWNED_TEST_PORT':str(port),
            'LLM_API_KEY':'','LLM_BASE_URL':'http://127.0.0.1:1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
            'PHASE45I_CLOSE_OFFLINE':'1','PHASE45I_CLOSE_OUTPUT':str(out),'NAIWA_CLOSEOUT_EVIDENCE':str(out),
            'PYTHONIOENCODING':'utf-8'}
        command=[sys.executable,'-m','pytest','-q','-rA',f'--junitxml={out / "junit.xml"}',*args.tests]
        with (out/'pytest.log').open('xb') as log:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                timeout=400,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        after={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        save('result.json',{'command':[sys.executable,'-m','pytest','-q','-rA',*args.tests],
            'exit_code':result.returncode,'protected_before':hashes,'protected_after':after,
            'protected_unchanged':hashes==after,'real_model_requests':0,'captured_at':time.time()})
        print(json.dumps({'output':str(out),'exit_code':result.returncode,'protected_unchanged':hashes==after}))
    finally:
        if started:
            pg.stop();save('stopped.json',{'postmaster':pg._identity(),'verified':pg._identity() is None})


if __name__=='__main__':main()
