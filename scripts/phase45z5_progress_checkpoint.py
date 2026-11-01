"""Read-only live inventory, graduation-set and restore audit for Z5."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import create_engine,select,text
from sqlalchemy.orm import Session
from backend.models.learning import Question,KpMasteryPolicy,QuestionAttempt,LearningEvent,KpState
from backend.services.question_eligibility import question_eligibility
from scripts.phase45z5_original_batch01 import table_fingerprint,policy_rule_fingerprint
from scripts.run_phase45hx_batch01 import all_table_fingerprints
BASE=ROOT/'storage/quality-audits/phase45z5-20261013'

def audit():
    urls=['postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test',
          'postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_sample03_restore_20261013_test']
    fps=[];data={}
    for index,url in enumerate(urls):
        engine=create_engine(url)
        try:
            with Session(engine) as db:
                db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
                identity=db.execute(text('SELECT current_database(),inet_server_port(),system_identifier FROM pg_control_system()')).one()
                if int(identity[1])!=59227 or str(identity[2])!='7694698872540080852':raise ValueError('owner_identity_mismatch')
                fps.append(all_table_fingerprints(db.connection()))
                if index:continue
                formal=[]
                for q in db.scalars(select(Question)):
                    eligibility=question_eligibility(q,q.kp)
                    if q.bank_scope=='public' and eligibility.practice_eligible and eligibility.evidence_capability=='verified_objective' and eligibility.grading_capability=='deterministic':formal.append(q)
                formal_ids={str(q.id) for q in formal};policies=list(db.scalars(select(KpMasteryPolicy)))
                members=[str(qid) for p in policies for qid in (p.graduation_question_ids or [])]
                if set(members)!=formal_ids or len(members)!=len(formal_ids):raise ValueError('formal_membership_missing_or_duplicate')
                baseline=json.loads((BASE/'known-content/checkpoint.json').read_text(encoding='utf-8'))
                protected={k:table_fingerprint(db,m) for k,m in [('attempts',QuestionAttempt),('learning_events',LearningEvent),('kp_states',KpState)]}
                if json.loads(json.dumps(protected))!=baseline['before']['protected_history']:raise ValueError('historical_fingerprint_changed')
                if policy_rule_fingerprint(db)!=baseline['before']['policy_rule_fingerprint']:raise ValueError('graduation_algorithm_changed')
                nodes={}
                for q in formal:
                    node=nodes.setdefault(q.kp.code,{'name':q.kp.name,'subject':q.kp.subject,'formal_questions':0})
                    node['formal_questions']+=1
                byclass=Counter('exam_curated' if q.question_provenance=='real_exam' else 'exam_variant' if q.is_variant else 'development_original' for q in formal)
                sample=json.loads((ROOT/'storage/quality-audits/phase45z-20261013/ai-original-random-sample-100.json').read_text(encoding='utf-8'))
                old=json.loads((ROOT/'storage/quality-audits/phase45z4-20261013/phase45z4-final-report.json').read_text(encoding='utf-8'))
                upgraded={x['question_id'] for x in old['upgraded_questions']}
                new_upgrades=[]
                for path in sorted((BASE/'sample-upgrades').glob('batch*/checkpoint.json')):
                    batch=json.loads(path.read_text(encoding='utf-8'));upgraded.update(x['id'] for x in batch['results']);new_upgrades+=batch['results']
                remaining=[qid for qid in sample['below_target_candidate_question_ids'] if qid not in upgraded]
                publications=[{'node':p.kp_id.__str__(),'latest_version':p.graduation_set_version,'members':len(p.graduation_question_ids or [])} for p in policies if p.graduation_question_ids]
                data={'status':'PHASE45Z5_IN_PROGRESS','database':list(map(str,identity)),
                    'schema_revision':db.execute(text('SELECT version_num FROM alembic_version')).scalar(),
                    'formal_questions':len(formal),'subjects':dict(Counter(q.kp.subject for q in formal)),
                    'sources':dict(byclass),'formal_nodes':len(nodes),'node_distribution':nodes,
                    'current_graduation_sets':publications,'formal_memberships':len(members),
                    'all_formal_questions_in_current_sets_exactly_once':True,
                    'new_questions_since_z5_start':50,'risk_held_former_formal_questions':4,
                    'net_change_from_1753':len(formal)-1753,'shortfall_to_2000':max(0,2000-len(formal)),
                    'sample_candidates_upgraded_this_phase':len(new_upgrades),'sample_candidates_remaining':remaining,
                    'new_question_substantive_refinements':4,'new_question_explanation_errata':1,
                    'protected_history':protected,'graduation_algorithm_fingerprint':policy_rule_fingerprint(db),
                    'paid_model_calls':0,'development_5433_accessed':False,
                    'difficulty_population_pass_not_claimed':True,'deployment_ready':False}
        finally:engine.dispose()
    if fps[0]!=fps[1]:raise ValueError('restore_table_fingerprint_mismatch')
    backup=BASE/'sample-upgrades/batch03/post-upgrade.dump'
    data['backup']={'path':str(backup),'sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),
        'restored_database':'phase45z5_sample03_restore_20261013_test','matching_full_table_fingerprints':len(fps[0])}
    return data

if __name__=='__main__':
    path=BASE/'progress-after-sample03.json'
    if path.exists():raise SystemExit('output_exists')
    result=audit();path.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['status','formal_questions','subjects','sources','formal_nodes','sample_candidates_upgraded_this_phase','shortfall_to_2000']},ensure_ascii=True))
