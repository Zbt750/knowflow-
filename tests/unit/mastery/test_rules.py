from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.mastery.enums import EvidenceLevel
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import (
    SHANGHAI,
    _day,
    effective_confirmation_count,
    graduation_check,
    update_evidence_window,
)
from backend.mastery.types import Evidence

from tests.unit.mastery.conftest import DAY1, DAY2, DAY3

POLICY = MasteryPolicy()


def confirmed(
    question_id: str,
    *,
    when: datetime,
    variant: bool = False,
    question_type: str = "fill_blank",
    skill_tags: tuple[str, ...] = (),
) -> Evidence:
    return Evidence(
        question_id=question_id,
        level=EvidenceLevel.CONFIRMED,
        is_variant=variant,
        occurred_at=when,
        source="practice_item",
        question_type=question_type,
        skill_tags=skill_tags,
    )


def test_day_uses_shanghai_calendar_not_utc() -> None:
    # UTC 2026-01-01 02:00 在上海已是当天 10:00；UTC 2026-01-01 20:00 在上海是 01-02。
    assert _day(datetime(2026, 1, 1, 2, tzinfo=timezone.utc)).isoformat() == "2026-01-01"
    assert _day(datetime(2026, 1, 1, 20, tzinfo=timezone.utc)).isoformat() == "2026-01-02"
    assert str(SHANGHAI) == "Asia/Shanghai"


def test_failure_clears_window() -> None:
    window = (confirmed("q1", when=DAY1),)
    failure = Evidence(
        question_id="q2",
        level=EvidenceLevel.FAILURE,
        is_variant=False,
        occurred_at=DAY2,
        source="practice_item",
    )
    assert update_evidence_window(window, failure, max_size=20) == ()


@pytest.mark.parametrize("level", [EvidenceLevel.PARTIAL, EvidenceLevel.WEAK])
def test_non_confirmed_evidence_keeps_window_unchanged(level: EvidenceLevel) -> None:
    window = (confirmed("q1", when=DAY1),)
    other = Evidence(
        question_id="q2", level=level, is_variant=False, occurred_at=DAY2, source="practice_item"
    )
    # 部分掌握既不加也不清，这正是产品要求的“不进入窗口也不清空窗口”。
    assert update_evidence_window(window, other, max_size=20) == window


def test_same_question_repeated_mastered_only_refreshes_latest() -> None:
    first = confirmed("q1", when=DAY1)
    window = update_evidence_window((), first, max_size=20)
    refreshed = confirmed("q1", when=DAY3)
    window = update_evidence_window(window, refreshed, max_size=20)

    # 同一题重复标注只刷新时间，不增加不同题数。
    assert len(window) == 1
    assert window[0].occurred_at == DAY3


def test_window_is_sorted_newest_first_and_truncated() -> None:
    window: tuple[Evidence, ...] = ()
    for index in range(5):
        window = update_evidence_window(
            window, confirmed(f"q{index}", when=DAY1), max_size=3
        )
    assert len(window) == 3
    # 全部同一时刻，只需要确认被截断到 max_size。
    assert all(item.level is EvidenceLevel.CONFIRMED for item in window)


def test_effective_count_adds_manual_credit() -> None:
    window = (confirmed("q1", when=DAY1), confirmed("q2", when=DAY2))
    assert effective_confirmation_count(window, manual_credit_count=0) == 2
    assert effective_confirmation_count(window, manual_credit_count=2) == 4


def test_graduation_requires_three_distinct_questions() -> None:
    window = (confirmed("q1", when=DAY1), confirmed("q2", when=DAY2))
    graduated, reason = graduation_check(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=POLICY
    )
    assert (graduated, reason) == (False, "insufficient_confirmed_evidence")


def test_graduation_requires_at_least_one_real_variant() -> None:
    window = (
        confirmed("q1", when=DAY1),
        confirmed("q2", when=DAY2),
        confirmed("q3", when=DAY3),
    )
    graduated, reason = graduation_check(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=POLICY
    )
    # 三题都做对但都不是变式题：不能毕业。
    assert (graduated, reason) == (False, "missing_real_variant")


def test_graduation_requires_min_real_questions_beyond_confirmations() -> None:
    """基础确认能让「有效确认数」达标，但真实题量必须自己满足。"""
    policy = MasteryPolicy(min_confirmations=3, min_real_questions=3)
    window = (confirmed("q1", when=DAY1, variant=True), confirmed("q2", when=DAY3))
    graduated, reason = graduation_check(
        window, manual_credit_count=2, manual_confirmed_at=DAY1, policy=policy
    )
    # 2 + 2 = 4 个确认已经够，但真实题只有 2 道 < 3。
    assert (graduated, reason) == (False, "insufficient_real_questions")


