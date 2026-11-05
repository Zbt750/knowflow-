"""Read-only closeout for the V2 acceptance stopped on audit preservation drift."""
from pathlib import Path
import hashlib,json,shutil,time
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_agent_full_v2_20261021 import (
    OUT,RUN,OLD_RUN,OLD_LEDGERS,LEDGER_PATH,CONTROL_PATH,BASELINE_PATH,read,save,sha,
    snapshot_database,compare_snapshot,
)

def collect():
    ledger=read(LEDGER_PATH)
    assert len(ledger['requests'])==1
    assert read(CONTROL_PATH)['paid_enabled'] is False
    assert sha(LEDGER_PATH)==sha(OUT/'A1-ledger-original.json'),'original V2 request changed'
    baseline=read(BASELINE_PATH)
    old={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in OLD_LEDGERS}
    assert old==baseline['old_ledger_sha256']
    data=snapshot_database(OUT/'database-final-before-fixed.json')
    registry=read(RUN/'session-registry.json')['sessions']
    diff=compare_snapshot(read(OUT/'database-before.json'),data,
        mutable_session_ids=[s['session_id'] for s in registry],
        mutable_plan_id=read(RUN/'runtime-data.json').get('today_plan_id'))
    assert diff['preexisting_rows_preserved']
    save(OUT/'database-diff.json',diff)
    session_ids={s['session_id'] for s in registry}
    messages=[m for m in data['chat_messages'] if m['session_id'] in session_ids]
    sessions=[s for s in data['chat_sessions'] if s['id'] in session_ids]
    save(OUT/'complete-chat-records.json',{'sessions':sessions,'messages':messages})
    protected_path=ROOT/'storage/quality-audits/naiwa-f123-repair-zero-20261021/protected-sha256-before.json'
    expected=read(protected_path)
    changes=[]
    destination=OUT/'overwritten-legacy-diagnostics-current-copy'
    destination.mkdir(exist_ok=True)
    for name,prior in expected.items():
        target=ROOT/name
        current=sha(target) if target.is_file() else None
        if current!=prior:
            assert target.is_file()
            copy=destination/(target.parent.name+'__'+target.name)
            if not copy.exists():shutil.copy2(target,copy)
            candidates=[p for p in (ROOT/'storage/quality-audits').rglob(target.name)
                if p.is_file() and sha(p)==prior]
            changes.append({'path':name,'original_sha256':prior,'current_sha256':current,
                'original_bytes_recovered':False,'matching_copy_paths':[str(p) for p in candidates],
                'current_replayed_bytes_preserved_at':str(copy)})
    save(OUT/'history-preservation-incident.json',{
        'time':time.time(),'status':'FAIL_LEGACY_DIAGNOSTIC_JSON_OVERWRITTEN_BY_DIRECT_PYTEST',
        'cause':'Legacy test functions use hard-coded audit output paths; initial direct pytest runs did not redirect them.',
        'affected_count':len(changes),'files':changes,'restoration_claimed':False,
        'old_reports_junit_hash_manifests_and_model_ledgers_not_rewritten':True,
        'subsequent_tests_redirected':'scripts/run_naiwa_agent_full_v2_zero.py',
        'further_real_model_testing_stopped':True})
    row=ledger['requests'][0]
    terminal=any(line.strip()=='data: [DONE]' for line in row['response_text'].splitlines())
    save(OUT/'dispatch-reconciliation.json',{
        'request_id':row['request_id'],'budget_reservations':1,'confirmed_model_http_sent':1,
        'http_dispatch_attempts':row['http_dispatch_attempts'],'http_responses_received':1,
        'http_status':row['http_status'],'usage':row['usage'],'finish_reason':row['finish_reason'],
        'latency_seconds':row['latency_seconds'],'terminal_done_observed':terminal,
        'original_ledger_sha256':sha(LEDGER_PATH),'original_ledger_unchanged':True,
        'spurious_unknown_phase_retained_in_original':True,
        'dynamic_reproduction':'stream-terminal-before.xml',
        'cause':'Provider stops normally at DONE. Async raw iterator receives GeneratorExit and the old wrapper labels it an interrupted network stream.',
        'independent_accounting':'full HTTP response + parsed usage + stop + DONE proves this physical model request completed',
        'physical_requests_this_round':1,'remaining_slots_not_authorization_to_continue':39,
        'paid_enabled':False})
    save(OUT/'ledger-verification.json',{
        'old_ledger_sha256':old,'old_ledger_unchanged':True,
        'old_confirmed_historical_counts':[19,5],'round5_failed_reservations':len(read(OLD_LEDGERS[2])['requests']),
        'v2_count':1,'v2_original_request_sha256':sha(LEDGER_PATH),
        'v2_record_unchanged_since_A1':True,'paid_enabled':False})
    live_manifest=read(RUN/'loaded-code.json')
    save(OUT/'loaded-real-code-before-stop.json',live_manifest)
    for name in ('runtime.json','loaded-code.json'):
        source=OLD_RUN/name
        copy=OUT/('preserved-before-fixed-'+name)
        if source.exists() and not copy.exists():shutil.copy2(source,copy)
    a=read(OUT/'A1-welcome-journey.json');b=read(OUT/'A1-welcome-refresh.json')
    save(OUT/'browser-A1-verification.json',{
        'actual_visible_system_chrome':True,'ui_message_sent':a['userText'],'session_id':sessions[0]['id'],
        'sse_and_final_response_recorded':True,'refresh_text_identical':a['text']==b['text'],
        'refresh_katex_errors':b['katexErrors'],'horizontal_overflow':b['horizontalOverflow'],
        'persisted_messages':len(messages),'true_model_requests':1,
        'normal_user_experience':'PARTIAL_GENERIC_ONBOARDING_DOES_NOT_EXPLAIN_PROJECT_TOOLS',
        'no_new_question_plan_attempt_learning_event':all(diff['tables'][t]['added']==0 for t in
            ['questions','question_versions','daily_plans','practice_items','question_attempts','learning_events'])})
    print(json.dumps({'physical_requests':1,'paid_enabled':False,'historical_db_rows_preserved':True,
        'old_ledgers_preserved':True,'legacy_diagnostic_json_drift':len(changes),
        'model_testing_stopped':True,'saved_chat_messages':len(messages)},ensure_ascii=False))

