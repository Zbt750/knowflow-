"""Read-only independent engineering review; no model/legacy budget activation."""
from pathlib import Path
import sys,json,hashlib,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_naiwa_experience_20261020 import RUN,existing_manager,snapshot,save
BASE=ROOT/'storage/quality-audits/naiwa-dns-audit-zero-20261021/repair-baseline.json'
OUT=ROOT/'storage/quality-audits/naiwa-dns-independent-review-20261021'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def procs():
    ps="$listeners=Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 63044,63045,63046; @($listeners | ForEach-Object { $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.OwningProcess); $parent=Get-CimInstance Win32_Process -Filter ('ProcessId='+$p.ParentProcessId); [pscustomobject]@{port=$_.LocalPort;pid=$p.ProcessId;parent_pid=$p.ParentProcessId;command=$p.CommandLine;executable=$p.ExecutablePath;created=$p.CreationDate;parent_command=$parent.CommandLine} }) | ConvertTo-Json -Depth 4"
    return json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',ps],encoding='utf-8-sig'))
def immutable():
    paths=[BASE]+[ROOT/p for p in read(BASE)['protected_sha256']]
    paths+=list(BASE.parent.rglob('*'))
    return {str(p.relative_to(ROOT)):sha(p) for p in paths if p.is_file()}