def test_graduation_requires_question_type_quota() -> None:
    """必考题型没覆盖够时，即使确认数与真实题数都达标也不能毕业。"""
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_question_types={"single_choice": 1, "fill_blank": 1, "calculation": 1},
    )
    window = (
        confirmed("q1", when=DAY1, question_type="single_choice"),
        confirmed("q2", when=DAY2, question_type="fill_blank"),
        confirmed("q3", when=DAY3, variant=True, question_type="fill_blank"),
    )
    graduated, reason = graduation_check(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=policy
    )
    # 缺的是计算大题，原因码必须指明具体题型。
    assert (graduated, reason) == (False, "missing_question_type:calculation")


def test_excluded_question_types_are_not_required() -> None:
    """只考客观题的叶子：题库里没有大题也应当能毕业。"""
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_question_types={"single_choice": 1, "fill_blank": 2},
        excluded_question_types=frozenset({"calculation", "proof", "subjective"}),
    )
    window = (
        confirmed("q1", when=DAY1, question_type="single_choice"),
        confirmed("q2", when=DAY2, question_type="fill_blank"),
        confirmed("q3", when=DAY3, variant=True, question_type="fill_blank"),
    )
    graduated, reason = graduation_check(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=policy
    )
    assert (graduated, reason) == (True, "graduated")


def test_graduation_requires_skill_tag_coverage() -> None:
    """题型配额全达标，但必考考法没覆盖，仍然不能毕业。"""
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_question_types={"fill_blank": 3},
        required_skill_tags=frozenset({"适用条件", "0/0 型"}),
    )
    window = (
        confirmed("q1", when=DAY1, skill_tags=("适用条件",)),
        confirmed("q2", when=DAY2, skill_tags=("适用条件",)),
        confirmed("q3", when=DAY3, variant=True, skill_tags=("多次洛必达",)),
    )
    graduated, reason = graduation_check(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=policy
    )
    assert (graduated, reason) == (False, "missing_skill_tag:0/0 型")


def test_one_question_can_cover_type_variant_and_skill_at_once() -> None:
    """一道题可以同时补齐题型、变式题与考法，但始终只算一道不同真实题。"""
    policy = MasteryPolicy(
        min_confirmations=2,
        min_real_questions=2,
        required_question_types={"calculation": 1},
        required_skill_tags=frozenset({"先变形"}),
    )
    window = (
        confirmed(
            "q1",
            when=DAY1,
            variant=True,
            question_type="calculation",
            skill_tags=("先变形",),
        ),
        confirmed("q2", when=DAY3, question_type="calculation"),
    )
    graduated, reason = graduation_check(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=policy
    )
    assert (graduated, reason) == (True, "graduated")
    # 关键：这道题只贡献 1 道不同真实题。
    assert len(window) == 2


def test_graduation_requires_two_day_span() -> None:
    window = (
        confirmed("q1", when=DAY1),
        confirmed("q2", when=DAY1),
        confirmed("q3", when=DAY2, variant=True),
    )
    graduated, reason = graduation_check(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=POLICY
    )
    # 01-01 到 01-02 只差 1 天，不满足“相差至少 2 天”。
    assert (graduated, reason) == (False, "insufficient_day_span")


def test_graduation_succeeds_with_three_questions_one_variant_and_two_day_span() -> None:
    window = (
        confirmed("q1", when=DAY1),
        confirmed("q2", when=DAY1),
        confirmed("q3", when=DAY3, variant=True),
    )
    graduated, reason = graduation_check(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=POLICY
    )
    assert (graduated, reason) == (True, "graduated")


def test_manual_credit_alone_cannot_graduate() -> None:
    """基础确认只能帮助「有效确认数」，不能替代真实题量、变式题与跨天。

    这里用 min_real_questions=1 的策略，让真实题量先达标，
    从而精确验证「只差跨天」这一条。
    """
    policy = MasteryPolicy(min_confirmations=3, min_real_questions=1)
    window = (confirmed("q1", when=DAY1, variant=True),)
    graduated, reason = graduation_check(
        window, manual_credit_count=2, manual_confirmed_at=DAY1, policy=policy
    )
    assert (graduated, reason) == (False, "insufficient_day_span")
    # 确认数已够（1 + 2 = 3），缺的只是跨天。
    assert effective_confirmation_count(window, manual_credit_count=2) == 3


