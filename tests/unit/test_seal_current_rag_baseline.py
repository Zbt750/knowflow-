from copy import deepcopy

import pytest

from scripts.freeze_current_rag_baseline import SAFE_CONFIG
from scripts.seal_current_rag_baseline import build_measurement


def inputs():
    current = {key: {} if key in ("model_parameters", "retrieval_configuration") else "fixed" for key in SAFE_CONFIG}
    current.update(workspace_file_sha256={"backend/chat/service.py": "same"}, dataset_cases=[{"id": "failure"}],
                   endpoint_sha256="endpoint", fixture_sha256={"fixture": "hash"}, expected_judge_configuration={"model": "same"})
    audit = {"current_manifest": deepcopy(current), "reports": [{"original_failure": True}],
             "duplicate_checkpoints": [], "legacy_inventory": [], "limitations": ["old current measurement absent", "human pending"]}
    manifest = deepcopy(current)
    manifest.update(planned_question_requests=18, question_request_limit=18)
    raw = {"summary": {"case_errors": 1}, "evaluation_configuration": manifest,
           "cases": [{"case_id": "failure", "error_type": "EvalError"}]}
    review = {"human_review_status": "pending", "case_reviews": [{"case_id": "failure"}]}
    return audit, raw, review, current


def test_keeps_failure_and_does_not_claim_quality_pass():
    result = build_measurement(*inputs())
    assert result["measurement"]["cases"][0]["error_type"] == "EvalError"
    assert result["quality_pass_claimed"] is False
    assert result["p1_started"] is False
    assert result["usage"]["monetary_total"] is None
    assert result["historical_evidence"][0]["original_failure"] is True


@pytest.mark.parametrize("change", ["checkpoint", "case_filter", "request_limit", "prompt", "source", "endpoint", "human_verified"])
def test_refuses_incomplete_filtered_or_changed_run(change):
    audit, raw, review, current = inputs()
    if change == "checkpoint": raw["status"] = "in_progress"
    elif change == "case_filter": raw["cases"] = []
    elif change == "request_limit": raw["evaluation_configuration"]["question_request_limit"] = 20
    elif change == "prompt": current["prompt_version"] = "changed"
    elif change == "source": current["workspace_file_sha256"]["backend/chat/service.py"] = "changed"
    elif change == "endpoint": current["endpoint_sha256"] = "different"
    elif change == "human_verified": review["human_review_status"] = "verified"
    with pytest.raises(ValueError):
        build_measurement(audit, raw, review, current)


def test_keeps_zero_score_and_judge_verdict_fraction_without_score_adjustment():
    from tests.unit.test_current_rag_baseline import row
    audit, raw, review, current = inputs()
    sample = row()
    sample["case_id"] = "failure"
    sample["metrics"]["context_precision"].update(diagnostics_complete=True, diagnostics=[{"verdict": 0}])
    sample["first_useful_body_ms"] = 100
    raw["cases"] = [sample]
    result = build_measurement(audit, raw, review, current)
    case = result["measurement"]["cases"][0]
    assert case["metrics"]["context_precision"]["value"] == 0
    assert case["precision_block_diagnostic"]["positive_fraction"] == 0
    assert "judge-verdict diagnostic" in case["precision_block_diagnostic"]["meaning"]
    assert "incomplete_usage" in case["flags"]
    assert case["manual_review"]["status"] == "pending"


def test_scored_snapshot_tampering_blocks_seal():
    from tests.unit.test_current_rag_baseline import row
    audit, raw, review, current = inputs()
    sample = row()
    sample["case_id"] = "failure"
    sample["actual_evidence"]["contexts"] = ["tampered"]
    raw["cases"] = [sample]
    with pytest.raises(ValueError, match="valid actual evidence"):
        build_measurement(audit, raw, review, current)
