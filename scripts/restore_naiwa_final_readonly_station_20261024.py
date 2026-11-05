"""Restore only the owned final32 database. No migrations, seed or model requests."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/naiwa-final-freeze-20261024/host-station'
OLD=ROOT/'storage/manual-experience/naiwa-real-20261020/agent-full-v33-continue-20261023-r8z-fresh-20261024-final32'
RUN=ROOT/'storage/manual-experience/naiwa-real-20261020/agent-full-v33-continue-20261023-r8z-fresh-20261024-final32manual'
os.environ.update(NAIWA_DIFFERENTIATED_RUNTIME_TAG='final32manual',
    NAIWA_DIFFERENTIATED_DATABASE='naiwa_differentiated_final32_test',
    NAIWA_DIFFERENTIATED_PG_PORT='64325',NAIWA_DIFFERENTIATED_API_PORT='64575',
    NAIWA_DIFFERENTIATED_WEB_PORT='64576')
from scripts import naiwa_differentiated_test_runtime_20261024 as wrapper
from scripts.naiwa_freeze_gate_20261021 import atomic_json

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,data):
    with path.open('x',encoding='utf-8') as out:json.dump(data,out,ensure_ascii=False,indent=2,default=str)

def main():
    import httpx
    from sqlalchemy.engine import make_url
    from desktop.postgres import ManagedPostgres, APP_USER
    from desktop.runtime_paths import RuntimePaths
    prior=ROOT/'storage/quality-audits/naiwa-differentiated-acceptance-20261024/fresh-runtime-final32'
    assert read(prior/'postgres-stop-verification.json')['stop_verified']
    assert read(wrapper.runtime.OUT/'control.json')['paid_enabled'] is False
    ledger=read(wrapper.runtime.LEDGER); assert len(ledger['requests'])==17
    assert all(r.get('finished') for r in ledger['requests'])
    wrapper.runtime.validate_parent_ledger();wrapper.runtime.paid.validate_history()
    active=read(OLD/'active-source-hashes.json')
    assert active['epoch']==32 and active['source_sha256']==wrapper.runtime.source_hashes()
    if OUT.exists() or RUN.exists():raise RuntimeError('restore audit paths already exist')
    OUT.mkdir(parents=True);RUN.mkdir(parents=True)
    for name in ('active-source-hashes.json','session-registry.json','runtime-data.json'):
        save(RUN/name,read(OLD/name))
    # Never grant a new write window. This nonce is local-only and gate remains sealed.
    with (RUN/'browser-nonce.txt').open('x',encoding='ascii') as out:out.write(os.urandom(32).hex())
    pg=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=wrapper.OWNED_DATA),wrapper.PG_BIN,port=64325)
    children=[];logs=[];started=False
    try:
        pg.start();started=True
        assert pg.owner['cluster_id']=='75c291dd1be548158fd57c5f03c37e02'
        with pg._connect(user=APP_USER,database='naiwa_differentiated_final32_test') as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            identity=list(conn.execute('SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()').fetchone())
        assert identity==['naiwa_differentiated_final32_test',APP_USER,'127.0.0.1',64325]
        effective,key=wrapper._provider_settings()
        dburl=make_url(pg.database_url).set(database=identity[0]).render_as_string(hide_password=False)
        env={**os.environ,'APP_ENV':'test','DATABASE_URL':dburl,'TEST_DATABASE_URL':dburl,
            'NAIWA_CLUSTER_ID':pg.owner['cluster_id'],'NAIWA_EXPECTED_CLUSTER_ID':pg.owner['cluster_id'],
            'NAIWA_CLUSTER_MARKER':str(pg.marker.resolve()),'NAIWA_FRESH_TEST_DATABASE':'1',
            'UPLOAD_DIR':str(wrapper.DATA_HOME.parent/'naiwa-differentiated-test-20261024-final32/uploads'),
            'CHROMA_DIR':str(wrapper.DATA_HOME.parent/'naiwa-differentiated-test-20261024-final32/chroma'),
            'MODEL_CACHE_DIR':str(ROOT/'storage/models'),'MODEL_SETTINGS_PATH':str(RUN/'model-settings.bin'),
            'LLM_API_KEY':key,'LLM_BASE_URL':effective.llm_base_url,'LLM_MODEL':effective.llm_model,
            'ALLOWED_WEB_ORIGINS':json.dumps(['http://127.0.0.1:64576']),
            'VITE_API_PROXY_TARGET':'http://127.0.0.1:64575','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
            'DO_NOT_TRACK':'1','ANONYMIZED_TELEMETRY':'False','OTEL_SDK_DISABLED':'true','PYTHONIOENCODING':'utf-8'}
        commands=[[sys.executable,'-m','uvicorn','scripts.naiwa_differentiated_test_runtime_20261024:app_factory','--factory','--host','127.0.0.1','--port','64575'],
            [str(wrapper.NODE),'node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','64576','--strictPort']]
        for name,command,cwd in zip(('backend','frontend'),commands,(ROOT,ROOT/'frontend')):
            log=(OUT/(name+'.log')).open('x',encoding='utf-8');logs.append(log)
            children.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        process_record={'backend_pid':children[0].pid,'frontend_pid':children[1].pid,
            'database_identity':{'postmaster_identity':list(pg._owned_identity),'cluster_id':pg.owner['cluster_id']},
            'supervisor_pid':os.getpid(),'commands':commands,'no_seed_or_migration':True,'paid_enabled':False}
        save(OUT/'service-processes.json',process_record)
        with httpx.Client(trust_env=False,timeout=3) as client:
            for _ in range(120):
                if any(p.poll() is not None for p in children):raise RuntimeError('restored child exited')
                try:
                    if client.get('http://127.0.0.1:64575/api/health').status_code==200:break
                except httpx.RequestError:pass
                time.sleep(1)
            else:raise RuntimeError('restored service health timeout')
        # Verify from a separate ordinary process in this supported execution context.
        verifyenv={**env,'NAIWA_FINAL_RUNTIME_RUN':str(RUN),'NAIWA_FINAL_STATION_AUDIT':str(OUT)}
        log=(OUT/'readonly-verification.log').open('x',encoding='utf-8');logs.append(log)
        completed=subprocess.run([sys.executable,'scripts/verify_naiwa_final_freeze_20261024.py'],cwd=ROOT,
            env=verifyenv,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        save(OUT/'restore-result.json',{'verification_exit_code':completed.returncode,
            'identity':identity,'paid_enabled':read(wrapper.runtime.OUT/'control.json')['paid_enabled'],
            'ledger_count':len(read(wrapper.runtime.LEDGER)['requests']),'browser_ui_tested':False})
        if completed.returncode:raise RuntimeError('read-only verification failed; preserve logs')
        while not (OUT/'stop.request').exists():
            if any(p.poll() is not None for p in children):raise RuntimeError('restored child exited')
            if read(wrapper.runtime.OUT/'control.json')['paid_enabled']:raise RuntimeError('unexpected paid gate open')
            time.sleep(1)
    finally:
        wrapper.runtime.paid.gate().seal('readonly_station_closed_or_failed')
        for child in children:
            if child.poll() is None:child.terminate()
        for child in children:
            try:child.wait(timeout=15)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        for log in logs:log.close()
        if started:pg.stop()
        if OUT.exists():save(OUT/'station-stopped.json',{'owned_pg_stopped':pg._identity() is None,'paid_enabled':False})

if __name__=='__main__':main()
