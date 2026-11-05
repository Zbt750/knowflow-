"""Read-only answer-trust and graduation-opportunity audit for the Phase 4.5A slice.

The report contains aggregate counts and stable node codes only. It does not
emit question text, answer text, attempt text, or learner histories. No rows are
written and no model/network call is made.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import (
    DailyPlan, KpMasteryPolicy, KpState, KnowledgePoint, LearningEvent,
    PracticeItem, Question, QuestionAnswerConsistencyRun,
    QuestionAnswerVerificationEvent, QuestionAttempt, QuestionSourceAttestation,
)
from backend.models.practice_request import PracticeRequest
from backend.services.answer_verification import current_answer_verification
from backend.services.evidence_pool import assess_evidence_pool
from backend.services.question_eligibility import question_eligibility
from backend.mastery.policy import LEGACY_POLICY_FIELDS, VERSIONED_POLICY_FIELDS
from backend.mastery.storage import policy_from_storage


GOLDEN_NODE_CODES = (
    "math.exam.fd2f9e3739d9",       # 反常积分（数学二）
    "math.exam.f37948c82a05",       # 曲线凹凸与拐点（数学二）
    "cs408.ds.topic.1efaf3d00b50",  # 二叉树基础（408）
    "cs408.os.topic.cb972030e503",  # 文件基本概念（408）
)

COUNT_MODELS = {
    "questions": Question,
    "question_attempts": QuestionAttempt,
    "learning_events": LearningEvent,
    "kp_states": KpState,
    "daily_plans": DailyPlan,
    "practice_items": PracticeItem,
    "practice_requests": PracticeRequest,
    "question_answer_consistency_runs": QuestionAnswerConsistencyRun,
    "question_source_attestations": QuestionSourceAttestation,
    "question_answer_verification_events": QuestionAnswerVerificationEvent,
}

POLICY_FIELDS = VERSIONED_POLICY_FIELDS


def _policy_snapshot(rows: list[KpMasteryPolicy]) -> tuple[list[dict], str]:
    values = []
    for row in sorted(rows, key=lambda item: str(item.kp_id)):
        values.append({"kp_id": str(row.kp_id), **{
            field: getattr(row, field) for field in POLICY_FIELDS
        }})
    raw = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return values, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _pool_support_gaps(policy: KpMasteryPolicy | None, *, objective: list[Question],
                       unattempted: list[Question]) -> list[str]:
    required_confirmations = policy.min_confirmations if policy else 3
    required_real = policy.min_real_questions if policy else 3
    type_quota = dict(policy.required_question_types or {}) if policy else {}
    required_variants = policy.required_variant_count if policy else 1
    required_tags = set(policy.required_skill_tags or []) if policy else set()
    gaps = []
    if len(objective) < required_confirmations:
        gaps.append("INSUFFICIENT_DISTINCT_VERIFIED_CONFIRMATION_OPPORTUNITIES")
    if len(objective) < required_real:
        gaps.append("INSUFFICIENT_DISTINCT_VERIFIED_REAL_QUESTIONS")
    counts = Counter(question.question_type for question in objective)
    for question_type, required in sorted(type_quota.items()):
        if counts[question_type] < required:
            gaps.append(f"MISSING_REQUIRED_TYPE:{question_type}")
    origins = Counter(q.question_provenance for q in objective)
    for origin, required in sorted(dict(getattr(policy, "required_question_origins", None) or {}).items()):
        if origins[origin] < required:
            gaps.append(f"MISSING_REQUIRED_ORIGIN:{origin}")
    if sum(bool(question.is_variant) for question in objective) < required_variants:
        gaps.append("INSUFFICIENT_VERIFIED_VARIANTS")
    covered_tags = {tag for question in objective for tag in (question.skill_tags or [])}
    gaps.extend(f"MISSING_REQUIRED_SKILL_TAG:{tag}" for tag in sorted(required_tags - covered_tags))
    if not unattempted and (not policy or policy.policy_version == 1):
        gaps.append("NO_UNATTEMPTED_VERIFIED_OPPORTUNITY")
    # Time can be scheduled in the future. This is a potential only, not a claim
    # that the learner has produced evidence across the required day span.
    return gaps


def build_report(db, *, node_codes: tuple[str, ...] = GOLDEN_NODE_CODES) -> dict:
    counts = {
        name: db.scalar(select(func.count()).select_from(model)) or 0
        for name, model in COUNT_MODELS.items()
    }
    questions = list(db.scalars(select(Question).where(
        Question.is_active.is_(True), Question.kp_id.in_(
            select(KnowledgePoint.id).where(KnowledgePoint.code.in_(node_codes))
        )).order_by(Question.kp_id, Question.id)))
    nodes = {node.code: node for node in db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.code.in_(node_codes)))}
    policies = {row.kp_id: row for row in db.scalars(select(KpMasteryPolicy).where(
        KpMasteryPolicy.kp_id.in_(select(KnowledgePoint.id).where(
            KnowledgePoint.code.in_(node_codes)))))}
    all_policy_rows = list(db.scalars(select(KpMasteryPolicy)))
    policy_values, policy_sha = _policy_snapshot(all_policy_rows)
    policy_summary = {
        "row_count": len(policy_rows := all_policy_rows),
        "canonical_sha256": policy_sha,
        "fields": list(POLICY_FIELDS),
    }
    attempted_ids = {question_id for question_id in db.scalars(select(QuestionAttempt.question_id)
        .where(QuestionAttempt.question_id.is_not(None))) if question_id is not None}

    distributions = {
        "answer_provenance": Counter(),
        "answer_reliability": Counter(),
        "current_verification_type": Counter(),
        "grading_capability": Counter(),
        "evidence_capability": Counter(),
    }
    assessments = {}
    for question in questions:
        node = nodes.get(next((code for code in node_codes
            if nodes.get(code) and nodes[code].id == question.kp_id), ""))
        assessment = question_eligibility(question, node)
        assessments[question.id] = assessment
        distributions["answer_provenance"][question.answer_provenance or "unknown"] += 1
        distributions["answer_reliability"][question.answer_reliability or "unknown"] += 1
        event = current_answer_verification(question)
        distributions["current_verification_type"][event.verification_type if event else "none"] += 1
        if assessment.practice_eligible:
            distributions["grading_capability"][assessment.grading_capability] += 1
            distributions["evidence_capability"][assessment.evidence_capability] += 1

    node_reports = []
    for code in node_codes:
        node = nodes.get(code)
        if node is None:
            node_reports.append({"code": code, "status": "NODE_MISSING"})
            continue
        rows = [question for question in questions if question.kp_id == node.id]
        row_assessments = {question.id: assessments[question.id] for question in rows}
        practice = [question for question in rows if row_assessments[question.id].practice_eligible]
        trusted_answer = [question for question in rows if row_assessments[question.id].answer_verification_current]
        deterministic = [question for question in practice
            if row_assessments[question.id].verified_grading_method is not None]
        objective = [question for question in practice
            if row_assessments[question.id].evidence_capability == "verified_objective"]
        unique_objective = {question.id: question for question in objective}
        unattempted = [question for question in unique_objective.values() if question.id not in attempted_ids]
        policy = policies.get(node.id)
        pool = assess_evidence_pool(questions=rows, eligibility_by_id=row_assessments,
            attempted_question_ids=attempted_ids, known=node.is_assessable, policy=policy_from_storage(policy))
        support_gaps = _pool_support_gaps(policy, objective=list(unique_objective.values()),
                                         unattempted=unattempted)
        node_reports.append({
            "code": code,
            "name": node.name,
            "subject": node.subject,
            "assessable": node.is_assessable,
            "active_question_count": len(rows),
            "practice_eligible_count": len(practice),
            "real_exam_question_count": sum(q.question_provenance == "real_exam" for q in rows),
            "trusted_answer_count": len(trusted_answer),
            "human_verified_answer_count": sum(q.answer_provenance == "human_verified"
                and row_assessments[q.id].answer_verification_current for q in rows),
            "verified_reference_answer_count": sum(q.answer_provenance == "verified_reference"
                and row_assessments[q.id].answer_verification_current for q in rows),
            "deterministic_gradeable_count": len(deterministic),
            "verified_objective_question_count": len(unique_objective),
            "independent_confirmation_opportunity_count": len(unique_objective),
            "unattempted_verified_objective_count": len(unattempted),
            "verified_variant_count": sum(q.is_variant for q in unique_objective.values()),
            "evidence_pool_status": pool.status,
            "evidence_pool_reasons": list(pool.reasons),
            "current_graduation_policy": ({field: getattr(policy, field) for field in POLICY_FIELDS
                if field != "note"} if policy else "DEFAULT_POLICY"),
            "potential_pool_support": "POTENTIALLY_SUPPORTABLE" if not support_gaps else "INSUFFICIENT_EVIDENCE_POOL",
            "pool_support_gaps": support_gaps,
            "learner_mastery_claim": "NOT_ASSESSED_BY_THIS_INVENTORY_AUDIT",
            "answer_verification_status": "CURRENT_VERIFIED_ANSWER" if trusted_answer else "UNVERIFIED_ANSWER",
            "source_availability": "NOT_AUDITED",
        })

    return {
        "schema_version": "phase45-answer-trust-slice-audit-v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "model_calls": 0,
        "counts": counts,
        "policy_fingerprint": policy_summary,
        "policy_snapshot_internal_count": len(policy_values),
        "answer_provenance_distribution_in_slice": dict(sorted(distributions["answer_provenance"].items())),
        "answer_reliability_distribution_in_slice": dict(sorted(distributions["answer_reliability"].items())),
        "current_verification_distribution_in_slice": dict(sorted(distributions["current_verification_type"].items())),
        "practice_eligible_grading_capability_in_slice": dict(sorted(distributions["grading_capability"].items())),
        "practice_eligible_evidence_capability_in_slice": dict(sorted(distributions["evidence_capability"].items())),
        "golden_slice": node_reports,
        "limits": [
            "Pool support is an inventory opportunity estimate, not learner mastery or guaranteed graduation.",
            "Source availability requires an independent offline source audit; absence of an answer verification event is not evidence that a file is missing.",
            "HUMAN_VERIFIED is an operator declaration; this workflow does not authenticate verifier identity.",
            "VERIFIED_REFERENCE metadata is an allowlisted declaration; this workflow does not independently authenticate the external source.",
            "No question or answer text, attempt content, or user study history is emitted.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-code", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    codes = tuple(dict.fromkeys(args.node_code)) if args.node_code else GOLDEN_NODE_CODES
    if args.node_code and not 4 <= len(codes) <= 8:
        parser.error("Select four to eight distinct candidate nodes")
    if args.output:
        from scripts.answer_trust_migration_preflight import private_output
        output = private_output(args.output)
    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    if settings.app_env != "dev" or (url.database or "").lower().endswith("_test"):
        raise SystemExit("Refusing: this audit is limited to the configured APP_ENV=dev database.")
    engine = create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "f46b2c8d901a":
                raise SystemExit(
                    "Refusing to run: apply versioned policy migration f46b2c8d901a in the intended local environment first. "
                    f"Current schema revision is {revision!r}. No data was written."
                )
            report = build_report(db, node_codes=codes)
            db.rollback()
        if args.output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"read_only": True, "node_count": len(codes), "output": str(output)}, ensure_ascii=False))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
