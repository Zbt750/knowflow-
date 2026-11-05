"""Frozen export audit and isolated public-bank rehearsal. Never dev DB apply."""
import argparse,json,sys,hashlib
from pathlib import Path
from collections import Counter
from uuid import UUID
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy import select,func
from backend.models.learning import KnowledgePoint,Question,KpMasteryPolicy,QuestionAnswerConsistencyRun,QuestionAttempt,LearningEvent
from backend.mastery.storage import policy_from_storage
from backend.services.golden_learning_slice import digest
from backend.services.question_verification_upgrade import snapshot
from backend.services.question_quality import duplicates,audit_question,audit_teaching_question,stage
from backend.services.question_repair import local_pack_registry,identity_counts,diagnose,restore_pack_binding
from backend.services.question_eligibility import question_eligibility
from backend.services.public_bank_supply import supply_for_node,VERSION
from backend.services.public_practice_release import publish_bounded_public,release_hash
from backend.services.question_generation import assess_output,promote
from backend.services.auto_question_review import qualify_public_question,question_snapshot_sha256
from scripts.run_question_repair_pilot import decoded,clone_inventory,isolated_factory
from scripts.audit_question_quality import safe_output,json_input,registry_from_existing,add_q6_correction_observation
from backend.services.quality_sources import NativePageReader,material_descriptor,inspect_source
from scripts.public_bank_originals import originals


def read_frozen(path):
    report=json_input(path/'report.json');raw=json_input(path/'inventory-snapshot.json')
    if report.get('database','').endswith('_test') or digest(raw)!=report.get('inventory_snapshot_sha256'):
        raise ValueError('Need intact captured development export, not a fixture or an altered snapshot')
    if any(q.get('answer_verification_event_id') for q in raw['questions']):
        raise ValueError('Export has verification pointers but no event table; require complete safe export')
    return raw,report


