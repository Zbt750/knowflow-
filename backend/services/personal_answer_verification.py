"""Persist an independent, version-bound machine answer proof.

This is intentionally separate from human answer attestations and public
quality qualification. An event with status ``verified`` proves only the
answer for this exact personal question version.
"""
from __future__ import annotations

from hashlib import sha256
from sqlalchemy import select

from backend.models.learning import PersonalAnswerVerificationEvent, QuestionVersion
from backend.services.answer_verification import answer_version_sha256
from backend.services.question_generation import current_generation_binding
from backend.services.quality_verifiers import verify_problem, VERSION as VERIFIER_VERSION


def record_personal_answer_verification(db, question, node) -> PersonalAnswerVerificationEvent:
    version_id = getattr(question, "current_version_id", None)
    version = db.get(QuestionVersion, version_id) if version_id else None
    if version is None or version.question_id != question.id:
        raise ValueError("personal_answer_verification_version_missing")

    try:
        actual = verify_problem(question)
    except Exception as exc:  # Fail closed; preserve a typed uncertainty event.
        actual = {"status": "ERROR", "reason": "independent_verifier_error",
                  "error_type": type(exc).__name__}
    actual = actual if isinstance(actual, dict) else {"status": "UNKNOWN", "reason": "verifier_result_missing"}
    generation = (question.grading_config or {}).get("generation")
    generation = generation if isinstance(generation, dict) else {}
    expected = generation.get("independent_verification")
    expected = expected if isinstance(expected, dict) else {}
    eligible_review = generation.get("review_status") in {
        "AUTO_PASS", "ANSWER_VERIFIED_EXPLANATION_REFERENCE_ONLY",
    }
    binding_current = bool(eligible_review and generation.get("answer_independently_verified") is True
        and current_generation_binding(question, node))
    verified = bool(binding_current and actual.get("status") == "PASS"
        and expected.get("status") == "PASS"
        and actual.get("adapter") == expected.get("adapter")
        and actual.get("proof") == expected.get("proof"))
    status = "verified" if verified else "rejected" if actual.get("status") == "FAIL" else "needs_review"
    adapter = str(actual.get("adapter") or expected.get("adapter") or "unsupported")[:120]
    answer_sha = answer_version_sha256(question)
    key_source = f"{version.id}:{version.content_hash}:{answer_sha}:{VERIFIER_VERSION}:{adapter}:{status}"
    idempotency_key = sha256(key_source.encode("utf-8")).hexdigest()
    existing = db.scalar(select(PersonalAnswerVerificationEvent).where(
        PersonalAnswerVerificationEvent.idempotency_key == idempotency_key))
    if existing is not None:
        if (existing.question_id != question.id or existing.question_version_id != version.id
                or existing.question_snapshot_sha256 != version.content_hash
                or existing.answer_sha256 != answer_sha or existing.status != status):
            raise ValueError("personal_answer_verification_idempotency_conflict")
        return existing

    event = PersonalAnswerVerificationEvent(
        question_id=question.id,
        question_version_id=version.id,
        question_snapshot_sha256=version.content_hash,
        answer_sha256=answer_sha,
        verifier_version=VERIFIER_VERSION,
        adapter=adapter,
        status=status,
        proof={"independent_verification": actual,
               "generation_review_status": generation.get("review_status"),
               "answer_independently_verified_claim": generation.get("answer_independently_verified") is True},
        idempotency_key=idempotency_key,
    )
    db.add(event)
    db.flush()
    return event
