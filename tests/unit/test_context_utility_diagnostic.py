import pytest

from scripts.run_ragas_chat_eval import context_utility_diagnostic


def metric(verdicts):
    return {"status": "scored", "value": 1.0, "diagnostics_complete": True,
            "diagnostic_context_count": len(verdicts),
            "diagnostics": [{"context_index": i, "verdict": v} for i, v in enumerate(verdicts)]}


def test_perfect_rank_precision_does_not_hide_eleven_irrelevant_chunks():
    data = metric([1] + [0] * 11)
    result = context_utility_diagnostic(data)
    assert result["useful_count"] == 1 and result["useful_fraction"] == 1 / 12
    assert result["rank_precision_can_hide_noise"]
    assert data["value"] == 1.0 and not result["score_adjusted"]


def test_zero_precision_is_retained_not_corrected_by_diagnostic():
    data = {**metric([0, 0]), "value": 0.0}
    result = context_utility_diagnostic(data)
    assert result["useful_fraction"] == 0 and not result["rank_precision_can_hide_noise"]
    assert data["value"] == 0


@pytest.mark.parametrize("override", [
    {"status": "error"}, {"diagnostics_complete": False}, {"diagnostic_context_count": 3},
    {"diagnostics": [{"context_index": 1, "verdict": 1}]},
    {"diagnostics": [{"context_index": 0, "verdict": True}]},
    {"diagnostics": [{"context_index": 0, "verdict": 2}]},
])
def test_partial_invalid_or_reordered_audit_is_not_relevance_proof(override):
    assert context_utility_diagnostic({**metric([1]), **override})["status"] == "unobserved"
