"""按缺口选题与时间预算的单元测试。

这些用例锁住新设计的核心行为：
- 只考客观题的叶子永远不会被推荐计算大题；
- 缺口优先补题型，而不是重复已经达标的题型；
- 时间预算会裁剪卷子长度，且跳过放不下的题而不是直接停止；
- 一道变式计算大题可以同时补题型、变式与考法，但只算一道真实题。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.mastery.enums import EvidenceLevel, TimeBudget
from backend.mastery.policy import MasteryPolicy
from backend.mastery.selection import (
    Priority,
    QuestionCandidate,
    budget_minutes,
    select_questions,
    summarize_plan,
)
from backend.mastery.types import Evidence

from tests.unit.mastery.conftest import DAY1, DAY3


def ev(
    question_id: str,
    *,
    when=DAY1,
    question_type: str = "fill_blank",
    variant: bool = False,
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


def cand(
    question_id: str,
    *,
    question_type: str = "fill_blank",
    variant: bool = False,
    skill_tags: tuple[str, ...] = (),
    minutes: int = 5,
    last_self_grade: str | None = None,
    last_practiced_at=None,
    confirmed: bool = False,
) -> QuestionCandidate:
    return QuestionCandidate(
        question_id=question_id,
        question_type=question_type,
        skill_tags=skill_tags,
        is_variant=variant,
        estimated_minutes=minutes,
        last_self_grade=last_self_grade,
        last_practiced_at=last_practiced_at,
        confirmed=confirmed,
    )


OBJECTIVE_ONLY = MasteryPolicy(
    min_confirmations=3,
    min_real_questions=3,
    required_question_types={"single_choice": 1, "fill_blank": 2},
    excluded_question_types=frozenset({"calculation", "proof", "subjective"}),
)


def test_budget_minutes_has_three_levels_and_safe_default() -> None:
    assert budget_minutes(TimeBudget.LIGHT.value) == 45
    assert budget_minutes(TimeBudget.STANDARD.value) == 90
    assert budget_minutes(TimeBudget.DEEP.value) == 120
    # 未知预算按标准处理，绝不返回 0（否则一道题都选不出来）。
    assert budget_minutes("unknown") == 90


def test_excluded_question_types_are_never_selected() -> None:
    """只考客观题的叶子：计算大题、证明题永远不入选。"""
    candidates = [
        cand("calc-1", question_type="calculation", minutes=12),
        cand("choice-1", question_type="single_choice", minutes=3),
        cand("proof-1", question_type="proof", minutes=20),
    ]
    result = select_questions(OBJECTIVE_ONLY, (), candidates)
    selected = {item.question_id for item in result.items}
    assert "calc-1" not in selected
    assert "proof-1" not in selected
    assert "choice-1" in selected


def test_selector_fills_missing_question_type_first() -> None:
    """选择题已达标、填空题缺口未补时，优先推荐填空题。"""
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_question_types={"single_choice": 1, "fill_blank": 2},
    )
    window = (ev("c-1", question_type="single_choice"),)
    candidates = [
        cand("c-2", question_type="single_choice", minutes=3),
        cand("f-2", question_type="fill_blank", minutes=5),
    ]
    result = select_questions(policy, window, candidates)
    # 填空题缺口优先于已经达标的选择题。
    top = result.items[0]
    assert top.question_type == "fill_blank"
    assert top.priority is Priority.REQUIRED_TYPE


def test_failed_question_gets_highest_priority_label() -> None:
    """上次未掌握的题会被标成最高优先级标签，方便页面解释推荐原因。

    注意：选题本身是按「能补齐多少缺口」决定的，
    所以「未掌握」不会无条件压过正在补硬缺口的题——
    但一旦入选，它的优先级标签与文案必须体现「上次未掌握」。
    """
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_question_types={"fill_blank": 1},
    )
    candidates = [
        cand("c-1", question_type="single_choice", minutes=3, last_self_grade="not_mastered"),
    ]
    result = select_questions(policy, (), candidates)
    assert result.items[0].question_id == "c-1"
    assert result.items[0].priority is Priority.FAILED_TYPE
    assert "上次未掌握" in result.items[0].reason


def test_partial_question_gets_partial_priority_label() -> None:
    policy = MasteryPolicy(min_confirmations=3, min_real_questions=3)
    candidates = [cand("p-1", minutes=5, last_self_grade="partial")]
    result = select_questions(policy, (), candidates)
    assert result.items[0].priority is Priority.PARTIAL_TYPE
    assert "部分掌握" in result.items[0].reason


def test_variant_question_is_selected_when_missing() -> None:
    """确认数与真实题数都够，但缺变式题时应当补一道变式题。"""
    policy = MasteryPolicy(min_confirmations=3, min_real_questions=3)
    window = (
        ev("q1", when=DAY1),
        ev("q2", when=DAY1),
        ev("q3", when=DAY3),
    )
    candidates = [
        cand("plain-1", minutes=5),
        cand("variant-1", variant=True, minutes=5),
    ]
    result = select_questions(policy, window, candidates)
    assert result.items[0].question_id == "variant-1"


def test_skill_tag_gap_drives_selection() -> None:
    """必考考法没覆盖时，推荐带该考法标签的题。"""
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_skill_tags=frozenset({"先变形"}),
    )
    window = (
        ev("q1", skill_tags=("适用条件",)),
        ev("q2", skill_tags=("适用条件",)),
        ev("q3", skill_tags=("适用条件",), variant=True, when=DAY3),
    )
    candidates = [
        cand("plain-1", skill_tags=("适用条件",), minutes=5),
        cand("reshape-1", skill_tags=("先变形",), minutes=12, question_type="calculation"),
    ]
    result = select_questions(policy, window, candidates)
    assert result.items[0].question_id == "reshape-1"
    assert "先变形" in result.items[0].reason


def test_time_budget_caps_total_minutes() -> None:
    """轻量预算下不会塞进五道 20 分钟的大题。"""
    policy = MasteryPolicy(min_confirmations=10, min_real_questions=10)
    candidates = [
        cand(f"proof-{index}", question_type="proof", minutes=20) for index in range(6)
    ]
    result = select_questions(policy, (), candidates, budget=TimeBudget.LIGHT.value)
    assert result.budget == 45
    assert result.total_minutes <= 45
    # 最多两道 20 分钟的题。
    assert len(result.items) <= 2
    assert result.skipped_over_budget == 6 - len(result.items)


def test_budget_skips_long_question_but_keeps_short_one() -> None:
    """放不下长题时跳过它，而不是直接结束——后面短题还能用上预算。"""
    policy = MasteryPolicy(min_confirmations=10, min_real_questions=10)
    candidates = [
        cand("proof-1", question_type="proof", minutes=20),
        cand("proof-2", question_type="proof", minutes=20),
        cand("choice-1", question_type="single_choice", minutes=3),
    ]
    result = select_questions(policy, (), candidates, budget=TimeBudget.LIGHT.value)
    ids = [item.question_id for item in result.items]
    assert "choice-1" in ids
    assert result.total_minutes <= 45


def test_one_question_can_cover_type_variant_and_skill() -> None:
    """一道变式计算大题可以同时补题型、变式与考法，但只算一道真实题。"""
    policy = MasteryPolicy(
        min_confirmations=2,
        min_real_questions=2,
        required_question_types={"calculation": 1},
        required_skill_tags=frozenset({"先变形"}),
    )
    candidates = [
        cand(
            "rich-1",
            question_type="calculation",
            variant=True,
            skill_tags=("先变形",),
            minutes=15,
        )
    ]
    result = select_questions(policy, (), candidates)
    assert len(result.items) == 1
    # 只占一道题的位置，但它的 reason 反映了缺口。
    assert result.items[0].question_type == "calculation"
    assert result.items[0].is_variant is True


def test_limit_caps_number_of_questions() -> None:
    policy = MasteryPolicy(min_confirmations=10, min_real_questions=10)
    candidates = [
        cand(f"c-{index}", question_type="single_choice", minutes=3) for index in range(10)
    ]
    result = select_questions(policy, (), candidates, limit=3)
    assert len(result.items) == 3


def test_missing_gap_outranks_review_and_unpracticed() -> None:
    """缺口题优先于复测题与从未练习的题。

    收益模型里，只有新题能推进题型/考法/变式缺口；
    复测题仅在「重做能把跨天跨度拉开」时才有收益；
    从未练习的题如果没有补到任何缺口，也不会被优先选。
    """
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_question_types={"calculation": 1, "fill_blank": 1},
        required_skill_tags=frozenset({"适用条件"}),
    )
    window = (
        ev("q1", when=DAY1, question_type="calculation", skill_tags=("其他考法",)),
    )
    candidates = [
        # 久未复测的旧题：但重做它补不了「填空题」与「适用条件」缺口。
        cand("old-1", question_type="calculation", skill_tags=("其他考法",),
             minutes=12, confirmed=True, last_practiced_at=DAY1 - timedelta(days=30)),
        # 从未练习、且正好覆盖缺口的新题。
        cand("new-fill", question_type="fill_blank", skill_tags=("适用条件",),
             minutes=5, confirmed=False, last_practiced_at=None),
    ]
    result = select_questions(policy, window, candidates)
    assert result.items[0].question_id == "new-fill"
    assert result.items[0].priority is Priority.REQUIRED_TYPE


def test_review_is_not_offered_when_span_cannot_grow() -> None:
    """同一天再确认一次不会拉开跨度，就不该推荐复测题（否则用户白做一遍）。

    典型场景：用户当天已经做完全部题目，又点了「追加练习题」；
    此时缺口只剩跨天，而当天再做也无法满足，因此系统如实返回「没有需要补的题」。
    """
    policy = MasteryPolicy(
        min_confirmations=2,
        min_real_questions=2,
        required_question_types={"calculation": 2},
    )
    window = (
        ev("q1", when=DAY1, question_type="calculation", variant=True),
        ev("q2", when=DAY1, question_type="calculation"),
    )
    candidates = [
        cand("q1", question_type="calculation", variant=True, minutes=12,
             confirmed=True, last_practiced_at=DAY1),
        cand("q2", question_type="calculation", minutes=12,
             confirmed=True, last_practiced_at=DAY1),
    ]
    # 参考时间与已有确认同一天：重做也拉不开跨度。
    result = select_questions(policy, window, candidates, reference_time=DAY1)
    assert result.items == ()

    # 换成第三天，复测就能推进跨度，于是给出复测题。
    later = select_questions(policy, window, candidates, reference_time=DAY3)
    assert len(later.items) == 1
    assert later.items[0].is_review is True


def test_never_practiced_question_is_classified_correctly() -> None:
    """没有确认过、也没练过的题，归入「尚未练习」。"""
    policy = MasteryPolicy(min_confirmations=10, min_real_questions=10)
    candidates = [cand("new-1", last_practiced_at=None, confirmed=False, minutes=5)]
    result = select_questions(policy, (), candidates)
    assert result.items[0].priority is Priority.NEVER_PRACTICED
    assert "尚未练习" in result.items[0].reason


def test_summarize_plan_counts_by_type() -> None:
    policy = MasteryPolicy(min_confirmations=10, min_real_questions=10)
    candidates = [
        cand("c-1", question_type="single_choice", minutes=3),
        cand("c-2", question_type="single_choice", minutes=3),
        cand("f-1", question_type="fill_blank", minutes=5),
    ]
    result = select_questions(policy, (), candidates)
    summary = summarize_plan(result.items)
    assert summary == {"single_choice": 2, "fill_blank": 1}


def test_empty_candidates_yield_empty_selection() -> None:
    result = select_questions(MasteryPolicy(), (), [])
    assert result.items == ()
    assert result.total_minutes == 0
    assert "没有需要补的题" in result.reason