"""Read-only final precheck; never instantiate or enable a live model gate."""
from pathlib import Path
import sys,json,hashlib,subprocess,urllib.request
from datetime import datetime,timezone
from uuid import UUID,uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_naiwa_experience_20261020 import RUN,snapshot,save,existing_manager,database_url
from scripts.naiwa_proxy_zero_20261021 import read,sha,LEDGERS
PREVIOUS=ROOT/'storage/quality-audits/naiwa-proxy-attribution-zero-20261021'
OUT=ROOT/'storage/quality-audits/naiwa-final-zero-precheck-20261021'

def verify():
    OUT.mkdir(exist_ok=False)
    runtime=read(RUN/'runtime.json');loaded=read(RUN/'loaded-code.json')
    assert runtime['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    script="$listeners=Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 63044,63045,63046; @($listeners | ForEach-Object { $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.OwningProcess); [pscustomobject]@{port=$_.LocalPort;pid=$p.ProcessId;parent=$p.ParentProcessId;command=$p.CommandLine;executable=$p.ExecutablePath;created=$p.CreationDate} }) | ConvertTo-Json -Depth 4"
    processes=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',script],encoding='utf-8-sig'))
    for port,key in [(63044,'postgres_pid'),(63045,'backend_pid'),(63046,'frontend_pid')]:
        rows=[p for p in processes if p['port']==port];assert len(rows)==1 and rows[0]['pid']==runtime[key]
    assert loaded['pid']==runtime['backend_pid'] and loaded['workspace']==str(ROOT)
    assert 'restore_naiwa_experience_20261020:sealed_app' in next(p['command'] for p in processes if p['port']==63045)
    checks={p:sha(ROOT/p)==h for p,h in loaded['source_sha256'].items()};assert all(checks.values())
    assert loaded['physical_gate']['preparation_permanently_closed'] and loaded['guard_self_check_passed']
    assert loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL' and loaded['http_policy']['trust_env'] is False
    current=json.loads(json.dumps(snapshot('final-zero-precheck-before'),default=str))
    assert current==read(PREVIOUS/'database-after.json'),'historical database mismatch; STOP'
    previous=read(PREVIOUS/'ledger-verification.json')['sha256']
    hashes={str(p.relative_to(ROOT)):sha(p) for p in LEDGERS};assert hashes==previous
    ledger=read(LEDGERS[-1]);control=read(LEDGERS[-1].parent/'control.json')
    assert ledger['requests']==[] and not control['paid_enabled']
    sessions={str(r['id']):r for r in current['chat_sessions']};tasks={str(r['id']):r for r in current['learning_tasks']}
    fixtures=read(PREVIOUS/'asgi-regression.json')['cases']
    assert len(fixtures)==9
    assert all(c['session_id'] in sessions and c['task_id'] in tasks for c in fixtures)
    save(OUT/'database-before.json',current);save(OUT/'loaded-code.json',loaded)
    save(OUT/'processes.json',processes)
    save(OUT/'baseline.json',{'cluster_id':runtime['cluster_id'],'source_checks':checks,'ledger_sha256':hashes,
        'physical_requests':0,'remaining':{'global':5,'AGENT':4,'GENERATE':1},'paid_enabled':False,
        'loaded_manifest_pid_matches_listener':True,'loaded_manifest_is_startup_evidence_not_live_memory_dump':True,
        'nine_diagnostic_sessions_and_tasks_unchanged':True})
    health={}
    for port,path in [(63045,'/api/health'),(63046,'/api/health'),(63046,'/')]:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}{path}',timeout=15) as r:
            health[str(port)+path]={'status':r.status,'body':json.loads(r.read()) if 'health' in path else 'Vue HTML accessible'}
    save(OUT/'health.json',health)
    print('PASS identity, process/startup hash evidence, immutable history and ledgers; exit remains closed')

