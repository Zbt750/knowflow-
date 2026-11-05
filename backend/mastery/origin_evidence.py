"""Version-2 confirmations use facts captured by a trusted submission receipt."""
import re
from backend.mastery.enums import EvidenceLevel

INDEPENDENT_CATEGORIES = frozenset({"first_independent_correct", "independent_retest_correct", "repeat_correct"})
CONFIRMATION_FACT_FIELDS = (
    "attempt_id", "policy_version", "question_provenance", "question_content_sha256",
    "answer_version_sha256", "answer_verification_event_id", "answer_provenance",
    "answer_reliability", "question_content_trust", "source_status",
    "grading_capability", "method", "assisted", "assistance_level", "confidence", "sequence_category",
    "sequence_version", "result", "evidence_reliability",
    "bank_scope", "generation_batch_id",
    "auto_review_event_id", "auto_review_version", "auto_review_snapshot_sha256",
    # Optional on historical facts; never backfilled. Traceable generated
    # variants need the class captured from a current full public review.
    "auto_review_qualification_class",
)


def compatible_confirmation(evidence, policy) -> bool:
    facts = evidence.confirmation_facts or {}
    method = facts.get("method")
    auto_reviewed = (facts.get("answer_provenance") == "auto_verified"
        and facts.get("question_content_trust") == "auto_verified"
        and facts.get("answer_reliability") == "verified"
        and facts.get("auto_review_event_id")
        and facts.get("auto_review_version") in {
            "public-question-auto-review-v1", "public-question-auto-review-v2",
            "public-question-auto-review-v3", "public-question-auto-review-v4", "public-question-auto-review-v5",
            "public-question-auto-review-v6", "public-question-auto-review-v7",
            "public-question-auto-review-v8"
        }
        and isinstance(facts.get("auto_review_snapshot_sha256"), str)
        and re.fullmatch(r"[a-f0-9]{64}", facts["auto_review_snapshot_sha256"]))
    answer_provenance_valid = (facts.get("answer_provenance") in {"human_verified", "verified_reference"}
        or auto_reviewed)
    trust_valid = (facts.get("question_content_trust") == "verified" or auto_reviewed)
    provenance = facts.get("question_provenance")
    source_status = facts.get("source_status")
    # A generated practice question cannot inherit an exam-origin claim from a
    # pack's metadata. Auto-reviewed real-exam content may use the stronger
    # current source-bound review path; non-exam origins retain their explicit
    # not-applicable source semantics.
    source_valid = (
        provenance == "real_exam" and source_status == "verified"
        or provenance == "trusted_practice"
            and source_status in {"verified", "traceable", "not_applicable"}
        or provenance == "ai_generated_practice" and source_status == "not_applicable"
        or (auto_reviewed and provenance == "ai_generated_practice"
            and source_status == "traceable"
            and facts.get("auto_review_qualification_class") == "exam_variant")
        or auto_reviewed and provenance == "real_exam"
            and source_status in {"verified", "traceable"}
    )
    supported = {"single_choice": {"single_choice_v1"},
        "fill_blank": {"exact_numeric_v1", "exact_logarithm_v1", "exact_constant_v1"},
        "calculation": {"exact_numeric_v1", "exact_logarithm_v1", "exact_constant_v1"}}
    return bool(evidence.question_id and evidence.source == "objective_final"
        and facts.get("bank_scope", "public") == "public" and not facts.get("generation_batch_id")
        and evidence.level is EvidenceLevel.CONFIRMED and evidence.reliability == "verified_objective"
        # A v3 policy may project immutable, previously trusted v2 receipts.
        # This is not a new receipt or a retroactive trust upgrade: all current
        # content/answer/source/grader guards below still run against live data.
        and (facts.get("policy_version") == policy.policy_version
            or policy.policy_version == 3 and facts.get("policy_version") == 2)
        and facts.get("question_provenance") in {"real_exam", "trusted_practice", "ai_generated_practice"}
        and trust_valid and source_valid and answer_provenance_valid
        and facts.get("answer_reliability") == "verified"
        and (auto_reviewed or facts.get("answer_verification_event_id"))
        and facts.get("grading_capability") == "deterministic" and method in supported.get(evidence.question_type, set())
        and facts.get("result") == "right" and facts.get("evidence_reliability") == "verified_objective"
        and facts.get("assisted") is False and facts.get("assistance_level") == "none"
        and facts.get("confidence") not in {"guess", "no_idea"}
        and facts.get("sequence_version") == "attempt-sequence-v1"
        and facts.get("sequence_category") in INDEPENDENT_CATEGORIES and facts.get("attempt_id")
        and all(isinstance(facts.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", facts[key])
            for key in ("answer_version_sha256", "question_content_sha256")))


def policy_confirmation_window(window, policy):
    if policy.policy_version == 1:
        return window
    by_id = {}
    for evidence in sorted(window, key=lambda e: e.occurred_at):
        if compatible_confirmation(evidence, policy):
            by_id[evidence.question_id] = evidence
    return tuple(by_id.values())
