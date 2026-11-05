"""Final quality release: guarded revisions, retirement, version publication."""
from __future__ import annotations
import argparse,hashlib,json,sys
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/phase45z-final-20261013'
DB='phase45z5_work_20261013_test';PORT=59227;SID='7694698872540080852'
BASE_DUMP=ROOT/'storage/quality-audits/phase45z5-20261013/originals/batch15-retry1/post-batch.dump'
BASE_SHA='21A4F0F9F4FF89297E31B2118B862CC9A6CBDC928087C361E5273EF683F95088'
def norm(v):return json.loads(json.dumps(v,default=str))
def save(name,v):
 p=OUT/name
 if p.exists():raise RuntimeError('existing_evidence_refuse_overwrite:'+name)
 p.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def execute(db,apply):
 from sqlalchemy import select,text
 from backend.models.learning import Question,QuestionAttempt,LearningEvent,KpState,KnowledgePoint,KpMasteryPolicy,KpGraduationQuestionSetVersion,QuestionAutoReviewEvent
 from scripts.phase45z5_original_batch01 import table_fingerprint,policy_rule_fingerprint
 from scripts.run_phase45hx_batch01 import all_table_fingerprints
 from backend.services.auto_question_review import current_auto_review,revoke_auto_qualification,question_snapshot_sha256
 from backend.services.graduation_question_set import publish_all_public_question_set_version
 from backend.services.question_eligibility import question_eligibility
 from scripts import phase45z5_sample_upgrade_batch01 as upgrade_runner
 from scripts.phase45z_final_upgrades import final_specs,verify
 identity=db.execute(text('SELECT current_database(),inet_server_port(),system_identifier FROM pg_control_system()')).one()
 if tuple(map(str,identity))!=(DB,str(PORT),SID):raise RuntimeError('work_identity_mismatch')
 tables_before=all_table_fingerprints(db.connection())
 protected=norm({m.__tablename__:table_fingerprint(db,m) for m in (QuestionAttempt,LearningEvent,KpState)})
 rules=policy_rule_fingerprint(db)
 review262=json.loads((OUT/'review-262.json').read_text(encoding='utf-8'))['results']
 review100=json.loads((OUT/'review-100.json').read_text(encoding='utf-8'))['results']
 plans={r['question_id']:r for r in review262+review100}
 # Protect real historical uses and the immutable set pinned by a begun learner.
 history_ids=set(db.scalars(select(QuestionAttempt.question_id)))
 for state in db.scalars(select(KpState)):
  if state.graduation_set_version is not None and state.state!='unseen':
   prior=db.get(KpGraduationQuestionSetVersion,(state.kp_id,state.graduation_set_version))
   if prior:history_ids.update(UUID(str(qid)) for qid in prior.question_ids)
 protected_keeps=[]
 for qid,plan in plans.items():
  q=db.get(Question,UUID(qid));fields={'stem':q.stem,'options':q.options,'answer':q.correct_answer,'explanation':q.explanation}
  if fields!=plan['source_fields']:raise RuntimeError('frozen_content_changed:'+qid)
  if plan['decision']=='RETIRE' and q.id in history_ids:
   plan=deepcopy(plan);plan.update(decision='KEEP',depth='FOUNDATION_LEGACY_BOUND',
    training_value_rationale='保留为已有学习实例绑定的必要基础，避免使其适用旧题集失去可完成题；答案与解析已逐题确认，无已知严重错误。')
   plans[qid]=plan;protected_keeps.append(qid)
 expected=json.loads((OUT/'preview.json').read_text(encoding='utf-8')) if apply else None
 if apply and (expected['protected_history']!=protected or expected['graduation_algorithm_fingerprint']!=rules or expected['tables_before']!=tables_before):
  raise RuntimeError('database_changed_after_preview')
 upgrade_runner.OUT=OUT;upgrade_runner.specs=final_specs
 verification=verify();result=upgrade_runner.run(db,apply)
 changed={db.get(Question,UUID(r['id'])).kp_id for r in result['results']}
 retired=[]
 for qid,plan in sorted(plans.items()):
  if plan['decision']!='RETIRE':continue
  q=db.scalar(select(Question).where(Question.id==UUID(qid)).with_for_update());node=q.kp
  event=current_auto_review(q,node);before=question_snapshot_sha256(q)
  if q.id in history_ids or event is None or q.bank_scope!='public':raise RuntimeError('retirement_guard_failed:'+qid)
  if apply and before!=next(r['before_snapshot'] for r in expected['retired'] if r['id']==qid):raise RuntimeError('retirement_snapshot_changed:'+qid)
  old_content={'stem':q.stem,'options':deepcopy(q.options),'answer':q.correct_answer,'explanation':q.explanation}
  revoked=revoke_auto_qualification(db,question_id=q.id,expected_event_id=event.id,expected_snapshot_sha256=before,
    idempotency_key='phase45z-final-retire:'+qid+':'+before)
  q.is_active=False
  config=deepcopy(q.grading_config or {});config.setdefault('quality_retirements',[]).append({
    'version':'phase45z-final-v1','before_snapshot_sha256':before,'revocation_event_id':str(revoked.id),
    'reason':plan['training_value_rationale'],'retained_coverage_question_id':plan['retained_coverage_question_id'],
    'at':datetime.now(timezone.utc).isoformat(),'human_verified':False})
  q.grading_config=config;db.flush()
  if {'stem':q.stem,'options':q.options,'answer':q.correct_answer,'explanation':q.explanation}!=old_content:raise RuntimeError('retirement_changed_original_content')
  if question_eligibility(q,node).practice_eligible:raise RuntimeError('retired_question_still_public_practice')
  retired.append({'id':qid,'node':node.code,'before_snapshot':before,'after_snapshot':question_snapshot_sha256(q),'revocation_event_id':str(revoked.id),'original_content_preserved':True})
  changed.add(q.kp_id)
 publications=[]
 for node_id in sorted(changed,key=str):
  node=db.get(KnowledgePoint,node_id);policy=db.get(KpMasteryPolicy,node_id)
  old=db.get(KpGraduationQuestionSetVersion,(node_id,policy.graduation_set_version))
  ids=[]
  for q in db.scalars(select(Question).where(Question.kp_id==node_id,Question.bank_scope=='public')):
   e=question_eligibility(q,node)
   if e.practice_eligible and e.evidence_capability=='verified_objective' and e.grading_capability=='deterministic':ids.append(q.id)
  if not ids:raise RuntimeError('quality_release_would_empty_node:'+node.code)
  _,publication=publish_all_public_question_set_version(db,kp_id=node_id,question_ids=ids,
   expected_set_version=policy.graduation_set_version,expected_set_sha256=old.question_ids_sha256,
   publication_key='phase45z-final:'+node.code,reason='Final reviewed quality release; retire redundant assessments, preserve learner-pinned historical sets.')
  publications.append({'node':node.code,**publication})
 db.flush()
 after=all_table_fingerprints(db.connection())
 allowed={'questions','question_auto_review_events','kp_mastery_policies','kp_graduation_question_set_versions'}
 if any(after[k]!=v for k,v in tables_before.items() if k not in allowed):raise RuntimeError('non_content_business_table_changed')
 if norm({m.__tablename__:table_fingerprint(db,m) for m in (QuestionAttempt,LearningEvent,KpState)})!=protected or policy_rule_fingerprint(db)!=rules:raise RuntimeError('history_or_graduation_algorithm_changed')
 if tables_before['questions']['count']!=after['questions']['count']:raise RuntimeError('question_added_or_deleted')
 return {**result,'retired':retired,'publications':publications,'protected_keeps':protected_keeps,
   'applied_decisions':plans,'protected_history':protected,'graduation_algorithm_fingerprint':rules,
   'tables_before':tables_before,'tables_after':after,'verification':verification,
   'status':'FINAL_QUALITY_APPLIED' if apply else 'DRY_RUN_ROLLED_BACK'}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
 destination='checkpoint.json' if args.apply else 'preview.json'
 if (OUT/destination).exists():raise SystemExit('existing_output_refuse_repeat')
 if hashlib.sha256(BASE_DUMP.read_bytes()).hexdigest().upper()!=BASE_SHA:raise RuntimeError('baseline_dump_hash_mismatch')
 from scripts import run_phase45i_agent_real as infra
 from sqlalchemy import create_engine
 from sqlalchemy.orm import Session
 _,cluster,port=infra.load_existing_owner()
 if port!=PORT:raise RuntimeError('owned_port_mismatch')
 infra.OUT_DIR=OUT/'runtime';infra.OUT_DIR.mkdir(exist_ok=True)
 started=infra.start_owned_database(cluster,port);engine=create_engine(f'postgresql+psycopg://postgres@127.0.0.1:{PORT}/{DB}')
 try:
  infra.verify_database(cluster,port)
  before_dump=OUT/'before-final.dump'
  if not args.apply:
   if before_dump.exists():raise RuntimeError('before_dump_exists')
   infra.command([str(infra.PG_BIN/'pg_dump.exe'),'-h','127.0.0.1','-p',str(port),'-U','postgres','-d',DB,'-Fc','-f',str(before_dump)],timeout=180)
   toc=infra.command([str(infra.PG_BIN/'pg_restore.exe'),'--list',str(before_dump)],timeout=60)
   save('before-backup.json',{'path':before_dump.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(before_dump.read_bytes()).hexdigest().upper(),'toc_entries':len(toc.stdout.splitlines())})
  else:
   meta=json.loads((OUT/'before-backup.json').read_text(encoding='utf-8'))
   if hashlib.sha256(before_dump.read_bytes()).hexdigest().upper()!=meta['sha256']:raise RuntimeError('before_backup_changed')
  with Session(engine,expire_on_commit=False) as db:
   try:
    result=execute(db,args.apply)
    db.commit() if args.apply else db.rollback()
   except BaseException:db.rollback();raise
  save(destination,result)
  print(json.dumps({'status':result['status'],'upgraded':len(result['results']),'retired':len(result['retired']),
    'protected_keeps':result['protected_keeps'],'new_set_versions':len(result['publications']),
    'question_rows':result['tables_after']['questions']['count']},ensure_ascii=True),flush=True)
 finally:
  engine.dispose()
  if started:
   stop=infra.command([str(infra.PG_BIN/'pg_ctl.exe'),'-D',str(cluster),'-m','fast','-w','-t','60','stop'],timeout=75,check=False,capture=False)
   print('ISOLATED_CLUSTER_STOPPED_NORMALLY' if stop.returncode==0 else 'NORMAL_STOP_FAILED',flush=True)
if __name__=='__main__':main()
