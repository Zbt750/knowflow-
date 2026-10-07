import sys
from pathlib import Path

import pytest

from scripts import run_isolated_chat_ragas as runner
from scripts.run_ragas_chat_eval import load_cases


def test_fixed_two_targets_and_one_setup():
    ids, budget = runner._case_selection(cross_file_budget=None, file_focus_v4=False, repairs_v9=True)
    assert ids == ("math-followup", "cross-file") and budget == 3
    cases = [c for c in load_cases(Path("eval/dataset/chat_baseline_v3_1.jsonl")) if c.case_id in ids]
    assert len(cases) == 2 and sum(1 + len(c.setup_questions) for c in cases) == 3


@pytest.mark.parametrize("other", ["current_v8_closeout", "cross_file_budget", "file_focus_v4", "stage_scope_p6", "knowledge_followup_p6", "context_screening_p6"])
def test_selection_refuses_other_paid_modes(other):
    kwargs = dict(cross_file_budget=None, file_focus_v4=False, repairs_v9=True)
    kwargs[other] = "filter" if other == "context_screening_p6" else 4000 if other == "cross_file_budget" else True
    with pytest.raises(ValueError, match="不得"):
        runner._case_selection(**kwargs)


@pytest.mark.parametrize("extra", [["--limit", "3"], ["--current-v8-closeout"], ["--serve-ui"], ["--context-screening-p6", "off"], ["--multifile-browser"]])
def test_cli_rejects_mixed_scope_before_database(monkeypatch, tmp_path, extra):
    monkeypatch.setattr(sys, "argv", ["runner", "--repairs-v9", "--baseline-v3-1", "--limit", "2", "--output", str(tmp_path / "new.json")] + extra)
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2


def test_existing_report_is_unchanged(monkeypatch, tmp_path):
    output = tmp_path / "frozen.json"
    output.write_text("original", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["runner", "--repairs-v9", "--baseline-v3-1", "--limit", "2", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2 and output.read_text(encoding="utf-8") == "original"


def test_prompt_version_drift_is_rejected_before_database(monkeypatch, tmp_path):
    from backend.chat import call_trace
    monkeypatch.setattr(call_trace, "PROMPT_VERSION", "future-version")
    monkeypatch.setattr(sys, "argv", ["runner", "--repairs-v9", "--baseline-v3-1", "--limit", "2", "--output", str(tmp_path / "new.json")])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
