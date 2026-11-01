"""One final scan, restore drill, real-bank API exercise and isolated regressions."""
from __future__ import annotations
import contextlib,hashlib,json,os,sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
SOURCE=ROOT/'storage/quality-audits/phase45z-final-20261013'
OUT=SOURCE/'validation-retry1'
WORK='phase45z5_work_20261013_test';PORT=59227
def write(name,data):
 p=OUT/name
 if p.exists():raise RuntimeError('existing_final_evidence_refuse_overwrite:'+name)
 p.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def main():
 if OUT.exists():raise RuntimeError('existing_retry_evidence_refuse_overwrite')
 OUT.mkdir()
 from scripts import run_phase45i_agent_real as infra
 from scripts.run_phase45hx_batch01 import all_table_fingerprints
 from sqlalchemy import create_engine,select,text
 from sqlalchemy.orm import Session,selectinload
 from backend.models.learning import Question,KnowledgePoint,KpMasteryPolicy,KpState,QuestionAttempt,LearningEvent,KpGraduationQuestionSetVersion
 from backend.services.question_eligibility import question_eligibility
 from backend.services.question_identity import text_identity,historical_identity,verified_identity
 from backend.services.auto_question_review import question_snapshot_sha256
 from backend.services.question_production_pipeline import validate_question_content
 from backend.services.graduation_question_set import question_set_sha256
 from backend.services.answer_grading import grade_final_answer
 from scripts.phase45z_final_upgrades import verify
 import psycopg
 from psycopg import sql
 cp=json.loads((SOURCE/'checkpoint.json').read_text(encoding='utf-8'))
 if cp['status']!='FINAL_QUALITY_APPLIED':raise RuntimeError('quality_apply_not_complete')
 _,cluster,port=infra.load_existing_owner()
 if port!=PORT:raise RuntimeError('owned_port_mismatch')
 infra.OUT_DIR=OUT/'validation-runtime';infra.OUT_DIR.mkdir(exist_ok=True)
 started=infra.start_owned_database(cluster,port);engine=create_engine(f'postgresql+psycopg://postgres@127.0.0.1:{PORT}/{WORK}')
 result={'status':'PHASE45Z_FINAL_QUALITY_BLOCKED','paid_model_calls':0,'development_5433_accessed':False}
 def restore(dump,name):
  with psycopg.connect(host='127.0.0.1',port=PORT,user='postgres',dbname='postgres',sslmode='disable',connect_timeout=8,autocommit=True) as conn:
   if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():raise RuntimeError('restore_database_already_exists:'+name)
   conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
  infra.command([str(infra.PG_BIN/'pg_restore.exe'),'--exit-on-error','-h','127.0.0.1','-p',str(PORT),'-U','postgres','-d',name,str(dump)],timeout=240)
  return create_engine(f'postgresql+psycopg://postgres@127.0.0.1:{PORT}/{name}')
 try:
  infra.verify_database(cluster,port)
  with Session(engine) as db:
   db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
   before=all_table_fingerprints(db.connection())
   if before!=cp['tables_after']:raise RuntimeError('work_changed_after_quality_release')
   questions=list(db.scalars(select(Question).options(selectinload(Question.kp))))
   formal=[]
   for q in questions:
    e=question_eligibility(q,q.kp)
    if q.bank_scope=='public' and e.practice_eligible and e.evidence_capability=='verified_objective' and e.grading_capability=='deterministic':formal.append(q)
   policies=list(db.scalars(select(KpMasteryPolicy)))
   members=[str(qid) for p in policies for qid in p.graduation_question_ids]
   if set(members)!={str(q.id) for q in formal} or len(members)!=len(set(members)):raise RuntimeError('formal_set_membership_mismatch')
   sets=[]
   for p in policies:
    if not p.graduation_question_ids:continue
    v=db.get(KpGraduationQuestionSetVersion,(p.kp_id,p.graduation_set_version));node=db.get(KnowledgePoint,p.kp_id)
    if v.question_ids!=p.graduation_question_ids or v.question_ids_sha256!=question_set_sha256(v.question_ids):raise RuntimeError('set_record_or_hash_mismatch')
    sets.append({'node_id':str(node.id),'node_code':node.code,'name':node.name,'subject':node.subject,'version':p.graduation_set_version,'members':len(v.question_ids),'question_ids_sha256':v.question_ids_sha256})
   if len(sets)!=253:raise RuntimeError('specific_node_coverage_lost')
   bad=[];gradebad=[];cases=0;exact=defaultdict(list);exam=defaultdict(list);semantic=defaultdict(list)
   for q in formal:
    issues=[v for v in validate_question_content(q).detected_issues if v!='human_content_review_required']
    if issues:bad.append({'id':str(q.id),'issues':issues})
    exact[text_identity(q)].append(str(q.id));historical=historical_identity(q);sem=verified_identity(q)
    if historical:exam[str(historical)].append(str(q.id))
    if sem:semantic[sem].append(str(q.id))
    inputs=[(label,None,'right' if label==q.correct_answer else 'wrong') for label in q.options]+[('',None,'unknown'),('Z',None,'unknown')] if q.question_type=='single_choice' else [(None,q.correct_answer,'right'),(None,'','unknown')]
    for label,answer,expected in inputs:
     verdict=grade_final_answer(question_type=q.question_type,config=q.grading_config,answer=answer,selected_option=label,expected=q.correct_answer,options=q.options)
     cases+=1
     if verdict.result!=expected:gradebad.append({'id':str(q.id),'input':label or answer,'actual':verdict.result,'expected':expected})
   dup={'exact':[v for v in exact.values() if len(v)>1],'historical':[v for v in exam.values() if len(v)>1],'verified_semantic':[v for v in semantic.values() if len(v)>1]}
   scan={'formal_questions':len(formal),'subjects':dict(Counter(q.kp.subject for q in formal)),
    'sources':dict(Counter('exam_curated' if q.question_provenance=='real_exam' else 'exam_variant' if q.is_variant else 'development_original' for q in formal)),
    'question_records':len(questions),'current_sets':sets,'formal_memberships':len(members),
    'structure_failures':bad,'grader_cases':cases,'grader_failures':gradebad,'duplicate_groups':dup,
    'node_member_distribution':dict(Counter(v['members'] for v in sets)),
    'revision':db.execute(text('SELECT version_num FROM alembic_version')).scalar()}
   if bad or gradebad or any(dup.values()):
    write('scan-blocker.json',scan);raise RuntimeError('final_content_or_duplicate_scan_failed')
   all_by_id={str(q.id):q for q in questions};applied=cp['applied_decisions']
   review262=json.loads((SOURCE/'review-262.json').read_text(encoding='utf-8'))['results'];review100=json.loads((SOURCE/'review-100.json').read_text(encoding='utf-8'))['results']
   upper={4,5,8,9,10,15,21,31,37,39,40,43,46,47,53,54,55,57,58,59,62,65,71,74,75,76,77,79,80,81,86,88,89,95,97,100}
   hard={25,38,41,49,63,67,83,91,92}
   for group in (review262,review100):
    for row in group:
     q=all_by_id[row['question_id']];decision=applied[row['question_id']]['decision']
     if decision=='PASS':decision='KEEP'
     if decision=='RETIRE' and (q.is_active or str(q.id) in set(members)):raise RuntimeError('retired_member_active')
     if decision in {'KEEP','UPGRADE'} and str(q.id) not in set(members):raise RuntimeError('retained_member_missing')
     row['final_decision']=('PASS' if decision=='KEEP' else decision) if group is review100 else decision
     row['final_snapshot_sha256']=question_snapshot_sha256(q)
     row['history_bound_exception']=row['question_id'] in cp['protected_keeps']
     if group is review100:
      if row['final_decision']=='RETIRE':row['final_depth']='RETIRED_LOW_VALUE'
      elif row['history_bound_exception'] or row['depth'].startswith('FOUNDATION'):row['final_depth']='NECESSARY_FOUNDATION'
      elif row['final_decision']=='UPGRADE':row['final_depth']='INTERMEDIATE' if row['index']==60 else 'UPPER_INTERMEDIATE'
      else:row['final_depth']='ADVANCED_REASONING' if row['index'] in hard else 'UPPER_INTERMEDIATE' if row['index'] in upper else 'INTERMEDIATE'
   write('review-262-applied.json',{'reviewed':262,'counts':dict(Counter(r['final_decision'] for r in review262)),'results':review262})
   write('review-100-applied.json',{'reviewed':100,'seed':451015,'counts':dict(Counter(r['final_decision'] for r in review100)),
    'retained_depth_counts':dict(Counter(r['final_depth'] for r in review100 if r['final_decision']!='RETIRE')),
    'interpretation':'The fixed pre-cleanup sample includes every retirement and upgrade; depth counts on retained members are conditional, not an unbiased population estimate.','results':review100})
   write('formal-content-snapshot.json',[{'id':str(q.id),'node_code':q.kp.code,'stem':q.stem,'options':q.options,'answer':q.correct_answer,'explanation':q.explanation,'snapshot_sha256':question_snapshot_sha256(q)} for q in formal])
   write('quality-scan-report.json',scan)
   # Choose untouched, unseen real-bank nodes for the API clone, one per subject.
   api_targets=[]
   used=set(db.scalars(select(QuestionAttempt.question_id)))
   for subject in ('考研数学','408'):
    possible=[]
    for row in sets:
     st=db.get(KpState,UUID(row['node_id']));pol=db.get(KpMasteryPolicy,UUID(row['node_id']))
     if row['subject']==subject and st and st.state=='unseen' and st.graduation_set_version is None and not any(UUID(str(qid)) in used for qid in pol.graduation_question_ids):possible.append(row)
    if not possible:raise RuntimeError('no_unbegun_api_target:'+subject)
    api_targets.append(min(possible,key=lambda r:(r['members'],r['node_code'])))
  # Independent before/after restores preserve and compare old append-only rows.
  old_engine=restore(SOURCE/'before-final.dump','phase45z_final_before_restore_r1_20261013_test')
  try:
   with old_engine.connect() as conn:oldfps=all_table_fingerprints(conn)
   if oldfps!=cp['tables_before']:raise RuntimeError('before_backup_restore_fingerprint_mismatch')
   with old_engine.connect() as old,engine.connect() as current:
    for table,keys in (('question_auto_review_events',['id']),('kp_graduation_question_set_versions',['kp_id','set_version'])):
     old_rows=[dict(r) for r in old.execute(text('SELECT * FROM '+table)).mappings()]
     new_rows={tuple(r[k] for k in keys):dict(r) for r in current.execute(text('SELECT * FROM '+table)).mappings()}
     if any(new_rows.get(tuple(r[k] for k in keys))!=r for r in old_rows):raise RuntimeError('historical_audit_or_set_row_changed:'+table)
  finally:old_engine.dispose()
  dump=OUT/'final-sealed.dump'
  if dump.exists():raise RuntimeError('final_dump_exists')
  infra.command([str(infra.PG_BIN/'pg_dump.exe'),'-h','127.0.0.1','-p',str(PORT),'-U','postgres','-d',WORK,'-Fc','-f',str(dump)],timeout=180)
  sha=hashlib.sha256(dump.read_bytes()).hexdigest().upper();toc=infra.command([str(infra.PG_BIN/'pg_restore.exe'),'--list',str(dump)],timeout=60)
  restored=restore(dump,'phase45z_final_restore_r1_20261013_test')
  try:
   with restored.connect() as conn:restoredfps=all_table_fingerprints(conn)
   if restoredfps!=before:raise RuntimeError('final_restore_fingerprint_mismatch')
  finally:restored.dispose()
  result['backup']={'path':dump.relative_to(ROOT).as_posix(),'sha256':sha,'toc_entries':len(toc.stdout.splitlines()),'restored_database':'phase45z_final_restore_r1_20261013_test','table_count':len(before),'all_rows_and_table_fingerprints_match':True,'historical_events_and_set_versions_preserved':True}
  # Network guard applies to both actual-bank API calls and fixture regressions.
  os.environ.update({'APP_ENV':'test','PHASE45I_CLOSE_OFFLINE':'1','PHASE45I_CLOSE_OUTPUT':str(OUT)})
  from scripts.phase45i_offline_guard import install,BLOCKED
  install()
  api_engine=restore(dump,'phase45z_final_api_r1_20261013_test')
  api_url=f'postgresql+psycopg://postgres@127.0.0.1:{PORT}/phase45z_final_api_r1_20261013_test'
  os.environ.update({'DATABASE_URL':api_url,'TEST_DATABASE_URL':api_url,'KAOYAN_OWNED_TEST_PORT':str(PORT)})
  from backend.config import get_settings
  get_settings.cache_clear()
  from backend.app import create_app
  from backend.api.deps import get_time_provider
  from fastapi.testclient import TestClient
  now=datetime(2026,10,25,2,tzinfo=timezone.utc);app=create_app();app.dependency_overrides[get_time_provider]=lambda:lambda:now
  try:
   with TestClient(app) as client:
    setup=client.get('/api/plans/today');assert setup.status_code==200 and setup.json()['status']=='setup',setup.text
    generated=client.post('/api/plans/today/generate',json={'selected_kp_ids':[r['node_id'] for r in api_targets],'budget':'standard'})
    assert generated.status_code==201,generated.text
    plan=generated.json();plan_id=plan['plan_id']
    with Session(api_engine) as db:
     needed=[str(qid) for r in api_targets for qid in db.get(KpMasteryPolicy,UUID(r['node_id'])).graduation_question_ids]
     shown={i['question_id'] for i in plan['items']};missing=[qid for qid in needed if qid not in shown]
    if missing:
     appended=client.post(f'/api/plans/{plan_id}/questions',json={'question_ids':missing});assert appended.status_code==200,appended.text;plan=appended.json()
    resume=client.get('/api/plans/today').json();assert resume['plan_id']==plan_id and [r['id'] for r in resume['items']]==[r['id'] for r in plan['items']]
    receipts=[]
    with Session(api_engine) as db:answers={qid:db.get(Question,UUID(qid)).correct_answer for qid in needed}
    for entry in plan['items']:
     body={'idempotency_key':'phase45z-final-api-'+entry['id'],'confidence':'certain'}
     body['selected_option' if entry['question_type']=='single_choice' else 'raw_answer']=answers[entry['question_id']]
     reply=client.post('/api/practice-items/'+entry['id']+'/answer-submissions',json=body);assert reply.status_code==200,reply.text
     receipt=reply.json();assert receipt['result']=='right',receipt
     receipts.append({'question_id':entry['question_id'],'result':receipt['result'],'evidence_reliability':receipt.get('evidence_reliability'),'mastery_reason':receipt.get('mastery_reason')})
    with Session(api_engine) as db:
     graduates=[]
     for target in api_targets:
      state=db.get(KpState,UUID(target['node_id']));assert state.state=='mastered' and state.mastered_at is not None,(target,state.state)
      detail=client.get('/api/knowledge/'+target['node_id']);assert detail.status_code==200,detail.text
      graduates.append({'node':target['node_code'],'subject':target['subject'],'set_version':state.graduation_set_version,'required':target['members'],'state':state.state})
    result['real_bank_api']={'status':'PASS','setup_before_confirmation':True,'user_confirmation_generate':True,'same_day_restore':True,'submitted_answers':len(receipts),'graduates':graduates,'receipts':receipts,'database':'phase45z_final_api_r1_20261013_test','synthetic_user_test_not_real_learning_history':True}
  finally:api_engine.dispose()
  # Run the existing focused tests in a completely empty independent database.
  testdb='phase45z_final_regression_r1_20261013_test'
  with psycopg.connect(host='127.0.0.1',port=PORT,user='postgres',dbname='postgres',sslmode='disable',connect_timeout=8,autocommit=True) as conn:
   if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(testdb,)).fetchone():raise RuntimeError('final_regression_db_exists')
   conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(testdb)))
  testurl=f'postgresql+psycopg://postgres@127.0.0.1:{PORT}/{testdb}'
  os.environ.update({'DATABASE_URL':testurl,'TEST_DATABASE_URL':testurl});get_settings.cache_clear()
  from scripts.phase45z5_final_audit import FILES
  import pytest
  with (OUT/'pytest-final.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
   rc=pytest.main([*FILES,'-q','-o','addopts=','--basetemp',str(OUT/'pytest-final-temp'),'--junitxml',str(OUT/'pytest-final.xml')])
  xml=ElementTree.parse(OUT/'pytest-final.xml').getroot();counts={k:sum(int(e.attrib.get(k,0)) for e in xml.findall('testsuite')) for k in ('tests','failures','errors','skipped')}
  by_file=Counter(t.attrib['classname'] for t in xml.iter('testcase'))
  result['regressions']={'exit_code':int(rc),'counts':counts,'by_file':dict(by_file),'database':testdb}
  if rc:raise RuntimeError('final_regressions_failed')
  with engine.connect() as conn:after=all_table_fingerprints(conn)
  if after!=before:raise RuntimeError('work_modified_by_validation_or_api_tests')
  result.update(status='PHASE45Z_FINAL_QUALITY_PASS',inventory={k:scan[k] for k in ('formal_questions','subjects','sources','question_records','formal_memberships','revision','node_member_distribution')},
   current_sets=253,upgrade_count=len(cp['results']),retirement_count=len(cp['retired']),new_questions=0,
   protected_history=cp['protected_history'],graduation_algorithm_fingerprint=cp['graduation_algorithm_fingerprint'],
   grader_cases=cases,grader_failures=0,structure_failures=0,duplicate_groups=dup,
   reviewer_kind='AI_ASSISTED_CONTENT_REVIEW_WITH_PROGRAM_CHECKS',human_verified=False,
   work_database_all_25_tables_unchanged_during_validation=True,network_guard_events=BLOCKED,
   content_optimization_closed=True,next_phase='4.5Y; development database access requires explicit authorization')
  write('final-validation.json',result)
  write('seal-manifest.json',{'status':result['status'],'sealed':True,'optimization_closed':True,'inventory':result['inventory'],'backup':result['backup'],
   'review262_sha256':hashlib.sha256((OUT/'review-262-applied.json').read_bytes()).hexdigest(),
   'review100_sha256':hashlib.sha256((OUT/'review-100-applied.json').read_bytes()).hexdigest(),
   'question_snapshot_sha256':hashlib.sha256((OUT/'formal-content-snapshot.json').read_bytes()).hexdigest(),
   'quality_report_sha256':hashlib.sha256((OUT/'quality-scan-report.json').read_bytes()).hexdigest(),
   'current_sets':scan['current_sets'],'no_further_question_changes':True})
  print(json.dumps({k:result[k] for k in ('status','inventory','upgrade_count','retirement_count','grader_cases','regressions','real_bank_api','backup')},ensure_ascii=True),flush=True)
 except BaseException as exc:
  result['error']=str(exc);write('final-blocker.json',result);raise
 finally:
  engine.dispose()
  if started:
   stopped=infra.command([str(infra.PG_BIN/'pg_ctl.exe'),'-D',str(cluster),'-m','fast','-w','-t','60','stop'],timeout=75,check=False,capture=False)
   print('ISOLATED_CLUSTER_STOPPED_NORMALLY' if stopped.returncode==0 else 'NORMAL_STOP_FAILED',flush=True)
if __name__=='__main__':main()
