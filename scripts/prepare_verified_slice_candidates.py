"""Prepare an UNVERIFIED review worklist from existing local exam/source metadata.

No downloads, model calls, question imports, answer verification, or policy writes.
Source availability is separate from answer trust. Original question papers and
AI/transcription drafts alone do not prove the stored answer.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint, KpMasteryPolicy, Question
from backend.services.answer_grading import available_grading_method
from backend.services.answer_verification import answer_version_sha256
from backend.services.question_eligibility import question_eligibility
from scripts.answer_trust_migration_preflight import local_database_url, private_output

TARGET = "f46b2c8d901a"


def normalize_subject(value) -> str | None:
    if value in {"math2", "数学二", "考研数学"}:
        return "math2"
    return "408" if value == "408" else None


def complete_source_identity(source: dict) -> bool:
    return (source.get("source_type") == "exam" and normalize_subject(source.get("subject")) is not None
        and type(source.get("year")) is int and 2000 <= source["year"] <= 2100
        and type(source.get("question_number")) is int and 1 <= source["question_number"] <= 200
        and bool(str(source.get("paper_title") or "").strip())
        and bool(str(source.get("citation") or "").strip()))


def _existing_file(root: Path, locator: str, role: str) -> dict | None:
    """Only inspect declared files under the supplied local source root."""
    path = (root / locator.replace("\\", "/")).resolve()
    if (not path.is_relative_to(root.resolve()) or not path.is_file()
            or path.is_symlink() or path.suffix.lower() not in {".pdf", ".md", ".txt"}):
        return None
    stat = path.stat()
    if not 0 < stat.st_size <= 128 * 1024 * 1024:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        header = stream.read(1024)
        if path.suffix.lower() == ".pdf" and b"%PDF-" not in header:
            return None
        digest.update(header)
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("A source changed during the audit")
    return {"locator": path.relative_to(root.resolve()).as_posix(), "role": role,
        "bytes": stat.st_size, "sha256": digest.hexdigest()}


def audit_source_availability(source: dict, root: Path) -> dict:
    if not complete_source_identity(source):
        return {"status": "SOURCE_MISSING", "files": [], "question_source_available": False,
            "answer_source_available": False, "reasons": ["source_identity_incomplete"],
            "answer_verified": False}
    files = {}
    citation = source["citation"]
    # Inspect only relative paths already declared in the current source record.
    for locator in re.findall(r"(?:个人复习原卷|逐题整理)[/\\][^；;，,\n\r（）()]+?\.(?:pdf|md)", citation):
        role = "original_question_paper" if locator.startswith("个人复习原卷") else "transcription_draft"
        found = _existing_file(root, locator, role)
        if found:
            files[found["locator"]] = found
    for key in ("answer_key_path", "answer_source_path", "answer_reference_path"):
        locator = source.get(key)
        if isinstance(locator, str) and locator.strip():
            found = _existing_file(root, locator, "declared_answer_reference_pending_review")
            if found:
                files[found["locator"]] = found
    question_available = any(f["role"] == "original_question_paper" for f in files.values())
    answer_available = any(f["role"] == "declared_answer_reference_pending_review" for f in files.values())
    if answer_available:
        status, reasons = "SOURCE_AVAILABLE_FOR_REVIEW", ["declared_local_answer_material_requires_human_comparison"]
    elif files:
        status, reasons = "SOURCE_AMBIGUOUS", ["question_paper_or_draft_does_not_establish_current_answer"]
    else:
        status, reasons = "SOURCE_METADATA_ONLY", ["source_names_urls_or_locators_only_no_local_answer_material"]
    return {"status": status, "files": list(files.values()),
        "question_source_available": question_available, "answer_source_available": answer_available,
        "reasons": reasons, "answer_verified": False}


def bounded_candidate_method(question) -> str | None:
    if question.question_type == "single_choice":
        return available_grading_method(question_type=question.question_type,
            config={"verified": True, "method": "single_choice"},
            expected=question.correct_answer, options=question.options)
    if question.question_type in {"fill_blank", "calculation"}:
        return available_grading_method(question_type=question.question_type,
            config={"verified": True, "method": "numeric_final"},
            expected=question.correct_answer, options=question.options)
    return None


def build_worklist(db, *, source_root: Path, nodes_per_subject: int = 2, schema_revision: str = TARGET) -> dict:
    groups = defaultdict(list)
    nodes, policies = {}, {}
    source_cache = {}
    excluded = Counter()
    rows = db.execute(select(Question, KnowledgePoint)
        .join(KnowledgePoint, KnowledgePoint.id == Question.kp_id)
        .where(Question.is_active.is_(True), KnowledgePoint.is_active.is_(True),
            KnowledgePoint.is_assessable.is_(True))
        .order_by(KnowledgePoint.code, Question.id)).all()
    for question, node in rows:
        method = bounded_candidate_method(question)
        config = question.grading_config if isinstance(question.grading_config, dict) else {}
        provenance = config.get("provenance") or {}
        source = (provenance.get("source") or {}) if isinstance(provenance, dict) else {}
        subject = normalize_subject(source.get("subject")) if isinstance(source, dict) else None
        if question.question_provenance != "real_exam" or not method or not subject:
            excluded["not_real_exam_or_bounded_objective"] += 1
            continue
        if not complete_source_identity(source):
            excluded["incomplete_source_metadata"] += 1
            continue
        if normalize_subject(node.subject) != subject:
            excluded["source_and_node_subject_mismatch"] += 1
            continue
        eligibility = question_eligibility(question, node)
        if any(reason in eligibility.blocking_reasons for reason in (
            "question_content_incomplete", "choice_options_incomplete", "choice_answer_invalid",
            "answer_missing", "explanation_missing")) or re.search(r"待补|未识别|OCR|\ufffd", question.stem, re.I):
            excluded["incomplete_or_ambiguous_transcription"] += 1
            continue
        cache_key = json.dumps(source, ensure_ascii=False, sort_keys=True)
        if cache_key not in source_cache:
            source_cache[cache_key] = audit_source_availability(source, source_root)
        availability = source_cache[cache_key]
        nodes[node.code] = node
        policies[node.code] = db.get(KpMasteryPolicy, node.id)
        groups[(subject, node.code)].append({"question_id": str(question.id),
            "question_type": question.question_type, "question_origin": question.question_provenance,
            "stem": question.stem, "options": question.options, "current_answer": question.correct_answer,
            "answer_provenance": question.answer_provenance, "answer_reliability": question.answer_reliability,
            "answer_sha256": answer_version_sha256(question), "source": source,
            "source_availability": availability, "current_eligibility": eligibility.public_dict(),
            "supported_method_if_reviewed": method,
            "review_decision": "PENDING_HUMAN_REVIEW", "verification_type": None,
            "reviewed_by": None, "review_note": None, "reference_metadata": None})
    selected = []
    for subject in ("math2", "408"):
        candidates = [(code, values) for (key, code), values in groups.items() if key == subject]
        candidates.sort(key=lambda item: (
            -sum(v["source_availability"]["answer_source_available"] for v in item[1]),
            -sum(v["source_availability"]["question_source_available"] for v in item[1]),
            -sum(v["current_eligibility"]["practice_eligible"] for v in item[1]),
            -len(item[1]), item[0]))
        for code, values in candidates[:nodes_per_subject]:
            node, policy = nodes[code], policies[code]
            values.sort(key=lambda v: (-int(v["source_availability"]["answer_source_available"]),
                -int(v["source_availability"]["question_source_available"]),
                -int(v["current_eligibility"]["practice_eligible"]), v["source"]["year"],
                v["source"]["question_number"], v["question_id"]))
            selected.append({"code": code, "name": node.name, "subject": subject,
                "reference_only": node.is_reference_only, "bounded_candidate_count": len(values),
                "questions": values[:4], "policy_required_question_types": policy.required_question_types if policy else {},
                "policy_version": policy.policy_version if policy else 1,
                "policy_required_question_origins": dict(policy.required_question_origins or {}) if policy else {},
                "policy_note": policy.note if policy else None,
                "graduation_compatibility": "ONLINE_TYPES_DO_NOT_SATISFY_EXTERNAL_EXAM" if policy and
                    "external_exam" in (policy.required_question_types or {}) else "REQUIRES_VERIFIED_POOL_AND_EVIDENCE"})
    return {"format": "verified-slice-review-worklist-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "database_revision": schema_revision, "read_only": True, "model_calls": 0,
        "source_root": str(source_root), "node_count": len(selected),
        "subject_node_counts": dict(Counter(n["subject"] for n in selected)),
        "selection_status": "PROVISIONAL_REVIEW_CANDIDATES" if len(selected) == nodes_per_subject * 2 else "INSUFFICIENT_CANDIDATES",
        "source_status_counts_selected": dict(Counter(q["source_availability"]["status"]
            for n in selected for q in n["questions"])), "excluded_inventory_counts": dict(excluded),
        "nodes": selected, "verification_data_written": False,
        "limits": ["This worklist is intentionally not an executable verification manifest.",
            "A local question paper or AI draft is not an authoritative answer source.",
            "No source was downloaded and no answer was asserted correct.",
            "The suggested grading method is only a supported comparator, not an activated trusted grader.",
            "Content, source, mapping, answer and policy compatibility still require review."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--nodes-per-subject", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_root, output = args.source_root.resolve(), private_output(args.output)
    if not source_root.is_dir() or source_root.is_symlink():
        parser.error("The declared local source root must exist")
    url = local_database_url(get_settings())
    engine = create_db_engine(str(url))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            revision = db.scalar(text("SELECT version_num FROM public.alembic_version"))
            if revision != TARGET:
                raise ValueError("Activate the expected answer-trust schema first")
            report = build_worklist(db, source_root=source_root, nodes_per_subject=args.nodes_per_subject, schema_revision=revision)
            db.rollback()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["selection_status"], "node_count": report["node_count"],
            "source_status_counts": report["source_status_counts_selected"], "output": str(output)}, ensure_ascii=False))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
