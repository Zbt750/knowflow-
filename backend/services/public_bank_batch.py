"""Versioned, resumable historical bank repairs in an explicit isolated DB."""
import json,re,random
from copy import deepcopy
from pathlib import Path
from uuid import UUID
from hashlib import sha256
from sqlalchemy import select,text
from backend.models.learning import Question,KnowledgePoint,KpMasteryPolicy
from backend.services.auto_question_review import (question_snapshot_payload,question_snapshot_sha256,current_auto_review,
    prepare_exam_curated_repair,qualify_public_question,assess_auto_qualification,render_curated_explanation,AUTO_REVIEW_VERSION)
from backend.services.answer_verification import answer_version_sha256
from backend.services.quality_verifiers import verify_problem,VERSION as VERIFIER_VERSION
from backend.services.question_eligibility import question_eligibility
from backend.services.question_production_pipeline import validate_question_content
from backend.services.golden_learning_slice import digest


def save(path,data):
    temporary=path.with_suffix(path.suffix+'.new')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    temporary.replace(path)


def normalized_options(options):
    return {k:re.sub(r'\n-\s*$','',v).strip() for k,v in options.items()} if isinstance(options,dict) else options


def resolve_approved_q6(db,baseline,out):
    """Reconstruct one already authorized correction; never merge trust fields."""
    from backend.services.question_pack import QuestionPack,fingerprint
    from backend.services.question_answer_revision import revise_transcription_content
    from backend.services.question_verification_upgrade import snapshot
    from scripts.run_question_repair_pilot import local_pack_registry
    from scripts.audit_phase45h_completion_archive import source_pack_evidence
    root=Path(__file__).resolve().parents[2]
    conflict=next((r for r in baseline['conflicts'] if r['question_id']=='d1691564-0c42-43c0-8ab2-b011fd88ac65'),None)
    if conflict is None:return {'status':'NO_CONFLICT'}
    q=db.get(Question,UUID(conflict['question_id']));latest=conflict['latest']
    probe=Question(kp_id=q.kp_id,stem=latest['stem'],options=latest['options'],question_type=latest['question_type'],correct_answer=latest['correct_answer'])
    expected='5fb758a3588eef8774cef2eb0334da00129826d59dbec2d3ca5b7823b44fb88e'
    if answer_version_sha256(probe)!=expected:raise ValueError('Approved Q6 version does not match latest snapshot; no merge')
    already_corrected=(normalized_options(q.options)==normalized_options(latest['options']) and
        q.stem==latest['stem'] and q.correct_answer==latest['correct_answer'])
    if not already_corrected and (q.correct_answer!='A' or {k:v for k,v in q.options.items() if k!='C'}!={k:v for k,v in latest['options'].items() if k!='C'}):
        raise ValueError('Q6 conflict includes other content; do not reconcile')
    registry,_=local_pack_registry(root);original_provenance=conflict['backup']['grading_config']['provenance'];key=original_provenance['key'];fp=original_provenance['sha256']
    entry=next(item for item in registry[key] if item['fingerprint']==fp)
    original=json.loads(Path(entry['path']).read_text(encoding='utf-8'))
    pack=QuestionPack.model_validate(original);item=entry['question'].model_copy(update={'options':latest['options']},deep=True)
    version='hs-q6-approved-replay-20261010';derived=pack.model_copy(update={'version':version,'questions':[item]},deep=True)
    folder=root/'storage/question-intake/phase45hs-20261010-q6-replay';folder.mkdir(parents=True,exist_ok=True)
    path=folder/'question-pack-compatible-v2.json';body=json.dumps(derived.model_dump(mode='json',exclude_unset=True),ensure_ascii=False,indent=2)
    if fingerprint(QuestionPack.model_validate(json.loads(body)).questions[0])!=fingerprint(item):
        raise ValueError('Source pack serialization changed fingerprint')
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=json.loads(body):raise ValueError('Derived source artifact conflict')
    if not path.exists():path.write_text(body,encoding='utf-8')
    if already_corrected:return {'status':'ALREADY_CORRECTED','approved_answer_sha256':expected}
    before=deepcopy(question_snapshot_payload(q))
    result=revise_transcription_content(db,q.id,digest(snapshot(q)),{'options':latest['options']},
        basis='Replay the user-approved C-option minus-sign correction into the isolated pre-correction backup. Approved answer SHA '+expected,
        proposed_source_pack_sha256=fingerprint(item),proposed_pack_version=version,apply=True)
    if answer_version_sha256(q)!=expected:raise ValueError('Approved replay did not produce the expected answer hash')
    return {'status':'REPLAYED_APPROVED_CORRECTION_IN_ISOLATION','before':before,'latest_retained':latest,
        'after':question_snapshot_payload(q),'approved_answer_sha256':expected,'result':result,
        'derived_source_archive_sha256':sha256(path.read_bytes()).hexdigest(),'trust_fields_not_copied':True}


