"""Read-only policy audit and non-executable origin-quota migration proposal."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, text
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import ExamQuestionReference, KnowledgePoint, KpMasteryPolicy, KpState, Question, QuestionAttempt
from backend.services.question_eligibility import question_eligibility
from scripts.answer_trust_migration_preflight import local_database_url, private_output
from scripts.audit_answer_trust_slice import POLICY_FIELDS, _policy_snapshot


def build_policy_report(db) -> dict:
    policies = list(db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id)))
    nodes = {n.id: n for n in db.scalars(select(KnowledgePoint))}
    references = dict(db.execute(select(ExamQuestionReference.knowledge_point_id,
        func.count()).group_by(ExamQuestionReference.knowledge_point_id)).all())
    questions = defaultdict(list)
    for q in db.scalars(select(Question).where(Question.is_active.is_(True))):
        questions[q.kp_id].append(q)
    proposals = []
    for policy in policies:
        quota = (policy.required_question_types or {}).get("external_exam")
        if not quota:
            continue
        node = nodes[policy.kp_id]
        values = {field: getattr(policy, field) for field in POLICY_FIELDS}
        seeded = (policy.note or "").startswith("历年真题索引策略：")
        matches_formula = bool(seeded and references.get(node.id, 0) > 0
            and quota == min(3, references[node.id]) and policy.min_confirmations == quota
            and policy.min_real_questions == quota and policy.required_variant_count == 0
            and policy.required_question_types == {"external_exam": quota}
            and policy.min_day_span == min(2, quota-1)
            and policy.required_skill_tags == [node.name])
        proposals.append({"node_code": node.code, "node_name": node.name,
            "node_id": str(node.id), "subject": node.subject, "node_active": node.is_active,
            "reference_only": node.is_reference_only, "reference_count": references.get(node.id, 0),
            "online_question_type_counts": dict(Counter(q.question_type for q in questions[node.id])),
            "current_verified_objective_count": sum(
                question_eligibility(q, node).practice_eligible
                and question_eligibility(q, node).evidence_capability == "verified_objective"
                for q in questions[node.id]),
            "matches_reference_seed_formula": matches_formula, "before_policy": values,
            "proposal_only": {"requires_user_approval": True,
                "required_question_origins": {"real_exam": quota},
                "required_question_types": {k:v for k,v in policy.required_question_types.items() if k != "external_exam"},
                "all_other_thresholds": "preserve exactly",
                "historical_attempts_and_states": "preserve, do not reinterpret or upgrade",
                "activation_boundary": "new versioned policy and future evidence only"}})
    _, digest = _policy_snapshot(policies)
    window_distribution = Counter()
    for state in db.scalars(select(KpState)):
        for item in state.evidence_window or []:
            window_distribution[(item.get("question_type", "unknown"), item.get("source", "unknown"),
                item.get("reliability", "unknown"))] += 1
    return {"format": "graduation-policy-compatibility-audit-v2",
        "created_at": datetime.now(timezone.utc).isoformat(), "read_only": True,
        "model_calls": 0, "policy_rows": len(policies), "policy_sha256": digest,
        "required_type_distribution": dict(Counter(json.dumps(p.required_question_types or {},
            ensure_ascii=False, sort_keys=True) for p in policies)),
        "external_exam_policy_count": len(proposals),
        "policy_version_distribution": dict(Counter(p.policy_version for p in policies)),
        "origin_quota_distribution": dict(Counter(json.dumps(p.required_question_origins or {},
            ensure_ascii=False,sort_keys=True) for p in policies)),
        "seed_formula_match_count": sum(p["matches_reference_seed_formula"] for p in proposals),
        "classification": "CASE_B_HISTORICAL_REFERENCE_POLICY_INCOMPATIBLE_WITH_CURRENT_OBJECTIVE_EVIDENCE" if proposals else "NO_LEGACY_EXTERNAL_EXAM_QUOTAS",
        "historical_external_reference_attempts": db.scalar(select(func.count()).select_from(QuestionAttempt)
            .where(QuestionAttempt.exam_reference_id.is_not(None))),
        "stored_evidence_window_distribution": [{"question_type": q, "source": s, "reliability": r, "count": n}
            for (q,s,r),n in sorted(window_distribution.items())],
        "explanation": "external_exam denotes a legacy source-pointer practice representation, not a proctored exam or every real-exam Question. The old seed populated this pseudo-type quota for self-reported external practice; new self reports cannot grant confirmations.",
        "proposal_status": "NOT_APPROVED_NOT_APPLIED", "affected_policies": proposals,
        "limitations": ["No policy or historical evidence was modified.",
            "Origin-quota semantics are a review proposal, not an inferred already-approved product contract.",
            "This JSON is not an executable policy migration or verification manifest.",
            "Policies not matching the exact old seed formula must be manually reviewed before any future bulk migration."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = private_output(args.output)
    engine = create_db_engine(str(local_database_url(get_settings())))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            if db.scalar(text("SELECT version_num FROM public.alembic_version")) != "f46b2c8d901a":
                raise ValueError("Expected answer-trust migration must be active first")
            report = build_policy_report(db)
            db.rollback()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"policy_rows": report["policy_rows"], "affected": report["external_exam_policy_count"],
            "exact_seed_formula_matches": report["seed_formula_match_count"], "policy_mutations": 0,
            "output": str(output)}, ensure_ascii=False))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
