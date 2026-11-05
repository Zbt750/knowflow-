"""Conservative supply analysis; no learner evidence or policy mutation."""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json,re
from backend.services.question_eligibility import question_eligibility

VERSION='public-bank-supply-v1'
MAX_SEARCH_STATES=100000


def content_key(q):
    return sha256(json.dumps({'type':q.question_type,'stem':re.sub(r'\s+','',q.stem or '').replace('$',''),
        'options':q.options},ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def source_key(q):
    s=(q.grading_config or {}).get('provenance',{}).get('source',{})
    if q.question_provenance=='real_exam' and s.get('subject') and s.get('year') and s.get('question_number'):
        return str((s['subject'],s['year'],s['question_number']))
    parent=(q.grading_config or {}).get('generation',{}).get('parent_question_id')
    return 'parent:'+str(parent) if parent else None


def supply_for_node(questions,node,policy):
    public=[q for q in questions if (q.bank_scope or 'public')=='public' and not q.generation_batch_id]
    eligible={q.id:question_eligibility(q,node) for q in public}
    practice=[q for q in public if q.is_active and not q.is_hidden and eligible[q.id].practice_eligible]
    strict=[q for q in practice if eligible[q.id].evidence_capability=='verified_objective'
        and q.question_type not in policy.excluded_question_types]
    # Equivalence components dedup both same-content and same-paper question;
    # alternate versions in a component can be chosen but not counted twice.
    groups=[]
    for q in strict:
        from backend.services.question_identity import match_reasons
        matches=[i for i,g in enumerate(groups) if any(match_reasons(p,q) or source_key(q) and source_key(p)==source_key(q) for p in g)]
        if not matches:groups.append([q])
        else:
            combined=[q]
            for i in reversed(matches):combined.extend(groups.pop(i))
            groups.append(combined)
    types=list(policy.required_question_types);tags=sorted(policy.required_skill_tags)
    target=(max(policy.min_confirmations,policy.min_real_questions),
        *[policy.required_question_types[k] for k in types],policy.required_variant_count,(1<<len(tags))-1)
    typecounts=Counter(q.question_type for q in strict);origincounts=Counter(q.question_provenance for q in strict)
    observed_tags={t for q in strict for t in (q.skill_tags or [])}
    reasons=[]
    if len(groups)<target[0]:reasons.append('DISTINCT_TRUSTED_QUESTION_SHORTAGE')
    if target[0]>policy.max_evidence_window:reasons.append('POLICY_EXCEEDS_EVIDENCE_WINDOW')
    for k,n in policy.required_question_types.items():
        if typecounts[k]<n:reasons.append('TYPE_SHORTAGE:'+k)
    for t in tags:
        if t not in observed_tags:reasons.append('SKILL_SHORTAGE:'+t)
    if sum(q.is_variant for q in strict)<policy.required_variant_count:reasons.append('VARIANT_SHORTAGE')
    zero=(0,)*(len(target)-1)+(0,);states={zero:()};solution=None;exhausted=False
    if not reasons:
        for group in groups:
            updated=dict(states)
            for state,path in states.items():
                if len(path)>=policy.max_evidence_window:continue
                for q in group:
                    values=(1,*[int(q.question_type==k) for k in types],int(q.is_variant))
                    new=tuple(min(target[i],state[i]+v) for i,v in enumerate(values))+(state[-1]|sum(1<<i for i,t in enumerate(tags) if t in (q.skill_tags or [])),)
                    candidate=path+(str(q.id),)
                    if new not in updated or len(candidate)<len(updated[new]):updated[new]=candidate
            states=updated
            if target in states:solution=states[target];break
            if len(states)>MAX_SEARCH_STATES:exhausted=True;break
        if solution is None:reasons.append('SEARCH_BOUND_EXCEEDED' if exhausted else 'COMBINED_QUOTAS_OR_SOURCE_DEDUP_CONFLICT')
    return {'version':VERSION,'node_id':str(node.id),'code':node.code,'name':node.name,'subject':node.subject,
        'policy':{**asdict(policy),'required_skill_tags':tags,'excluded_question_types':sorted(policy.excluded_question_types)},
        'public_total':len(public),'active':sum(q.is_active for q in public),'practice_eligible':len(practice),
        'strict_eligible_raw':len(strict),'strict_independent_source_groups':len(groups),
        'type_distribution':dict(typecounts),'origin_distribution':dict(origincounts),'skill_coverage':sorted(observed_tags),
        'blocking_reasons':reasons,'status':'CONDITIONAL_FUTURE_SUBMISSIONS' if solution else 'UNPROVEN' if exhausted else 'INSUFFICIENT',
        'witness_question_ids':list(solution or []),'future_cross_day_requirement':policy.min_day_span,
        'learner_graduated':False,'learner_state_checked':False,'evidence_written':False,
        'qualification_reasons':dict(Counter(r for q in public for r in eligible[q.id].blocking_reasons)),
        'repair_priority':'TRUST_AND_SOURCE_FIRST' if public else 'CONTENT_SUPPLY_FIRST'}
