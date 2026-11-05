import pytest
from backend.services.grading_basis import submission_grading_basis

@pytest.mark.parametrize("evidence,expected",[
    ({},"legacy_self_reported"),
    ({"method":"ai_answer_single_choice_v1","evidence_reliability":"ai_consistent_objective","assessment_basis":"legacy_self_reported"},"ai_consistent_reference_v1"),
    ({"method":"ai_answer_single_choice_v1","answer_provenance":"ai_generated","answer_reliability":"ai_generated_consistent"},"ai_consistent_reference_v1"),
    ({"method":"single_choice_v1","evidence_reliability":"verified_objective"},"objective_v1"),
    ({"method":"numeric_v1","grading_config":{"verified":True},"assessment_basis":"objective_v1"},"objective_v1"),
    ({"method":"untrusted_reference_v1","result":"unknown"},"ungraded"),
])
def test_submission_basis_preserves_answer_trust_and_legacy_semantics(evidence,expected):
    assert submission_grading_basis(evidence)==expected
