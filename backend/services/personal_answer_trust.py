"""Narrow trust predicate for personal-answer FSRS scheduling.

This permits an independently verified answer to schedule its own version
without treating the personal question as BKT or graduation evidence.
"""


def personal_answer_independently_verified(question, node) -> bool:
    if (question is None or node is None
            or getattr(question, "bank_scope", None) != "personal"
            or getattr(question, "question_provenance", None) != "ai_generated_practice"
            or getattr(question, "answer_provenance", None) != "ai_generated"):
        return False
    config = getattr(question, "grading_config", None)
    record = config.get("generation") if isinstance(config, dict) else None
    if not isinstance(record, dict):
        return False
    # The immutable QuestionVersion hook runs the independent math gate again.
    # A generation record alone cannot replace its persisted verifier result.
    verification = config.get("math_verification") if isinstance(config, dict) else None
    if not isinstance(verification, dict) or verification.get("status") != "verified":
        return False
    if record.get("prompt_version") not in {
        "question-generation-c4-v1", "question-generation-c7-v1",
    }:
        return False
    independent = record.get("independent_verification")
    if (record.get("answer_independently_verified") is not True
            or not isinstance(independent, dict)
            or independent.get("status") != "PASS"
            or record.get("review_status") not in {
                "AUTO_PASS", "ANSWER_VERIFIED_EXPLANATION_REFERENCE_ONLY",
            }):
        return False
    from backend.services.question_generation import current_generation_binding
    return bool(current_generation_binding(question, node))
