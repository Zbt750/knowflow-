from backend.services.learning_assistant_service import (
    _bank_confirmation_kind,
    _question_matches_confirmation,
    _select_bank_confirmation,
)


def proposal(task_id="task-1", *, status="ready", committed=False, current=True, stem="曲线 x^2+xy+y^2=3 求导"):
    return {
        "task_id": task_id,
        "draft_version": f"version-{task_id}",
        "draft": {"questions": [{"question_id": "question-1", "question_version": "version-q1", "stem": stem}]},
        "status": status,
        "committed": committed,
        "current": current,
    }


def test_confirmation_language_is_distinguished_from_unrelated_acknowledgement():
    assert _bank_confirmation_kind("确认") == "bare"
    assert _bank_confirmation_kind("就这题吧给我放在今日卷") == "explicit"
    assert _bank_confirmation_kind("洛必达法则的适用条件是什么？") is None


def test_unique_same_session_preview_resolves_bare_and_explicit_formula_confirmation():
    candidate = proposal()
    target, notice, resolution = _select_bank_confirmation([candidate], "确认")
    assert target is candidate and notice is None and resolution == "pending"

    target, notice, resolution = _select_bank_confirmation(
        [candidate], "加入预览的 (x^2+xy+y^2=3) 那道题"
    )
    assert target is candidate and notice is None and resolution == "pending"


def test_formula_mismatch_partial_multi_question_and_multiple_previews_are_not_guessed():
    candidate = proposal()
    target, notice, resolution = _select_bank_confirmation([candidate], "加入预览的 (y=sin x) 那道题")
    assert target is None and resolution == "mismatch" and "没有加入今日卷" in notice

    multi = proposal()
    multi["draft"]["questions"].append({"question_id": "question-2", "question_version": "version-q2", "stem": "另一题"})
    target, notice, resolution = _select_bank_confirmation([multi], "加入预览的 (x^2+xy+y^2=3) 那道题")
    assert target is None and resolution == "partial_selection" and "单题预览" in notice

    target, notice, resolution = _select_bank_confirmation([proposal("a"), proposal("b")], "确认")
    assert target is None and resolution == "ambiguous" and "多个有效" in notice


def test_missing_stale_and_already_committed_previews_have_distinct_outcomes():
    target, notice, resolution = _select_bank_confirmation([], "确认")
    assert target is None and resolution == "missing" and "没有可确认" in notice

    stale = proposal(status="cancelled", current=True)
    target, notice, resolution = _select_bank_confirmation([stale], "确认")
    assert target is None and resolution == "stale" and "已取消" in notice

    committed = proposal(status="answered", committed=True)
    target, notice, resolution = _select_bank_confirmation([committed], "确认")
    assert target is committed and notice is None and resolution == "committed"


def test_question_reference_compares_formula_without_losing_the_original_preview_text():
    assert _question_matches_confirmation("求 \u5bfc数 x^2+xy+y^2=3 的 y'", "加到今日卷 (x^2+xy+y^2=3)")
    assert not _question_matches_confirmation("曲线 y=sin x", "加入预览的 (x^2+xy+y^2=3) 那道题")
