"""Snapshot-bound explanation erratum; reuse the existing Z4 revoke/review flow."""
import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from backend.models.learning import Question, QuestionAttempt, LearningEvent, KpState
from backend.services.auto_question_review import (current_auto_review, revoke_auto_qualification,
    question_snapshot_payload, question_snapshot_sha256, attach_codex_independent_review,
    assess_auto_qualification, qualify_public_question)
from backend.services.question_generation import generation_hash
from scripts.phase45z5_original_batch01 import table_fingerprint, policy_rule_fingerprint
from scripts.phase45z5_original_batch05 import candidates

QID = UUID('80efec62-6ffb-5218-b15e-63c32915d90d')
EXPECTED = 'c6ee30d9ec07c3b2bb83407409e714ac0739558e98fa7cfab251877d3aa39491'
BACKUP = ROOT/'storage/quality-audits/phase45z5-20261013/originals/batch05/post-batch05.dump'
BACKUP_SHA = '7EE328865F9264F4D8740CD7513882F185BA4777455082DCE052CE61DE945943'
KEY = 'phase45z5-batch05-ode-explanation-erratum-v1'

def run(db):
    ident = db.execute(text('SELECT current_database(),inet_server_port(),system_identifier FROM pg_control_system()')).one()
    if tuple(map(str, ident)) != ('phase45z5_work_20261013_test','59227','7694698872540080852'):
        raise ValueError('isolated_database_identity_mismatch')
    before = {m.__tablename__:table_fingerprint(db,m) for m in (QuestionAttempt,LearningEvent,KpState)}
    rules = policy_rule_fingerprint(db)
    q = db.scalar(select(Question).where(Question.id==QID).with_for_update())
    spec = next(x for x in candidates() if x['request']=='z5b5-math-nonlinear-autonomous-ode')
    config = deepcopy(q.grading_config)
    if any(x.get('revision_key')==KEY for x in config.get('content_revisions',[])):
        if q.explanation != spec['output'].explanation or current_auto_review(q,q.kp) is None:
            raise ValueError('replay_conflict')
        return {'status':'NOOP','question_id':str(QID)}
    event = current_auto_review(q,q.kp)
    if question_snapshot_sha256(q)!=EXPECTED or event is None or str(event.id)!='3c550f70-cef5-4ef1-8c00-ce0e80df9f32':
        raise ValueError('snapshot_or_event_changed')
    if q.bank_scope!='public' or q.generation_batch_id or q.answer_verification_event_id:
        raise ValueError('wrong_question_scope')
    if db.scalar(select(QuestionAttempt.id).where(QuestionAttempt.question_id==QID).limit(1)):
        raise ValueError('attempt_history_present')
    old = question_snapshot_payload(q)
    revoke_auto_qualification(db,question_id=QID,expected_event_id=event.id,
        expected_snapshot_sha256=EXPECTED,idempotency_key=KEY+':revoke')
    q.explanation = spec['output'].explanation
    config = deepcopy(q.grading_config)
    config.setdefault('content_revisions',[]).append({'revision_key':KEY,
        'before':old,'before_snapshot_sha256':EXPECTED,
        'changes':{'explanation':q.explanation},'reason':'Correct stale evaluation point in the explanation; stem and answer unchanged.',
        'at':datetime.now(timezone.utc).isoformat(),'human_verified':False})
    config.pop('codex_independent_review',None)
    q.grading_config=config
    attach_codex_independent_review(q,q.kp,derived_answer='C',method_evidence=spec['methods'],
        explanation_key_steps=spec['steps'],option_truth_table=spec['truth'])
    config=deepcopy(q.grading_config);config['generation']['verified_content_hash']=generation_hash(q)
    q.grading_config=config;db.flush()
    allq=list(db.scalars(select(Question).where(Question.bank_scope=='public')))
    assessment=assess_auto_qualification(db,q,q.kp,all_questions=allq)
    if assessment['status']!='AUTO_VERIFIED':raise ValueError('requalification_failed')
    snapshot=question_snapshot_sha256(q)
    new_event,result=qualify_public_question(db,question_id=QID,node_id=q.kp_id,
        expected_snapshot_sha256=snapshot,idempotency_key=KEY+':'+snapshot)
    after={m.__tablename__:table_fingerprint(db,m) for m in (QuestionAttempt,LearningEvent,KpState)}
    if before!=after or rules!=policy_rule_fingerprint(db):raise ValueError('protected_history_changed')
    if any(getattr(q,k)!=old[k] for k in ('stem','options','correct_answer')):raise ValueError('unapproved_field_changed')
    return {'status':'CORRECTED_AND_REVIEWED','question_id':str(QID),'before_snapshot':EXPECTED,
        'after_snapshot':question_snapshot_sha256(q),'new_event':str(new_event.id),
        'protected_history':after,'policy_rule_fingerprint':rules,'assessment':result}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper()!=BACKUP_SHA:raise SystemExit('backup_hash_mismatch')
    engine=create_engine('postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test')
    try:
        with Session(engine,expire_on_commit=False) as db:
            result=run(db)
            db.commit() if args.apply else db.rollback()
        path=BACKUP.parent/('explanation-correction-applied.json' if args.apply else 'explanation-correction-preview.json')
        if path.exists():raise SystemExit('report_exists')
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'status':result['status'],'applied':args.apply}))
    finally:engine.dispose()
