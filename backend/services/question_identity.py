"""Conservative, independently explainable question identity within one bank."""
import re,json
from functools import lru_cache
from hashlib import sha256

PUBLIC_BANK_LOCK=4520261021


def digest(value):return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def normalized_text(value):
    return re.sub(r'\s+','',str(value or '')).replace('$','').replace('`','').replace('−','-')


def historical_identity(q):
    source=(q.grading_config or {}).get('provenance',{}).get('source',{})
    from backend.services.question_attestation import _subject
    canonical = _subject(source.get('subject'))
    subject={'数学二':'math2','考研数学':'math2','math2':'math2','408':'408','cs408':'408'}.get(canonical)
    if source.get('source_type')=='exam' and subject and source.get('year') and source.get('question_number') and not q.is_variant:
        return (subject,source['year'],source['question_number'])
    return None


def text_identity(q):
    options=sorted(normalized_text(value) for value in (q.options or {}).values()) if isinstance(q.options,dict) else None
    return digest({'stem':normalized_text(q.stem),'options':options,'type':q.question_type})


@lru_cache(maxsize=4096)
def _verified_identity(stem,kind,answer,options):
    from types import SimpleNamespace
    from backend.services.quality_verifiers import verify_problem
    q=SimpleNamespace(stem=stem,question_type=kind,correct_answer=answer,options=json.loads(options))
    result=verify_problem(q)
    if not result or result.get('status')!='PASS':return None
    if result.get('problem_identity') is not None:return digest(result['problem_identity'])
    # In option-classification problems the options themselves are premises.
    # Do not infer semantic identity from a proof that omits their exact values.
    if result.get('adapter')=='binary_rational_v1':return None
    return digest({'adapter':result.get('adapter'),'proof':result.get('proof')})


def verified_identity(q):
    return _verified_identity(q.stem,q.question_type,getattr(q,'correct_answer',None),json.dumps(q.options,sort_keys=True,ensure_ascii=False)) if getattr(q,'correct_answer',None) else None


def match_reasons(left,right):
    reasons=[]
    if historical_identity(left) and historical_identity(left)==historical_identity(right):reasons.append('same_exam_identity')
    if text_identity(left)==text_identity(right):reasons.append('same_normalized_content')
    key=verified_identity(left)
    if key is not None and key==verified_identity(right):reasons.append('same_verified_problem')
    return reasons


def duplicate_findings(question,others):
    matches=[];similar=[];key=verified_identity(question)
    from difflib import SequenceMatcher
    for other in others:
        if question.id is not None and other.id==question.id or (other.bank_scope or 'public')!=(question.bank_scope or 'public'):continue
        reasons=match_reasons(question,other)
        if reasons:matches.append({'question_id':str(other.id),'reasons':reasons});continue
        if other.kp_id!=question.kp_id:continue
        other_key=verified_identity(other)
        if key is not None and other_key is not None and key!=other_key:continue  # independently different parameters/goal
        if SequenceMatcher(None,normalized_text(question.stem),normalized_text(other.stem),autojunk=False).ratio()>=.96:
            similar.append(str(other.id))
    return {'matches':matches,'uncertain_similar':similar,'semantic_dedup_executed':True}