def choose_pilot(rows):
    active=[r for r in rows if r['active']];groups={}
    for row in active:groups.setdefault(('408' if row['subject']=='408' else 'math2',row['payload']['question_type']),[]).append(row)
    rng=random.Random(4545)
    for pool in groups.values():rng.shuffle(pool)
    selected=[]
    for subject in ('math2','408'):
        pools=[pool for (s,_),pool in sorted(groups.items()) if s==subject]
        i=0
        while sum(('408' if r['subject']=='408' else 'math2')==subject for r in selected)<25:
            pool=pools[i%len(pools)];i+=1
            if pool:selected.append(pool.pop())
    # Include observed missing-asset/format/ambiguous-condition cases, replacing
    # a same-subject item. Selection is not driven by solver PASS eligibility.
    defects=[r for r in active if r['structure']['completeness']!='complete' or not r['payload']['correct_answer']
        or not r['payload']['explanation'] or any(tag in r['payload']['stem'] for tag in ('CRC','译码串'))]
    for row in defects:
        if row['question_id'] not in {r['question_id'] for r in selected}:
            replace=next(i for i,r in enumerate(selected) if r['subject']==row['subject'] and r not in defects)
            selected[replace]=row
    assert len(selected)==50 and len({r['question_id'] for r in selected})==50
    return [r['question_id'] for r in selected]


