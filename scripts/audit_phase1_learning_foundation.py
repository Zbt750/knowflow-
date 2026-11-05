"""Read-only Phase 1 audit for question trust, coverage, evidence, lessons and tasks.

Writes audit artifacts only. The configured PostgreSQL transaction is set READ
ONLY before querying. No model calls or business-row updates are performed.
Run: python scripts/audit_phase1_learning_foundation.py --output-dir tmp/phase1_20261006
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = Path(r"C:\Users\ZBT\Desktop\数学二与408逐题知识点索引_2000至今")
CANONICAL_QUESTION_PACK = Path("storage/question-intake/past-exam-import-20261005-v3-160318/question-pack.json")


def norm_subject(value: str | None) -> str:
    value = (value or "").strip()
    if value in {"408", "计算机408", "计算机学科专业基础"}:
        return "408"
    if value in {"数学二", "数学", "考研数学", "math2", "math"}:
        return "数学二"
    return value


def safe_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: safe_cell(row.get(key)) for key in columns})


def brace_imbalance(text: str) -> int:
    """Cheap signal only: ignores escaped braces and does not parse TeX."""
    balance = 0
    for index, char in enumerate(text):
        if char not in "{}":
            continue
        slashes = 0
        cursor = index - 1
        while cursor >= 0 and text[cursor] == "\\":
            slashes += 1
            cursor -= 1
        if slashes % 2:
            continue
        balance += 1 if char == "{" else -1
    return balance


def lesson_flags(text: str | None, node: Any, is_parent: bool) -> dict[str, Any]:
    text = text or ""
    headings = re.findall(r"(?m)^#{1,4}\s+(.+)$", text)
    heading_text = " ".join(headings)
    content = re.sub(r"(?m)^#{1,6}\s+.*$", "", text)
    concept = bool(re.search(r"概念|直观|定义|基本思想|知识点地图", heading_text + " " + content[:600]))
    conditions = bool(re.search(r"条件|适用范围|边界|前提|假设|性质", heading_text))
    method = bool(re.search(r"方法|步骤|判别|推导|原理|计算|证明|执行过程|机制", heading_text))
    # These are heading-level structure checks, not semantic/content verification.
    # Broad body-word matching made a single word like “因此” look like a worked solution.
    example = bool(re.search(r"例题|示例|例子|例\s*\d|例[：:]", heading_text))
    solution = bool(re.search(r"解答|解析|解题过程|逐步推导|参考解", heading_text))
    mistakes = bool(re.search(r"易错|误区|注意事项|常见错误|容易混淆", heading_text))
    summary = bool(re.search(r"小结|总结|本节回顾|记忆要点", heading_text))
    index_only = len(content.strip()) < 700 and bool(re.search(
        r"原卷|题号关联|查看考点来源|原题题干|不在系统内", text
    )) and not example and not concept
    title = headings[0] if headings else ""
    title_mismatch = bool(title and node.name not in title and title not in node.name)
    unbalanced = brace_imbalance(text)
    replacement_char = "\ufffd" in text
    if not text.strip():
        state = "NO_LESSON"
    elif index_only:
        state = "INDEX_ONLY"
    elif is_parent:
        state = "STRUCTURALLY_COMPLETE" if concept and (conditions or method) else "STRUCTURALLY_INCOMPLETE"
    else:
        state = "STRUCTURALLY_COMPLETE" if all((concept, conditions, method, example, solution, mistakes, summary)) else "STRUCTURALLY_INCOMPLETE"
    issues = []
    if not concept:
        issues.append("missing_concept_or_definition")
    if not is_parent:
        for label, flag in (("missing_conditions", conditions), ("missing_method", method),
                            ("missing_example", example), ("missing_solution", solution),
                            ("missing_mistake_analysis", mistakes), ("missing_summary", summary)):
            if not flag:
                issues.append(label)
    elif not (conditions or method):
        issues.append("missing_structure_or_learning_path")
    if index_only:
        issues.append("index_only")
    if title_mismatch:
        issues.append("possible_topic_mismatch")
    if unbalanced:
        issues.append("formula_brace_balance_signal")
    if replacement_char:
        issues.append("replacement_character")
    issues.append("content_review_required")
    return {
        "lesson_state": state, "char_count": len(text), "heading_count": len(headings),
        "empty_lesson": not bool(text.strip()), "very_short_signal_under_500_chars": len(text.strip()) < 500,
        "first_heading": title, "has_concept": concept, "has_conditions": conditions,
        "has_method": method, "has_example": example, "has_solution": solution,
        "has_mistake_analysis": mistakes, "has_summary": summary, "index_only": index_only,
        "possible_topic_mismatch": title_mismatch, "formula_brace_balance": unbalanced,
        "replacement_character": replacement_char, "example_review_required": example,
        "formula_review_required": bool(unbalanced or replacement_char),
        "exam_reference_only_signal": index_only,
        "content_review_required": True, "structural_issues": issues,
        "priority": ("P0" if state in {"NO_LESSON", "INDEX_ONLY"} else
                     "P1" if not concept or (not is_parent and not example) else
                     "P2" if state == "STRUCTURALLY_INCOMPLETE" else "P3_CONTENT_REVIEW"),
        "content_correctness": "NOT_AUTOMATICALLY_VERIFIED",
    }


def parse_frontmatter(md: str) -> dict[str, str]:
    return {key.strip(): value.strip().strip(chr(96))
            for key, value in re.findall(r"(?m)^-\s*([^：:]+)[：:]\s*(.*)$", md)}


def archive_candidates(archive: Path, nodes_by_name: dict[str, list[Any]]) -> list[dict[str, Any]]:
    question_root = archive / "逐题整理"
    rows = []
    if not question_root.is_dir():
        return rows
    for path in sorted(question_root.rglob("Q*.md")):
        match = re.fullmatch(r"Q(\d+)\.md", path.name, re.I)
        if not match:
            continue
        rel = path.relative_to(question_root)
        parts = rel.parts
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        md = path.read_text(encoding="utf-8")
        fields = parse_frontmatter(md)
        subject, year, qno = norm_subject(parts[0]), int(parts[1]), int(match.group(1))
        knowledge_label = fields.get("候选知识点", "")
        exact_nodes = nodes_by_name.get(knowledge_label, [])
        incomplete = any(term in fields.get("题面完整度", "") for term in (
            "不完整", "未逐字", "必须配合原卷", "草稿"
        ))
        stem_part = re.split(r"(?m)^##\s*题目\s*$", md, maxsplit=1)
        stem_text = stem_part[-1].split("\n## ", 1)[0].strip() if len(stem_part) > 1 else ""
        rows.append({
            "asset_id": f"{subject}:{year}:Q{qno:02d}", "asset_kind": "personal_question_draft",
            "relative_path": rel.as_posix(), "subject": subject, "year": year, "question_number": qno,
            "question_type_label": fields.get("题型", ""), "stem_present": bool(stem_text),
            "stem_chars": len(stem_text), "answer_present": bool(re.search(r"(?m)^##\s*参考答案", md)),
            "answer_review_state": "draft_unverified" if "未标 VERIFIED" in fields.get("状态", "") else "needs_human_review",
            "content_state": "incomplete_or_requires_original" if incomplete else "draft_requires_review",
            "source_state": "source_reference_present" if fields.get("题面来源") else "source_missing",
            "review_state": "needs_human_review", "candidate_kp_label": knowledge_label,
            "exact_name_node_match_count": len(exact_nodes), "exact_name_node_codes": [n.code for n in exact_nodes],
            "identity": (subject, year, qno), "mapping_status": "UNMATCHED",
            "mapping_question_ids": [], "mapping_reason": "",
        })
    return rows


def walk_question_records(value: Any):
    if isinstance(value, dict):
        if isinstance(value.get("stem"), str) and (
            "question_type" in value or "source_id" in value or "correct_answer" in value
        ):
            yield value
        for child in value.values():
            yield from walk_question_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_question_records(child)


def source_identity(source: dict[str, Any]) -> tuple[str, int | None, int | None]:
    subject = norm_subject(source.get("subject"))
    try:
        year = int(source.get("year")) if source.get("year") is not None else None
    except (TypeError, ValueError):
        year = None
    try:
        qno = int(source.get("question_number")) if source.get("question_number") is not None else None
    except (TypeError, ValueError):
        qno = None
    return subject, year, qno


def timestamp_key(value: Any) -> str | None:
    """Normalize aware timestamps to match immutable attempt receipts."""
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "tmp/phase1_20261006")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(ROOT))
    from sqlalchemy import select, text
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    from backend.db import create_db_engine, create_session_factory
    from backend.models.learning import (
        DailyPlan, ExamQuestionReference, KpMasteryPolicy, KpState, KnowledgePoint,
        LearningEvent, PracticeItem, Question, QuestionAttempt,
    )
    from backend.models.learning_task import LearningTask
    from backend.models.chat import ChatSession
    from backend.services.answer_grading import available_grading_method, available_practice_grading_method
    from backend.services.lesson_service import read_lesson
    from backend.services.question_pack import PackQuestion, fingerprint
    from backend.services.answer_submission_service import question_content_hash

    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    if (url.database or "").lower().endswith("_test") or (url.database or "").lower() == "test":
        raise RuntimeError("Refusing to audit a test database; use the configured development DB.")
    engine = create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            captured_at = db.scalar(text("SELECT transaction_timestamp()"))
            nodes = list(db.scalars(select(KnowledgePoint)))
            questions = list(db.scalars(select(Question)))
            references = list(db.scalars(select(ExamQuestionReference)))
            attempts = list(db.scalars(select(QuestionAttempt)))
            events = list(db.scalars(select(LearningEvent)))
            items = list(db.scalars(select(PracticeItem)))
            plans = list(db.scalars(select(DailyPlan)))
            states = list(db.scalars(select(KpState)))
            policies = list(db.scalars(select(KpMasteryPolicy)))
            tasks = list(db.scalars(select(LearningTask).order_by(LearningTask.created_at.desc()).limit(500)))
            sessions = {row.id: row for row in db.scalars(select(ChatSession))}
    finally:
        engine.dispose()

    active_nodes = [n for n in nodes if n.is_active]
    nodes_by_id = {n.id: n for n in nodes}
    children = defaultdict(list)
    nodes_by_name = defaultdict(list)
    for node in active_nodes:
        nodes_by_name[node.name].append(node)
        if node.parent_id:
            children[node.parent_id].append(node)
    archive_rows = archive_candidates(args.archive, nodes_by_name)
    candidate_count_by_code = Counter()
    candidate_label_count_by_code = Counter()
    candidate_label_codes = defaultdict(list)
    for row in archive_rows:
        for code in row["exact_name_node_codes"]:
            candidate_label_count_by_code[code] += 1
            candidate_label_codes[code].append(row["asset_id"])

    qpack_files = sorted((ROOT / "storage/question-intake").rglob("question-pack.json"))
    canonical_pack_path = ROOT / CANONICAL_QUESTION_PACK
    if not canonical_pack_path.is_file() and qpack_files:
        # Explicit deterministic fallback for a relocated/renamed intake archive.
        canonical_pack_path = qpack_files[-1]
    canonical_pack_rel = canonical_pack_path.relative_to(ROOT).as_posix() if canonical_pack_path.is_relative_to(ROOT) else str(canonical_pack_path)
    pack_rows, pack_asset_rows = [], []
    for pack_path in qpack_files:
        try:
            payload = json.loads(pack_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pack_id = payload.get("pack_id", "")
        questions_payload = payload.get("questions", [])
        pack_asset_rows.append({
            "asset_id": f"question_pack:{pack_id or pack_path.parent.name}",
            "asset_kind": "structured_question_pack", "relative_path": pack_path.relative_to(ROOT).as_posix(),
            "candidate_records": len(questions_payload) if isinstance(questions_payload, list) else 0,
            "source_version": payload.get("version", ""),
            "content_status_counts": dict(Counter(str(q.get("content_status", "reviewed_default"))
                for q in questions_payload if isinstance(q, dict))),
            "note": "版本快照可能重叠；不可跨文件相加为独立题量。",
        })
        is_canonical_pack = pack_path.resolve() == canonical_pack_path.resolve()
        for raw in questions_payload if isinstance(questions_payload, list) else []:
            if not isinstance(raw, dict):
                continue
            try:
                packed = PackQuestion.model_validate(raw)
                digest = fingerprint(packed)
            except Exception:
                digest = ""
            source = raw.get("source", {}) if isinstance(raw.get("source"), dict) else {}
            record = {
                "pack_id": pack_id, "source_id": raw.get("source_id", ""), "kp_code": raw.get("kp_code", ""),
                "identity": source_identity(source), "fingerprint": digest,
                "content_status": raw.get("content_status", "reviewed_default"),
                "answer_reviewed_by": raw.get("answer_reviewed_by", ""),
                "grading_method": raw.get("grading_method", ""), "stem_chars": len(raw.get("stem", "")),
            }
            pack_rows.append(record)
            if is_canonical_pack and record["kp_code"]:
                candidate_count_by_code[record["kp_code"]] += 1

    db_by_provenance_key = defaultdict(list)
    db_by_identity = defaultdict(list)
    attempts_by_qid = defaultdict(list)
    event_by_attempt = defaultdict(list)
    for attempt in attempts:
        if attempt.question_id:
            attempts_by_qid[attempt.question_id].append(attempt)
    for event in events:
        if event.event_type == "answer_submitted" and event.source_id:
            event_by_attempt[event.source_id].append(event)

    question_rows = []
    question_content_hashes = {}
    for q in questions:
        config = q.grading_config if isinstance(q.grading_config, dict) else {}
        provenance = config.get("provenance", {}) if isinstance(config.get("provenance"), dict) else {}
        source = provenance.get("source", {}) if isinstance(provenance.get("source"), dict) else {}
        key = provenance.get("key", "")
        if key:
            db_by_provenance_key[key].append(q)
        identity = source_identity(source)
        if identity[1] and identity[2]:
            db_by_identity[identity].append(q)
        node = nodes_by_id.get(q.kp_id)
        method = available_grading_method(question_type=q.question_type, config=config,
                                          expected=q.correct_answer, options=q.options)
        practice_method = available_practice_grading_method(question_type=q.question_type, config=config,
                                                             expected=q.correct_answer, options=q.options)
        answer_present = bool((q.correct_answer or "").strip())
        explanation_present = bool((q.explanation or "").strip())
        content_status = provenance.get("content_status", "legacy_or_missing")
        answer_reviewer = provenance.get("answer_reviewed_by", "")
        answer_review_declared = content_status == "reviewed" and bool(answer_reviewer)
        verified_config = config.get("verified") is True and bool(method)
        source_complete = bool(source.get("citation")) and bool(source.get("rights_basis")) and bool(source.get("reviewed_by"))
        official_attestation_complete = answer_review_declared and source_complete and bool(
            provenance.get("mapping_reviewed_by") or provenance.get("knowledge_mapping_reviewed_by")
        )
        stem = q.stem or ""
        figure_cue = bool(re.search(r"如图|见图|下图|图\s*\d|表\s*\d|如下表|图中", stem))
        figure_marker = bool(re.search(r"!\[[^\]]*\]\([^)]+\)|<img\b|\\includegraphics", stem, re.I))
        balance = brace_imbalance(stem + "\n" + (q.correct_answer or "") + "\n" + (q.explanation or ""))
        placeholders = bool(re.search(r"待补|待核对|OCR|占位|TODO|未识别|（图略）|\ufffd", stem, re.I))
        q_attempts = attempts_by_qid[q.id]
        strong_events = sum(e.evidence_level == "confirmed"
            for a in q_attempts for e in event_by_attempt.get(a.id, []))
        practice_eligible = bool(q.is_active and node and node.is_active and node.is_assessable and q.estimated_minutes > 0)
        evidence_eligible = bool(practice_eligible and verified_config)
        answer_state = "ANSWER_VERIFIED_BY_DECLARATION" if answer_review_declared else (
            "UNVERIFIED_TRANSCRIPTION" if content_status == "source_transcribed" else
            "ANSWER_PRESENT_UNVERIFIED" if answer_present else "ANSWER_MISSING")
        answer_source = provenance.get("answer_source") or provenance.get("answer_citation") or source.get("answer_source")
        mapping_status = "active_assessable_node" if node and node.is_active and node.is_assessable else (
            "inactive_or_missing_node" if not node or not node.is_active else "non_assessable_node")
        question_rows.append({
            "question_id": str(q.id), "subject": node.subject if node else "",
            "year": source.get("year", ""), "source_type": source.get("source_type", ""),
            "source_identity_key": key, "source_citation_present": bool(source.get("citation")),
            "source_rights_basis_present": bool(source.get("rights_basis")),
            "source_reviewed_by_present": bool(source.get("reviewed_by")),
            "source_question_number": source.get("question_number", ""), "subquestion": source.get("subquestion", ""),
            "question_type": q.question_type, "question_role": q.question_role,
            "stem_present": bool(stem.strip()), "stem_chars": len(stem),
            "prompt_completeness_signal": "REVIEW_REQUIRED" if placeholders or len(stem.strip()) < 10 else "NO_AUTOMATIC_RED_FLAG",
            "placeholder_or_ocr_signal": placeholders, "options_present": bool(q.options),
            "options_count": len(q.options or {}), "required_figure_cue": figure_cue,
            "embedded_figure_marker": figure_marker, "figure_risk": figure_cue and not figure_marker,
            "formula_brace_balance_signal": balance, "formula_review_required": balance != 0 or "\ufffd" in stem,
            "answer_present": answer_present, "answer_state": answer_state,
            "answer_source_present": bool(answer_source), "answer_reviewed_by_present": bool(answer_reviewer),
            "explanation_present": explanation_present, "explanation_chars": len(q.explanation or ""),
            "kp_id": str(q.kp_id), "kp_code": node.code if node else "", "kp_name": node.name if node else "",
            "kp_active": bool(node and node.is_active), "kp_assessable": bool(node and node.is_assessable),
            "kp_reference_only": bool(node and node.is_reference_only), "mapping_status": mapping_status,
            "grading_mode": q.grading_mode, "grading_config_verified_flag": config.get("verified"),
            "verified_grading_method": method or "", "practice_answer_comparison_method": practice_method or "",
            "active": q.is_active, "practice_eligible_current_code": practice_eligible,
            "evidence_eligible_current_code": evidence_eligible, "content_status": content_status,
            "attempt_count": len(q_attempts), "strong_confirmed_event_count": strong_events,
            "attempted": bool(q_attempts), "official_target_attestation_complete": official_attestation_complete,
            "provenance_hash_present": bool(provenance.get("sha256")), "source_identity": identity,
        })
        question_content_hashes[q.id] = question_content_hash(q)

    pack_by_identity = defaultdict(list)
    for packed in pack_rows:
        pack_by_identity[packed["identity"]].append(packed)
    mapping_rows = []
    for candidate in archive_rows:
        identity = candidate["identity"]
        exact_ids, conflict_ids, found_ids = [], [], []
        for packed in pack_by_identity.get(identity, []):
            key = f'{packed["pack_id"]}:{packed["source_id"]}'
            for match in db_by_provenance_key.get(key, []):
                found_ids.append(str(match.id))
                provenance = (match.grading_config or {}).get("provenance", {})
                (exact_ids if packed["fingerprint"] and provenance.get("sha256") == packed["fingerprint"]
                 else conflict_ids).append(str(match.id))
        if exact_ids:
            status, reason = "EXACT", "stable import key and stored content fingerprint match"
            found_ids = exact_ids
        elif conflict_ids:
            status, reason = "CONFLICT", "stable import key exists but content fingerprint differs"
            found_ids = conflict_ids
        else:
            identity_matches = db_by_identity.get(identity, [])
            found_ids.extend(str(q.id) for q in identity_matches)
            found_ids = list(dict.fromkeys(found_ids))
            stem_hashes = {hashlib.sha256((q.stem or "").encode("utf-8")).hexdigest() for q in identity_matches}
            if len(stem_hashes) > 1:
                status, reason = "CONFLICT", "same exam identity maps to records with different stems"
            elif identity_matches:
                status, reason = "POSSIBLE", "bibliographic identity matches; local draft text/hash not compared"
            elif pack_by_identity.get(identity):
                status, reason = "UNMATCHED", "structured candidate exists but no matching DB import key/identity"
            else:
                status, reason = "UNMATCHED", "no matching database exam identity"
        candidate["mapping_status"], candidate["mapping_question_ids"], candidate["mapping_reason"] = status, found_ids, reason
        mapping_rows.append({
            "candidate_id": candidate["asset_id"], "candidate_path": candidate["relative_path"],
            "subject": candidate["subject"], "year": candidate["year"], "question_number": candidate["question_number"],
            "candidate_kp_label": candidate["candidate_kp_label"], "exact_name_node_codes": candidate["exact_name_node_codes"],
            "candidate_status": candidate["review_state"], "mapping_status": status,
            "matched_question_ids": found_ids, "match_count": len(found_ids), "reason": reason,
        })

    artifact_rows = list(pack_asset_rows)
    for path in sorted((ROOT / "storage/question-intake").rglob("*.json")):
        if path.name == "question-pack.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records = list(walk_question_records(payload))
        name = path.name.lower()
        if records or any(term in name for term in (
            "manifest", "intake-review", "human-decision", "derivation-review",
            "source-finding", "answer", "candidate", "preview", "review",
        )):
            identities = []
            for item in records:
                src = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
                identities.append(source_identity(src))
            artifact_rows.append({
                "asset_id": f"artifact:{path.relative_to(ROOT).as_posix()}",
                "asset_kind": "structured_candidate_or_review_artifact",
                "relative_path": path.relative_to(ROOT).as_posix(), "candidate_records": len(records),
                "years": sorted({i[1] for i in identities if i[1]}),
                "source_version": payload.get("version", "") if isinstance(payload, dict) else "",
                "note": "版本/复核快照可能重叠；不是独立题量。",
            })
    asset_inventory_rows = []
    for label, folder in (("project_question_intake", ROOT / "storage/question-intake"),
                          ("personal_exam_archive", args.archive)):
        by_suffix = defaultdict(list)
        if folder.is_dir():
            for path in folder.rglob("*"):
                if path.is_file():
                    by_suffix[path.suffix.lower() or "[no_extension]"].append(path)
        for suffix, paths in sorted(by_suffix.items()):
            asset_inventory_rows.append({
                "asset_scope": label, "file_extension": suffix, "file_count": len(paths),
                "total_bytes": sum(path.stat().st_size for path in paths),
                "content_or_license_verified": False,
                "note": "只做文件类型、数量和大小盘点；不读取、不宣称题目内容或版权状态已核验。",
            })
    annual_root = ROOT / "storage/question-intake/annual-pages-20261002"
    if annual_root.is_dir():
        manifest_path = annual_root / "manifest.json"
        annual_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        file_records = 0
        for path in annual_root.rglob("*.json"):
            if path.name == "manifest.json":
                continue
            try:
                file_records += len(list(walk_question_records(json.loads(path.read_text(encoding="utf-8")))))
            except (OSError, json.JSONDecodeError):
                continue
        artifact_rows.append({
            "asset_id": "annual_source_page_intake_manifest", "asset_kind": "page_transcription_or_ocr_manifest",
            "relative_path": manifest_path.relative_to(ROOT).as_posix() if manifest_path.exists() else "",
            "candidate_records": file_records, "source_version": annual_manifest.get("version", ""),
            "source_pages": annual_manifest.get("pages", ""),
            "online_questions_imported": annual_manifest.get("online_questions_imported", ""),
            "note": "逐页OCR/人工页资产不是正式在线Question；导入数使用manifest字段。",
        })
    if args.archive.is_dir():
        artifact_rows.append({
            "asset_id": "personal_archive_pdfs", "asset_kind": "personal_original_exam_source_files",
            "relative_path": "个人复习原卷/**/*.pdf",
            "candidate_records": len(list(args.archive.rglob("*.pdf"))),
            "source_version": "local_personal_archive",
            "note": "只统计文件数量；不认定许可或题面正确。",
        })

    questions_by_node = defaultdict(list)
    refs_by_node = defaultdict(list)
    attempts_by_node = defaultdict(list)
    for q in questions:
        if q.is_active:
            questions_by_node[q.kp_id].append(q)
    for ref in references:
        refs_by_node[ref.knowledge_point_id].append(ref)
    for attempt in attempts:
        attempts_by_node[attempt.kp_id].append(attempt)
    policies_by_node = {p.kp_id: p for p in policies}
    states_by_node = {s.kp_id: s for s in states}
    questions_by_id_text = {str(q.id): q for q in questions}
    attempts_by_receipt = defaultdict(list)
    for attempt in attempts:
        if attempt.question_id:
            attempts_by_receipt[(str(attempt.question_id), timestamp_key(attempt.submitted_at))].append(attempt)
    evidence_integrity_rows = []
    evidence_status_counts = Counter()
    stale_mastered_state_ids = set()
    independent_categories = {"first_independent_correct", "independent_retest_correct", "repeat_correct"}
    for state in states:
        entries = state.evidence_window if isinstance(state.evidence_window, list) else []
        if state.assessment_basis != "objective_v1":
            if entries or state.manual_credit_count:
                evidence_integrity_rows.append({
                    "kp_code": nodes_by_id[state.kp_id].code if state.kp_id in nodes_by_id else "",
                    "state_basis": state.assessment_basis, "state_value": state.state,
                    "question_id": "", "occurred_at": "", "stored_level": "",
                    "receipt_count": 0, "current_grader_verified": False,
                    "receipt_content_hash_matches": False,
                    "integrity_status": "LEGACY_SUBJECTIVE_OR_PRE_OBJECTIVE_STATE",
                    "integrity_reasons": ["state predates objective_v1; preserve as historical subjective basis, not current objective receipt"],
                    "affects_current_mastered_state": state.state == "mastered",
                    "human_review_required": False,
                })
                evidence_status_counts["LEGACY_SUBJECTIVE_OR_PRE_OBJECTIVE_STATE"] += 1
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                entry = {}
            qid = str(entry.get("question_id") or "")
            occurred = entry.get("occurred_at")
            matched_receipts = attempts_by_receipt.get((qid, timestamp_key(occurred)), [])
            question = questions_by_id_text.get(qid)
            reasons = []
            if entry.get("source") != "objective_final" or entry.get("level") != "confirmed":
                reasons.append("window_entry_not_objective_confirmed")
            current_method = ""
            content_hash_matches = False
            if question is None:
                reasons.append("question_missing")
            else:
                node = nodes_by_id.get(question.kp_id)
                if not question.is_active:
                    reasons.append("question_inactive")
                if node is None or not node.is_active or not node.is_assessable:
                    reasons.append("knowledge_node_not_currently_assessable")
                config = question.grading_config if isinstance(question.grading_config, dict) else {}
                current_method = available_grading_method(question_type=question.question_type,
                    config=config, expected=question.correct_answer, options=question.options) or ""
                if not current_method or config.get("verified") is not True:
                    reasons.append("current_grader_not_verified")
                if matched_receipts:
                    expected_hash = question_content_hashes.get(question.id)
                    content_hash_matches = any((a.grading_evidence or {}).get("question_content_sha256") == expected_hash
                                               for a in matched_receipts)
                    if not content_hash_matches:
                        reasons.append("question_content_changed_since_attempt")
                else:
                    reasons.append("no_matching_attempt_receipt")
                if entry.get("question_type") != question.question_type:
                    reasons.append("stored_question_type_mismatch")
                if bool(entry.get("is_variant")) != bool(question.is_variant):
                    reasons.append("stored_variant_flag_mismatch")
                stored_tags = tuple(sorted(str(tag) for tag in (entry.get("skill_tags") or [])))
                current_tags = tuple(sorted(str(tag) for tag in (question.skill_tags or [])))
                if stored_tags != current_tags:
                    reasons.append("stored_skill_tags_mismatch")
            if matched_receipts:
                eligible = False
                for attempt in matched_receipts:
                    receipt = attempt.grading_evidence or {}
                    if (attempt.objective_result == "right" and attempt.self_grade is None
                            and receipt.get("sequence_version") == "attempt-sequence-v1"
                            and receipt.get("assessment_basis") == "objective_v1"
                            and receipt.get("sequence_category") in independent_categories
                            and receipt.get("assisted") is False
                            and receipt.get("confidence") not in {"guess", "no_idea"}
                            and question is not None
                            and receipt.get("question_content_sha256") == question_content_hashes.get(question.id)):
                        eligible = True
                if not eligible:
                    reasons.append("receipt_not_independent_confirming_attempt")
            valid = not reasons
            status = "CURRENT_OBJECTIVE_RECEIPT_VALID" if valid else "STALE_OR_INELIGIBLE_OBJECTIVE_RECEIPT"
            evidence_status_counts[status] += 1
            if not valid and state.state == "mastered":
                stale_mastered_state_ids.add(str(state.kp_id))
            evidence_integrity_rows.append({
                "kp_code": nodes_by_id[state.kp_id].code if state.kp_id in nodes_by_id else "",
                "state_basis": state.assessment_basis, "state_value": state.state,
                "question_id": qid, "occurred_at": occurred or "", "stored_level": entry.get("level", ""),
                "receipt_count": len(matched_receipts), "current_grader_verified": bool(current_method),
                "receipt_content_hash_matches": content_hash_matches,
                "integrity_status": status, "integrity_reasons": reasons,
                "affects_current_mastered_state": bool(not valid and state.state == "mastered"),
                "human_review_required": bool(not valid and state.state == "mastered"),
            })
    items_by_plan = defaultdict(list)
    for item in items:
        items_by_plan[item.plan_id].append(item)
    local_today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    today_plan_rows = []
    for plan in sorted(plans, key=lambda row: row.study_date):
        plan_items = items_by_plan[plan.id]
        today_plan_rows.append({
            "plan_id": str(plan.id), "study_date": plan.study_date, "is_current_shanghai_date": plan.study_date == local_today,
            "status": plan.status, "item_count": len(plan_items),
            "online_question_count": sum(item.question_id is not None for item in plan_items),
            "reference_only_task_count": sum(item.exam_reference_id is not None for item in plan_items),
            "completed_count": sum(item.completed_at is not None for item in plan_items),
            "incomplete_count": sum(item.completed_at is None for item in plan_items),
            "answer_revealed_count": sum(item.answer_revealed_at is not None for item in plan_items),
            "note": "只读快照；题目正文和原始答案不导出。",
        })
    attempt_result_counts = Counter(a.objective_result for a in attempts)
    attempt_basis_counts = Counter((a.grading_evidence or {}).get("assessment_basis", "legacy_or_missing")
                                   for a in attempts)
    attempt_sequence_counts = Counter((a.grading_evidence or {}).get("sequence_category", "legacy_or_missing")
                                      for a in attempts)
    state_counts = Counter((state.assessment_basis, state.state) for state in states)
    coverage_rows, provisional_rows, lesson_rows, gap_plan_rows, human_rows = [], [], [], [], []
    for node in sorted(active_nodes, key=lambda n: n.code):
        qs, refs = questions_by_node[node.id], refs_by_node[node.id]
        distinct_refs = {(norm_subject(r.subject), r.year, r.question_number) for r in refs}
        trusted = [q for q in qs if (q.grading_config or {}).get("provenance", {}).get("content_status") == "reviewed"
                   and (q.grading_config or {}).get("provenance", {}).get("answer_reviewed_by")]
        verified = [q for q in qs if available_grading_method(question_type=q.question_type,
                     config=q.grading_config or {}, expected=q.correct_answer, options=q.options)]
        practice_comparable = [q for q in qs if available_practice_grading_method(question_type=q.question_type,
                                  config=q.grading_config or {}, expected=q.correct_answer, options=q.options)]
        node_attempts = attempts_by_node[node.id]
        attempted_ids = {a.question_id for a in node_attempts if a.question_id}
        unused = {q.id for q in qs} - attempted_ids
        type_dist = Counter(q.question_type for q in qs)
        role_dist = Counter(q.question_role for q in qs)
        year_dist = Counter(str((q.grading_config or {}).get("provenance", {}).get("source", {}).get("year", "unknown")) for q in qs)
        lesson = lesson_flags(read_lesson(node.code), node, bool(children[node.id]))
        lesson_rows.append({
            "node_id": str(node.id), "node_code": node.code, "node_name": node.name, "subject": node.subject,
            "parent_code": nodes_by_id[node.parent_id].code if node.parent_id in nodes_by_id else "",
            "is_parent": bool(children[node.id]), "assessable": node.is_assessable, **lesson,
        })
        policy, state = policies_by_node.get(node.id), states_by_node.get(node.id)
        required_types = dict(policy.required_question_types or {}) if policy else {}
        available_types = dict(type_dist)
        missing_types = {name: required - available_types.get(name, 0)
                         for name, required in required_types.items()
                         if available_types.get(name, 0) < required}
        required_tags = set(policy.required_skill_tags or []) if policy else set()
        available_tags = {tag for q in qs for tag in (q.skill_tags or [])}
        missing_tags = sorted(required_tags - available_tags)
        variant_count = sum(bool(q.is_variant) for q in qs)
        minimum_real_questions = policy.min_real_questions if policy else 3
        required_variants = policy.required_variant_count if policy else 1
        gap_items = []
        if not qs:
            gap_items.append("NO_ACTIVE_ONLINE_QUESTION")
            if refs:
                gap_items.append("EXAM_REFERENCES_HAVE_NO_EMBEDDED_STEM")
            if candidate_count_by_code[node.code] or candidate_label_count_by_code[node.code]:
                gap_items.append("LOCAL_CANDIDATE_REQUIRES_MAPPING_OR_REVIEW")
        else:
            if len(qs) < minimum_real_questions:
                gap_items.append(f"QUESTION_COUNT_BELOW_POLICY_BASELINE:{len(qs)}/{minimum_real_questions}")
            if missing_types:
                gap_items.append("POLICY_REQUIRED_TYPE_SHORTAGE:" + json.dumps(missing_types, ensure_ascii=False, sort_keys=True))
            if variant_count < required_variants:
                gap_items.append(f"VARIANT_SHORTAGE:{variant_count}/{required_variants}")
            if missing_tags:
                gap_items.append("POLICY_REQUIRED_SKILL_TAGS_MISSING:" + "|".join(missing_tags))
            if not verified:
                gap_items.append("NO_CURRENT_VERIFIED_GRADER_FOR_OBJECTIVE_EVIDENCE")
            if len(type_dist) == 1:
                gap_items.append("QUESTION_TYPE_CONCENTRATION")
        gap_plan_rows.append({
            "node_code": node.code, "node_name": node.name, "subject": node.subject,
            "parent_code": nodes_by_id[node.parent_id].code if node.parent_id in nodes_by_id else "",
            "assessable_current_flag": node.is_assessable, "reference_only_flag": node.is_reference_only,
            "active_question_count": len(qs), "exam_reference_count": len(distinct_refs),
            "canonical_pack_proposed_candidate_count": candidate_count_by_code[node.code],
            "exact_label_candidate_count": candidate_label_count_by_code[node.code],
            "question_type_distribution": dict(type_dist), "required_question_type_quotas": required_types,
            "missing_policy_question_types": missing_types,
            "variant_count": variant_count, "required_variant_count": required_variants,
            "required_skill_tags": sorted(required_tags), "currently_available_question_skill_tags": sorted(available_tags),
            "missing_policy_skill_tags": missing_tags,
            "verified_grader_count": len(verified), "practice_answer_comparable_count": len(practice_comparable),
            "prior_attempt_count": len(node_attempts), "unused_active_question_count": len(unused),
            "lesson_state": lesson["lesson_state"], "primary_gap_signals": gap_items or ["NO_STRUCTURAL_POOL_GAP_DETECTED"],
            "transfer_retest_proof": "UNKNOWN_HUMAN_REVIEW_REQUIRED",
            "independent_assessability": "HUMAN_REVIEW_REQUIRED" if node.is_reference_only or not node.is_assessable else "CANDIDATE_ONLY_NOT_APPROVED",
            "note": "Reference rows have no stem; raw counts do not establish pedagogic coverage, source trust, or mapping correctness.",
        })
        candidate_class = (
            "TEACHING_ONLY_CANDIDATE" if not node.is_assessable else
            "HUMAN_REVIEW_REQUIRED" if node.is_reference_only else
            "ASSESSABLE_INDEPENDENT_CANDIDATE" if qs else "HUMAN_REVIEW_REQUIRED"
        )
        class_reason = (
            "当前非考核节点标记；只作为现行树语义的候选分类" if not node.is_assessable else
            "参考索引叶子与在线题并存；独立毕业边界需人工判定" if node.is_reference_only else
            "当前节点标记可考核且有在线题；质量与语义边界尚未认证" if qs else
            "节点无在线题；不能仅据此认定为教学型"
        )
        coverage_rows.append({
            "node_id": str(node.id), "node_code": node.code, "node_name": node.name, "subject": node.subject,
            "parent_code": nodes_by_id[node.parent_id].code if node.parent_id in nodes_by_id else "",
            "is_leaf": not bool(children[node.id]), "active": node.is_active, "assessable": node.is_assessable,
            "reference_only": node.is_reference_only, "candidate_classification": candidate_class,
            "classification_reason": class_reason, "policy_present": bool(policy),
            "policy_min_questions": policy.min_real_questions if policy else "",
            "policy_required_types": dict(policy.required_question_types or {}) if policy else {},
            "active_question_count": len(qs), "answer_review_declared_count": len(trusted),
            "practice_answer_comparable_count": len(practice_comparable), "evidence_eligible_grader_count": len(verified),
            "official_target_fully_attested_count": sum(
                1 for q in qs if next((r["official_target_attestation_complete"] for r in question_rows
                                      if r["question_id"] == str(q.id)), False)),
            "prior_attempt_count": len(node_attempts), "distinct_attempted_question_count": len(attempted_ids),
            "unused_active_question_count": len(unused), "exam_reference_binding_count": len(refs),
            "distinct_exam_reference_count": len(distinct_refs), "reference_year_distribution": sorted({r.year for r in refs}),
            "local_candidate_proposed_code_count": candidate_count_by_code[node.code],
            "local_candidate_exact_name_label_count": candidate_label_count_by_code[node.code],
            "candidate_label_asset_ids": candidate_label_codes[node.code],
            "question_type_distribution": dict(type_dist), "question_role_distribution": dict(role_dist),
            "question_source_year_distribution": dict(year_dist),
            "reference_only_no_online_question": bool(node.is_reference_only and not qs and refs),
            "lesson_state": lesson["lesson_state"], "lesson_issues": lesson["structural_issues"],
            "state_present": bool(state), "state_assessment_basis": state.assessment_basis if state else "",
            "state_value": state.state if state else "",
        })
        if not qs:
            risk, basis = "P0", "no active online Question; references/candidates are separately reported and are not usable stems"
        elif not verified:
            risk, basis = "P1", "active Questions exist but no configured verified grader yields objective evidence"
        elif len(qs) < 3 or len(type_dist) == 1:
            risk, basis = "P2", "small and/or single-type pool; evidence opportunities may be concentrated"
        else:
            risk, basis = "P3", "several rows/types; quality, mapping and graduation sufficiency remain unproven"
        provisional_rows.append({
            "node_id": str(node.id), "node_code": node.code, "node_name": node.name, "subject": node.subject,
            "classification": risk, "classification_basis": basis,
            "official_content_status": "ATTESTED_QUESTION_PRESENT" if any(
                r["official_target_attestation_complete"] for r in question_rows
                if r["kp_code"] == node.code and r["active"]
            ) else "NO_FULLY_ATTESTED_ACTIVE_QUESTION",
            "official_attested_active_question_count": sum(
                1 for r in question_rows if r["kp_code"] == node.code and r["active"]
                and r["official_target_attestation_complete"]
            ),
            "unverified_active_practice_count": max(0, len(qs) - sum(
                1 for r in question_rows if r["kp_code"] == node.code and r["active"]
                and r["official_target_attestation_complete"]
            )),
            "uncertainty": "Counts do not prove content correctness, mapping correctness, or capability coverage.",
            "policy_dependency": "Actual node policy may be stricter; P0-P3 is audit-only, never graduation state.",
            "human_review_required": True,
        })
        if node.is_assessable and (not qs or not verified or node.is_reference_only or candidate_label_count_by_code[node.code] or lesson["lesson_state"] != "STRUCTURALLY_COMPLETE"):
            human_rows.append({
                "review_type": "knowledge_node", "record_id": node.code, "subject": node.subject,
                "year": "", "question_number": "", "issue": "NODE_ASSESSABILITY_MAPPING_POOL_OR_LESSON",
                "evidence": f"class={candidate_class}; active_q={len(qs)}; evidence_graders={len(verified)}; refs={len(distinct_refs)}; candidate_label={candidate_label_count_by_code[node.code]}; lesson={lesson['lesson_state']}",
                "required_decision": "人工确认是否独立考核、映射是否正确、题型/题量是否充分；不因空题自动降级",
            })

    integrity_rows = []
    for row in question_rows:
        risks = []
        if not row["stem_present"] or row["stem_chars"] < 10 or row["placeholder_or_ocr_signal"]:
            risks.append(("CONTENT_RISK", "题面空/极短或出现未完成、OCR、占位信号"))
        if not row["answer_present"]:
            risks.append(("ANSWER_UNVERIFIED", "标准答案缺失"))
        elif row["answer_state"] != "ANSWER_VERIFIED_BY_DECLARATION":
            risks.append(("ANSWER_UNVERIFIED", "有答案文本但没有可追溯的人审答案状态"))
        if not row["source_citation_present"] or not row["source_type"] or not row["source_identity_key"]:
            risks.append(("SOURCE_RISK", "来源身份/引文/稳定来源键缺失"))
        if row["required_figure_cue"] and not row["embedded_figure_marker"]:
            risks.append(("FIGURE_RISK", "题干提示依赖图表，但数据库正文未发现图像标记；须核对原题"))
        if row["formula_review_required"]:
            risks.append(("FORMULA_RISK", "发现替换字符或花括号平衡异常信号"))
        if row["mapping_status"] != "active_assessable_node":
            risks.append(("MAPPING_RISK", row["mapping_status"]))
        # KnowledgePoint.is_reference_only is explicitly documented as a leaf
        # holding only exam pointers (no embedded stem). A real Question linked
        # to such a node may be valid content, but it conflicts with that stored
        # node contract and must not be silently treated as an ordinary mapping.
        if row.get("kp_reference_only"):
            risks.append(("MAPPING_RISK", "Question is attached to a node declared reference-only; verify node semantics and mapping"))
        if row["grading_mode"] in {"auto", "automatic", "machine"} and not row["verified_grading_method"]:
            risks.append(("GRADING_RISK", "无已核验自动判题方法；不等于不能作为纸笔正式题"))
        if row["content_status"] == "source_transcribed":
            risks.append(("EVIDENCE_RISK", "转录题可练习对照答案，但verified=false时不能产生强客观Evidence"))
        elif row["evidence_eligible_current_code"] and not row["official_target_attestation_complete"]:
            risks.append(("EVIDENCE_RISK", "verified配置可产生强Evidence，但独立答案/来源/映射核验信息不全"))
        if not risks:
            risks.append(("UNKNOWN", "无明显结构告警；内容正确性/来源/映射仍须人工复核"))
        for category, reason in risks:
            integrity_rows.append({
                "question_id": row["question_id"], "subject": row["subject"], "year": row["year"],
                "question_number": row["source_question_number"], "kp_code": row["kp_code"],
                "risk_category": category, "risk": reason, "machine_confidence": "STRUCTURAL_SIGNAL_ONLY",
                "human_review_required": category != "GRADING_RISK",
            })
        human_rows.append({
            "review_type": "database_question", "record_id": row["question_id"],
            "subject": row["subject"], "year": row["year"], "question_number": row["source_question_number"],
            "issue": "|".join(category for category, _ in risks),
            "evidence": f"answer={row['answer_state']}; content={row['content_status']}; grader={row['verified_grading_method'] or 'none'}; mapping={row['mapping_status']}; reference_only={row['kp_reference_only']}; figure={row['figure_risk']}; formula={row['formula_review_required']}",
            "required_decision": "核对题面、答案、来源、图表和知识映射；禁止仅凭结构扫描标为VERIFIED",
        })

    for candidate in archive_rows:
        human_rows.append({
            "review_type": "local_candidate", "record_id": candidate["asset_id"],
            "subject": candidate["subject"], "year": candidate["year"], "question_number": candidate["question_number"],
            "issue": candidate["content_state"] + "|" + candidate["answer_review_state"] + "|" + candidate["mapping_status"],
            "evidence": f"candidate_kp={candidate['candidate_kp_label']}; exact_name_match={candidate['exact_name_node_match_count']}; db_matches={len(candidate['mapping_question_ids'])}",
            "required_decision": "核验原题、答案来源和项目节点；个人稿/第三方解析不等于可信题",
        })
    for row in lesson_rows:
        human_rows.append({
            "review_type": "lesson", "record_id": row["node_code"], "subject": row["subject"],
            "year": "", "question_number": "", "issue": "|".join(row["structural_issues"]),
            "evidence": f"state={row['lesson_state']}; chars={row['char_count']}; headings={row['heading_count']}",
            "required_decision": "人工核对概念、条件、例题推导与结论；结构扫描不认证知识正确",
        })

    task_trace_rows = []
    task_tool_counts, task_error_counts = Counter(), Counter()
    for task in tasks:
        trace = task.trace if isinstance(task.trace, list) else []
        calls = (task.metrics or {}).get("calls", []) if isinstance(task.metrics, dict) else []
        goal = task.goal or ""
        context = task.context if isinstance(task.context, dict) else {}
        previous_goals = [str(context.get(k) or "") for k in ("original_goal", "previous_goal")]
        broad_inventory = bool(re.search(r"(哪些|那些|什么).{0,12}(章节|节点|知识点).{0,12}(有|能找到|可用).{0,8}(题|练习)|在线练习题.{0,8}(哪些|那些|什么)|除了.{0,16}以外.{0,16}(哪些|那些|什么).{0,8}(节点|章节)", goal))
        current_line = goal.rsplit("\n", 1)[-1]
        current_line_broad_inventory = bool(re.search(r"(哪些|那些|什么).{0,12}(章节|节点|知识点).{0,12}(有|能找到|可用).{0,8}(题|练习)|在线练习题.{0,8}(哪些|那些|什么)|除了.{0,16}以外.{0,16}(哪些|那些|什么).{0,8}(节点|章节)", current_line))
        current_has_known_node = any(n.name and n.name in goal for n in active_nodes)
        current_line_has_known_node = any(n.name and n.name in current_line for n in active_nodes)
        current_line_positive_node = False
        current_line_excluded_node = False
        for node in active_nodes:
            if not node.name:
                continue
            for match in re.finditer(re.escape(node.name), current_line):
                prefix = current_line[max(0, match.start() - 12):match.start()]
                if re.search(r"(?:除了|除去|不含|不包括|排除|避开)\s*$", prefix):
                    current_line_excluded_node = True
                else:
                    current_line_positive_node = True
        previous_has_known_node = any(n.name and any(n.name in g for g in previous_goals) for n in active_nodes)
        tags = []
        if "补两道" in goal or "补两题" in goal:
            tags.append("A_add_two_questions")
        if "洛必达" in goal:
            tags.append("B_lhopital_scope")
        if broad_inventory or "哪些章节有题" in goal or "哪些节点有题" in goal or ("其他" in goal and "有题" in goal):
            tags.append("C_global_question_inventory")
        if "安排未完成" in task.message or task.status == "failed":
            tags.append("D_failed_task")
        sequence, summaries = [], []
        for entry in trace:
            tool, status = str(entry.get("tool", "unknown")), str(entry.get("status", "unknown"))
            result = entry.get("result", {}) if isinstance(entry.get("result"), dict) else {}
            task_tool_counts[(tool, status)] += 1
            if status == "error" or result.get("error") or result.get("valid") is False:
                task_error_counts[str(result.get("error") or "|".join(result.get("errors", [])) or status)] += 1
            sequence.append(f"{tool}:{status}")
            if tool == "search_knowledge":
                summaries.append(f"search_nodes={len(result.get('nodes', []))};explicit_scope={result.get('explicit_scope_enforced')}")
            elif tool == "find_questions":
                qs = result.get("questions", [])
                summaries.append(f"find_questions={len(qs)};all_in_today={bool(qs) and all(q.get('in_today_plan') for q in qs)};refs={sum((result.get('exam_reference_counts') or {}).values())}")
            elif tool == "validate_plan":
                summaries.append(f"validate={result.get('valid')};errors={result.get('errors', [])}")
            elif result.get("error"):
                summaries.append(f"{tool}_error={result.get('error')}")
        session = sessions.get(task.session_id) if task.session_id else None
        task_trace_rows.append({
            "task_id": str(task.id), "created_at": task.created_at.isoformat() if task.created_at else "",
            "case_tags": tags, "status": task.status, "error_code": task.error_code or "",
            "prompt_version": (task.metrics or {}).get("prompt_version", ""),
            "session_id_present": bool(task.session_id), "session_mode": session.mode if session else "",
            "tool_sequence": sequence, "result_summary": summaries, "tool_calls": len(trace), "model_calls": len(calls),
            "model_call_statuses": [c.get("status") for c in calls], "rounds": (task.metrics or {}).get("rounds", ""),
            "duration_ms": (task.metrics or {}).get("duration_ms", ""),
            "conclusion_error_count": len((task.metrics or {}).get("conclusion_errors", [])),
            "current_goal_broad_inventory_request": broad_inventory,
            "current_goal_last_line_broad_inventory_request": current_line_broad_inventory,
            "current_goal_has_known_node_name": current_has_known_node,
            "current_goal_last_line_has_known_node_name": current_line_has_known_node,
            "current_goal_last_line_has_positive_scope_node": current_line_positive_node,
            "current_goal_last_line_mentions_node_as_exclusion": current_line_excluded_node,
            "context_original_goal_present": bool(context.get("original_goal")),
            "context_previous_goal_present": bool(context.get("previous_goal")),
            "context_has_known_node_name": previous_has_known_node,
            "broad_query_plus_prior_specific_node_scope_risk": bool(current_line_broad_inventory and ((previous_has_known_node or current_has_known_node) and not current_line_positive_node or current_line_excluded_node)),
            "stored_tool_arguments": False,
            "limitations": "persisted trace omits tool arguments; exact search string/model intent cannot be reconstructed",
        })
    task_trace_rows = [r for r in task_trace_rows if r["case_tags"] or r["error_code"] or r["status"] in {"failed", "needs_info"}]

    # Combine all required CSV inventories. CSVs deliberately contain no stem, key, or answer text.
    write_csv(output / "question_inventory.csv", question_rows)
    write_csv(output / "candidate_inventory.csv", archive_rows + artifact_rows)
    write_csv(output / "local_asset_inventory.csv", asset_inventory_rows)
    write_csv(output / "candidate_question_mapping.csv", mapping_rows)
    write_csv(output / "knowledge_question_coverage.csv", coverage_rows)
    write_csv(output / "question_integrity_risks.csv", integrity_rows)
    write_csv(output / "evidence_integrity.csv", evidence_integrity_rows)
    write_csv(output / "provisional_coverage_risk.csv", provisional_rows)
    write_csv(output / "lesson_audit.csv", lesson_rows)
    write_csv(output / "question_gap_plan.csv", gap_plan_rows)
    write_csv(output / "human_review_required.csv", human_rows)
    write_csv(output / "agent_task_trace.csv", task_trace_rows)
    write_csv(output / "today_plan_inventory.csv", today_plan_rows)

    question_counts = Counter()
    for row in question_rows:
        question_counts["active" if row["active"] else "inactive"] += 1
        question_counts["practice_eligible_current_code" if row["practice_eligible_current_code"] else "not_practice_eligible_current_code"] += 1
        question_counts["answer_review_declared" if row["answer_state"] == "ANSWER_VERIFIED_BY_DECLARATION" else "answer_not_reviewed_or_unverified"] += 1
        question_counts["verified_grader" if row["verified_grading_method"] else "no_verified_grader"] += 1
        question_counts["practice_comparable" if row["practice_answer_comparison_method"] else "no_supported_answer_comparator"] += 1
        question_counts["official_target_attested" if row["official_target_attestation_complete"] else "official_target_not_fully_attested"] += 1
        if row["active"]:
            question_counts["active_answer_review_declared" if row["answer_state"] == "ANSWER_VERIFIED_BY_DECLARATION" else "active_answer_not_reviewed_or_unverified"] += 1
            question_counts["active_verified_grader" if row["verified_grading_method"] else "active_no_verified_grader"] += 1
            question_counts["active_practice_comparable" if row["practice_answer_comparison_method"] else "active_no_supported_answer_comparator"] += 1
            question_counts["active_official_target_attested" if row["official_target_attestation_complete"] else "active_official_target_not_fully_attested"] += 1
    assessable = [r for r in coverage_rows if r["assessable"]]
    coverage_totals = {
        "active_nodes": len(active_nodes), "assessable_nodes": len(assessable),
        "active_questions": sum(q.is_active for q in questions),
        "assessable_nodes_with_active_question": sum(r["active_question_count"] > 0 for r in assessable),
        "assessable_nodes_without_active_question": sum(r["active_question_count"] == 0 for r in assessable),
        "zero_question_with_reference": sum(r["active_question_count"] == 0 and r["distinct_exam_reference_count"] > 0 for r in assessable),
        "zero_question_without_reference": sum(r["active_question_count"] == 0 and r["distinct_exam_reference_count"] == 0 for r in assessable),
        "zero_evidence_grader": sum(r["evidence_eligible_grader_count"] == 0 for r in assessable),
        "assessable_nodes_with_zero_fully_attested_active_questions": sum(r["official_target_fully_attested_count"] == 0 for r in assessable),
        "ref_only_with_question": sum(r["reference_only"] and r["active_question_count"] > 0 for r in assessable),
        "candidate_proposed_code_total_canonical_pack_only": sum(r["local_candidate_proposed_code_count"] for r in assessable),
        "candidate_exact_label_total": sum(r["local_candidate_exact_name_label_count"] for r in assessable),
    }
    lesson_counts = Counter(row["lesson_state"] for row in lesson_rows)
    lesson_issue_counts = Counter(issue for row in lesson_rows for issue in row["structural_issues"])
    lesson_signal_counts = {
        "total": len(lesson_rows),
        "no_lesson": sum(row["lesson_state"] == "NO_LESSON" for row in lesson_rows),
        "empty": sum(row["empty_lesson"] for row in lesson_rows),
        "very_short_under_500_chars": sum(row["very_short_signal_under_500_chars"] for row in lesson_rows),
        "index_or_exam_reference_only_signal": sum(row["exam_reference_only_signal"] for row in lesson_rows),
        "missing_concept": sum(not row["has_concept"] for row in lesson_rows),
        "missing_conditions": sum(not row["has_conditions"] for row in lesson_rows if not row["is_parent"]),
        "missing_method": sum(not row["has_method"] for row in lesson_rows if not row["is_parent"]),
        "missing_example_heading": sum(not row["has_example"] for row in lesson_rows if not row["is_parent"]),
        "missing_solution_heading": sum(not row["has_solution"] for row in lesson_rows if not row["is_parent"]),
        "missing_mistake_analysis": sum(not row["has_mistake_analysis"] for row in lesson_rows if not row["is_parent"]),
        "missing_summary": sum(not row["has_summary"] for row in lesson_rows if not row["is_parent"]),
        "possible_topic_mismatch": sum(row["possible_topic_mismatch"] for row in lesson_rows),
        "formula_structure_signal": sum(row["formula_review_required"] for row in lesson_rows),
        "examples_requiring_human_review": sum(row["example_review_required"] for row in lesson_rows),
        "content_review_required": sum(row["content_review_required"] for row in lesson_rows),
        "leaf_count": sum(not row["is_parent"] for row in lesson_rows),
        "parent_count": sum(row["is_parent"] for row in lesson_rows),
    }
    mapping_counts = Counter(row["mapping_status"] for row in mapping_rows)
    candidate_year_counts = Counter((r["subject"], r["year"]) for r in archive_rows)
    archive_fingerprint = None
    if archive_rows:
        digest = hashlib.sha256()
        for row in archive_rows:
            path = args.archive / "逐题整理" / Path(row["relative_path"])
            digest.update(row["relative_path"].encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
        archive_fingerprint = digest.hexdigest()
    source_hash, source_file_count = hashlib.sha256(), 0
    for folder in (ROOT / "backend", ROOT / "frontend/src", ROOT / "seed/lessons", ROOT / "scripts"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or any(part in {"__pycache__", "node_modules", "dist"} for part in path.parts):
                continue
            if path.suffix.lower() not in {".py", ".vue", ".ts", ".md", ".json"}:
                continue
            source_hash.update(path.relative_to(ROOT).as_posix().encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
            source_file_count += 1
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty_count = len(subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines())
    except Exception:
        head, dirty_count = "unavailable", -1
    manifest = {
        "audit": "Phase 1 — Learning Content & Evidence Foundation Audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_snapshot_time": captured_at.isoformat() if captured_at else None,
        "database_target": {"database_name": url.database, "host": url.host, "transaction_read_only": True},
        "code_version": {"git_head": head, "dirty_status_entry_count": dirty_count,
                         "source_fingerprint_sha256": source_hash.hexdigest(), "source_file_count": source_file_count},
        "candidate_dataset": {"personal_archive_markdown_questions": len(archive_rows),
                              "archive_fingerprint_sha256": archive_fingerprint,
                              "structured_question_pack_files": len(qpack_files)},
        "canonical_question_pack": {"path": canonical_pack_rel,
            "candidate_records": next((r["candidate_records"] for r in pack_asset_rows if r["relative_path"] == canonical_pack_rel), 0),
            "note": "Per-node proposed candidate counts use exactly one snapshot to avoid overlap; identity matching scans every version."},
        "question_counts": dict(question_counts), "coverage_totals": coverage_totals,
        "lesson_state_counts": dict(lesson_counts), "lesson_structural_issue_counts": dict(lesson_issue_counts),
        "lesson_signal_counts": lesson_signal_counts,
        "evidence_integrity": {"entry_status_counts": dict(evidence_status_counts),
            "mastered_states_with_stale_or_ineligible_objective_entry": len(stale_mastered_state_ids),
            "note": "Read-only cross-check of stored evidence-window entries against current questions, verified grader configuration and immutable answer-attempt receipts."},
        "learning_history_snapshot": {
            "question_attempt_rows": len(attempts), "objective_result_counts": dict(attempt_result_counts),
            "attempt_basis_counts": dict(attempt_basis_counts), "attempt_sequence_category_counts": dict(attempt_sequence_counts),
            "learning_event_rows": len(events),
            "state_basis_status_counts": {f"{basis}:{state}": count for (basis, state), count in sorted(state_counts.items())},
        },
        "today_plan_snapshot": {
            "current_shanghai_date": local_today,
            "plan_count": len(plans),
            "current_date_plan_count": sum(row["is_current_shanghai_date"] for row in today_plan_rows),
            "plan_status_counts": dict(Counter(row["status"] for row in today_plan_rows)),
            "note": "Per-plan counts are available in today_plan_inventory.csv; no plan content or answer text is exported."},
        "candidate_mapping_counts": dict(mapping_counts),
        "candidate_archive_subject_year_distribution": {f"{s}:{y}": c for (s, y), c in sorted(candidate_year_counts.items())},
        "agent_trace_scope": {"tasks_scanned": len(tasks), "tasks_reported": len(task_trace_rows),
                              "tool_status_counts": {f"{k[0]}:{k[1]}": v for k, v in sorted(task_tool_counts.items())},
                              "error_counts": dict(task_error_counts),
                              "raw_goals_or_stems_exported": False, "tool_arguments_persisted": False},
        "method": "read-only PostgreSQL snapshot plus source/asset structural inspection; no model calls, no migrations, no DB writes, no VERIFIED changes",
    }
    (output / "audit_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "candidate_asset_summary.md").write_text(
        "# Candidate 与本地资产摘要\n\n"
        f"- 个人逐题 Markdown 草稿：{len(archive_rows)}；CSV只列相对路径/元数据，不含题干和答案。\n"
        f"- 桌面归档稳定清单 SHA256：{archive_fingerprint or '未发现归档'}。\n"
        f"- question-pack 快照：{len(qpack_files)} 份，按版本逐文件计数；版本可能重叠，不能相加为独立题量。\n"
        f"- 候选→数据库匹配：{json.dumps(dict(mapping_counts), ensure_ascii=False)}。\n"
        "- 只有导入稳定键和内容指纹吻合才标 EXACT；单纯题号/年份相同标 POSSIBLE。\n"
        "- 原卷 PDF/页图只盘点数量与状态，不认定许可或题面正确。\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output_dir": str(output), "database_name": url.database,
        "questions": dict(question_counts), "coverage": coverage_totals,
        "candidates": {"archive_markdown": len(archive_rows), "mapping": dict(mapping_counts), "pack_files": len(qpack_files)},
        "lessons": {"state_counts": dict(lesson_counts), "issue_counts": dict(lesson_issue_counts)},
        "agent_tasks_reported": len(task_trace_rows), "write_mode": "audit artifacts only; DB transaction read-only",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