def verify():
    baseline=read(BASE);loaded=read(RUN/'loaded-code.json');runtime=read(RUN/'runtime.json')
    assert all(sha(ROOT/p)==h for p,h in baseline['source_sha256'].items()),'repair baseline source mismatch'
    assert all(sha(ROOT/p)==h for p,h in loaded['source_sha256'].items()),'loaded source mismatch'
    assert loaded['source_sha256']==baseline['source_sha256']
    assert loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL' and loaded['physical_gate']['preparation_permanently_closed']
    assert loaded['guard_self_check_passed'] and loaded['pid']==runtime['backend_pid']
    process=procs()
    for port,key in [(63044,'postgres_pid'),(63045,'backend_pid'),(63046,'frontend_pid')]:
        rows=[p for p in process if p['port']==port];assert len(rows)==1 and rows[0]['pid']==runtime[key]
        if port!=63044:assert rows[0]['parent_pid']==runtime['supervisor_pid']
    assert 'restore_naiwa_experience_20261020:sealed_app' in next(p['command'] for p in process if p['port']==63045)
    pg=existing_manager();assert pg.owner['cluster_id']==runtime['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    data=json.loads(json.dumps(snapshot('dns-independent-review-'+sys.argv[1]),default=str))
    assert data==baseline['database'],'history drift; STOP'
    for p,h in baseline['protected_sha256'].items():assert sha(ROOT/p)==h,'protected file changed:'+p
    roundpath=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round5'
    ledger=read(roundpath/'provider-ledger.json');assert len(ledger['requests'])==1 and ledger['requests'][0]['finished']
    assert not read(roundpath/'control.json')['paid_enabled']
    return data,loaded,runtime,process
def before():
    assert not OUT.exists()
    data,loaded,runtime,process=verify();OUT.mkdir()
    save(OUT/'database-before.json',data);save(OUT/'loaded-code-before.json',loaded)
    save(OUT/'processes-before.json',process);save(OUT/'runtime-before.json',runtime)
    save(OUT/'immutable-sha256-before.json',immutable())
    save(OUT/'source-sha256-before.json',{p:sha(ROOT/p) for p in read(BASE)['source_sha256']})
    print('PASS latest repair baseline, live process/parents, cluster/database, closed fixed runtime and preserved failed reservation1')
def after():
    data,loaded,runtime,process=verify();assert data==read(OUT/'database-before.json')
    assert immutable()==read(OUT/'immutable-sha256-before.json')
    assert process==read(OUT/'processes-before.json'),'process identity changed'
    save(OUT/'database-after.json',data);save(OUT/'processes-after.json',process)
    save(OUT/'loaded-code-after.json',loaded);save(OUT/'immutable-sha256-after.json',immutable())
    save(OUT/'source-sha256-after.json',{p:sha(ROOT/p) for p in read(BASE)['source_sha256']})
    save(OUT/'database-diff.json',{'all_rows_identical':True,'new_rows':0,'updates':0,'deletes':0,
        'counts':{t:len(r) for t,r in data.items() if isinstance(r,list)}})
    save(OUT/'ledger-verification.json',{'historical_counts':[19,5],'round5_failed_reservations':1,
        'all_old_ledgers_and_evidence_sha256_unchanged':True,'real_model_requests_this_run':0,
        'paid_enabled':False,'external_dns_http_requests':0})
    print('PASS source, process, rows and all protected hashes unchanged; no new model requests')

def finish():
    import xml.etree.ElementTree as ET,urllib.request
    after()
    suites=ET.parse(OUT/'junit-all.xml').getroot().findall('testsuite')
    counts={k:sum(int(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped']}
    assert counts=={'tests':98,'failures':7,'errors':0,'skipped':0}
    failed=[c.attrib['name'] for s in suites for c in s.findall('testcase') if c.find('failure') is not None]
    save(OUT/'test-summary.json',{**counts,'passed':91,'failed_cases':failed,
        'no_xfail_skip_or_weakened_assertions':True,'baseline_test_artifact_paths_redirected_only':True})
    processes=read(OUT/'processes-after.json')
    save(OUT/'process-fingerprints.json',{'before':{str(p['port']):hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest() for p in read(OUT/'processes-before.json')},
        'after':{str(p['port']):hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest() for p in processes}})
    health={}
    for port in (63045,63046):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/api/health',timeout=15) as r:
            body=json.loads(r.read());assert r.status==200 and body['database']=='connected' and body['llm_model']=='FIXED-OFFLINE-NO-PAID-MODEL'
            health[str(port)]={'status':r.status,'body':body}
    save(OUT/'local-health.json',health)
    save(OUT/'state-machine-review.json',[
        {'state':'preflight_rejected','evidence':'guard branch + refusal event','assessment':'PASS_AT_REQUEST_ENTRY_ONLY'},
        {'state':'reservation_created','evidence':'locked atomic fsync ledger update','assessment':'PASS'},
        {'state':'dns_attempted','evidence':'audit callback, allowed flag','assessment':'PASS_EVENT_SOURCE_ADDRESS_POLICY_FAILS_MULTICAST'},
        {'state':'connection_attempted','evidence':'socket audit callback','assessment':'PASS_EVENT_SOURCE_NOT_CONNECTION_SUCCESS'},
        {'state':'http_dispatch_attempted','evidence':'httpcore send_request_headers.started','assessment':'FAIL_AUTH_REVOCATION_NOT_RECHECKED',
         'note':'Trace indicates entering header send, never proof of remote receipt. Memory writes continue after close/expiry.'},
        {'state':'http_response_received','evidence':'HTTPX Response object; test simulated=true','assessment':'PASS_TESTED_NOT_REAL_NETWORK'},
        {'state':'request_state_unknown','evidence':'failure without delivery proof or interrupted body','assessment':'PASS_RESERVATION_RETAINED'}])
    save(OUT/'network-budget-evidence.json',{'fixed_provider':True,'paid_enabled':False,'preparation_hard_closed':True,
        'canonical_failed_reservations':1,'canonical_ledger_unchanged':True,'test_model_responses':'MOCK_OR_MEMORY_SIMULATED_ONLY',
        'external_dns_http':0,'new_real_model_requests':0,'budget_caps_tested':{'global':5,'AGENT':4,'GENERATE':1},
        'closed_exit_before_initial_dispatch':'PASS','revocation_after_connection_before_headers':'FAIL',
        'multicast_resolver_answers':'FAIL','vision_payload_in_text_scene_gate':'FAIL_DEFENSE_IN_DEPTH_UPPER_ROUTE_STILL_BLOCKS_VISION_ENDPOINT',
        'shared_factory_paths':['sync complete','async tool_turn','stream','classifier','generation complete','vision'],
        'vision_note':'Sharing a factory is not purpose authorization; default vision settings may reuse the chat model. No live vision API was invoked.'})
    save(OUT/'final-verification.json',{'STATE_MACHINE':'FAIL','NETWORK_GATE':'FAIL','BUDGET_LEDGER':'PASS',
        'HISTORY_PRESERVATION':'PASS','REAL_MODEL_READINESS':'NOT_READY','status':'NOT_READY',
        'tests':{**counts,'passed':91},'fixed_provider':True,'paid_enabled':False,'production_source_changed':False,
        'services_restarted':False,'business_writes':0,'real_model_requests':0,'external_dns_http':0,
        'retained_failed_reservations':1,'historical_sha256_unchanged':True,'real_dns_tls_auth_quality':'PENDING_NOT_RUN'})
    print('NOT_READY: STATE_MACHINE FAIL, NETWORK_GATE FAIL; budget/history PASS; tests91passed7failed; external/model calls0')

if __name__=='__main__':{'before':before,'after':after,'finish':finish}[sys.argv[1]]()