def repair_one(db,q,node,registry,*,expected_hash):
    from scripts.audit_phase45h_completion_archive import source_pack_evidence
    from backend.services.question_identity import PUBLIC_BANK_LOCK
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':PUBLIC_BANK_LOCK})
    if db.bind.url.port==5433 or not db.bind.url.database.endswith('_test'):raise ValueError('Isolated database required')
    q=db.scalar(select(Question).where(Question.id==q.id).with_for_update().execution_options(populate_existing=True))
    if question_snapshot_sha256(q)!=expected_hash:raise ValueError('Live snapshot changed')
    before=deepcopy(question_snapshot_payload(q));evidence=source_pack_evidence(q,registry,node)
    result={'question_id':str(q.id),'node_code':node.code,'subject':node.subject,'before':before,'before_sha256':expected_hash,
        'source_evidence':evidence,'active':q.is_active,'changed_fields':[],'formal_eligible':False}
    if not q.is_active:
        result.update(classification='INSUFFICIENT_EVIDENCE',reason='inactive_source_identity_not_recovered');return result
    if (q.bank_scope or 'public')!='public' or q.generation_batch_id:
        result.update(classification='REJECTED',reason='personal_bank_excluded');return result
    if current_auto_review(q,node):
        result.update(classification='AUTO_VERIFIED_FORMAL_ELIGIBLE',reason='current_qualification_noop',formal_eligible=True,
            after=before,after_sha256=expected_hash,operation='NOOP');return result
    # Inspect normalized choices in memory first; unsupported rows are retained
    # verbatim rather than invalidating an old practice record merely for style.
    original_options=q.options;q.options=normalized_options(q.options);independent=verify_problem(q);result['independent']=independent
    if independent.get('status')!='PASS':
        q.options=original_options
        reason=independent.get('reason','independent_solver_unsupported')
        e=question_eligibility(q,node)
        result.update(classification='NEEDS_EXCEPTION_REVIEW' if reason in {'crc_zero_does_not_prove_no_transmission_error','incomplete_bitstream'} else
            'PRACTICE_ONLY' if e.practice_eligible else 'INSUFFICIENT_EVIDENCE',reason=reason,
            practice_eligible=e.practice_eligible,paper_reference_available=bool(q.stem and q.correct_answer),
            grading_capability=e.grading_capability)
        return result
    if not evidence:
        q.options=original_options;result.update(classification='NEEDS_EXCEPTION_REVIEW',reason='source_or_exact_mapping_unresolved');return result
    from backend.services.phase45hs_verifiers import SOLVERS
    hints={'hs_stack_operations':['栈'],'hs_stack_arithmetic':['栈'],'hs_ipv4_fragment':['IPv4'],
        'hs_cache_tag':['Cache'],'hs_huffman_wpl':['哈夫曼'],'hs_huffman_decode':['哈夫曼'],'hs_huffman_nodes':['哈夫曼'],
        'hs_ieee_decode':['IEEE754'],'hs_ieee_encode':['IEEE754'],'hs_ieee_min_normal':['IEEE754'],
        'hs_limit_parameters':['极限'],'hs_span_intersection':['线性表示'],'hs_rank_square_zero':['秩'],
        'hs_list_insertion':['双链表'],'hs_log_integral_min':['反常积分'],
        'hs_doubly_list_two_step_pointer_v1':['双链表'],
        'hs_rail_tracks_minimum_fifo_v1':['队列'],
        'hx_infinitesimal_orders_v1':['无穷小'], 'hx_piecewise_primitive_v1':['不定积分'],
        'hx_inverse_exponential_improper_v1':['反常积分'],
        'hx_crc_received_zero_remainder_v1':['差错控制','CRC']}
    if independent.get('adapter') in SOLVERS and not any(s in node.name for s in hints.get(independent['adapter'], [])):
        q.options=original_options;result.update(classification='NEEDS_EXCEPTION_REVIEW',reason='solver_domain_node_mapping_conflict');return result
    if render_curated_explanation(q,independent) is None:
        q.options=original_options;result.update(classification='PRACTICE_ONLY',reason='verified_answer_no_checked_explanation_renderer');return result
    config=deepcopy(q.grading_config or {})
    config.setdefault('content_revisions',[]).append({'version':'phase45hs-isolated-repair-v1','before':before,
        'independent_verification':independent,'human_verified':False})
    q.grading_config=config
    if q.options!=original_options:
        q.source_attestation_key=None;q.source_attestation_sha256=None
        q.answer_attestation_key=None;q.answer_attestation_sha256=None
    # Only the current exact version receives a fresh automatic qualification;
    # historical verification events and learner receipts are never rewritten.
    evidence=source_pack_evidence(q,registry,node)
    prepare_exam_curated_repair(q,node,evidence)
    db.flush();evidence=source_pack_evidence(q,registry,node)
    current_hash=question_snapshot_sha256(q)
    event,assessment=qualify_public_question(db,question_id=q.id,node_id=node.id,expected_snapshot_sha256=current_hash,
        idempotency_key='phase45hs:'+str(q.id)+':'+current_hash,source_evidence=evidence)
    after=question_snapshot_payload(q);changed=[k for k in before if before[k]!=after[k]]
    e=question_eligibility(q,node)
    result.update(classification='REPAIRED_AND_VERIFIED' if event else 'PRACTICE_ONLY' if e.practice_eligible else 'INSUFFICIENT_EVIDENCE',
        reason=assessment.get('reason') or assessment['status'],assessment=assessment,
        changed_fields=changed,after=after,after_sha256=question_snapshot_sha256(q),
        formal_eligible=e.practice_eligible and e.evidence_capability=='verified_objective',practice_eligible=e.practice_eligible,
        grading_capability=e.grading_capability,event_id=str(event.id) if event else None,mapping_checked=True)
    if event:
        fresh=assess_auto_qualification(db,q,node,source_evidence=source_pack_evidence(q,registry,node),
            all_questions=list(db.scalars(select(Question))))
        if fresh['status']!='AUTO_VERIFIED' or not current_auto_review(q,node):raise ValueError('Post-qualification recheck failed')
    return result