def audit_rows(nodes,qs,policies,runs,*,registry,full_sources=None):
    public=[q for q in qs if (q.bank_scope or 'public')=='public' and not q.generation_batch_id]
    duplicate=duplicates(public);by_node={n.id:n for n in nodes};rows=[]
    for q in public:
        node=by_node.get(q.kp_id)
        relevant=[r for r in runs if r.question_id==q.id]
        original=audit_question(q,node,source_check=(full_sources or {}).get(str(q.id),stage('UNKNOWN','frozen_export_not_full_paper_concordance')),runs=relevant,duplicate=duplicate[str(q.id)])
        quality=audit_teaching_question(q,node,old_audit=original)
        e=question_eligibility(q,node)
        rows.append({'question_id':str(q.id),'kp_id':str(q.kp_id),'node_code':node.code if node else None,
            'content_hash':original['binding']['question_content_sha256'],'snapshot_hash':digest(snapshot(q)),
            'eligibility':e.public_dict(),'quality':quality,'stages':original['stages'],'duplicates':duplicate[str(q.id)],
            'source_pdf_check':(full_sources or {}).get(str(q.id),{'status':'NOT_RUN'})})
    supplies=[supply_for_node([q for q in public if q.kp_id==n.id],n,policy_from_storage(policies.get(n.id))) for n in nodes if n.is_active and n.is_assessable]
    category_counts=Counter()
    for r in rows:
        for key,value in r['stages'].items():
            if value['status'] in {'UNKNOWN','ERROR','FAIL'}:category_counts[f'{key}:{value["status"]}:{value["reason"]}']+=1
    return {'summary':{'public_rows_in_source':len(public),'active':sum(q.is_active for q in public),
        'practice_eligible':sum(r['eligibility']['practice_eligible'] for r in rows),
        'automatic_comparison':sum(bool(r['eligibility']['answer_comparison_method']) for r in rows),
        'answer_present':sum(bool(q.correct_answer and q.correct_answer.strip()) for q in public),
        'explanation_present':sum(bool(q.explanation and q.explanation.strip()) for q in public),
        'independent_answers_pass':sum(r['stages']['independent_answer']['status']=='PASS' for r in rows),
        'explanation_bounded_pass':sum(r['stages']['explanation']['status']=='PASS' for r in rows),
        'strict_eligible':sum(r['eligibility']['practice_eligible'] and r['eligibility']['evidence_capability']=='verified_objective' for r in rows),
        'canonical_origin_counts':dict(Counter(q.question_provenance for q in public)),
        'quality_use_counts':dict(Counter(r['quality']['primary_use'] for r in rows)),
        'quality_fail_reasons':dict(Counter(f"{key}:{v['reason']}" for r in rows for key,v in r['stages'].items() if v['status']=='FAIL')),
        'quality_issue_categories':dict(category_counts),
        'eligibility_blockers':dict(Counter(reason for r in rows for reason in r['eligibility']['blocking_reasons'])),
        'exact_duplicate_rows':sum(bool(r['duplicates']['exact']) for r in rows),'near_duplicate_rows':sum(bool(r['duplicates']['near']) for r in rows),
        'assessable_nodes':len(supplies),'conditional_supply_nodes':sum(s['status']=='CONDITIONAL_FUTURE_SUBMISSIONS' for s in supplies)},
        'questions':rows,'nodes':supplies,'learner_graduation_inferred':False}


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def run(args):
    output=safe_output(args.output_dir);output.mkdir(parents=True,exist_ok=False)
    raw,capture=read_frozen(args.snapshot_dir)
    nodes=[KnowledgePoint(**r) for r in decoded(KnowledgePoint,raw['knowledge_points'])]
    qs=[Question(**{'bank_scope':'public','is_hidden':False,**r}) for r in decoded(Question,raw['questions'])]
    policies={r.kp_id:r for r in [KpMasteryPolicy(**v) for v in decoded(KpMasteryPolicy,raw['kp_mastery_policies'])]}
    runs=[QuestionAnswerConsistencyRun(**r) for r in decoded(QuestionAnswerConsistencyRun,raw['question_answer_consistency_runs'])]
    registry,_=local_pack_registry(ROOT)
    before=audit_rows(nodes,qs,policies,runs,registry=registry)
    with (args.snapshot_dir/'inventory-snapshot.json').open('rb') as stream:source_file_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    evidence={'version':'phase45h-frozen-export-v1','source_snapshot_sha256':digest(raw),'source_file_sha256':source_file_sha,
        'total_question_count_at_capture':capture.get('protection',{}).get('before',{}).get('questions',{}).get('count'),
        'captured_at':capture['checked_at'],'captured_revision':capture['revision'],'source_scope':'captured_active_questions_only',
        'source_database_claim':capture['database'],'original_database_connected':False,'inactive_question_contents_not_exported':True,
        'learning_history_copied':False,'model_calls':0,'source_before_after_equal':True}
    write(output/'source.json',evidence);write(output/'before.json',before);write(output/'node-supply-before.json',before['nodes'])
    if not args.rehearse:
        print(json.dumps({'scope':evidence['source_scope'],'summary':before['summary']},ensure_ascii=False));return
    import os
    from sqlalchemy.engine import make_url
    url=os.environ.get('TEST_DATABASE_URL','');parsed=make_url(url)
    if parsed.host!='127.0.0.1' or not parsed.database.endswith('_test') or str(parsed.port)!=os.environ.get('PHASE45E_OWNED_TEST_PORT') or parsed.port==5433:
        raise ValueError('Rehearsal requires the new owned temporary test cluster, never original database')
    repairs=[];candidates=[];rejected=[];source_checks={}
    with isolated_factory(url) as (factory,schema):
        clone_inventory(factory,raw)
        with factory() as db:
            objects=list(db.scalars(select(Question)));identities=identity_counts(objects);by_node={n.id:n for n in db.scalars(select(KnowledgePoint))}
            dup=duplicates(objects)
            plans=[diagnose(q,by_node[q.kp_id],runs=[r for r in runs if r.question_id==q.id],registry=registry,identities=identities,duplicate=dup[str(q.id)]) for q in objects if before['questions'][[r['question_id'] for r in before['questions']].index(str(q.id))]['stages']['independent_answer']['status']=='PASS']
        reader=NativePageReader();source_registry=registry_from_existing()
        roots=[Path('C:/Users/ZBT/Desktop/数学二与408逐题知识点索引_2000至今/个人复习原卷'),Path('C:/Users/ZBT/Desktop/考研知识点')]
        for plan in plans:
            with factory.begin() as db:
                q=db.get(Question,UUID(plan['question_id']));node=db.get(KnowledgePoint,q.kp_id)
                desc=add_q6_correction_observation(q,material_descriptor(q,source_registry,roots))
                source_checks[str(q.id)]=inspect_source(q,desc,reader)
                if source_checks[str(q.id)]['status']=='FAIL' or source_checks[str(q.id)].get('reason')=='source_material_version_changed':
                    rejected.append({'question_id':str(q.id),'kind':'source_conflict','reason':'source_pdf_conflict_or_version_change'})
                    continue
                if plan.get('pack_link') and plan['pack_link']['usable'] and not question_eligibility(q,node).source_attestation_current:
                    repaired=restore_pack_binding(db,q,node,plan,registry,identities);repairs.append(repaired)
                    if restore_pack_binding(db,q,node,plan,registry,identities)['status']!='NOOP':raise ValueError('Source restore not idempotent')
                try:
                    h=release_hash(q);preview=publish_bounded_public(db,q,node,expected_hash=h)
                    result=publish_bounded_public(db,q,node,expected_hash=h,apply=True)
                    if publish_bounded_public(db,q,node,expected_hash=h,apply=True)['status']!='NOOP':raise ValueError('Publication replay failed')
                    repairs.append({'question_id':str(q.id),'publication':result,'preview':preview})
                except ValueError as exc:
                    quality=audit_teaching_question(q,node)
                    rejected.append({'question_id':str(q.id),'kind':'existing_publication','reason':str(exc),
                        'quality_blockers':quality['blocking_reasons'],'objective_grading_eligible':quality['objective_grading_eligible']})
        with factory.begin() as db:
            available_nodes=list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True),KnowledgePoint.is_assessable.is_(True))))
            for family,keyword,out in originals():
                matches=[n for n in available_nodes if keyword in n.name and '.family.' not in n.code]
                if not matches:rejected.append({'family':family,'reason':'node_not_found'});continue
                matches.sort(key=lambda n:(n.name!=keyword,len(n.name),n.code));node=matches[0]
                cid='h-public-original-v1:'+node.code+':'+family
                candidate=assess_output(out,node,request_id=cid,mode='original',family=family,
                    trace={'model':'codex_offline_authoring','prompt_version':'h-original-v1','mode':'codex_offline','model_calls':0})
                if candidate['status']!='AUTO_PASS':rejected.append({'family':family,'reason':candidate['status'],'errors':candidate['errors']});continue
                duplicate=duplicates([candidate['question'],*list(db.scalars(select(Question)))])[str(candidate['question'].id)]
                if duplicate['exact'] or duplicate['near']:rejected.append({'family':family,'reason':'duplicate_or_near','duplicates':duplicate});continue
                old=db.get(Question,candidate['question'].id)
                if old and (old.bank_scope!='public' or old.generation_batch_id):raise ValueError('Public candidate identity overlaps personal bank')
                q,_=promote(db,candidate,node);q.bank_scope='public';db.flush()
                auto_event,auto_result=qualify_public_question(db,question_id=q.id,node_id=node.id,
                    expected_snapshot_sha256=question_snapshot_sha256(q),
                    idempotency_key=f'phase45h-auto:{q.id}',
                    now=__import__('datetime').datetime(2026,10,9,tzinfo=__import__('datetime').timezone.utc))
                if auto_event is None:
                    release=publish_bounded_public(db,q,node,expected_hash=release_hash(q),apply=True)
                    candidates.append({'question_id':str(q.id),'node_code':node.code,'family':family,
                        'status':'ORDINARY_ONLY','auto_review':auto_result,'release':release,'question':snapshot(q)})
                else:
                    if qualify_public_question(db,question_id=q.id,node_id=node.id,
                        expected_snapshot_sha256=auto_result.get('prequalification_snapshot_sha256',question_snapshot_sha256(q)),
                        idempotency_key=f'phase45h-auto:{q.id}')[0].id != auto_event.id:
                        raise ValueError('Automatic question review replay was not idempotent')
                    candidates.append({'question_id':str(q.id),'node_code':node.code,'family':family,
                        'status':'AUTO_VERIFIED','qualification_class':auto_event.qualification_class,
                        'auto_review':auto_result,'question':snapshot(q)})
        with factory() as db:
            after=audit_rows(list(db.scalars(select(KnowledgePoint))),list(db.scalars(select(Question))),
                {p.kp_id:p for p in db.scalars(select(KpMasteryPolicy))},list(db.scalars(select(QuestionAnswerConsistencyRun))),registry=registry,full_sources=source_checks)
            protection={'policy_rows':len(policies),'policy_equal':all({c.name:getattr(p,c.name) for c in KpMasteryPolicy.__table__.columns}=={c.name:getattr(policies[p.kp_id],c.name) for c in KpMasteryPolicy.__table__.columns} for p in db.scalars(select(KpMasteryPolicy))),
                'attempt_count':db.scalar(select(func.count()).select_from(QuestionAttempt)),'learning_event_count':db.scalar(select(func.count()).select_from(LearningEvent)),
                'actual_graduation_claimed':False,'human_verifications_created':False}
            if not protection['policy_equal'] or protection['attempt_count'] or protection['learning_event_count']:raise ValueError('Snapshot rehearsal protection failed')
        write(output/'after.json',after);write(output/'node-supply-after.json',after['nodes']);write(output/'repairs.json',repairs)
        write(output/'new-candidates-private.json',candidates);write(output/'rejected.json',rejected);write(output/'protection.json',protection)
        from scripts.run_question_repair_pilot import business_check
        ids=[r['question_id'] for r in candidates]+[r['question_id'] for r in repairs if r.get('publication')]
        business=business_check(factory,ids,None)
        write(output/'business.json',{'ordinary_practice':business,'scope':'real frozen export and H originals in isolated schema; no real model'})
        write(output/'golden-slice.json',[n for n in after['nodes'] if n['node_id'] in {str(by_node[UUID(p['kp_id'])].id) for p in plans} or n['code'] in {c['node_code'] for c in candidates}])
    if digest(json_input(args.snapshot_dir/'inventory-snapshot.json'))!=evidence['source_snapshot_sha256']:raise ValueError('Frozen source was changed')
    result={'before':before['summary'],'after':after['summary'],'new_public_questions':len(candidates),'repair_operations':len(repairs),
        'rejected':dict(Counter(r['reason'] for r in rejected)),'original_database_written':False,'snapshot_sha256':evidence['source_snapshot_sha256']}
    write(output/'summary.json',result)
    (output/'summary.md').write_text('# 公共题库冻结导出隔离重审\n\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n\n不是原库实时库存或实际毕业结果；逐节点见node-supply-after.json。\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--snapshot-dir',type=Path,default=ROOT/'storage/quality-audits/phase45d-20261009/diagnosis')
    p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--rehearse',action='store_true');run(p.parse_args())
