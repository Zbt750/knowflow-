"""One fail-closed decision for entering new practice, independent of answer source."""
from __future__ import annotations

from dataclasses import dataclass

from backend.models.learning import KnowledgePoint, Question
from backend.services.answer_grading import available_grading_method, available_practice_grading_method
from backend.services.answer_consistency import has_current_answer_attestation
from backend.services.question_attestation import has_current_source_attestation


KNOWN_QUESTION_TYPES = {"single_choice", "fill_blank", "calculation", "proof", "discussion", "program", "subjective"}


@dataclass(frozen=True)
class QuestionEligibility:
    question_provenance: str
    content_trust: str
    source_status: str
    answer_provenance: str
    answer_reliability: str
    mapping_status: str
    source_attestation_current: bool
    answer_attestation_current: bool
    practice_eligible: bool
    grading_capability: str
    evidence_capability: str
    answer_comparison_method: str | None
    verified_grading_method: str | None
    blocking_reasons: tuple[str, ...]

    def public_dict(self) -> dict:
        result = self.__dict__.copy()
        result["blocking_reasons"] = list(self.blocking_reasons)
        return result


def question_eligibility(question: Question, node: KnowledgePoint | None = None) -> QuestionEligibility:
    """Practice eligibility is not a claim that an AI answer is authoritative."""
    provenance = getattr(question, "question_provenance", "legacy_unknown") or "legacy_unknown"
    trust = getattr(question, "content_trust", "unreviewed") or "unreviewed"
    source_status = getattr(question, "source_status", "unknown") or "unknown"
    answer_provenance = getattr(question, "answer_provenance", "unknown") or "unknown"
    answer_reliability = getattr(question, "answer_reliability", "unknown") or "unknown"
    config = question.grading_config if isinstance(question.grading_config, dict) else {}
    expected = question.correct_answer
    options = question.options
    reasons: list[str] = []

    if not question.is_active:
        reasons.append("inactive")
    source_attested = trust == "source_attested" and has_current_source_attestation(question)
    human_verified = trust == "verified" and bool(question.content_reviewed_by and question.content_reviewed_at)
    answer_attested = (answer_provenance == "ai_generated"
        and answer_reliability == "ai_generated_consistent"
        and has_current_answer_attestation(question))
    if not human_verified and not source_attested:
        reasons.append("content_not_verified")
    if provenance not in {"real_exam", "trusted_practice", "ai_generated_practice"}:
        reasons.append("question_provenance_unknown")
    if provenance == "real_exam" and not (
        source_status == "verified" and human_verified
        or source_status == "traceable" and source_attested
    ):
        reasons.append("exam_source_not_verified")
    elif provenance == "trusted_practice" and not (
        source_status == "verified" and human_verified
        or source_status == "traceable" and source_attested
        or source_status == "not_applicable"
    ):
        reasons.append("practice_source_not_traceable")
    elif provenance == "ai_generated_practice" and source_status != "not_applicable":
        reasons.append("generated_question_source_invalid")
    if not isinstance(question.stem, str) or len(question.stem.strip()) < 5:
        reasons.append("question_content_incomplete")
    if question.question_type == "single_choice":
        if not isinstance(options, dict) or len(options) < 2 or any(not str(k).strip() or not isinstance(v, str) or not v.strip() for k, v in options.items()):
            reasons.append("choice_options_incomplete")
        elif not isinstance(expected, str) or expected.strip().upper() not in {str(k).strip().upper() for k in options}:
            reasons.append("choice_answer_invalid")
    elif isinstance(options, dict) and any(not isinstance(v, str) or not v.strip() for v in options.values()):
        reasons.append("question_content_incomplete")
    if not isinstance(expected, str) or not expected.strip():
        reasons.append("answer_missing")
    if not isinstance(question.explanation, str) or not question.explanation.strip():
        reasons.append("explanation_missing")
    if answer_provenance not in {"verified_reference", "ai_generated"}:
        reasons.append("answer_provenance_unknown")
    if answer_provenance == "verified_reference" and (
        answer_reliability != "verified" or not question.answer_reviewed_by or not question.answer_reviewed_at
    ):
        reasons.append("reference_answer_not_verified")
    if answer_provenance == "ai_generated" and answer_reliability not in {
        "model_generated", "unverified", "ai_generated_consistent", "ai_disagreement"
    }:
        reasons.append("ai_answer_reliability_unknown")
    if question.question_type not in KNOWN_QUESTION_TYPES:
        reasons.append("practice_mode_unknown")

    mapping_status = "missing"
    if node is not None:
        if not node.is_active:
            mapping_status = "inactive"
            reasons.append("mapping_inactive")
        elif not node.is_assessable:
            mapping_status = "not_assessable"
            reasons.append("mapping_not_assessable")
        elif node.is_reference_only and source_attested:
            # A reference-only leaf normally represents an external pointer.
            # A full Question may be practiced only when its own stable source
            # identity, pack fingerprint, and exact node code were attested.
            mapping_status = "source_attested_reference_topic"
        elif node.is_reference_only:
            mapping_status = "reference_only"
            reasons.append("reference_only_mapping")
        else:
            mapping_status = "assessable_leaf"
    else:
        reasons.append("mapping_missing")

    verified_method = None if (answer_provenance == "ai_generated" and answer_reliability == "ai_disagreement") else available_grading_method(
        question_type=question.question_type, config=config, expected=expected, options=options)
    answer_ready = (
        (human_verified or source_attested)
        and (
            (answer_provenance == "verified_reference" and answer_reliability == "verified"
             and human_verified and question.answer_reviewed_by is not None and question.answer_reviewed_at is not None)
            or (answer_provenance == "ai_generated" and (
                human_verified and answer_reliability in {"model_generated", "unverified", "ai_generated_consistent"}
                or source_attested and answer_attested
            ))
        )
    )
    comparison_method = available_practice_grading_method(question_type=question.question_type,
        config=config, expected=expected, options=options,
        answer_provenance=answer_provenance, content_trust=trust,
        answer_reliability=answer_reliability) if answer_ready else None
    if verified_method:
        grading_capability = "deterministic"
    elif comparison_method and not comparison_method.startswith("ai_generated_"):
        grading_capability = "final_answer_limited"
    elif comparison_method and comparison_method.startswith("ai_generated_"):
        # The comparison operation is mechanical, but the reference itself is
        # AI-authored; do not describe the overall grading as deterministic.
        grading_capability = "final_answer_limited"
    elif question.question_type in {"proof", "discussion", "program", "subjective", "calculation"}:
        grading_capability = "process_review_only"
    else:
        grading_capability = "unsupported"
    # A known process-review/self-assessment mode is sufficient for practice.
    # It is not a machine-grade and never upgrades evidence capability.
    if grading_capability == "unsupported":
        reasons.append("grading_or_practice_mode_unsupported")

    if (answer_provenance == "verified_reference" and answer_reliability == "verified"
            and human_verified and verified_method and provenance in {"real_exam", "trusted_practice"}):
        evidence_capability = "verified_objective"
    elif source_attested and answer_attested and comparison_method:
        evidence_capability = "ai_consistent_objective"
    elif answer_provenance == "ai_generated" and comparison_method:
        evidence_capability = "ai_low_reliability"
    elif grading_capability == "process_review_only":
        evidence_capability = "process_review_not_objective_evidence"
    else:
        evidence_capability = "self_report_only"

    return QuestionEligibility(
        question_provenance=provenance,
        content_trust=trust,
        source_status=source_status,
        answer_provenance=answer_provenance,
        answer_reliability=answer_reliability,
        mapping_status=mapping_status,
        source_attestation_current=source_attested,
        answer_attestation_current=answer_attested,
        practice_eligible=not reasons,
        grading_capability=grading_capability,
        evidence_capability=evidence_capability,
        answer_comparison_method=comparison_method,
        verified_grading_method=verified_method,
        blocking_reasons=tuple(dict.fromkeys(reasons)),
    )


def is_practice_eligible(question: Question, node: KnowledgePoint | None = None) -> bool:
    return question_eligibility(question, node).practice_eligible
