from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import zipfile

import pytest

from scripts import freeze_current_rag_baseline as baseline


def row():
    context = "[C1] synthetic evidence"
    return {
        "case_id": "bad-case", "answer": "answer", "manual_review": {"status": "pending"},
        "actual_evidence": {"version": "actual-model-evidence-v2", "request_id": "m1",
                            "contexts": [context], "blocks": [{"label": "C1", "chunk_id": "c1", "context": context}],
                            "citations": {"C1": "c1"}, "evidence_sha256": sha256(context.encode()).hexdigest(),
                            "model_called": True},
        "metrics": {"context_precision": {"status": "scored", "value": 0},
                    "faithfulness": {"status": "error", "error_type": "TimeoutError"},
                    "context_recall": {"status": "skipped"}},
        "total_latency_ms": 41000,
        "generation_trace": {"request_id": "m1", "retry_count": 1,
                             "observed_usage": {"total_tokens": 42}, "total_usage_complete": False,
                             "calls": [{"status": "failed", "finish_reason": "length"}, {"status": "completed"}]},
    }


def current():
    return {"workspace_file_sha256": {"backend/chat/service.py": "current"}, "prompt_version": "v5",
            "model": "synthetic-model", "model_parameters": {}, "dataset_sha256": "dataset"}


def test_preserves_zero_failures_slow_cases_retries_and_partial_usage():
    original = row()
    result = baseline.case_record(original)
    assert result["snapshot_audit"]["status"] == "valid"
    assert result["metrics"] == original["metrics"]
    assert result["manual_review"] == {"status": "pending"}
    assert result["generation_trace"]["observed_usage"]["total_tokens"] == 42
    assert {"judge_error", "zero_context_precision", "over_30_seconds", "retried",
            "output_limit_attempt", "incomplete_usage"} <= set(result["flags"])
    assert "answer" not in result and "contexts" not in result["snapshot_audit"]


@pytest.mark.parametrize("tamper", ["request", "context", "citations"])
def test_snapshot_tamper_is_retained_as_invalid(tamper):
    sample = row()
    if tamper == "request":
        sample["generation_trace"]["request_id"] = "different"
    elif tamper == "context":
        sample["actual_evidence"]["contexts"][0] = "changed"
    else:
        sample["actual_evidence"]["citations"]["C1"] = "wrong"
    result = baseline.case_record(sample)
    assert result["snapshot_audit"]["status"] == "invalid"
    assert result["case_id"] == "bad-case"


def test_failed_request_uses_saved_diagnostic_not_retrieval():
    original = row()
    failed = {"case_id": "failed", "error_type": "EvalError", "failure_diagnostic": {
        "message_id": "m1", "total_ms": 2500, "actual_evidence": original["actual_evidence"],
        "generation_trace": original["generation_trace"]}}
    result = baseline.case_record(failed)
    assert result["snapshot_audit"]["status"] == "valid"
    assert result["error_type"] == "EvalError"
    assert result["metrics"] == {}
    assert result["failed_request_total_ms"] == 2500


def test_missing_trace_does_not_claim_independent_request_binding():
    sample = row()
    sample.pop("generation_trace")
    assert baseline.case_record(sample)["snapshot_audit"]["request_id_binding"] == "snapshot_only"


def test_changed_source_with_same_prompt_label_is_not_current_score():
    now = current()
    before = deepcopy(now)
    before["workspace_file_sha256"]["backend/chat/service.py"] = "old"
    result = baseline.report_record("old.json", {"evaluation_configuration": before, "cases": [row()]}, now)
    assert result["classification"] == "historical_not_current_measurement"
    assert result["recomputed_metrics"]["context_precision"] == {"n": 1, "mean": 0, "min": 0}
    assert result["recomputed_metrics"]["faithfulness"]["n"] == 0


def test_checkpoint_duplicate_is_not_an_independent_sample(monkeypatch):
    monkeypatch.setattr(baseline, "REPORTS", ("final.json",))
    monkeypatch.setattr(baseline, "CHECKPOINTS", {"checkpoint.json": "final.json"})
    report = {"evaluation_configuration": current(), "cases": [row()]}
    result = baseline.build_audit(current(), {"final.json": report}, {"checkpoint.json": deepcopy(report)})
    assert len(result["reports"]) == 1
    assert result["duplicate_checkpoints"][0]["included_as_independent_samples"] is False
    assert all(v["value"] is None for v in result["current_metrics"].values())
    changed = deepcopy(report)
    changed["cases"][0]["answer"] = "different"
    with pytest.raises(ValueError, match="cannot deduplicate"):
        baseline.build_audit(current(), {"final.json": report}, {"checkpoint.json": changed})


@pytest.mark.parametrize("name", [".env", ".env.example", "storage/config/model-settings.bin",
                                  "storage/uploads/private.md", ".git/config", ".venv-ragas/pyvenv.cfg"])
def test_secret_and_runtime_files_not_archived(name):
    assert not baseline.source_path(name)


def test_freeze_archives_inputs_without_overwriting_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    monkeypatch.setattr(baseline, "REPORTS", ("final.json",))
    monkeypatch.setattr(baseline, "CHECKPOINTS", {})
    now = current()
    now["workspace_file_sha256"] = {}
    monkeypatch.setattr(baseline, "collect_current", lambda: now)
    reports_dir = tmp_path / "eval/reports"
    reports_dir.mkdir(parents=True)
    original = {"evaluation_configuration": now, "cases": [row()]}
    path = reports_dir / "final.json"
    path.write_text(json.dumps(original), encoding="utf-8")
    body = path.read_bytes()
    result = baseline.freeze(reports_dir / "frozen")
    assert result["live_calls_performed"] == 0
    with zipfile.ZipFile(reports_dir / "frozen/reproduction-inputs.zip") as bundle:
        assert bundle.read("historical-reports/final.json") == body
    assert path.read_bytes() == body
    with pytest.raises(FileExistsError):
        baseline.freeze(reports_dir / "frozen")
    with pytest.raises(ValueError, match="new subdirectory"):
        baseline.freeze(tmp_path / "outside")
