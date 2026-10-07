from pathlib import Path
import sys

import pytest

from scripts import run_isolated_chat_ragas as runner
from scripts.run_ragas_chat_eval import load_cases


def test_six_targets_and_two_setups_are_exactly_eight_requests():
    ids, budget = runner._case_selection(cross_file_budget=None, file_focus_v4=False, current_v8_closeout=True)
    assert set(ids) == {"math-followup", "408-page", "file-exact", "file-alias", "cross-file", "missing-reference"}
    cases = [c for c in load_cases(Path("eval/dataset/chat_baseline_v3_1.jsonl")) if c.case_id in ids]
    assert len(cases) == 6
    assert sum(1 + len(c.setup_questions) for c in cases) == budget == 8


@pytest.mark.parametrize("other", ["cross_file_budget", "file_focus_v4", "stage_scope_p6", "knowledge_followup_p6", "context_screening_p6"])
def test_selection_refuses_mixed_paid_scope(other):
    kwargs = dict(cross_file_budget=None, file_focus_v4=False, current_v8_closeout=True)
    kwargs[other] = "filter" if other == "context_screening_p6" else 4000 if other == "cross_file_budget" else True
    with pytest.raises(ValueError, match="不得"):
        runner._case_selection(**kwargs)


@pytest.mark.parametrize("extra", [["--limit", "5"], ["--serve-ui"], ["--context-screening-p6", "off"], ["--stage-scope-p6"], ["--multifile-browser"]])
def test_cli_scope_is_checked_before_external_activity(monkeypatch, tmp_path, extra):
    monkeypatch.setattr(sys, "argv", ["runner", "--current-v8-closeout", "--baseline-v3-1", "--limit", "6", "--output", str(tmp_path / "new.json")] + extra)
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2


def test_cli_requires_explicit_dataset_limit_and_new_report(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["runner", "--current-v8-closeout"])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2


def test_existing_report_is_never_overwritten(monkeypatch, tmp_path):
    output = tmp_path / "frozen.json"
    output.write_text("frozen", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["runner", "--current-v8-closeout", "--baseline-v3-1", "--limit", "6", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert output.read_text(encoding="utf-8") == "frozen"
