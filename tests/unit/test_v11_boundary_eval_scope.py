from pathlib import Path
import sys

import pytest
from scripts import run_isolated_chat_ragas as runner
from scripts.run_ragas_chat_eval import load_cases


def test_v11_has_three_targets_and_one_setup_only():
    ids, budget = runner._case_selection(cross_file_budget=None, file_focus_v4=False, v11_boundary=True)
    cases = [c for c in load_cases(Path("eval/dataset/chat_baseline_v3_1.jsonl")) if c.case_id in ids]
    assert set(ids) == {"missing-reference", "file-alias", "408-page"}
    assert len(cases) == 3 and sum(1 + len(c.setup_questions) for c in cases) == budget == 4


@pytest.mark.parametrize("extra", [["--limit", "4"], ["--serve-ui"], ["--current-v10-closeout"]])
def test_v11_rejects_expansion_before_external_activity(monkeypatch, tmp_path, extra):
    monkeypatch.setattr(sys, "argv", ["runner", "--v11-boundary", "--baseline-v3-1", "--limit", "3",
                                    "--output", str(tmp_path / "new.json"), *extra])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2


def test_v11_preserves_existing_evidence(monkeypatch, tmp_path):
    output = tmp_path / "old.json"
    output.write_text("old", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["runner", "--v11-boundary", "--baseline-v3-1", "--limit", "3", "--output", str(output)])
    with pytest.raises(SystemExit):
        runner.main()
    assert output.read_text(encoding="utf-8") == "old"


def test_v11_checks_prompt_version_before_database_activity(monkeypatch, tmp_path):
    from backend.chat import call_trace
    monkeypatch.setattr(call_trace, "PROMPT_VERSION", "future-version")
    monkeypatch.setattr(sys, "argv", ["runner", "--v11-boundary", "--baseline-v3-1", "--limit", "3", "--output", str(tmp_path / "new.json")])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
