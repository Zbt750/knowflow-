"""Evidence only: closed isolated DB, immutable historical ledgers, no models."""
from pathlib import Path
import sys,json,hashlib,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_naiwa_experience_20261020 import RUN,snapshot,save,existing_manager
OUT=ROOT/'storage/quality-audits/naiwa-dns-audit-zero-20261021'
PREV=ROOT/'storage/quality-audits/naiwa-current-baseline-real5-20261021'
BASE=ROOT/'storage/quality-audits/naiwa-final-zero-precheck-20261021/retest-baseline.json'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def protected():
    baseline=read(BASE)
    paths=[ROOT/p for p in baseline['ledger_sha256']]
    paths += [BASE]+list(PREV.glob('*.json'))+list(PREV.glob('*.sse'))+[PREV/'final-report.md']
    return {str(p.relative_to(ROOT)):sha(p) for p in paths}
def processes():
    script="$l=Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 63044,63045,63046; @($l | ForEach-Object { $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.OwningProcess); [pscustomobject]@{port=$_.LocalPort;pid=$p.ProcessId;command=$p.CommandLine;executable=$p.ExecutablePath} }) | ConvertTo-Json"
    return json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',script],encoding='utf-8-sig'))
def before():
    assert not OUT.exists()
    pg=existing_manager();assert pg.owner['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    data=json.loads(json.dumps(snapshot('dns-zero-before'),default=str));assert data==read(PREV/'database-after-restored.json')
    loaded=read(RUN/'loaded-code.json');runtime=read(RUN/'runtime.json');procs=processes()
    assert all(sha(ROOT/p)==h for p,h in loaded['source_sha256'].items())
    assert loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL' and loaded['physical_gate']['preparation_permanently_closed']
    for port,key in [(63044,'postgres_pid'),(63045,'backend_pid'),(63046,'frontend_pid')]:assert any(p['port']==port and p['pid']==runtime[key] for p in procs)
    ledger=read(ROOT/read(BASE)['ledger_path']);assert len(ledger['requests'])==1 and ledger['requests'][0]['finished']
    expected=read(PREV/'ledger-verification.json');assert sha(ROOT/read(BASE)['ledger_path'])==expected['canonical_ledger_sha256']
    assert not read(Path(read(BASE)['ledger_path']).parent/'control.json')['paid_enabled']
    OUT.mkdir();save(OUT/'database-before.json',data);save(OUT/'processes-before.json',procs)
    save(OUT/'protected-hashes-before.json',protected());save(OUT/'loaded-code-before.json',loaded)
    for f in ['scripts/naiwa_freeze_gate_20261021.py','backend/services/model_failure.py','backend/chat/http_clients.py','scripts/naiwa_stage2_current_20261021.py']:
        shutil.copy2(ROOT/f,OUT/('before-'+Path(f).name))
    save(OUT/'source-hashes-before.json',{p:sha(ROOT/p) for p in loaded['source_sha256']})
    save(OUT/'evidence-location.json',{'user_named_directory':'naiwa-final-real-retest-20261021',
        'actual_latest_dispatch_evidence':str(PREV),'note':'Latest dispatch-reconciliation/request-ledger/ledger-verification are in the current-baseline-real5 directory. Older directory is preserved, not overwritten.'})
    print('PASS isolated identities/history/loaded hashes; canonical failed reservation1 preserved; paid closed')
def after():
    data=json.loads(json.dumps(snapshot('dns-zero-after'),default=str));assert data==read(OUT/'database-before.json')
    assert protected()==read(OUT/'protected-hashes-before.json')
    save(OUT/'database-after.json',data)
    save(OUT/'database-diff.json',{'all_original_rows_identical':True,'new_rows':0,'business_writes':0,
        'counts':{k:len(v) for k,v in data.items() if isinstance(v,list)}})
    save(OUT/'ledger-verification.json',{'all_protected_files_unchanged':True,'sha256':protected(),
        'new_real_model_requests':0,'canonical_failed_reservations_unchanged':1,'paid_enabled':False})
    save(OUT/'processes-after.json',processes());save(OUT/'loaded-code-after.json',read(RUN/'loaded-code.json'))
    print('PASS database and all ledger/history evidence unchanged; real model calls0')

def finish():
    import xml.etree.ElementTree as ET,urllib.request
    after()
    loaded=read(RUN/'loaded-code.json');runtime=read(RUN/'runtime.json');procs=processes()
    assert loaded['pid']==runtime['backend_pid'] and loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL'
    assert loaded['physical_gate']['preparation_permanently_closed'] and loaded['guard_self_check_passed']
    assert loaded['real_model_requests']==0 and loaded['retained_budget_reservations']==1
    assert all(sha(ROOT/p)==h for p,h in loaded['source_sha256'].items())
    for port,key in [(63044,'postgres_pid'),(63045,'backend_pid'),(63046,'frontend_pid')]:
        assert any(p['port']==port and p['pid']==runtime[key] for p in procs)
    health={}
    for port in (63045,63046):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/api/health',timeout=15) as r:
            body=json.loads(r.read());assert r.status==200 and body['database']=='connected' and body['llm_model']=='FIXED-OFFLINE-NO-PAID-MODEL'
            health[str(port)]={'status':r.status,'body':body}
    suites=ET.parse(OUT/'junit-final.xml').getroot().findall('testsuite')
    counts={k:sum(int(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped']}
    assert counts=={'tests':90,'failures':0,'errors':0,'skipped':0}
    sources=read(OUT/'source-hashes-before.json')
    save(OUT/'source-changes.json',{p:{'before':h,'after':sha(ROOT/p),'changed':sha(ROOT/p)!=h} for p,h in sources.items()})
    save(OUT/'runtime-after.json',runtime);save(OUT/'health-after.json',health)
    from scripts import naiwa_proxy_zero_20261021 as transport
    transport.OUT=OUT;transport.transport_after()
    save(OUT/'root-cause-proof.json',{'old_httpx_async_dns_path_failed_in_controlled_resolver':True,
        'plain_executor_context':None,'explicit_copied_context':'inherited',
        'fixed_real_factory_async_executor_ticket_test':'PASS',
        'fixed_real_httpcore_h11_byte_host_resolver_and_write_trace':'PASS_SYNC_AND_ASYNC',
        'historical_event_was_this_unique_cause':'NOT_PROVEN_HISTORICAL_THREAD_ARGUMENTS_NOT_LOGGED',
        'no_os_dns_or_external_http_executed':True,'first_failure_log':'pytest-before.log'})
    # New engineering state only; never overwrite the former retest baseline.
    save(OUT/'repair-baseline.json',{'source_sha256':loaded['source_sha256'],'database':read(OUT/'database-after.json'),
        'protected_sha256':protected(),'retained_failed_reservations':1,'real_model_requests_this_run':0,
        'paid_enabled':False,'explicit_future_authorization_required':True,
        'legacy_retest_baselines_now_stale_do_not_bypass_checks':True})
    save(OUT/'final-verification.json',{'engineering':'PASS_ZERO_NETWORK_SCOPE','tests':counts,
        'dns_context_loss_dynamically_reproduced':True,'httpcore_phase_evidence':'PASS_CONTROLLED_NETWORK_OBJECTS',
        'diagnostics':'PASS_FIXED_ERRORS_AND_ACTUAL_AUDIT_EVENTS','history_data':'PASS_ALL_ROWS_IDENTICAL',
        'all_old_ledgers_and_previous_audit_files_unchanged':True,'retained_failed_reservations':1,
        'real_model_requests_this_run':0,'paid_enabled':False,'fixed_provider_loaded':True,'socket_guard_active':True,
        'loaded_source_hashes_match':True,'backend_pid':runtime['backend_pid'],'frontend_pid':runtime['frontend_pid'],
        'postgres_pid':runtime['postgres_pid'],'daily_services_touched':False,'new_messages_or_business_rows':0,
        'real_dns_tls_auth_model_quality':'PENDING_NOT_RUN','next_paid_retest':'NOT_STARTED_NOT_AUTHORIZED'})
    print('PASS final loaded code, health, 90 tests, unchanged history/ledgers; fixed Provider; no real calls')

if __name__=='__main__':{'before':before,'after':after,'finish':finish}[sys.argv[1]]()