def run_batch_repair(factory,out):
    from scripts.run_question_repair_pilot import local_pack_registry
    from backend.services.public_bank_supply import supply_for_node
    from backend.mastery.storage import policy_from_storage
    root=Path(__file__).resolve().parents[2];baseline=json.loads((out/'baseline.json').read_text(encoding='utf-8'))
    with factory.begin() as db:resolution=resolve_approved_q6(db,baseline,out)
    if resolution['status']=='ALREADY_CORRECTED' and (out/'conflict-resolution.json').exists():
        resolution=json.loads((out/'conflict-resolution.json').read_text(encoding='utf-8'))
    else:save(out/'conflict-resolution.json',resolution)
    registry,_=local_pack_registry(root);pilot=choose_pilot(baseline['rows']);save(out/'pilot-selection.json',{'ids':pilot,'selection':'balanced_subject_type_fixed_seed_plus_observed_defects'})
    rows=[];progress_path=out/'progress.json'
    progress=json.loads(progress_path.read_text(encoding='utf-8')) if progress_path.exists() else {'version':1,'rows':[],'completed_ids':[]}
    prior={r['question_id']:r for r in progress['rows']}
    # Retry only the documented serialization/source-binding failure, keeping
    # its prior diagnosis as an append-only run artifact, not erasing failures.
    q6='d1691564-0c42-43c0-8ab2-b011fd88ac65'
    if q6 in prior and prior[q6]['reason']=='source_or_exact_mapping_unresolved':
        old=prior.pop(q6);save(out/'q6-source-binding-before-fix.json',old)
        progress['rows']=[r for r in progress['rows'] if r['question_id']!=q6]
        progress['completed_ids']=[qid for qid in progress['completed_ids'] if qid!=q6]
    active=[r['question_id'] for r in baseline['rows'] if r['active']];inactive=[r['question_id'] for r in baseline['rows'] if not r['active']]
    batches=[pilot,*[active[i:i+50] for i in range(0,len(active),50)],inactive];seen=set()
    for batch_number,ids in enumerate(batches):
        batch=[]
        for qid in ids:
            if qid in seen:continue
            seen.add(qid)
            if qid in prior:
                row=prior[qid]
                with factory() as db:
                    q=db.get(Question,UUID(qid))
                    if row.get('after_sha256') and question_snapshot_sha256(q)!=row['after_sha256']:raise ValueError('Checkpoint snapshot drift')
                rows.append(row);batch.append(row);continue
            with factory.begin() as db:
                q=db.get(Question,UUID(qid));node=db.get(KnowledgePoint,q.kp_id)
                row=repair_one(db,q,node,registry,expected_hash=question_snapshot_sha256(q))
            rows.append(row);batch.append(row);progress['rows'].append(row);progress['completed_ids'].append(qid)
            save(progress_path,progress)
        save(out/f'batch-{batch_number:02}.json',{'count':len(batch),'rows':batch})
        from scripts.audit_phase45h_completion_archive import fingerprints
        if fingerprints(str(factory.kw['bind'].url))!=json.loads((out/'history-before.json').read_text(encoding='utf-8')):
            raise ValueError('Batch history safety gate failed; stop expansion')
        with factory() as db:
            from sqlalchemy import func
            if db.scalar(select(func.count()).select_from(Question))!=baseline['total']:
                raise ValueError('Question conservation gate failed; stop expansion')
        print(f'batch {batch_number}: processed {len(batch)}; formal {sum(r["formal_eligible"] for r in batch)}',flush=True)
    with factory() as db:
        nodes=list(db.scalars(select(KnowledgePoint)));qs=list(db.scalars(select(Question)));policies={p.kp_id:p for p in db.scalars(select(KpMasteryPolicy))}
        coverage=[supply_for_node([q for q in qs if q.kp_id==n.id],n,policy_from_storage(policies[n.id])) for n in nodes if n.id in policies]
        from backend.models.learning import QuestionAutoReviewEvent
        dump={'questions':[{c.name:getattr(q,c.name) for c in Question.__table__.columns} for q in qs],
            'auto_review_events':[{c.name:getattr(e,c.name) for c in QuestionAutoReviewEvent.__table__.columns} for e in db.scalars(select(QuestionAutoReviewEvent))],
            'knowledge_points':[{c.name:getattr(n,c.name) for c in KnowledgePoint.__table__.columns} for n in nodes],
            'policies':[{c.name:getattr(p,c.name) for c in KpMasteryPolicy.__table__.columns} for p in policies.values()]}
        save(out/'formal-bank-export.json',dump)
    save(out/'coverage.json',coverage)
    result={'version':AUTO_REVIEW_VERSION,'verifier':VERIFIER_VERSION,'processed':len(rows),'pilot_count':50,'pilot_results':[prior for prior in rows if prior['question_id'] in pilot],
        'active_processed':len(active),'inactive_processed':len(inactive),'rows':rows,'formal_total':sum(r['formal_eligible'] for r in rows),
        'repair_counts':{field:sum(field in r['changed_fields'] for r in rows) for field in ('stem','options','correct_answer','explanation','kp_id')},
        'source_conflict_resolution':resolution['status'],'paid_calls':0,'development_5433_touched':False}
    save(out/'report.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in {'rows','pilot_results'}},ensure_ascii=False),flush=True)
