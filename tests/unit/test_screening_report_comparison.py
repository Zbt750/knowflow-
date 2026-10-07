from copy import deepcopy
from hashlib import sha256

import pytest

from backend.chat.context_screening import POLICY_VERSION
from scripts.compare_screening_reports import compare


def report(mode):
    config = {"dataset_sha256": "fixed", "model": "synthetic", "model_parameters": {},
              "embedding_model": "synthetic", "reranker_model": None, "prompt_version": "v6",
              "snapshot_version": "actual-model-evidence-v2", "retrieval_configuration": {},
              "workspace_file_sha256": {"backend/chat/service.py": "same"},
              "context_screening_configuration": {"mode": mode}, "selected_case_ids": ["408-page", "math-followup"],
              "planned_question_requests": 3, "question_request_limit": 3}
    contexts = ["synthetic evidence"]
    diagnostic = {"version": POLICY_VERSION, "threshold": 0.5, "mode": mode,
                  "before_count": 2 if mode == "filter" else 1, "after_count": 1,
                  "removed_count": 1 if mode == "filter" else 0, "would_remove_count": 1 if mode == "filter" else 0,
                  "applied": mode == "filter", "reason": "eligible" if mode == "filter" else "disabled"}
    cases = []
    for cid in ("408-page", "math-followup"):
        snap = {"version": "actual-model-evidence-v2", "request_id": cid, "contexts": contexts,
                "blocks": [{"label": "C1", "chunk_id": cid, "context": contexts[0]}],
                "citations": {"C1": cid}, "evidence_sha256": sha256(contexts[0].encode()).hexdigest(),
                "context_screening": diagnostic}
        cases.append({"case_id": cid, "actual_evidence": snap,
                      "generation_trace": {"request_id": cid, "retry_count": 0,
                          "observed_usage": {"total_tokens": 10}, "calls": [{"finish_reason": "stop"}]},
                      "metrics": {"context_precision": {"status": "scored", "value": 0,
                          "diagnostics": [{"verdict": 0}], "diagnostics_complete": True}},
                      "setup_results": [{"usage": {"total_tokens": 5}}] if cid == "math-followup" else []})
    return {"evaluation_configuration": config, "cases": cases}


def test_pair_preserves_low_scores_and_source_reports():
    off, filtered = report("off"), report("filter")
    originals = deepcopy((off, filtered))
    result = compare(off, filtered)
    assert (off, filtered) == originals
    assert result["additional_model_calls"] == 0
    assert result["generation_usage"]["off"]["observed_generation_tokens_including_setup"] == 25
    assert result["cases"][0]["arms"]["off"]["metrics"]["context_precision"]["value"] == 0


@pytest.mark.parametrize("field", ["dataset_sha256", "model", "model_parameters", "embedding_model", "prompt_version"])
def test_incompatible_provenance_is_not_averaged(field):
    off, filtered = report("off"), report("filter")
    filtered["evaluation_configuration"][field] = "changed"
    with pytest.raises(ValueError):
        compare(off, filtered)


def test_backend_source_change_is_rejected():
    off, filtered = report("off"), report("filter")
    filtered["evaluation_configuration"]["workspace_file_sha256"]["backend/chat/service.py"] = "changed"
    with pytest.raises(ValueError):
        compare(off, filtered)


def test_missing_case_and_budget_expansion_cannot_be_hidden():
    off, filtered = report("off"), report("filter")
    filtered["cases"].pop()
    with pytest.raises(ValueError):
        compare(off, filtered)
    filtered = report("filter")
    filtered["evaluation_configuration"]["planned_question_requests"] = 4
    with pytest.raises(ValueError):
        compare(off, filtered)


def test_unobserved_setup_usage_is_not_treated_as_zero_complete():
    off, filtered = report("off"), report("filter")
    off["cases"][1]["setup_results"][0]["usage"] = None
    assert not compare(off, filtered)["generation_usage"]["off"]["all_turn_usage_available_in_this_arm"]
