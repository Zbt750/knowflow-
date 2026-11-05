"""Post-graduation practice observations. Read-only; never changes graduation."""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, case, Integer
from backend.models.learning import Question, QuestionAttempt, KpState, KpMasteryPolicy, KnowledgePoint
from backend.mastery.enums import MasteryState
from backend.mastery.storage import policy_for_node
from backend.services.policy_evidence_service import current_policy_snapshot
from backend.services.answer_submission_service import question_content_hash_matches
from backend.services.answer_verification import answer_version_sha256
from backend.services.question_eligibility import question_eligibility
from backend.schemas.capability import PostGraduationPractice


@dataclass(frozen=True)
class ReviewRules:
    window_days: int = 30
    stale_days: int = 30
    max_attempts: int = 100
    risk_distinct_questions: int = 2
    recovery_distinct_questions: int = 3
    recovery_day_span: int = 1
    coverage_count: int = 2


RULES = ReviewRules()
VERSION = "post-graduation-practice-v1"
INDEPENDENT = {"first_independent_correct", "independent_retest_correct", "repeat_correct", "incorrect"}


def feedback_bound(a, q, node):
    """No new quality stamp is inferred for old, assisted or changed receipts."""
    s = a.grading_evidence if isinstance(a.grading_evidence,dict) else {}
    if s.get('version') in {5, 6}:
        from backend.services.capability_service import _auto_verified_progress_receipt
        return _auto_verified_progress_receipt(a, q, node, question_eligibility(q, node) if q else None)
    base = bool(q and q.is_active and a.self_grade is None and a.exam_reference_id is None and s.get('version') == 4
        and s.get('attempt_id') == str(a.id) and s.get('result') == a.objective_result
        and s.get('question_type') == q.question_type and s.get('skill_tags') == list(q.skill_tags or [])
        and question_content_hash_matches(s.get('question_content_sha256'), q)
        and s.get('answer_version_sha256') == answer_version_sha256(q))
    if not base: return False
    trust = question_eligibility(q, node)
    if s.get('evidence_reliability')=='public_practice_observation':
        from backend.services.public_practice_release import release_is_current
        return bool(s.get('bank_scope')=='public' and not s.get('generation_batch_id') and release_is_current(q,node)
            and s.get('method') in {'ai_answer_single_choice_v1','ai_answer_exact_numeric_v1','ai_answer_exact_logarithm_v1','ai_answer_constant_v1','reference_single_choice_v1','reference_exact_numeric_v1','reference_constant_v1'})
    if s.get('bank_scope') == 'personal':
        from backend.services.question_generation import current_generation_binding
        return bool(q.bank_scope == 'personal' and q.generation_batch_id and
            s.get('generation_batch_id') == str(q.generation_batch_id) and
            s.get('evidence_reliability') == 'personal_practice_observation' and
            s.get('method') in {'ai_answer_single_choice_v1','ai_answer_exact_numeric_v1','ai_answer_exact_logarithm_v1','ai_answer_constant_v1','ai_answer_range_v1'}
            and current_generation_binding(q,node))
    return bool(trust.practice_eligible and trust.evidence_capability == 'verified_objective'
        and s.get('evidence_reliability') == 'verified_objective' and s.get('answer_reliability') == 'verified'
        and s.get('answer_verification_event_id') == trust.answer_verification_event_id
        and s.get('method') in {'single_choice_v1','exact_numeric_v1','exact_logarithm_v1','exact_constant_v1'})


