"""Read-only final reconciliation. Never sends chat or opens a paid gate."""
from pathlib import Path
import ctypes
import hashlib
import json
import os
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'storage/quality-audits/naiwa-final-freeze-20261024'
AUDIT = Path(os.environ.get('NAIWA_FINAL_STATION_AUDIT', ROOT / 'storage/quality-audits/naiwa-differentiated-acceptance-20261024/fresh-runtime-final32'))
RUN = Path(os.environ.get('NAIWA_FINAL_RUNTIME_RUN', ROOT / 'storage/manual-experience/naiwa-real-20261020/agent-full-v33-continue-20261023-r8z-fresh-20261024-final32'))
LEDGER = ROOT / 'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-v33-exploratory-r8z/provider-ledger.json'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(name, data):
    with (OUT/name).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, default=str)

def process_image(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p,ctypes.c_ulong,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return {'pid':pid,'query_error':ctypes.get_last_error()}
    try:
        size = ctypes.c_ulong(32768); buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        return {'pid':pid,'image':buffer.value if ok else None,'query_error':0 if ok else ctypes.get_last_error()}
    finally:
        kernel.CloseHandle(handle)

def main():
    import sys
    sys.path.insert(0, str(ROOT))
    from desktop.postgres import ManagedPostgres, APP_USER
    from desktop.runtime_paths import RuntimePaths
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    import httpx

    loaded = read(RUN/'loaded-code.json')
    if loaded['source_epoch'] != 32:
        raise RuntimeError('unexpected epoch')
    hashes = loaded['source_sha256']
    mismatch = [name for name, value in hashes.items() if sha(ROOT/name).lower()!=value.lower()]
    if mismatch:
        raise RuntimeError('loaded source mismatch:'+str(mismatch))
    control = read(LEDGER.parent/'control.json')
    if control.get('paid_enabled'):
        raise RuntimeError('must wait for model gate to close')
    ledger = read(LEDGER)
    if any(not row.get('finished') for row in ledger['requests']):
        raise RuntimeError('unfinished reservation')
    pg = ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=
        ROOT/'storage/manual-experience/naiwa-differentiated-test-20261024-r8/owned-pg'),
        Path('C:/Program Files/PostgreSQL/18/bin'),port=64325)
    pg._load_owner(); pg._load_passwords()
    if pg.owner['cluster_id']!='75c291dd1be548158fd57c5f03c37e02':
        raise RuntimeError('cluster mismatch')
    url=make_url(pg.database_url).set(database='naiwa_differentiated_final32_test')
    if (url.host,url.port,url.database,url.username)!=('127.0.0.1',64325,'naiwa_differentiated_final32_test',APP_USER):
        raise RuntimeError('database mismatch')
    engine=create_engine(url)
    def snapshot():
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            identity=list(conn.execute(text('SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()')).one())
            names=list(conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars())
            tables={}
            for name in names:
                # Table names are supplied by pg_catalog, never by a user.
                quoted=engine.dialect.identifier_preparer.quote(name)
                rows=list(conn.execute(text(f'SELECT to_jsonb(t) FROM public.{quoted} t')).scalars())
                rows.sort(key=lambda row:json.dumps(row,sort_keys=True,ensure_ascii=False,default=str))
                payload=json.dumps(rows,sort_keys=True,ensure_ascii=False,default=str).encode()
                tables[name]={'count':len(rows),'sha256':hashlib.sha256(payload).hexdigest(),'rows':rows}
            return {'identity':identity,'tables':tables,'isolation':'REPEATABLE READ READ ONLY'}
    try:
        before=snapshot(); save('database-before-readonly.json',before)
        http=[]
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=20) as client:
            for base,path in [('http://127.0.0.1:64576','/chat'),('http://127.0.0.1:64575','/api/health'),
                    ('http://127.0.0.1:64576','/api/health')]:
                response=client.get(base+path)
                http.append({'url':base+path,'status':response.status_code})
            sessions=client.get('http://127.0.0.1:64575/api/chat/sessions')
            http.append({'url':'http://127.0.0.1:64575/api/chat/sessions','status':sessions.status_code})
            ids=[row['id'] for row in before['tables']['chat_sessions']['rows']]
            for session_id in ids:
                response=client.get(f'http://127.0.0.1:64575/api/chat/sessions/{session_id}/messages')
                http.append({'session_id':session_id,'history_status':response.status_code})
        after=snapshot(); save('database-after-readonly.json',after)
    finally:
        engine.dispose()
    changed=[name for name,value in before['tables'].items() if value['sha256']!=after['tables'][name]['sha256']]
    save('database-diff.json',{'changed_tables':changed,'readonly_gets_preserved_all_rows':not changed})
    frontend_previous=read(ROOT/'storage/quality-audits/frontend-sse-state-20261024/source-hashes.json')
    frontend_checks=[{'path':row['path'],'same':sha(ROOT/row['path']).lower()==row['sha256'].lower()}
        for row in frontend_previous if row['path'].startswith('frontend/')]
    processes=read(AUDIT/'service-processes.json')
    requests=[{key:row.get(key) for key in ('request_id','case_id','finished','http_dispatch_attempts','http_status','finish_reason','usage','state')}
        for row in ledger['requests']]
    save('final-verification.json',{'captured_at':time.time(),'source_epoch':32,
        'loaded_source_matches':not mismatch,'loaded_source_sha256':hashes,
        'frontend_previous_test_hashes':frontend_checks,'cluster_id':pg.owner['cluster_id'],
        'database_identity':before['identity'],'http_get_results':http,
        'readonly_gets_preserved_all_rows':not changed,'paid_enabled':False,
        'provider_control':control,'ledger_path':str(LEDGER),'ledger_sha256':sha(LEDGER),
        'ledger_count':len(requests),'remaining_global':40-len(requests),'requests':requests,
        'processes':[process_image(processes['backend_pid']),process_image(processes['frontend_pid']),process_image(processes['database_identity']['postmaster_identity'][0])],
        'browser_ui_tested':False,'manual_station_mode':'GET inspection only; writes still require existing scoped authorization',
        'browser_url_safety_stop':'still effective; no browser automation attempted'})
    print(json.dumps({'ledger_count':len(requests),'remaining_global':40-len(requests),'http':http,
        'changed_tables':changed,'loaded_source_matches':not mismatch},ensure_ascii=False))

if __name__=='__main__':
    main()
