"""Bounded inventory summaries shared by the API and Learning Task tools."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.learning import DailyPlan, ExamQuestionReference, KnowledgePoint, PracticeItem, Question, QuestionAttempt
from backend.services.question_eligibility import question_eligibility
from backend.services.evidence_pool import assess_evidence_pool


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _descendant_ids(db: Session, roots: set[UUID]) -> set[UUID]:
    if not roots:
        return set()
    tree = select(KnowledgePoint.id).where(KnowledgePoint.id.in_(roots)).cte("availability_scope", recursive=True)
    tree = tree.union(select(KnowledgePoint.id).join(tree, KnowledgePoint.parent_id == tree.c.id)
        .where(KnowledgePoint.is_active.is_(True)))
    return set(db.scalars(select(tree.c.id)))


def question_availability(db: Session, *, now: datetime, subject: str | None = None,
                          kp_ids: list[UUID] | None = None, exclude_kp_ids: list[UUID] | None = None,
                          exclude_question_ids: list[UUID] | None = None,
                          question_type: str | None = None, plan_id: UUID | None = None,
                          limit: int = 100) -> dict:
    """Count real practice inventory separately from source pointers and candidates."""
    query_nodes = select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))
    if subject:
        query_nodes = query_nodes.where(KnowledgePoint.subject == subject)
    if kp_ids:
        scoped = _descendant_ids(db, set(kp_ids))
        query_nodes = query_nodes.where(KnowledgePoint.id.in_(scoped))
    if exclude_kp_ids:
        excluded = _descendant_ids(db, set(exclude_kp_ids))
        query_nodes = query_nodes.where(KnowledgePoint.id.not_in(excluded))
    nodes = list(db.scalars(query_nodes.order_by(KnowledgePoint.ordinal, KnowledgePoint.code)))
    node_by_id = {n.id: n for n in nodes}
    node_ids = set(node_by_id)
    excluded_questions = set(exclude_question_ids or [])
    question_filters = [Question.kp_id.in_(node_ids or set()), Question.is_active.is_(True)]
    if question_type:
        question_filters.append(Question.question_type == question_type)
    if excluded_questions:
        question_filters.append(Question.id.not_in(excluded_questions))
    questions = list(db.scalars(select(Question).where(*question_filters)
        .order_by(Question.created_at, Question.id)))
    if plan_id is None:
        today = now.astimezone(SHANGHAI).date().isoformat()
        current_plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == today))
        plan_id = current_plan.id if current_plan else None
    plan_questions = set(db.scalars(select(PracticeItem.question_id).where(
        PracticeItem.plan_id == plan_id, PracticeItem.question_id.is_not(None)))) if plan_id else set()
    attempted = set(db.scalars(select(QuestionAttempt.question_id).where(
        QuestionAttempt.question_id.in_([q.id for q in questions] or [UUID(int=0)])).distinct()))
    reference_rows = db.execute(select(ExamQuestionReference.knowledge_point_id)
        .where(ExamQuestionReference.knowledge_point_id.in_(node_ids or {UUID(int=0)}))).all()
    reference_counts = Counter(row[0] for row in reference_rows)
    groups: dict[UUID, list[Question]] = defaultdict(list)
    assessments_by_node: dict[UUID, dict[UUID, object]] = defaultdict(dict)
    blocked_by_reason: Counter[str] = Counter()
    eligible: dict[UUID, list[tuple[Question, object]]] = defaultdict(list)
    distributions = {k: Counter() for k in ("question_provenance", "answer_provenance", "grading_capability", "evidence_capability")}
    for question in questions:
        node = node_by_id.get(question.kp_id)
        if node is None:
            continue
        groups[node.id].append(question)
        assessment = question_eligibility(question, node)
        assessments_by_node[node.id][question.id] = assessment
        if assessment.practice_eligible:
            eligible[node.id].append((question, assessment))
            for key in distributions:
                distributions[key][getattr(assessment, key)] += 1
        else:
            blocked_by_reason.update(assessment.blocking_reasons)

    node_summaries = []
    for node in nodes:
        choices = eligible.get(node.id, [])
        eligible_ids = {q.id for q, _ in choices}
        pool = assess_evidence_pool(questions=groups.get(node.id, []),
            eligibility_by_id=assessments_by_node.get(node.id, {}),
            attempted_question_ids=attempted, known=node.is_active and node.is_assessable)
        node_summaries.append({
            "kp_id": str(node.id), "code": node.code, "name": node.name,
            "subject": node.subject, "path": _node_path(db, node),
            "active_question_count": len(groups.get(node.id, [])),
            "practice_eligible_count": len(choices),
            "available_to_append_count": len(eligible_ids - plan_questions),
            "already_in_plan_count": len(eligible_ids & plan_questions),
            "previously_attempted_count": len(eligible_ids & attempted),
            "unused_count": len(eligible_ids - attempted),
            "reference_count": reference_counts[node.id],
            "candidate_count": None,
            "candidate_inventory_status": "not_indexed",
            "blocking_reasons": dict(Counter(r for q in groups.get(node.id, [])
                for r in question_eligibility(q, node).blocking_reasons)),
            "question_provenance_counts": dict(Counter(a.question_provenance for _, a in choices)),
            "answer_provenance_counts": dict(Counter(a.answer_provenance for _, a in choices)),
            "grading_capability_counts": dict(Counter(a.grading_capability for _, a in choices)),
            "evidence_capability_counts": dict(Counter(a.evidence_capability for _, a in choices)),
            "evidence_pool_status": pool.status,
            "evidence_pool_reasons": list(pool.reasons),
            "verified_objective_question_count": pool.verified_objective_question_count,
            "distinct_objective_question_count": pool.distinct_objective_question_count,
            "unattempted_objective_question_count": pool.unattempted_objective_question_count,
            "variation_objective_question_count": pool.variation_objective_question_count,
        })
    positive_nodes = [n for n in node_summaries if n["practice_eligible_count"] > 0]
    total_eligible = sum(len(rows) for rows in eligible.values())
    active_count = len(questions)
    return {
        "subject": subject,
        "scope_node_ids": [str(i) for i in kp_ids or []],
        "excluded_node_ids": [str(i) for i in exclude_kp_ids or []],
        "excluded_question_ids": [str(i) for i in exclude_question_ids or []],
        "question_type": question_type,
        "current_plan_id": str(plan_id) if plan_id else None,
        "active_question_count": active_count,
        "practice_eligible_count": total_eligible,
        "available_to_append_count": sum(n["available_to_append_count"] for n in node_summaries),
        "already_in_plan_count": sum(n["already_in_plan_count"] for n in node_summaries),
        "previously_attempted_count": sum(n["previously_attempted_count"] for n in node_summaries),
        "unused_count": sum(n["unused_count"] for n in node_summaries),
        "reference_count": sum(reference_counts.values()),
        "candidate_count": None,
        "candidate_inventory_status": "not_indexed",
        "blocked_question_count": active_count - total_eligible,
        "blocking_reasons": dict(blocked_by_reason),
        "question_provenance_counts": dict(distributions["question_provenance"]),
        "answer_provenance_counts": dict(distributions["answer_provenance"]),
        "grading_capability_counts": dict(distributions["grading_capability"]),
        "evidence_capability_counts": dict(distributions["evidence_capability"]),
        "evidence_pool_sufficient_node_count": sum(n["evidence_pool_status"] == "SUFFICIENT" for n in node_summaries),
        "evidence_pool_insufficient_node_count": sum(n["evidence_pool_status"] == "INSUFFICIENT" for n in node_summaries),
        "evidence_pool_unknown_node_count": sum(n["evidence_pool_status"] == "UNKNOWN" for n in node_summaries),
        "eligible_nodes": positive_nodes[:limit],
        "eligible_node_count": len(positive_nodes),
        "returned_node_count": len(positive_nodes[:limit]),
        "subject_counts": [{"subject": key,
            "question_count": sum(n["practice_eligible_count"] for n in positive_nodes if n["subject"] == key),
            "node_count": sum(n["subject"] == key for n in positive_nodes)}
            for key in sorted({n.subject for n in nodes})],
        "node_list_truncated": len(positive_nodes) > limit,
        "inventory_note": "candidate_count为null：候选资产当前没有请求时可查询的统一索引；null不表示0。原卷引用不含题干，不计入可练题。",
    }


def _node_path(db: Session, node: KnowledgePoint) -> list[str]:
    result, seen = [], set()
    current = node
    while current is not None and current.id not in seen and len(result) < 20:
        seen.add(current.id)
        result.append(current.name)
        current = db.get(KnowledgePoint, current.parent_id) if current.parent_id else None
    return list(reversed(result))