def project_post_practice(rows, *, now, graduated_at, truncated=False):
    """Rows are immutable observed receipts enriched by current version validation."""
    eligible = [r for r in rows if graduated_at < r['time'] <= now]
    recent = [r for r in eligible if r['time'] >= now-timedelta(days=RULES.window_days)]
    reliable = [r for r in recent if r['reliable'] and r['result'] in {'right','wrong'}]
    independent = [r for r in reliable if r['independent']]
    by_content = {}
    for r in independent: by_content[r['identity']] = r
    distinct = sorted(by_content.values(),key=lambda r:(r['time'],r['number']))
    latest = distinct[-max(RULES.recovery_distinct_questions,RULES.risk_distinct_questions):]
    wrong = [r for r in latest if r['result']=='wrong']
    assisted = [r for r in reliable if not r['independent'] and r['result']=='right']
    all_reliable = [r for r in eligible if r['reliable'] and r['result'] in {'right','wrong'}]
    last = max((r['time'] for r in all_reliable),default=None)
    stale = now-(last or graduated_at) >= timedelta(days=RULES.stale_days)
    covered_types={r['type'] for r in latest};covered_tags={t for r in latest for t in r['tags']}
    good = (len(latest)>=RULES.recovery_distinct_questions and all(r['result']=='right' for r in latest)
        and (max(r['time'] for r in latest).astimezone(ZoneInfo('Asia/Shanghai')).date()-min(r['time'] for r in latest).astimezone(ZoneInfo('Asia/Shanghai')).date()).days>=RULES.recovery_day_span
        and (len(covered_types)>=RULES.coverage_count or len(covered_tags)>=RULES.coverage_count)
        and not any(r['time']>=latest[0]['time'] for r in assisted) and not truncated)
    if len(wrong)>=RULES.risk_distinct_questions:
        status,label,reason,action='CONSOLIDATE','建议巩固',f'近期不同题目的独立练习中有{len(wrong)}道可靠判错；这是复习风险，不是撤销基础毕业。','targeted_practice'
    elif stale:
        status,label,reason,action='REVIEW','需要复习','距最近可靠练习（或毕业）已较久，建议复测；时间间隔不证明已经遗忘。','delayed_retest'
    elif good:
        status,label,reason,action='GOOD','保持良好',f'后续{len(latest)}道不同题独立正确，跨日并具备题型或技能覆盖；历史错误仍保留。','spaced_review'
    elif assisted:
        status,label,reason,action='REVIEW','建议独立复测','近期有非独立或独立性未能确认的正确比对，尚不足以说明独立恢复。','delayed_retest'
    else:
        status,label,reason,action='INSUFFICIENT','证据不足',('仅出现一次可靠错误，先记录风险、换题验证，不断言遗忘。' if wrong else '当前不同题目、独立性或技能覆盖证据不足；一次正确不代表恢复熟练。'),'validate_with_other_questions'
    return PostGraduationPractice(applicable=True,status=status,label=label,reason=reason,next_action=action,
        graduated_at=graduated_at.isoformat(),last_reliable_practice_at=last.isoformat() if last else None,
        observed_attempt_count=len(recent),reliable_attempt_count=len(reliable),distinct_question_count=len(by_content),
        independent_correct_count=sum(r['result']=='right' for r in independent),independent_wrong_count=sum(r['result']=='wrong' for r in independent),
        assisted_correct_count=len(assisted),excluded_attempt_count=len(recent)-len(reliable),history_truncated=truncated,
        evidence_summary=f'最近{RULES.window_days}天有{len(reliable)}次可可靠核对的练习；{len(by_content)}道有独立表现记录的不同题，{len(assisted)}次独立性不足的正确比对。',
        limitations=['仅限当前内容绑定和最终答案反馈；不证明过程能力或绝对熟练。']+
            (['部分记录无法可靠判题或版本绑定不完整，未当作错误或独立正确。'] if len(recent)>len(reliable) else [])+
            (['历史查询已截断，不能判为保持良好。'] if truncated else []))


