"""Snapshot-bound ordinary-practice publication, never graduation certification."""
from copy import deepcopy
from backend.services.golden_learning_slice import digest
from backend.services.question_verification_upgrade import snapshot
from backend.services.quality_verifiers import verify_problem,VERSION as VERIFIER_VERSION

VERSION='public-practice-release-h1'


def release_hash(q):
    s=snapshot(q)
    s['grading_config']=deepcopy(s['grading_config'] or {})
    s['grading_config'].pop('public_practice_release',None)
    return digest({'question':s,'bank_scope':q.bank_scope or 'public','batch':str(q.generation_batch_id) if q.generation_batch_id else None})


def release_is_current(q,node):
    record=(q.grading_config or {}).get('public_practice_release',{})
    return bool(q.bank_scope=='public' and not q.generation_batch_id and q.is_active and not q.is_hidden
        and node and node.is_active and node.is_assessable and record.get('version')==VERSION
        and record.get('verifier_version')==VERIFIER_VERSION and record.get('question_hash')==release_hash(q)
        and verify_problem(q).get('status')=='PASS')


def publish_bounded_public(db,q,node,*,expected_hash,apply=False):
    """Only an isolated rehearsal. Production deployment needs separate approval."""
    from sqlalchemy import text,select
    from backend.models.learning import Question
    import re
    schema=db.scalar(text('SELECT current_schema()'));database=db.scalar(text('SELECT current_database()'))
    marker=db.scalar(text("SELECT obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=:s"),{'s':schema})
    if not database.endswith('_test') or not re.fullmatch(r'question_repair_[0-9a-f]{16}',schema or '') or marker!='kaoyan-question-repair:v1' or db.scalar(text('SHOW search_path'))!=schema:
        raise ValueError('Public rehearsal requires owned isolated schema without public fallback')
    db.flush()
    q=db.scalar(select(Question).where(Question.id==q.id).with_for_update().execution_options(populate_existing=True))
    if not q or q.bank_scope!='public' or q.generation_batch_id:raise ValueError('Personal questions are never public repair subjects')
    if release_is_current(q,node) and release_hash(q)==expected_hash:return {'status':'NOOP','question_id':str(q.id)}
    if release_hash(q)!=expected_hash:raise ValueError('Publication snapshot drift')
    if q.answer_verification_event_id or q.content_trust=='verified':raise ValueError('Keep formal verified content outside this bounded publication path')
    from backend.services.question_quality import audit_teaching_question
    quality=audit_teaching_question(q,node)
    if not quality['objective_grading_eligible'] or verify_problem(q)['status']!='PASS':raise ValueError('Independent quality or comparator unsupported')
    result={'status':'PREVIEW','question_id':str(q.id),'question_hash':expected_hash,'teaching_use':quality['primary_use'],
        'strict_qualification_granted':False,'changed_fields':['grading_config.public_practice_release']}
    if apply:
        q.grading_config={**deepcopy(q.grading_config or {}),'public_practice_release':{'version':VERSION,'verifier_version':VERIFIER_VERSION,
            'question_hash':expected_hash,'independent_result':verify_problem(q),'human_verified':False}}
        db.flush();result['status']='APPLIED_IN_ISOLATION'
    return result
