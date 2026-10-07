"""Read-only, deterministic stages for producing trusted practice questions.

Production writes remain with the existing reviewed question-pack importer and
hash-bound verification bridge. This module only assesses state; it never
promotes trust, fixes content, changes mappings, or rewrites history.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Iterable

from backend.services.question_eligibility import question_eligibility
from backend.services.question_attestation import has_current_source_attestation


PIPELINE_VERSION = "question-production-assessment-v1"
_PLACEHOLDER = re.compile(r"待补|待核对|占位|TODO|未识别|未逐字|OCR|\ufffd|（图略）", re.I)
_FIGURE_CUE = re.compile(r"如图|见图|下图|图\s*\d|表\s*\d|如下表|图中")
_FIGURE_MARKER = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b|\\includegraphics", re.I)


def _norm_subject(value: Any) -> str | None:
    raw = str(value or "").strip().lower().replace(" ", "")
    if raw in {"408", "计算机408", "计算机学科专业基础"}:
        return "408"
    if raw in {"math2", "数学二", "数学", "考研数学"}:
        return "math2"
    return raw or None


def _as_identity(value: Any) -> tuple[str | None, int | None, int | None] | None:
    if not isinstance(value, dict):
        return None
    source = value.get("source") if isinstance(value.get("source"), dict) else value
    subject = _norm_subject(source.get("subject"))
    try:
        year = int(source.get("year")) if source.get("year") is not None else None
        number = int(source.get("question_number")) if source.get("question_number") is not None else None
    except (TypeError, ValueError):
        return None
    if not subject or year is None or number is None or year < 1900 or number < 1:
        return None
    return subject, year, number


@dataclass(frozen=True)
class IdentityResolution:
    status: str
    candidate_identity: tuple[str, int, int] | None
    matched_question_ids: tuple[str, ...]
    reason: str

    def public_dict(self) -> dict:
        result = asdict(self)
        result["candidate_identity"] = list(self.candidate_identity) if self.candidate_identity else None
        result["matched_question_ids"] = list(self.matched_question_ids)
        return result


def resolve_identity(candidate: dict, database_identities: Iterable[tuple[Any, Any]]) -> IdentityResolution:
    """Resolve only bibliographic identity; never use identity as content trust."""
    declared = [_as_identity(candidate)]
    for key in ("identity", "source_identity"):
        if key in candidate and isinstance(candidate[key], dict):
            declared.append(_as_identity(candidate[key]))
    usable = [item for item in declared if item is not None]
    if len(usable) > 1 and len(set(usable)) != 1:
        return IdentityResolution("CONFLICT", None, (), "candidate_declares_conflicting_identity")
    target = usable[0] if usable else None
    if target is None:
        return IdentityResolution("UNMATCHED", None, (), "identity_fields_missing_or_invalid")

    exact, partial = [], []
    for qid, raw_identity in database_identities:
        identity = raw_identity if (isinstance(raw_identity, tuple) and len(raw_identity) == 3) else _as_identity(raw_identity)
        if identity is None:
            continue
        normalized = (_norm_subject(identity[0]), int(identity[1]), int(identity[2]))
        if normalized == target:
            exact.append(str(qid))
        elif (normalized[1] == target[1] and normalized[2] == target[2]) or (
            normalized[0] == target[0] and normalized[1] == target[1]
        ):
            partial.append(str(qid))
    if len(exact) > 1:
        return IdentityResolution("CONFLICT", target, tuple(sorted(exact)), "duplicate_database_identity")
    if len(exact) == 1:
        return IdentityResolution("EXACT", target, tuple(exact), "single_exact_bibliographic_match")
    if len(partial) == 1:
        return IdentityResolution("POSSIBLE", target, tuple(partial), "partial_bibliographic_match_only")
    if len(partial) > 1:
        return IdentityResolution("CONFLICT", target, tuple(sorted(partial)), "ambiguous_partial_bibliographic_match")
    return IdentityResolution("UNMATCHED", target, (), "no_database_identity_match")


def content_digest(question: Any) -> str:
    payload = {key: getattr(question, key, None) for key in (
        "question_type", "stem", "options", "correct_answer", "explanation", "kp_id"
    )}
    if "kp_id" in payload and payload["kp_id"] is not None:
        payload["kp_id"] = str(payload["kp_id"])
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class ContentValidationResult:
    status: str
    completeness: str
    content_hash: str
    detected_issues: tuple[str, ...]
    validation_method: str = "deterministic_structure_checks_v1"

    def public_dict(self) -> dict:
        result = asdict(self)
        result["detected_issues"] = list(self.detected_issues)
        return result


def validate_question_content(question: Any, *, is_reference_only: bool = False,
                              duplicate_content: bool = False) -> ContentValidationResult:
    """Catch structural failures only; a clean result still needs human review."""
    issues: list[str] = []
    stem = str(getattr(question, "stem", "") or "").strip()
    answer = str(getattr(question, "correct_answer", "") or "").strip()
    explanation = str(getattr(question, "explanation", "") or "").strip()
    qtype = getattr(question, "question_type", None)
    options = getattr(question, "options", None)
    if is_reference_only:
        issues.append("reference_only_mapping_not_online_question")
    if len(stem) < 5:
        issues.append("stem_missing_or_too_short")
    if _PLACEHOLDER.search(stem):
        issues.append("placeholder_or_ocr_marker")
    if not answer:
        issues.append("answer_missing")
    if not explanation:
        issues.append("explanation_missing")
    if qtype == "single_choice":
        if not isinstance(options, dict) or len(options) < 2:
            issues.append("choice_options_missing")
        else:
            valid_keys = {str(key).strip().upper() for key in options if str(key).strip()}
            if (len(valid_keys) != len(options)
                    or any(not isinstance(value, str) or not value.strip() for value in options.values())):
                issues.append("choice_options_invalid_or_duplicate")
            # Keep the answer-reference check independent: malformed/duplicate
            # options should not hide a second, useful defect from the audit.
            if answer.upper() not in valid_keys:
                issues.append("choice_answer_not_in_options")
    elif options is not None:
        issues.append("non_choice_has_options")
    if _FIGURE_CUE.search(stem) and not _FIGURE_MARKER.search(stem):
        issues.append("figure_or_table_asset_not_embedded")
    if duplicate_content:
        issues.append("duplicate_question_content")
    normalized = re.sub(r"\s+", "", stem)
    if normalized and len(normalized) < 12 and qtype not in {"single_choice"}:
        issues.append("stem_may_be_title_or_summary_only")
    digest = content_digest(question)
    hard = {"reference_only_mapping_not_online_question", "stem_missing_or_too_short",
            "placeholder_or_ocr_marker", "answer_missing", "choice_options_missing",
            "choice_options_invalid_or_duplicate", "choice_answer_not_in_options",
            "non_choice_has_options", "figure_or_table_asset_not_embedded",
            "duplicate_question_content", "stem_may_be_title_or_summary_only"}
    structural = not any(issue in hard for issue in issues)
    return ContentValidationResult(
        "STRUCTURALLY_COMPLETE" if structural else "INCOMPLETE",
        "complete" if structural else "incomplete", digest,
        tuple(dict.fromkeys(issues + (["human_content_review_required"] if structural else []))),
    )


def assess_production_question(question: Any, node: Any | None, *, identity: IdentityResolution | None = None,
                               duplicate_content: bool = False) -> dict:
    """Return every pipeline stage with the real Phase 2 eligibility decision."""
    source_attested = (getattr(question, "content_trust", None) == "source_attested"
        and has_current_source_attestation(question))
    mapping_ok = bool(node and node.is_active and node.is_assessable
                      and (not node.is_reference_only or source_attested))
    content = validate_question_content(question,
        is_reference_only=bool(node and node.is_reference_only and not source_attested),
        duplicate_content=duplicate_content)
    eligibility = question_eligibility(question, node)
    source_reliability = getattr(question, "answer_reliability", "unknown") or "unknown"
    source_provenance = getattr(question, "answer_provenance", "unknown") or "unknown"
    answer_state = (
        "VERIFIED_REFERENCE" if source_provenance == "verified_reference" and source_reliability == "verified"
        else "AI_GENERATED" if source_provenance == "ai_generated"
        else "UNRESOLVED"
    )
    stages = {
        "identity_resolution": identity.status if identity else "UNKNOWN",
        "question_content_validation": content.status,
        "knowledge_mapping_validation": "VALID" if mapping_ok else "BLOCKED",
        "answer_resolution": answer_state,
        "answer_reliability": source_reliability,
        "grading_capability": eligibility.grading_capability,
        "eligibility": "ELIGIBLE" if eligibility.practice_eligible else "BLOCKED",
    }
    # `EXACT` only establishes identity. All other independently evaluated
    # gates still apply, and this function never writes a trust field.
    return {
        "pipeline_version": PIPELINE_VERSION,
        "stages": stages,
        "identity": identity.public_dict() if identity else None,
        "content_validation": content.public_dict(),
        "eligibility": eligibility.public_dict(),
        "production_ready": bool(eligibility.practice_eligible and content.status == "STRUCTURALLY_COMPLETE"),
        "automatic_trust_promotion": False,
        "history_rewritten": False,
    }