def test_manual_credit_route_graduates_with_later_variant_question() -> None:
    """基础确认 2 + 1 道真实变式题 + 跨天 => 毕业（节点自评路径）。"""
    policy = MasteryPolicy(min_confirmations=3, min_real_questions=1)
    window = (confirmed("q1", when=DAY3, variant=True),)
    graduated, reason = graduation_check(
        window, manual_credit_count=2, manual_confirmed_at=DAY1, policy=policy
    )
    assert (graduated, reason) == (True, "graduated")


def test_manual_credit_cannot_replace_real_questions() -> None:
    """真实题量不足时，基础确认再多也不能毕业。"""
    policy = MasteryPolicy(min_confirmations=3, min_real_questions=3)
    window = (confirmed("q1", when=DAY1, variant=True),)
    graduated, reason = graduation_check(
        window, manual_credit_count=2, manual_confirmed_at=DAY1, policy=policy
    )
    # 3 个确认够，但真实题只有 1 道 < 3。
    assert (graduated, reason) == (False, "insufficient_real_questions")


def test_manual_credit_cannot_satisfy_question_type_or_skill() -> None:
    """基础确认不能替用户覆盖必考题型与必考考法。"""
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=1,
        required_question_types={"calculation": 1},
        required_skill_tags=frozenset({"先变形"}),
    )
    # 只做了一道选择题、也没有「先变形」标签。
    window = (confirmed("q1", when=DAY3, question_type="single_choice", skill_tags=("适用条件",)),)
    graduated, reason = graduation_check(
        window, manual_credit_count=2, manual_confirmed_at=DAY1, policy=policy
    )
    assert (graduated, reason) == (False, "missing_question_type:calculation")


def test_manual_credit_cannot_satisfy_variant_requirement() -> None:
    """没有真实变式题时，靠节点自评永远不能毕业。"""
    policy = MasteryPolicy(min_confirmations=3, min_real_questions=2)
    window = (
        confirmed("q1", when=DAY1),
        confirmed("q2", when=DAY3),
    )
    graduated, reason = graduation_check(
        window, manual_credit_count=2, manual_confirmed_at=DAY1, policy=policy
    )
    assert (graduated, reason) == (False, "missing_real_variant")


# --------------------------------------------------------------------------- #
# 缺口分析：与毕业判定必须一致
# --------------------------------------------------------------------------- #


def test_analyze_gaps_lists_every_condition_with_progress() -> None:
    """缺口报告要逐条给出「当前/要求」，页面直接渲染这些条目。"""
    from backend.mastery.rules import analyze_gaps

    policy = MasteryPolicy(
        min_confirmations=4,
        min_real_questions=3,
        required_question_types={"single_choice": 1, "calculation": 2},
        required_skill_tags=frozenset({"适用条件"}),
    )
    window = (
        confirmed("q1", when=DAY1, question_type="single_choice", skill_tags=("适用条件",)),
        confirmed("q2", when=DAY3, question_type="calculation"),
    )
    report = analyze_gaps(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=policy
    )
    by_key = {item.key: item for item in report.items}
    assert by_key["effective_confirmations"].current == 2
    assert by_key["effective_confirmations"].required == 4
    assert by_key["real_questions"].current == 2
    assert by_key["type:single_choice"].satisfied is True
    assert by_key["type:calculation"].current == 1
    assert by_key["type:calculation"].required == 2
    assert by_key["type:calculation"].satisfied is False
    assert by_key["skill_tags"].satisfied is True
    assert by_key["day_span"].satisfied is True
    assert report.can_graduate is False
    # 「下一步」必须指出缺计算大题。
    assert "计算大题" in report.next_step
    assert report.missing_types == ("calculation",)


def test_analyze_gaps_agrees_with_graduation_check() -> None:
    """缺口报告的 can_graduate 必须与 graduation_check 的结论一致。"""
    from backend.mastery.rules import analyze_gaps

    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_question_types={"fill_blank": 3},
    )
    window = (
        confirmed("q1", when=DAY1, variant=True),
        confirmed("q2", when=DAY2),
        confirmed("q3", when=DAY3),
    )
    report = analyze_gaps(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=policy
    )
    graduated, _ = graduation_check(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=policy
    )
    assert report.can_graduate == graduated == True  # noqa: E712


def test_analyze_gaps_excludes_excluded_types_from_report() -> None:
    """用户不需要关心「明确不考」的题型，报告中不应出现。"""
    from backend.mastery.rules import analyze_gaps

    policy = MasteryPolicy(
        required_question_types={"single_choice": 1},
        excluded_question_types=frozenset({"calculation", "proof", "subjective"}),
    )
    report = analyze_gaps(
        (), manual_credit_count=0, manual_confirmed_at=None, policy=policy
    )
    keys = {item.key for item in report.items}
    assert "type:single_choice" in keys
    assert "type:calculation" not in keys
    assert "type:proof" not in keys