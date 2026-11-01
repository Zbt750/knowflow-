"""Deterministic source/content attestation for complete imported Questions.

This records local traceability and structural integrity only. It is not proof of
official authenticity, answer correctness, licensing, or human review.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any

from backend.services.question_pack import fingerprint


ATTESTATION_PIPELINE_VERSION = "machine-source-attestation-v1"
_ID_RE = re.compile(r"^(?P<subject>.+):(?P<year>\d{4}):Q(?P<number>\d{1,3})$", re.I)
_PLACEHOLDER_RE = re.compile(r"待补|待核对|占位|TODO|未识别|未逐字|OCR|\ufffd|题干略|答案略", re.I)
_TRUNCATION_RE = re.compile(r"(?:\.\.\.|……|待续|后略|以下略)\s*$")
_FIGURE_RE = re.compile(r"如图|见图|下图|图\s*\d|图中|如下表|见表|表\s*\d")
_FIGURE_ASSET_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b|\\includegraphics", re.I)


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, dict) else {}


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def _subject(value: Any) -> str:
    normalized = re.sub(r"\s+", "", str(value or "")).lower()
    if normalized in {"408", "计算机408", "计算机学科专业基础", "计算机学科专业基础（408）",
                      "计算机学科专业基础综合（408）"}:
        return "408"
    if normalized in {"数学二", "数学（二）", "考研数学二", "math2"}:
        return "math2"
    return normalized


def question_content_sha256(question: Any) -> str:
    """Hash the answer-independent Question stem, options, type, and node mapping."""
    payload = {
        "question_type": getattr(question, "question_type", None),
        "stem": getattr(question, "stem", None),
        "options": getattr(question, "options", None),
        "kp_id": str(getattr(question, "kp_id", "")),
    }
    return _sha(payload)


@dataclass(frozen=True)
class SourceAttestationAssessment:
    status: str
    attestation_key: str
    question_content_sha256: str
    source_content_sha256: str | None
    source_identity: dict[str, Any]
    source_locator: str
    mapping_type: str
    issues: tuple[str, ...]
    method: str = ATTESTATION_PIPELINE_VERSION

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attestation_key": self.attestation_key,
            "question_content_sha256": self.question_content_sha256,
            "source_content_sha256": self.source_content_sha256,
            "source_identity": self.source_identity,
            "source_locator": self.source_locator,
            "mapping_type": self.mapping_type,
            "issues": list(self.issues),
            "method": self.method,
        }


def assess_source_attestation(*, question: Any, node: Any, pack_question: Any,
                              pack_id: str, pack_version: str,
                              candidate_archive_sha256: str,
                              candidate_map_row: dict[str, Any]) -> SourceAttestationAssessment:
    """Require a unique exact identity+fingerprint path and complete source metadata."""
    data = _dump(pack_question)
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    provenance = (question.grading_config or {}).get("provenance", {}) if isinstance(
        getattr(question, "grading_config", None), dict) else {}
    saved_source = provenance.get("source", {}) if isinstance(provenance, dict) else {}
    issues: list[str] = []
    candidate_id = str(candidate_map_row.get("candidate_id") or "")
    locator = str(candidate_map_row.get("candidate_path") or "")[:500]
    match_status = str(candidate_map_row.get("mapping_status") or "").upper()
    try:
        matched_ids = json.loads(candidate_map_row.get("matched_question_ids") or "[]")
    except (TypeError, json.JSONDecodeError):
        matched_ids = []
    try:
        match_count = int(candidate_map_row.get("match_count") or 0)
    except (TypeError, ValueError):
        match_count = 0

    identity_match = _ID_RE.fullmatch(candidate_id)
    if match_status != "EXACT" or match_count != 1 or matched_ids != [str(question.id)]:
        issues.append("candidate_mapping_not_unique_exact")
    source_type = str(source.get("source_type") or "")
    if source_type not in {"exam", "mock"} or source.get("kind") == "original":
        issues.append("source_type_not_traceable_exam_or_mock")
    if not identity_match:
        issues.append("candidate_stable_identity_missing")
    else:
        identity = identity_match.groupdict()
        declared = (_subject(source.get("subject")), int(source.get("year") or 0),
                    int(source.get("question_number") or 0))
        candidate_identity = (_subject(identity["subject"]), int(identity["year"]), int(identity["number"]))
        if declared != candidate_identity:
            issues.append("candidate_source_identity_mismatch")
    if not all(str(source.get(field) or "").strip() for field in ("citation", "rights_basis", "reviewed_by", "paper_title", "subject")):
        issues.append("source_trace_metadata_incomplete")
    if not source.get("reviewed_on"):
        issues.append("source_review_date_missing")
    # SourceReview gained optional content_origin. Old persisted declarations
    # legitimately omit it; absent and explicit null carry the same meaning.
    # Non-null origins and every other source field still compare exactly.
    def compatible_source(value):
        data = _dump(value)
        if data.get("content_origin") is None:
            data.pop("content_origin", None)
        return data
    if compatible_source(source) != compatible_source(saved_source):
        issues.append("database_source_snapshot_mismatch")

    stable_key = f"{pack_id}:{data.get('source_id', '')}"
    if provenance.get("key") != stable_key:
        issues.append("stable_import_key_mismatch")
    try:
        import_fingerprint = fingerprint(pack_question)
    except Exception:
        import_fingerprint = None
    saved_fingerprint = provenance.get("sha256")
    if not import_fingerprint or saved_fingerprint != import_fingerprint:
        issues.append("source_pack_fingerprint_mismatch")
    if node is None or not node.is_active or not node.is_assessable:
        issues.append("knowledge_mapping_not_active_assessable")
    elif node.code != data.get("kp_code"):
        issues.append("knowledge_mapping_code_mismatch")

    fields = ("stem", "question_type", "options", "question_role", "difficulty",
              "skill_tags", "estimated_minutes", "is_variant")
    for field in fields:
        if getattr(question, field, None) != data.get(field):
            issues.append(f"database_pack_content_mismatch:{field}")

    # The imported answer/explanation are not part of question-source
    # authenticity. They remain untrusted inputs to the answer pipeline and may
    # be replaced only after a current A/B/C result. A stale or unreviewed
    # answer still has to match the candidate pack so the transformation is
    # traceable.
    answer_was_attested = False
    if (getattr(question, "answer_provenance", None) == "ai_generated"
            and getattr(question, "answer_reliability", None) == "ai_generated_consistent"):
        try:
            from backend.services.answer_consistency import has_current_answer_attestation
            answer_was_attested = has_current_answer_attestation(question)
        except Exception:
            answer_was_attested = False
    if not answer_was_attested and getattr(question, "correct_answer", None) != data.get("correct_answer"):
        issues.append("database_pack_content_mismatch:correct_answer")
    if getattr(question, "explanation", None) != data.get("explanation"):
        issues.append("database_pack_content_mismatch:explanation")

    stem = str(data.get("stem") or "").strip()
    qtype = data.get("question_type")
    if _PLACEHOLDER_RE.search(stem):
        issues.append("placeholder_or_ocr_marker")
    if _TRUNCATION_RE.search(stem):
        issues.append("possible_truncated_question")
    if _FIGURE_RE.search(stem) and not _FIGURE_ASSET_RE.search(stem):
        issues.append("required_figure_not_embedded")
    if qtype not in {"single_choice", "fill_blank", "calculation", "proof", "discussion", "program", "subjective"}:
        issues.append("question_type_unknown")
    options = data.get("options")
    if qtype == "single_choice" and (
        not isinstance(options, dict) or len(options) < 2
        or any(not str(k).strip() or not isinstance(v, str) or not v.strip() for k, v in options.items())
        or str(data.get("correct_answer") or "").strip().upper() not in {str(k).strip().upper() for k in options}
    ):
        issues.append("choice_options_or_candidate_answer_incomplete")
    if qtype != "single_choice" and isinstance(options, dict):
        issues.append("non_choice_has_options")
    if not isinstance(data.get("correct_answer"), str) or not data["correct_answer"].strip():
        issues.append("answer_missing")
    if not isinstance(data.get("explanation"), str) or len(data["explanation"].strip()) < 5:
        issues.append("explanation_missing_or_too_short")

    # Existing structural checks catch missing stems/options/formula red flags.
    # Import at call time to avoid the eligibility ↔ production-pipeline ↔
    # source-attestation module cycle during FastAPI startup.
    from backend.services.question_production_pipeline import validate_question_content
    structural = validate_question_content(question, is_reference_only=False)
    issues.extend(issue for issue in structural.detected_issues if issue != "human_content_review_required")
    issues = list(dict.fromkeys(issues))
    status = "source_attested" if not issues else "needs_review"
    source_identity = {
        "source_type": source_type,
        "subject": str(source.get("subject") or ""),
        "year": source.get("year"),
        "question_number": source.get("question_number"),
        "paper_title": source.get("paper_title"),
        "edition": source.get("edition"),
        "kind": source.get("kind"),
        "citation_sha256": sha256(str(source.get("citation") or "").encode()).hexdigest(),
        "rights_basis_status": "local_use_only_redistribution_not_cleared",
    }
    qhash = question_content_sha256(question)
    key = _sha({"question_id": str(question.id), "question_hash": qhash,
                "source_hash": import_fingerprint, "pack_id": pack_id,
                "pack_version": pack_version, "candidate_id": candidate_id})
    mapping_type = "exact_pack_fingerprint_and_stable_exam_identity"
    if node is not None and getattr(node, "is_reference_only", False):
        mapping_type = "exact_full_question_on_assessable_reference_topic"
    return SourceAttestationAssessment(status, key, qhash, import_fingerprint,
        source_identity, locator, mapping_type, tuple(issues))


def has_current_source_attestation(question: Any) -> bool:
    """Fail closed if the attested stem/options/type/node have since changed."""
    key = getattr(question, "source_attestation_key", None)
    digest = getattr(question, "source_attestation_sha256", None)
    return bool(key and digest and digest == question_content_sha256(question))


def create_source_attestation_record(*, question: Any, assessment: SourceAttestationAssessment,
                                     candidate_id: str, pack_id: str, pack_version: str,
                                     candidate_archive_sha256: str,
                                     attestation_source: str = "user_provided_local_question_pack"):
    from backend.models.learning import QuestionSourceAttestation

    return QuestionSourceAttestation(
        attestation_key=assessment.attestation_key, question_id=question.id,
        candidate_id=candidate_id, pack_id=pack_id, pack_version=pack_version,
        candidate_archive_sha256=candidate_archive_sha256,
        source_content_sha256=assessment.source_content_sha256 or "0" * 64,
        question_content_sha256=assessment.question_content_sha256,
        source_locator=assessment.source_locator or "candidate_locator_unavailable",
        mapping_type=assessment.mapping_type, attestation_method=assessment.method,
        attestation_source=attestation_source, source_identity=assessment.source_identity,
        detected_issues=list(assessment.issues), status=assessment.status,
        pipeline_version=ATTESTATION_PIPELINE_VERSION,
        created_at=datetime.now(timezone.utc),
    )
