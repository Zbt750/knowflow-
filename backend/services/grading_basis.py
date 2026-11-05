"""Submission grading basis is distinct from the node's mastery projection basis."""


def submission_grading_basis(evidence: dict) -> str:
    method = evidence.get("method", "")
    reliability = evidence.get("evidence_reliability")
    if method.startswith("ai_answer_") and (
        reliability == "ai_consistent_objective"
        or (evidence.get("answer_provenance") == "ai_generated"
            and evidence.get("answer_reliability") == "ai_generated_consistent")
    ):
        return "ai_consistent_reference_v1"
    if reliability == "verified_objective":
        return "objective_v1"
    # New receipts record their reliability explicitly. A legacy node projection
    # must not upgrade an ungraded/auxiliary submission's own grading basis.
    if isinstance(evidence.get("version"), int) and evidence["version"] >= 4:
        return "ungraded"
    if (evidence.get("assessment_basis") == "objective_v1"
        and isinstance(evidence.get("grading_config"), dict)
        and evidence["grading_config"].get("verified") is True
        and method and not method.startswith("ai_")):
        return "objective_v1"
    if not evidence:
        return "legacy_self_reported"
    return "ungraded"