def scope():
    from sqlalchemy import create_engine,event
    from sqlalchemy.orm import sessionmaker
    from backend.schemas.learning_assistant import StudyContext
    from backend.services.learning_assistant_service import planner_handoff
    from backend.services.assistant_router import CapabilityRoute
    from backend.services.learning_task_tools import TaskTools
    engine=create_engine(database_url(existing_manager()))
    @event.listens_for(engine,'begin')
    def readonly(conn):conn.exec_driver_sql('SET TRANSACTION READ ONLY')
    factory=sessionmaker(engine)
    ctx=StudyContext(surface='study',conversation_id=uuid4(),subject='考研数学',knowledge_node_ids=[UUID('32a29e1e-8ae3-41fc-9322-43f727596819')])
    cases=[('subject','为数学二整体安排80分钟复习建议，仅建议', 'explicit_subject_scope'),
        ('special','只复习洛必达法则25分钟，仅建议','explicit_user_scope'),
        ('current','围绕当前题目给我复习建议','explicit_current_question')]
    rows=[]
    try:
        for name,message,origin in cases:
            h=planner_handoff(factory,ctx=ctx,user_id=uuid4(),message=message,route=CapabilityRoute('planner','recommend',1,'zero-paid-precheck'),now=datetime.now(timezone.utc))
            assert h.constraints['scope_origin']==origin
            ids=h.constraints['resolved_scope_node_ids']
            assert len(ids)>1 if name=='subject' else ids==[str(ctx.knowledge_node_ids[0])]
            tools=TaskTools(factory,budget_minutes=h.available_minutes,now=datetime.now(timezone.utc),goal=message,handoff=h.model_dump(mode='json'))
            stock=tools.execute('get_question_availability',{})
            rows.append({'case':name,'input':message,'handoff':h.model_dump(mode='json'),'inventory':stock,'PASS':True})
    finally:engine.dispose()
    save(OUT/'agent-scope.json',{'cases':rows,'database_transactions_read_only':True,'model_calls':0})
    print('PASS three scopes and actual read-only inventory tools, no tasks/plans created')

def after():
    current=json.loads(json.dumps(snapshot('final-zero-precheck-after'),default=str));before=read(OUT/'database-before.json')
    assert current==before
    hashes={str(p.relative_to(ROOT)):sha(p) for p in LEDGERS};assert hashes==read(OUT/'baseline.json')['ledger_sha256']
    assert not read(LEDGERS[-1].parent/'control.json')['paid_enabled'] and read(LEDGERS[-1])['requests']==[]
    save(OUT/'database-after.json',current)
    save(OUT/'database-diff.json',{'all_rows_identical':True,'tables':{k:len(v) for k,v in current.items() if isinstance(v,list)},'business_writes':0})
    print('PASS all business/history rows and ledger bytes unchanged, real requests 0')

def mathematics():
    from backend.services.personal_question_general import GeneralOutput,assess_general_output
    from backend.services.generation_formula_consistency import bounded_calculus_check
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import sessionmaker
    from backend.models.learning import KnowledgePoint
    raw=read(LEDGERS[1]);record=next(r for r in raw['requests'] if r['case_id']=='GENERATE')
    from backend.services.question_generation import parse_generated_output,GeneratedFormatError
    try:
        parse_generated_output(json.loads(record['response_text'])['choices'][0]['message']['content'],compatibility=True,model_class=GeneralOutput)
    except (ValueError,GeneratedFormatError):rejected=True
    else:raise AssertionError('historical wrong output admitted')
    good=dict(stem=r'求极限 $\lim_{x\to0}\frac{e^x-1-x}{x^2}$。',question_type='calculation',options=None,
        correct_answer='1/2',final_value='1/2',explanation=r'由泰勒展开，分子为 $x^2/2+O(x^3)$，除以 $x^2$ 后极限为 $1/2$。',steps=[])
    engine=create_engine(database_url(existing_manager()));factory=sessionmaker(engine)
    try:
        with factory() as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            node=db.get(KnowledgePoint,UUID('32a29e1e-8ae3-41fc-9322-43f727596819'))
            admitted=assess_general_output(GeneralOutput.model_validate(good),node,
                request_id='zero-precheck-admission-not-persisted',trace={'model':'FIXED-NO-NETWORK'},difficulty='advanced')
            q=admitted['question'];assert q.bank_scope=='personal' and q.grading_config['verified'] is False
            info=q.grading_config['generation']
            assert info['answer_independently_verified'] is False and info['bounded_calculus_check']['whole_question_verified'] is False
    finally:engine.dispose()
    unknown=bounded_calculus_check('证明一般函数序列的一致收敛性。','结论成立','结论成立','尚无独立证明。')
    assert unknown['status']=='UNKNOWN'
    prior=ROOT/'storage/quality-audits/naiwa-scope-math-zero-20261021-v9/math-persistence-proof.json'
    proof=read(prior);assert proof['wrong_counts_before']==proof['wrong_counts_after']
    assert proof['correct_counts_after']['questions']==proof['correct_counts_before']['questions']+1
    save(OUT/'math-gate.json',{'historical_wrong_rejected':rejected,'correct_admission':admitted['status'],
        'fragment_check':info['bounded_calculus_check'],'mathematical_correctness_status':info['mathematical_correctness_status'],
        'answer_independently_verified':False,'unknown_example':unknown,'new_database_writes':0,
        'persistence_this_run':'NOT_RERUN_READ_ONLY_PRECHECK',
        'previous_isolated_persistence_evidence':str(prior),'previous_evidence_sha256':sha(prior),
        'previous_counts':{k:v for k,v in proof.items() if k.endswith('before') or k.endswith('after')}})
    print('PASS real wrong replay rejected, correct admission reference-only, unknown retained; no saving this run')

