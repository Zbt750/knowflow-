"""Read-only formal-bank inventory with the same admission rules as practice."""
from collections import Counter

from sqlalchemy import select

from backend.models.learning import KnowledgePoint, Question, QuestionAttempt
from backend.services.question_eligibility import question_eligibility
from backend.services.study_read_context import question_read_options


def subject_matches_408(node):
    return (node.subject in {'408', 'cs408', '计算机学科专业基础'}
            or node.code.startswith('cs408'))


def audit_public_subject_inventory(db, *, subject='408'):
    """Count stored rows, public/personal scope, admission, study and trust separately.

    The caller supplies the database session; this function does not select a
    database or relax admission. All eligibility decisions are delegated to
    ``question_eligibility`` and are pinned to the currently stored question.
    """
    nodes=list(db.scalars(select(KnowledgePoint).order_by(KnowledgePoint.code)))
    if subject == '408':
        nodes=[node for node in nodes if subject_matches_408(node)]
    else:
        nodes=[node for node in nodes if node.subject == subject]
    if not nodes:
        return {'subject':subject,'knowledge_point_count':0,'totals':{
            'question_total':0,'public_formal_question_count':0,'personal_question_count':0,
            'eligible_public_count':0,'eligible_unseen_count':0,'attempted_question_count':0,
            'reliable_attempted_question_count':0,'pending_recheck_count':0},'topics':[]}

    node_by_id={node.id:node for node in nodes}
    questions=db.scalars(select(Question).where(Question.kp_id.in_(node_by_id))
        .options(*question_read_options()).order_by(Question.kp_id,Question.id)).all()
    review_events={str(q.auto_review_event_id):q.current_auto_review for q in questions
        if q.auto_review_event_id and q.current_auto_review is not None}
    question_ids=[q.id for q in questions]
    attempts=db.scalars(select(QuestionAttempt).where(QuestionAttempt.question_id.in_(question_ids))
        .order_by(QuestionAttempt.submitted_at,QuestionAttempt.id)).all() if question_ids else []
    by_question={}
    for attempt in attempts:
        by_question.setdefault(attempt.question_id,[]).append(attempt)

    topics=[]
    for node in nodes:
        rows=[q for q in questions if q.kp_id==node.id]
        public=[q for q in rows if q.bank_scope=='public' and q.generation_batch_id is None]
        personal=[q for q in rows if q.bank_scope=='personal' or q.generation_batch_id is not None]
        eligibility={q.id:question_eligibility(q,node,auto_review_events=review_events) for q in public}
        eligible=[q for q in public if q.current_version_id is not None and eligibility[q.id].practice_eligible]
        attempted={q.id for q in eligible if by_question.get(q.id)}
        reliable={q.id for q in eligible if any(
            a.objective_result in {'right','wrong'}
            and a.question_version_id==q.current_version_id
            and (a.grading_evidence or {}).get('evidence_capability')=='verified_objective'
            and not (a.grading_evidence or {}).get('assisted')
            and (a.grading_evidence or {}).get('confidence')!='guess'
            for a in by_question.get(q.id,[]))}
        reasons=Counter(reason for q in public if not eligibility[q.id].practice_eligible
            for reason in eligibility[q.id].blocking_reasons)
        topics.append({
            'kp_id':str(node.id),'code':node.code,'name':node.name,'subject':node.subject,
            'active':node.is_active,'assessable':node.is_assessable,
            'question_total':len(rows),'public_formal_question_count':len(public),
            'personal_question_count':len(personal),
            'eligible_public_count':len(eligible),
            'eligible_unseen_count':len([q for q in eligible if q.id not in attempted]),
            'attempted_question_count':len(attempted),
            'reliable_attempted_question_count':len(reliable),
            'pending_recheck_count':len(public)-len(eligible),
            'missing_current_version_count':sum(q.current_version_id is None for q in public),
            'ineligible_reasons':dict(sorted(reasons.items())),
        })
    keys=('question_total','public_formal_question_count','personal_question_count',
        'eligible_public_count','eligible_unseen_count','attempted_question_count',
        'reliable_attempted_question_count','pending_recheck_count','missing_current_version_count')
    totals={key:sum(topic.get(key,0) for topic in topics) for key in keys}
    return {'subject':subject,'knowledge_point_count':len(topics),'totals':totals,'topics':topics}
