from pathlib import Path

import pytest

from scripts.run_isolated_chat_ragas import _case_selection
from scripts.run_ragas_chat_eval import load_cases


@pytest.mark.parametrize("mode", ["off", "filter"])
def test_screening_arm_locks_two_targets_and_one_setup(mode):
    ids, budget = _case_selection(cross_file_budget=None, file_focus_v4=False, context_screening_p6=mode)
    assert ids == ("math-followup", "408-page") and budget == 3
    selected = [c for c in load_cases(Path("eval/dataset/chat_baseline_v3_1.jsonl")) if c.case_id in ids]
    assert len(selected) == 2
    assert sum(1 + len(c.setup_questions) for c in selected) == 3
    from backend.chat.service import build_chat_retrieval_plan
    assert all(not build_chat_retrieval_plan(c.question, provider=None).diversify for c in selected)


@pytest.mark.parametrize("other", ["stage_scope_p6", "knowledge_followup_p6", "file_focus_v4", "cross_file_budget"])
def test_screening_arm_refuses_mixed_selection(other):
    kwargs = dict(cross_file_budget=None, file_focus_v4=False, context_screening_p6="filter")
    kwargs[other] = 4000 if other == "cross_file_budget" else True
    with pytest.raises(ValueError):
        _case_selection(**kwargs)


def test_shadow_is_not_a_real_filter_comparison_arm():
    with pytest.raises(ValueError):
        _case_selection(cross_file_budget=None, file_focus_v4=False, context_screening_p6="shadow")


@pytest.mark.parametrize("extra", [[], ["--limit", "1"], ["--stage-scope-p6"], ["--serve-ui"], ["--multifile-browser"]])
def test_screening_cli_refuses_incomplete_or_mixed_scope_before_external_tools(monkeypatch, tmp_path, extra):
    import sys
    from scripts import run_isolated_chat_ragas as runner
    base = ["runner", "--context-screening-p6", "filter"] if not extra else [
        "runner", "--context-screening-p6", "filter", "--baseline-v3-1", "--limit", "2",
        "--output", str(tmp_path / "new.json")]
    monkeypatch.setattr(sys, "argv", base + extra)
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2


def test_screening_cli_existing_report_fails_before_database(monkeypatch, tmp_path):
    import sys
    from scripts import run_isolated_chat_ragas as runner
    output = tmp_path / "frozen.json"
    output.write_text("frozen", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["runner", "--context-screening-p6", "off", "--baseline-v3-1",
                                    "--limit", "2", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2 and output.read_text(encoding="utf-8") == "frozen"


def test_p6_only_alias_with_one_setup_two_question_requests():
    ids, budget = _case_selection(cross_file_budget=None, file_focus_v4=False, stage_scope_p6=True)
    assert ids == ("file-alias",) and budget == 2
    selected = [c for c in load_cases(Path("eval/dataset/chat_baseline_v3_1.jsonl")) if c.case_id in ids]
    assert len(selected) == 1 and sum(1 + len(c.setup_questions) for c in selected) == budget


@pytest.mark.parametrize("cross_file,file_focus", [(4000, False), (None, True), (6000, True)])
def test_p6_refuses_mixed_paid_scope(cross_file, file_focus):
    with pytest.raises(ValueError, match="不得"):
        _case_selection(cross_file_budget=cross_file, file_focus_v4=file_focus, stage_scope_p6=True)


def test_existing_evaluation_selection_is_unchanged():
    assert _case_selection(cross_file_budget=None, file_focus_v4=False) == (None, None)
    assert _case_selection(cross_file_budget=None, file_focus_v4=True) == (("file-exact", "file-alias", "cross-file"), 4)


def test_knowledge_followup_selects_only_original_math_case_and_two_requests():
    ids, budget = _case_selection(cross_file_budget=None, file_focus_v4=False, knowledge_followup_p6=True)
    assert ids == ("math-followup",) and budget == 2
    selected = [c for c in load_cases(Path("eval/dataset/chat_baseline_v3_1.jsonl")) if c.case_id in ids]
    assert len(selected) == 1 and sum(1 + len(c.setup_questions) for c in selected) == budget


@pytest.mark.parametrize("other", ["stage_scope_p6", "file_focus_v4", "cross_file_budget"])
def test_knowledge_followup_refuses_any_other_paid_scope(other):
    kwargs = dict(cross_file_budget=None, file_focus_v4=False, knowledge_followup_p6=True)
    kwargs[other] = 4000 if other == "cross_file_budget" else True
    with pytest.raises(ValueError, match="不得"):
        _case_selection(**kwargs)