def finish():
    import xml.etree.ElementTree as ET
    from scripts import naiwa_proxy_zero_20261021 as diagnostic
    diagnostic.OUT=OUT;diagnostic.transport_after()
    suites=ET.parse(OUT/'junit.xml').getroot().findall('testsuite')
    counts={k:sum(int(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped']}
    assert counts['tests']==97 and counts['failures']==counts['errors']==counts['skipped']==0
    browser=read(OUT/'browser-readonly.json');assert len(browser['results'])==9 and browser['status']=='PASS'
    baseline=read(OUT/'baseline.json');loaded=read(OUT/'loaded-code.json')
    expected={**loaded['source_sha256'],'scripts/naiwa_final_real_20261021.py':sha(ROOT/'scripts/naiwa_final_real_20261021.py')}
    # A fresh evidence baseline only. This is not an authorization/control file
    # and does not repoint the historical stage2 launcher or open any exit.
    save(OUT/'retest-baseline.json',{'expected_source_hashes':expected,'ledger_sha256':baseline['ledger_sha256'],
        'ledger_path':str(LEDGERS[-1]),'global_remaining':5,'scene_remaining':{'AGENT':4,'GENERATE':1},
        'authorization_received':False,'paid_enabled':False,'database':read(OUT/'database-after.json'),
        'legacy_stage2_baseline_not_overwritten':True})
    save(OUT/'ledger-verification.json',{'sha256':baseline['ledger_sha256'],'counts':[len(read(p)['requests']) for p in LEDGERS],
        'remaining':baseline['remaining'],'paid_enabled':False,'unchanged':True,'real_calls_this_run':0})
    save(OUT/'send-paths.json',{'factory':'backend/chat/http_clients.py','gate':'scripts/naiwa_freeze_gate_20261021.py',
        'paths':{'sync_complete':'Provider.complete -> model_http.post -> sync_client',
        'classifier':'Provider.classify_retrieval_intent -> model_http.post -> sync_client',
        'async_tools':'Provider.tool_turn -> model_http.async_client',
        'stream':'Provider.stream -> model_http.async_client',
        'generation':'run_generation -> Provider.complete -> model_http.post',
        'vision':'vision_recognition_service -> model_http.async_client (not authorized for this round)'},
        'dispatch_gate':'sync + async HTTPX _send_single_request; below send/redirect; socket audit',
        'client_policy_evidence':'transport-diagnostic-after.json','physical_send_tests':'junit.xml',
        'daily_client_override':False,'paid_exit_opened':False})
    save(OUT/'final-verification.json',{'status':'READY_FOR_EXPLICIT_AUTHORIZATION',
        'environment_code':'PASS_STARTUP_MANIFEST_PID_HASH_AND_HEALTH_EVIDENCE',
        'transport_budget':'PASS_ZERO_NETWORK_TESTS','scope_and_errors':'PASS',
        'math_gate':'PASS_BOUNDED_CHECKS_REFERENCE_ONLY','data_history':'PASS_ALL_ROWS_IDENTICAL',
        'unit_tests':counts,'visible_chrome_readonly_cases':9,'readonly_scope_cases':3,
        'real_model_requests':0,'paid_enabled':False,'real_model_quality':'PENDING',
        'services_restarted':False,'new_question_save_this_run':'NOT_RUN_READ_ONLY_PRECHECK',
        'runtime_loaded_proof_limit':'startup manifest bound to current live PID plus source hashes; not a live heap dump',
        'next_stage_requires':['new explicit user authorization','fresh scoped runtime must bind this new baseline; do not bypass or overwrite old stage2 hash checks'],
        'real_network_tls_auth_reachability':'NOT_RUN'})
    print('READY_FOR_EXPLICIT_AUTHORIZATION; fixed Provider retained, paid exit remains closed, real calls 0')

if __name__=='__main__':{'before':verify,'scope':scope,'after':after,'math':mathematics,'finish':finish}[sys.argv[1]]()