def verify_fixed():
    import httpx,subprocess
    from scripts.restore_naiwa_experience_20261020 import existing_manager
    from scripts.naiwa_freeze_gate_20261021 import process_started,ROUND
    runtime=read(OLD_RUN/'runtime.json');loaded=read(OLD_RUN/'loaded-code.json')
    assert runtime['status']=='running' and runtime['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    assert loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL'
    assert loaded['physical_gate']['preparation_permanently_closed'] is True
    assert loaded['guard_self_check_passed'] is True
    assert loaded['pid']==runtime['backend_pid']
    assert all(sha(ROOT/name)==value for name,value in loaded['source_sha256'].items())
    health={}
    with httpx.Client(trust_env=False,timeout=5) as client:
        for port in (63045,63046):
            response=client.get(f'http://127.0.0.1:{port}/api/health')
            assert response.status_code==200 and response.json()['database']=='connected'
            assert response.json()['llm_model']=='FIXED-OFFLINE-NO-PAID-MODEL'
            assert response.headers['x-naiwa-backend-pid']==str(runtime['backend_pid'])
            health[str(port)]={'http_status':200,'body':response.json(),'backend_pid_header':response.headers['x-naiwa-backend-pid']}
    pg=existing_manager();identity=pg._identity()
    assert identity[0]==runtime['postgres_pid']
    data=snapshot_database(OUT/'database-after-fixed-restore.json',allow_live_identity=identity)
    previous=read(OUT/'database-final-before-fixed.json')
    assert data==previous,'fixed restore changed business rows'
    assert sha(LEDGER_PATH)==sha(OUT/'A1-ledger-original.json')
    baseline=read(BASELINE_PATH)
    assert {str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in OLD_LEDGERS}==baseline['old_ledger_sha256']
    assert read(CONTROL_PATH)['paid_enabled'] is False
    assert read(ROUND/'control.json')['paid_enabled'] is False
    ps="$ids=@("+','.join(str(runtime[k]) for k in ['supervisor_pid','postgres_pid','backend_pid','frontend_pid'])+"); @($ids | ForEach-Object {Get-CimInstance Win32_Process -Filter ('ProcessId='+$_) | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate}) | ConvertTo-Json -Depth 4"
    raw=subprocess.check_output(['powershell','-NoProfile','-Command',ps],encoding='utf-8-sig')
    process=json.loads(raw)
    assert all(next(p for p in process if p['ProcessId']==runtime[key])['ParentProcessId']==runtime['supervisor_pid'] for key in ['backend_pid','frontend_pid'])
    result={'state':'FIXED_PROVIDER_RESTORED','runtime':runtime,'processes':process,'health':health,
        'loaded_code_hashes_match_current_workspace':True,'fixed_provider':True,'preparation_hard_closed':True,
        'v2_paid_enabled':False,'round5_paid_enabled':False,'socket_audit_installed_and_self_check_passed':True,
        'business_rows_identical_across_fixed_restore':True,'old_ledgers_unchanged':True,
        'v2_original_request_unchanged':True,'real_model_requests_this_round':1,
        'further_paid_testing_blocked':'historical diagnostic artifact overwrite incident; original expected hashes retained',
        'pid_creation_ticks':{key:process_started(runtime[key]) for key in ['supervisor_pid','postgres_pid','backend_pid','frontend_pid']}}
    save(OUT/'final-fixed-verification.json',result)
    save(OUT/'final-fixed-loaded-code.json',loaded)
    chat=read(OUT/'complete-chat-records.json')
    lines=['# 奶蛙 V2 真实页面对话记录','', '日期：2026-10-22（Asia/Shanghai）。仅首条真实对话，随后按停止规则封闭出口。','']
    for message in sorted(chat['messages'],key=lambda row:row['created_at']):
        lines.extend(['## '+('用户' if message['role']=='user' else '奶蛙（真实 DeepSeek 返回）'),' ',message['content'],''])
    (OUT/'transcript.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'fixed_provider':True,'health':{k:v['http_status'] for k,v in health.items()},
        'backend_pid':runtime['backend_pid'],'frontend_pid':runtime['frontend_pid'],'postgres_pid':runtime['postgres_pid'],
        'business_rows_unchanged':True,'paid_enabled':False,'true_model_requests':1},ensure_ascii=False))

if __name__=='__main__':
    verify_fixed() if len(sys.argv)>1 and sys.argv[1]=='fixed' else collect()
