from scripts.audit_question_production import is_evidence_eligible_capability


def test_audit_counts_ai_consistent_objective_as_evidence_eligible_without_renaming_tier():
    assert is_evidence_eligible_capability("ai_consistent_objective")
    assert is_evidence_eligible_capability("verified_objective")
    assert not is_evidence_eligible_capability("ai_low_reliability")
    assert not is_evidence_eligible_capability("process_review_not_objective_evidence")


def test_audit_keeps_historical_answer_comparison_capability_compatible():
    assert is_evidence_eligible_capability("ai_answer_comparison_only")
    assert not is_evidence_eligible_capability(None)
