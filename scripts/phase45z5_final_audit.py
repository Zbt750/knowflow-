"""Read-only final bank checks; regressions write only to a new empty test DB."""
from __future__ import annotations
import contextlib,hashlib,json,os,random,sys
from collections import Counter,defaultdict
from pathlib import Path
from xml.etree import ElementTree
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
BASE=ROOT/'storage/quality-audits/phase45z5-20261013'
OUT=BASE/'final-candidate'
WORK='phase45z5_work_20261013_test';TEST='phase45z5_final_regression_20261013_test';PORT=59227
FILES=['tests/unit/test_codex_independent_review.py','tests/unit/test_phase45hs_identity.py',
 'tests/unit/mastery/test_frozen_graduation_set.py','tests/unit/test_current_graduation_projection.py',
 'tests/integration/test_auto_question_review.py','tests/integration/test_phase45hw_graduation.py',
 'tests/integration/test_personal_question_bank.py','tests/integration/test_post_graduation_practice.py',
 'tests/integration/test_answer_submissions.py']
def save(name,payload):
 (OUT/name).write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def main():
 if OUT.exists():raise SystemExit('existing_final_candidate_refuse_overwrite')
 OUT.mkdir(parents=True)
 from scripts import run_phase45i_agent_real as infra
 from scripts.run_phase45hx_batch01 import all_table_fingerprints
 from sqlalchemy import create_engine,select,text
 from sqlalchemy.orm import Session,selectinload
 from backend.models.learning import Question
 from backend.services.question_eligibility import question_eligibility
 from backend.services.question_identity import text_identity,historical_identity
 from backend.services.question_production_pipeline import validate_question_content
 from backend.services.answer_grading import grade_final_answer
 import psycopg
 from psycopg import sql
 _,cluster,port=infra.load_existing_owner()
 if port!=PORT:raise RuntimeError('owned_port_mismatch')
 infra.OUT_DIR=OUT/'runtime';infra.OUT_DIR.mkdir()
 started=infra.start_owned_database(cluster,port);engine=None
 try:
  infra.verify_database(cluster,port)
  engine=create_engine(f'postgresql+psycopg://postgres@127.0.0.1:{PORT}/{WORK}')
  with Session(engine) as db:
   db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
   identity=db.execute(text('SELECT current_database(),inet_server_port(),system_identifier FROM pg_control_system()')).one()
   if tuple(identity)!=(WORK,PORT,7694698872540080852):raise RuntimeError('work_identity_mismatch')
   before=all_table_fingerprints(db.connection());formal=[]
   for q in db.scalars(select(Question).options(selectinload(Question.kp))):
    e=question_eligibility(q,q.kp)
    if q.bank_scope=='public' and e.practice_eligible and e.evidence_capability=='verified_objective' and e.grading_capability=='deterministic':formal.append(q)
   records=[];bad=[];grader_bad=[];cases=0;content_groups=defaultdict(list);exam_groups=defaultdict(list)
   for q in formal:
    issues=[x for x in validate_question_content(q).detected_issues if x!='human_content_review_required']
    if issues:bad.append({'id':str(q.id),'issues':issues})
    content_groups[text_identity(q)].append(str(q.id))
    historical=historical_identity(q)
    if historical:exam_groups[str(historical)].append(str(q.id))
    if q.question_type=='single_choice':
     for label in (*q.options,'','Z'):
      result=grade_final_answer(question_type=q.question_type,config=q.grading_config,answer=None,selected_option=label,expected=q.correct_answer,options=q.options).result
      expected='right' if label==q.correct_answer else ('wrong' if label in q.options else 'unknown')
      cases+=1
      if result!=expected:grader_bad.append({'id':str(q.id),'input':label,'actual':result,'expected':expected})
    else:
     for answer,expected in ((q.correct_answer,'right'),('','unknown')):
      result=grade_final_answer(question_type=q.question_type,config=q.grading_config,answer=answer,selected_option=None,expected=q.correct_answer,options=q.options).result;cases+=1
      if result!=expected:grader_bad.append({'id':str(q.id),'input':answer,'actual':result,'expected':expected})
    records.append({'id':str(q.id),'node_code':q.kp.code,'node_name':q.kp.name,'subject':q.kp.subject,
     'source_class':'exam_curated' if q.question_provenance=='real_exam' else 'exam_variant' if q.is_variant else 'development_original',
     'stem':q.stem,'options':q.options,'answer':q.correct_answer,'explanation':q.explanation,
     'snapshot_version':q.grading_config.get('codex_independent_review',{}).get('version'),
     'difficulty_label_not_proof':q.difficulty})
   save('formal-questions.json',records)
   oldflags=json.loads((ROOT/'storage/quality-audits/phase45z-20261012/scan-49/quality-scan-flags.json').read_text(encoding='utf-8'))
   prior_risk={r['question_id'] for r in oldflags if r['provenance_class']=='development_original' and 'potentially_shallow_single_step_profile' in r['flags']}
   done={r['question_id'] for r in json.loads((ROOT/'storage/quality-audits/phase45z4-20261013/phase45z4-final-report.json').read_text(encoding='utf-8'))['upgraded_questions']}
   for checkpoint in (BASE/'sample-upgrades').glob('batch*/checkpoint.json'):
    done.update(r['id'] for r in json.loads(checkpoint.read_text(encoding='utf-8'))['results'])
   keeps=json.loads((BASE/'sample-upgrades/remaining-kept/decisions.json').read_text(encoding='utf-8'))['results']
   done.update(r['question_id'] for r in keeps)
   remaining=[r for r in records if r['id'] in prior_risk-done]
   save('remaining-depth-review.json',remaining)
   originals=[r for r in records if r['source_class']=='development_original']
   sample=random.Random(451015).sample(sorted(originals,key=lambda r:r['id']),100)
   save('fresh-original-sample-100.json',{'seed':451015,'review_status':'CONTENT_REVIEW_PENDING','questions':sample})
   scan={'formal_questions_scanned':len(formal),'structure_failures':bad,'grader_cases':cases,'grader_failures':grader_bad,
    'exact_content_duplicate_groups':[v for v in content_groups.values() if len(v)>1],
    'formal_exam_identity_duplicate_groups':[v for v in exam_groups.values() if len(v)>1],
    'previous_heuristic_original_candidates':len(prior_risk),'candidates_with_recorded_upgrades_or_keep_dispositions':len(prior_risk & done),
    'previous_candidates_without_recorded_content_disposition':len(remaining),
    'fresh_sample_content_review_completed':False,'medium_upper_population_percentage':None,
    'heuristics_not_automatic_rejections':True}
   save('quality-scan-report.json',scan)
  if bad or grader_bad or scan['exact_content_duplicate_groups'] or scan['formal_exam_identity_duplicate_groups']:
   raise RuntimeError('final_structure_grader_or_exact_duplicate_check_failed')
  with psycopg.connect(host='127.0.0.1',port=PORT,user='postgres',dbname='postgres',sslmode='disable',connect_timeout=8,autocommit=True) as conn:
   if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(TEST,)).fetchone():raise RuntimeError('regression_db_exists_refuse_overwrite')
   conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(TEST)))
  os.environ.update({'APP_ENV':'test','DATABASE_URL':f'postgresql+psycopg://postgres@127.0.0.1:{PORT}/{TEST}',
   'TEST_DATABASE_URL':f'postgresql+psycopg://postgres@127.0.0.1:{PORT}/{TEST}','KAOYAN_OWNED_TEST_PORT':str(PORT),
   'PHASE45I_CLOSE_OFFLINE':'1','PHASE45I_CLOSE_OUTPUT':str(OUT)})
  from scripts.phase45i_offline_guard import install,BLOCKED
  install()
  import pytest
  with (OUT/'pytest.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
   rc=pytest.main([*FILES,'-q','-o','addopts=','--basetemp',str(OUT/'pytest-temp'),'--junitxml',str(OUT/'pytest.xml')])
  suites=ElementTree.parse(OUT/'pytest.xml').getroot()
  counts={k:sum(int(e.attrib.get(k,0)) for e in suites.findall('testsuite')) for k in ('tests','failures','errors','skipped')}
  with engine.connect() as conn:after=all_table_fingerprints(conn)
  if before!=after:raise RuntimeError('work_bank_modified_by_test_suite')
  summary={'status':'REGRESSIONS_PASS' if rc==0 else 'REGRESSIONS_FAILED','exit_code':int(rc),'counts':counts,'files':FILES,
   'test_database':TEST,'work_database_unchanged_all_tables':True,'table_count':len(before),'network_guard_events':BLOCKED,
   'model_calls':0,'development_5433_accessed':False,'scan':scan}
  save('final-engineering-checks.json',summary);print(json.dumps(summary,ensure_ascii=True),flush=True)
 finally:
  if engine is not None:engine.dispose()
  if started:
   stop=infra.command([str(infra.PG_BIN/'pg_ctl.exe'),'-D',str(cluster),'-m','fast','-w','-t','60','stop'],timeout=75,check=False,capture=False)
   print('ISOLATED_CLUSTER_STOPPED_NORMALLY' if stop.returncode==0 else 'NORMAL_STOP_FAILED',flush=True)
if __name__=='__main__':main()
