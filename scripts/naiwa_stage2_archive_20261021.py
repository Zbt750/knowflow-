"""Read-only reconciliation of a stopped acceptance; never sends model calls."""
from pathlib import Path
import sys,json,hashlib,shutil,inspect,asyncio
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_naiwa_experience_20261020 import snapshot,save,RUN
OUT=ROOT/'storage/quality-audits/naiwa-current-baseline-real5-20261021'
BASE=ROOT/'storage/quality-audits/naiwa-final-zero-precheck-20261021/retest-baseline.json'
ROUND=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round5'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
before=read(OUT/'database-before.json');after=json.loads(json.dumps(snapshot('current-real5-final-'+sys.argv[1]),default=str))
save(OUT/('database-after-'+sys.argv[1]+'.json'),after)
diff={}
for table,rows in before.items():
    if not isinstance(rows,list):continue
    key=lambda r:str(r.get('id',r.get('kp_id')))
    a={key(r):r for r in rows};b={key(r):r for r in after[table]}
    assert all(b.get(k)==v for k,v in a.items()),'original changed:'+table
    new=[v for k,v in b.items() if k not in a]
    assert not new or table in {'chat_sessions','chat_messages','learning_tasks'},'unexpected new:'+table
    diff[table]={'before':len(a),'after':len(b),'original_unchanged':True,'new_ids':[key(r) for r in new]}
save(OUT/'database-diff.json',diff)
ledger=read(ROUND/'provider-ledger.json');assert len(ledger['requests'])==1
record=ledger['requests'][0];assert record['case_id']=='AGENT' and record['error_type']=='BudgetStop' and record['http_status'] is None
assert not read(ROUND/'control.json')['paid_enabled']
sessions=read(OUT/'sessions.json');task=next(t for t in after['learning_tasks'] if str(t['session_id'])==sessions['AGENT'])
assert task['status']=='failed' and task['metrics']['model_failure']['reason']=='external_dns_closed'
assert task['trace']==[]
scope=task['context']['planner_handoff']['constraints'];assert scope['scope_origin']=='explicit_subject_scope' and len(scope['resolved_scope_node_ids'])>1
save(OUT/'agent-scope-and-evaluation.json',{'session_id':sessions['AGENT'],'task_id':task['id'],'goal':task['goal'],
    'handoff':task['context']['planner_handoff'],'scope_resolution':'PASS_SUBJECT_MULTINODE',
    'actual_tool_trace':task['trace'],'actual_learning_data_tool_queries':0,'final_plan':None,
    'planning_completion':'BLOCKED','real_answer_quality':'NOT_EVALUABLE_NO_MODEL_RESPONSE',
    'reason':'socket audit refused external DNS before HTTP exchange; no retry, no generation scenario'})
summary={'reservations_retained':1,'transport_dispatch_attempts':1,'confirmed_model_http_requests_sent':0,
    'provider_http_responses':0,'usage':None,'finish_reason':None,'http_status':None,
    'budget_consumed_conservatively':1,'budget_released':False,'remaining_slots_not_authorized_for_reuse':{'global':4,'AGENT':3,'GENERATE':1},
    'stop_reason':'external_dns_closed','network_safety_stop':True,'record_number':record['number'],'request_id':record['request_id'],
    'latency_seconds':record.get('latency_seconds'),'canonical_summary_is_reservation_count_not_confirmed_network_exchange':True,
    'real_model_quality':'PENDING','generation_scenario':'BLOCKED_AGENT_NOT_PASSED','paid_enabled':False}
save(OUT/'dispatch-reconciliation.json',summary)
save(OUT/'request-ledger.json',ledger)
baseline=read(BASE);old={p:sha(ROOT/p) for p in baseline['ledger_sha256'] if str(ROOT/p)!=baseline['ledger_path']}
assert all(h==baseline['ledger_sha256'][p] for p,h in old.items())
save(OUT/'ledger-verification.json',{'old_ledger_sha256':old,'old_ledgers_unchanged':True,
    'canonical_ledger_sha256':sha(ROUND/'provider-ledger.json'),'canonical_reservations':1,'confirmed_model_http_requests_sent':0})
shutil.copy2(RUN/'loaded-code.json',OUT/('loaded-code-'+sys.argv[1]+'.json'))
save(OUT/'dns-context-source-evidence.json',{'asyncio_getaddrinfo_source':inspect.getsource(asyncio.BaseEventLoop.getaddrinfo),
    'diagnosis':'Confirmed external_dns_closed. Thread executor context inheritance is a source-level suspect; not dynamically proven in this run. No further network attempt performed.'})
print(json.dumps(summary,ensure_ascii=False))
if sys.argv[1]=='restored':
    import urllib.request,subprocess
    loaded=read(RUN/'loaded-code.json');runtime=read(RUN/'runtime.json')
    assert loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL' and loaded['physical_gate']['preparation_permanently_closed']
    assert loaded['pid']==runtime['backend_pid'] and all(sha(ROOT/p)==h for p,h in loaded['source_sha256'].items())
    health={}
    for port in [63045,63046]:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/api/health',timeout=10) as r:
            body=json.loads(r.read());assert r.status==200 and body['database']=='connected' and body['llm_model']=='FIXED-OFFLINE-NO-PAID-MODEL'
            health[str(port)]={'status':r.status,'body':body}
    save(OUT/'health-restored.json',health)
    ps="$l=Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 63044,63045,63046; @($l | ForEach-Object { $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.OwningProcess); [pscustomobject]@{port=$_.LocalPort;pid=$p.ProcessId;command=$p.CommandLine} }) | ConvertTo-Json"
    processes=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',ps],encoding='utf-8-sig'))
    for port,key in [(63044,'postgres_pid'),(63045,'backend_pid'),(63046,'frontend_pid')]:
        assert any(p['port']==port and p['pid']==runtime[key] for p in processes)
    save(OUT/'processes-final.json',processes);save(OUT/'runtime-restored.json',runtime)
    save(OUT/'final-verification.json',{'overall':'BLOCKED_BY_DNS_AUDIT','engineering_execution':'PARTIAL',
        'agent_subject_scope':'PASS','agent_plan':'BLOCKED_NO_MODEL_RESPONSE','real_model_quality':'PENDING',
        'mathematical_correctness':'NOT_RUN','difficulty_execution':'NOT_RUN','generation':'BLOCKED_AGENT_NOT_PASSED',
        'browser_failure_display_and_refresh':'PASS','data_safety':'PASS','diagnostic_precision':'FAIL_EGRESS_CLOSED_TEXT_NOT_SPECIFIC_TO_DNS',
        'confirmed_model_http_requests_sent':0,'conservative_budget_occupied':1,'retained_reservations':1,
        'paid_enabled':False,'fixed_provider_restored':True,'socket_protection_active':True,
        'old_ledgers_unchanged':True,'old_rows_unchanged':True,'new_sessions':1,'new_messages':2,'new_failed_tasks':1,
        'new_questions_versions_plans_practice_items_attempts_events':0,'daily_services_touched':False,
        'restored_backend_pid':runtime['backend_pid'],'frontend_url':'http://127.0.0.1:63046/study',
        'no_retry_no_reallocation':True,'usage':None,'finish_reason':None,'http_status':None})