def read_post_practice(db,node,*,now=None,snapshot=None,questions=None,attempts=None,policy=None):
    now=now or datetime.now(timezone.utc)
    if not node or not node.is_active or not node.is_assessable: return None
    state=db.get(KpState,node.id)
    policy=policy if policy is not None else policy_for_node(db,node.id)
    snapshot=snapshot or (current_policy_snapshot(db,state,policy) if state else None)
    if not snapshot or snapshot.state is not MasteryState.MASTERED or snapshot.assessment_basis!='objective_v1':
        return PostGraduationPractice(applicable=False,status='NOT_APPLICABLE',label='尚未严格毕业',reason='继续使用原有学习进展与严格毕业条件。',next_action='continue_learning')
    if not snapshot.mastered_at:
        return PostGraduationPractice(applicable=True,status='INSUFFICIENT',label='证据不足',reason='缺少可靠的毕业时间边界，不能臆造毕业后记录。',next_action='validate_with_other_questions')
    order=QuestionAttempt.grading_evidence['attempt_number'].as_string()
    number=case((order.op('~')(r'^[0-9]{1,2}$'),order.cast(Integer)),else_=0)
    attempts=list(attempts) if attempts is not None else list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id==node.id,
        QuestionAttempt.submitted_at>snapshot.mastered_at,QuestionAttempt.submitted_at<=now)
        .order_by(QuestionAttempt.submitted_at.desc(),number.desc(),QuestionAttempt.id).limit(RULES.max_attempts+1)))
    rows=[]
    from backend.services.evidence_pool import _content_identity
    from backend.services.question_versions import question_for_attempt
    for a in reversed(attempts[:RULES.max_attempts]):
        s=a.grading_evidence if isinstance(a.grading_evidence,dict) else {}
        try:q=question_for_attempt(db,a)
        except ValueError:q=None
        rows.append({'time':a.submitted_at,'number':s.get('attempt_number',0) if type(s.get('attempt_number')) is int else 0,'result':a.objective_result,
            'identity':_content_identity(q) if q else str(a.question_id),'type':s.get('question_type'),
            'tags':[t for t in s.get('skill_tags',[]) if isinstance(t,str) and t!=node.name] if isinstance(s.get('skill_tags'),list) else [],
            'reliable':feedback_bound(a,q,node) if q else False,
            'independent':s.get('sequence_version')=='attempt-sequence-v1' and s.get('assisted') is False
                and s.get('assistance_level')=='none' and s.get('history_unknown') is False
                and s.get('sequence_category') in INDEPENDENT and s.get('confidence') not in {'guess','no_idea'}})
    return project_post_practice(rows,now=now,graduated_at=snapshot.mastered_at,truncated=len(attempts)>RULES.max_attempts)


def list_review_needs(db,*,now,subject=None,limit=10,excluded=(),scope_ids=None):
    query=select(KnowledgePoint).join(KpState,KpState.kp_id==KnowledgePoint.id).where(KnowledgePoint.is_active.is_(True),
        KnowledgePoint.is_assessable.is_(True),KpState.state=='mastered',KnowledgePoint.id.not_in(set(excluded)))
    if subject:query=query.where(KnowledgePoint.subject==subject)
    if scope_ids is not None:query=query.where(KnowledgePoint.id.in_(scope_ids))
    results=[]
    for n in db.scalars(query.order_by(KnowledgePoint.code)):
        p=read_post_practice(db,n,now=now)
        if p and p.applicable and p.status in {'CONSOLIDATE','REVIEW','INSUFFICIENT'}:
            results.append({'kp_id':str(n.id),'name':n.name,'code':n.code,'post_graduation':p.model_dump(mode='json')})
    priority={'CONSOLIDATE':0,'REVIEW':1,'INSUFFICIENT':2}
    results.sort(key=lambda r:(priority[r['post_graduation']['status']],r['code']))
    return {'nodes':results[:limit],'total':len(results),'risk_count':sum(r['post_graduation']['status'] in {'CONSOLIDATE','REVIEW'} for r in results),'truncated':len(results)>limit,
        'note':'普通复习方案仍需确认；库存不足时可以显式要求出新题，本次查询不触发生成。'}
