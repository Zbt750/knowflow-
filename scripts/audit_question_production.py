"""Read-only Phase 3 production audit using live Phase 2 eligibility decisions.

Candidate CSVs are optional identity-only outputs from the Phase 1 audit; no
question text is copied to the report. This command never calls a model or writes
to business tables.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import ExamQuestionReference, KnowledgePoint, Question, QuestionAnswerConsistencyRun, QuestionAttempt
from backend.services.evidence_pool import assess_evidence_pool
from backend.services.question_eligibility import question_eligibility
from backend.services.question_production_pipeline import assess_production_question, content_digest

EVIDENCE_ELIGIBLE_CAPABILITIES = frozenset({
    "verified_objective",
    "ai_consistent_objective",
    # Historical compatibility; it is kept as a separate tier in the report.
    "ai_answer_comparison_only",
})


def is_evidence_eligible_capability(capability: str | None) -> bool:
    """Count evidence-eligible tiers without collapsing their reliability."""
    return capability in EVIDENCE_ELIGIBLE_CAPABILITIES


def _safe_counts(rows: list[dict], candidate_csv: Path | None) -> dict:
    q_by_id = {str(row["id"]): row for row in rows}
    duplicate_counts = Counter((row["kp_id"], row["content_hash"]) for row in rows if row["active"])
    out = Counter({key: 0 for key in ("EXACT", "POSSIBLE", "UNMATCHED", "CONFLICT")})
    matched_question_ids: set[str] = set()
    rejected: int | None = None
    if candidate_csv and candidate_csv.is_file():
        with candidate_csv.open("r", encoding="utf-8-sig", newline="") as stream:
            candidates = list(csv.DictReader(stream))
        for row in candidates:
            raw_status = (row.get("mapping_status") or "UNMATCHED").upper()
            ids = []
            try:
                ids = json.loads(row.get("matched_question_ids") or "[]")
            except (TypeError, json.JSONDecodeError):
                pass
            declared_conflict = "conflict" in (row.get("reason") or "").lower()
            try:
                duplicate_match = int(row.get("match_count") or 0) > 1
            except (ValueError, TypeError):
                duplicate_match = False
            status = "CONFLICT" if declared_conflict or duplicate_match else raw_status
            if status not in out:
                status = "UNMATCHED"
            out[status] += 1
            if status == "EXACT":
                matched_question_ids.update(str(item) for item in ids)
            if (row.get("candidate_status") or "").lower() == "rejected":
                rejected = (rejected or 0) + 1
        if rejected is None:
            rejected = None
    else:
        candidates = []
    return {
        "candidate_exact": out["EXACT"] if candidate_csv else None,
        "candidate_possible": out["POSSIBLE"] if candidate_csv else None,
        "candidate_unmatched": out["UNMATCHED"] if candidate_csv else None,
        "candidate_conflict": out["CONFLICT"] if candidate_csv else None,
        "matched_exact_candidate_count": len(matched_question_ids) if candidate_csv else None,
        "rejected_candidate_count": rejected,
        "unresolved_candidate_count": (out["POSSIBLE"] + out["UNMATCHED"] + out["CONFLICT"]) if candidate_csv else None,
        "candidate_map_rows": sum(out.values()) if candidate_csv else None,
        "candidate_map_sha256": __import__("hashlib").sha256(candidate_csv.read_bytes()).hexdigest() if candidate_csv and candidate_csv.is_file() else None,
    }


def build_report(db, *, candidate_csv: Path | None = None) -> dict:
    nodes = list(db.scalars(select(KnowledgePoint).order_by(KnowledgePoint.subject, KnowledgePoint.code)))
    questions = list(db.scalars(select(Question).order_by(Question.id)))
    refs = list(db.scalars(select(ExamQuestionReference)))
    attempts = list(db.scalars(select(QuestionAttempt)))
    consistency_runs = list(db.scalars(select(QuestionAnswerConsistencyRun)))
    node_by_id = {n.id: n for n in nodes}
    active_nodes = [n for n in nodes if n.is_active]
    q_by_node: dict = defaultdict(list)
    assessment_by_id: dict = {}
    question_records = []
    reasons = Counter()
    by_provenance = Counter()
    by_content_trust = Counter()
    by_answer_provenance = Counter()
    by_answer_reliability = Counter()
    by_grading_capability = Counter()
    by_evidence_capability = Counter()
    for q in questions:
        node = node_by_id.get(q.kp_id)
        assessment = question_eligibility(q, node)
        assessment_by_id[q.id] = assessment
        q_by_node[q.kp_id].append(q)
        by_provenance[q.question_provenance or "legacy_unknown"] += 1
        by_content_trust[q.content_trust or "unreviewed"] += 1
        by_answer_provenance[q.answer_provenance or "unknown"] += 1
        by_answer_reliability[q.answer_reliability or "unknown"] += 1
        if q.is_active and assessment.practice_eligible:
            by_grading_capability[assessment.grading_capability] += 1
            by_evidence_capability[assessment.evidence_capability] += 1
        else:
            reasons.update(assessment.blocking_reasons)
        question_records.append({
            "id": str(q.id), "kp_id": q.kp_id, "active": bool(q.is_active),
            "question_provenance": q.question_provenance or "legacy_unknown",
            "content_trust": q.content_trust or "unreviewed",
            "answer_provenance": q.answer_provenance or "unknown",
            "answer_reliability": q.answer_reliability or "unknown",
            "assessment": assessment, "content_hash": content_digest(q),
            "source": ((q.grading_config or {}).get("provenance", {}).get("source", {})
                       if isinstance(q.grading_config, dict) else {}),
        })
    attempted_ids = {attempt.question_id for attempt in attempts if attempt.question_id is not None}
    references_by_node = Counter(ref.knowledge_point_id for ref in refs)
    consistency_by_question: dict = defaultdict(list)
    for run in consistency_runs:
        consistency_by_question[run.question_id].append(run)

    # Duplicate content is measured per target node. The pipeline flags it for
    # review but does not retire or rewrite a Question.
    duplicate_by_qid: set[str] = set()
    duplicate_groups = Counter((row["kp_id"], row["content_hash"]) for row in question_records if row["active"])
    for row in question_records:
        if row["active"] and duplicate_groups[(row["kp_id"], row["content_hash"])] > 1:
            duplicate_by_qid.add(row["id"])

    node_rows = []
    pool_counts = Counter()
    coverage_total = Counter()
    for node in active_nodes:
        node_questions = q_by_node.get(node.id, [])
        node_assessments = {q.id: assessment_by_id[q.id] for q in node_questions}
        active_questions = [q for q in node_questions if q.is_active]
        pool = assess_evidence_pool(questions=active_questions, eligibility_by_id=node_assessments,
            attempted_question_ids=attempted_ids, known=node.is_assessable)
        pool_counts[pool.status] += 1
        eligible = [q for q in active_questions if node_assessments[q.id].practice_eligible]
        evidence_rows = [q for q in eligible if is_evidence_eligible_capability(
            node_assessments[q.id].evidence_capability)]
        verified_objective = [q for q in evidence_rows
            if node_assessments[q.id].evidence_capability == "verified_objective"]
        ai_consistent_objective = [q for q in evidence_rows
            if node_assessments[q.id].evidence_capability == "ai_consistent_objective"]
        ai = [q for q in active_questions if q.answer_provenance == "ai_generated"]
        verified_answers = [q for q in active_questions if q.answer_provenance == "verified_reference" and q.answer_reliability == "verified"]
        real_questions = [q for q in active_questions if q.question_provenance == "real_exam"]
        supported = [q for q in eligible if node_assessments[q.id].grading_capability in {"deterministic", "final_answer_limited"}]
        years = sorted({int(source["year"]) for q in active_questions
                        for source in [((q.grading_config or {}).get("provenance", {}).get("source", {})
                                        if isinstance(q.grading_config, dict) else {})]
                        if isinstance(source, dict) and str(source.get("year", "")).isdigit()})
        tags = sorted({tag for q in eligible for tag in (q.skill_tags or []) if isinstance(tag, str)})
        node_rows.append({
            "code": node.code, "name": node.name, "subject": node.subject,
            "is_assessable": bool(node.is_assessable), "is_reference_only": bool(node.is_reference_only),
            "active_question_count": len(active_questions), "practice_eligible_count": len(eligible),
            "real_exam_count": len(real_questions), "trusted_practice_count": sum(q.question_provenance == "trusted_practice" for q in eligible),
            "ai_generated_practice_count": sum(q.question_provenance == "ai_generated_practice" for q in eligible),
            "verified_reference_answer_count": len(verified_answers), "ai_generated_answer_count": len(ai),
            "ai_consistent_answer_count": sum(q.answer_reliability == "ai_generated_consistent" for q in ai),
            "ai_disagreement_count": sum(q.answer_reliability == "ai_disagreement" for q in ai),
            "grading_supported_count": len(supported),
            "evidence_eligible_count": len(evidence_rows),
            "verified_objective_evidence_eligible_count": len(verified_objective),
            "ai_consistent_objective_evidence_eligible_count": len(ai_consistent_objective),
            "unused_evidence_question_count": sum(q.id not in attempted_ids for q in evidence_rows),
            "attempted_distinct_question_count": len({q.id for q in node_questions if q.id in attempted_ids}),
            "capability_dimensions": tags, "year_span": [min(years), max(years)] if years else None,
            "reference_count": references_by_node[node.id],
            "evidence_pool_status": pool.status, "evidence_pool_reasons": list(pool.reasons),
            "evidence_pool_counts": pool.public_dict(),
            "blocked_by_reason": dict(Counter(reason for q in active_questions
                for reason in node_assessments[q.id].blocking_reasons)),
            "duplicate_content_question_count": sum(str(q.id) in duplicate_by_qid for q in active_questions),
            "candidate_remaining": None,
        })
        if node.is_assessable:
            coverage_total["assessable_nodes"] += 1
            coverage_total["nodes_with_practice"] += int(bool(eligible))
            coverage_total["nodes_without_practice"] += int(not eligible)

    eligible_records = [row for row in question_records if row["active"] and row["assessment"].practice_eligible]
    evidence_records = [row for row in eligible_records if is_evidence_eligible_capability(
        row["assessment"].evidence_capability)]
    verified_objective_evidence_records = [row for row in evidence_records
        if row["assessment"].evidence_capability == "verified_objective"]
    ai_consistent_evidence_records = [row for row in evidence_records
        if row["assessment"].evidence_capability == "ai_consistent_objective"]
    candidate_data = _safe_counts(question_records, candidate_csv)
    return {
        "schema_version": "question-production-audit-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "assessment_code": "Phase2 QuestionEligibilityService + deterministic content structure checks",
        "database_written": False,
        "model_calls": 0,
        "total_questions": len(questions), "active_questions": sum(q.is_active for q in questions),
        "inactive_questions": sum(not q.is_active for q in questions),
        "by_question_provenance": dict(by_provenance), "by_content_trust": dict(by_content_trust),
        "by_answer_provenance": dict(by_answer_provenance), "by_answer_reliability": dict(by_answer_reliability),
        "practice_eligible": len(eligible_records), "evidence_eligible": len(evidence_records),
        "verified_objective_evidence_eligible": len(verified_objective_evidence_records),
        "ai_consistent_objective_evidence_eligible": len(ai_consistent_evidence_records),
        "blocked_by_reason": dict(reasons),
        "real_exam_count": sum(q.question_provenance == "real_exam" for q in questions),
        "trusted_practice_count": sum(q.question_provenance == "trusted_practice" for q in questions),
        "ai_generated_practice_count": sum(q.question_provenance == "ai_generated_practice" for q in questions),
        "verified_reference_answer_count": sum(q.answer_provenance == "verified_reference" and q.answer_reliability == "verified" for q in questions),
        "ai_generated_answer_count": sum(q.answer_provenance == "ai_generated" for q in questions),
        "ai_consistent_answer_count": sum(q.answer_reliability == "ai_generated_consistent" for q in questions),
        "ai_disagreement_count": sum(q.answer_reliability == "ai_disagreement" for q in questions),
        "unknown_answer_count": sum(q.answer_provenance in {None, "unknown", "legacy_transcription"} for q in questions),
        "consistency_run_count": len(consistency_runs),
        "consistency_run_status_counts": dict(Counter(run.status for run in consistency_runs)),
        "knowledge_nodes_with_practice": coverage_total["nodes_with_practice"],
        "knowledge_nodes_without_practice": coverage_total["nodes_without_practice"],
        "assessable_knowledge_nodes": coverage_total["assessable_nodes"],
        "evidence_pool_sufficient_nodes": pool_counts["SUFFICIENT"],
        "evidence_pool_insufficient_nodes": pool_counts["INSUFFICIENT"],
        "evidence_pool_unknown_nodes": pool_counts["UNKNOWN"],
        **candidate_data,
        "nodes": node_rows,
        "limits": [
            "EXACT identity, structural completeness and parser applicability do not create human review or trust.",
            "candidate status counts are imported from the supplied identity-only Phase 1 CSV; null means not measured.",
            "evidence-pool status describes verified objective opportunities, not the learner or graduation threshold.",
            "candidate inventory is not indexed in the runtime API; per-node candidate_remaining is null.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-map", type=Path, help="optional identity-only Phase 1 CSV")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "phase3_20261006" / "production-audit-v1.json")
    args = parser.parse_args()
    output = args.output.resolve()
    if not any(output.is_relative_to(ROOT / folder) for folder in ("tmp", "eval/reports")):
        parser.error("audit output must stay under tmp/ or eval/reports/")
    if output.exists():
        parser.error("refuse to overwrite an existing report")
    if args.candidate_map and (not args.candidate_map.is_file() or args.candidate_map.stat().st_size > 16 * 1024 * 1024):
        parser.error("candidate map missing or larger than the 16 MiB audit bound")
    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    if (url.database or "").lower().endswith("_test") or (url.database or "").lower() == "test":
        parser.error("refuse to audit a test database; point settings at the development database")
    engine = create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            report = build_report(db, candidate_csv=args.candidate_map)
    finally:
        engine.dispose()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "total_questions", "active_questions", "practice_eligible", "evidence_eligible",
        "knowledge_nodes_with_practice", "knowledge_nodes_without_practice",
        "evidence_pool_sufficient_nodes", "evidence_pool_insufficient_nodes",
        "candidate_exact", "candidate_possible", "candidate_unmatched", "candidate_conflict",
        "database_written", "model_calls")}, ensure_ascii=False, indent=2))
    print(f"report={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
