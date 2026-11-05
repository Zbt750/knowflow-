from copy import deepcopy
from pathlib import Path
import subprocess
import sys

from scripts.audit_rag_answer_contract import replay_report


def test_direct_script_entrypoint_does_not_require_pythonpath():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/audit_rag_answer_contract.py"), "--help"],
        cwd=root, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "--output" in result.stdout


def test_replay_does_not_retrieve_or_modify_original_scores():
    report = {"cases": [{"case_id": "comparison", "question": "比较共同和独有",
        "answer": "| 数据保留 | 共同 | [C1] |", "metrics": {"faithfulness": 1.0},
        "actual_evidence": {"version": "actual-model-evidence-v2", "blocks": [
            {"label": "C1", "material_title": "甲"},
            {"label": "C2", "material_title": "乙"}]}}]}
    before = deepcopy(report)
    result = replay_report(report)
    assert report == before
    assert result["summary"]["flagged"] == 1
    assert result["external_calls"] == 0
    assert "answer" not in result["cases"][0]
    assert "blocks" not in result["cases"][0]
    assert result["semantic_correctness_proven"] is False


def test_missing_actual_snapshot_never_rebuilds_context():
    result = replay_report({"cases": [{"answer": "旧答案", "retrieved_contexts": ["片段"]}]})
    assert result["summary"]["unavailable"] == 1
    assert result["cases"][0]["reason"] == "actual_snapshot_or_full_answer_missing"


def test_unrecognized_prose_is_unobserved_not_passed():
    result = replay_report({"cases": [{"answer": "普通回答", "actual_evidence": {"blocks": []}}]})
    assert result["summary"]["unobserved"] == 1
    assert result["cases"][0]["observable_checks_passed"] is None
