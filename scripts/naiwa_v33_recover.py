"""Retained V32 offline runtime, independent recovery logs, no schema/data setup."""
import os, sys, time, json, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('NAIWA_V32_EPOCH', '10')
os.environ.setdefault('NAIWA_V32_STUDY_DATE', '2040-02-09')
from scripts import naiwa_v32_runtime as previous
from scripts import naiwa_v33_audit as audit
OUT=ROOT/'storage/quality-audits/naiwa-v33-final-20261023' if os.environ.get('NAIWA_V33_FINAL')=='1' else audit.OUT
def snapshot(label):
    original=audit.OUT;audit.OUT=OUT
    try:return audit.snapshot(label)
    finally:audit.OUT=original
def save(name,value):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,default=str)
def check():
    if os.environ.get('NAIWA_V33_FINAL')=='1':
        # This runtime may not redefine historical manifests; use the independent verifier.
        from scripts.naiwa_v33_final_audit import protect
        protect()
    else:audit.check()
RUN = OUT / os.environ.get('NAIWA_V33_RECOVERY','recovery-1')
previous.RUN = RUN
previous.base.RUN = RUN
previous.base.OUT = OUT

def app():
    return previous.app()

def serve():
    import socket
    from scripts.restore_naiwa_experience_20261020 import existing_manager, database_url
    from scripts.naiwa_freeze_gate_20261021 import process_started
    from desktop.postgres import _run
    check()
    pg = existing_manager()
    identity = pg._identity()
    if identity:
        try:
            process_started(identity[0])
        except ProcessLookupError:
            pass
        else:
            raise RuntimeError('existing_postmaster_requires_review')
    for port in (63044, 63245, 63246):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    RUN.mkdir()
    (RUN / 'writes').mkdir()
    pg.lock.acquire()
    result = _run([pg.binary('pg_ctl'), '-D', str(pg.cluster), '-l', str(RUN/'postgres.log'), '-o', '-p 63044 -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic', '-w', '-t', '30', 'start'], timeout=45, capture=False)
    assert result.returncode == 0
    identity = pg._identity()
    assert identity
    pg._owned_identity = identity
    children = []
    logs = []
    try:
        current = snapshot(RUN.name+'-recovered')
        old = json.loads((ROOT/'storage/quality-audits/naiwa-v32-20261022/database-final.json').read_text(encoding='utf-8'))
        if os.environ.get('NAIWA_V33_FINAL')=='1':
            old=json.loads((OUT/'database-before.json').read_text(encoding='utf-8'))
        assert all(set(hashes).issubset(set(current['row_sha256'][table])) for table,hashes in old['row_sha256'].items()), 'retained_database_drift_STOP'
        save(RUN.name+'-database-comparison.json', {'all_original_rows_unchanged': True, 'cluster_id': current['cluster_id'], 'identity': current['identity']})
        previous.base.put(RUN/'epoch.json', {'epoch':10,'source_sha256':previous.sources(),'pg_identity':list(identity),'test_clock':previous.clock_value().isoformat()})
        previous.base.put(RUN/'sessions.json', {})
        previous.base.put(RUN/'window.json', {'epoch':10,'enabled':False,'nonce':'closed-recovery','expires_at':0,'paid_enabled':False})
        env = {**os.environ, 'APP_ENV':'test','DATABASE_URL':database_url(pg).render_as_string(hide_password=False),'TEST_DATABASE_URL':database_url(pg).render_as_string(hide_password=False),'KAOYAN_OWNED_TEST_PORT':'63044','LLM_API_KEY':'offline-only','LLM_MODEL':'FIXED-OFFLINE-NO-PAID-MODEL','LLM_BASE_URL':'http://127.0.0.1:9','MODEL_SETTINGS_PATH':str(RUN/'offline-settings.bin'),'UPLOAD_DIR':str(previous.base.HOME/'uploads'),'CHROMA_DIR':str(previous.base.HOME/'chroma'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','ANONYMIZED_TELEMETRY':'False','DO_NOT_TRACK':'1','OTEL_SDK_DISABLED':'true','PYTHONIOENCODING':'utf-8','ALLOWED_WEB_ORIGINS':json.dumps(['http://127.0.0.1:63246']),'VITE_API_PROXY_TARGET':'http://127.0.0.1:63245'}
        commands = [[sys.executable,'-m','uvicorn','scripts.naiwa_v33_recover:app','--factory','--host','127.0.0.1','--port','63245'],[r'D:\应用安装包\node.exe','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','63246','--strictPort']]
        for name, cmd, cwd in zip(('api','web'), commands, (ROOT, ROOT/'frontend')):
            f = (RUN/f'{name}.log').open('x', encoding='utf-8'); logs.append(f)
            children.append(subprocess.Popen(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
        previous.base.put(RUN/'processes.json',{'supervisor':os.getpid(),'api':children[0].pid,'web':children[1].pid,'pg':identity[0],'commands':commands,'paid_enabled':False})
        while not (RUN/'stop.request').exists():
            if any(p.poll() is not None for p in children):
                raise RuntimeError('isolated_child_exited')
            time.sleep(1)
    finally:
        for p in reversed(children):
            if p.poll() is None:
                p.terminate(); p.wait(timeout=20)
        for f in logs: f.close()
        pg.stop()

if __name__ == '__main__':
    serve()
