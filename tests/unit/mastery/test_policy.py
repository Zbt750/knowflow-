"""每知识点毕业策略的构造与校验。

升级后的要点：策略不再只有「3 道题」这类总数要求，
还要表达「必考哪些题型、哪些题型明确不考、必考哪些考法」。
"""

from __future__ import annotations

import pytest

from backend.mastery.policy import MasteryPolicy


def test_default_policy_matches_product_rules() -> None:
    policy = MasteryPolicy()
    # 这些是「尚未单独配置」时的通用基线，改动必须是有意识的。
    assert policy.min_confirmations == 3
    assert policy.min_real_questions == 3
    assert policy.required_variant_count == 1
    assert policy.min_day_span == 2
    # 节点整体自评恰好贡献 2 个基础确认。
    assert policy.manual_mastered_credit == 2
    assert policy.review_intervals_days == (7, 15, 30)
    # 默认不限制题型，也不排除任何题型。
    assert policy.required_question_types == {}
    assert policy.excluded_question_types == frozenset()


def test_policy_expresses_question_type_quotas() -> None:
    """只考客观题的叶子：题型配额里不该出现大题，并且明确 excluded。"""
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_question_types={"single_choice": 1, "fill_blank": 2},
        excluded_question_types=frozenset({"calculation", "proof", "subjective"}),
        required_skill_tags=frozenset({"同阶与等价", "加减不能换"}),
    )
    assert policy.total_required_question_count == 3
    # excluded 的题型不出现在「可用题型」里，推荐与组卷据此排除它。
    assert "calculation" not in policy.available_question_types
    assert "single_choice" in policy.available_question_types


def test_policy_expresses_skill_tag_requirements() -> None:
    policy = MasteryPolicy(required_skill_tags=frozenset({"适用条件", "0/0 型"}))
    assert policy.required_skill_tags == frozenset({"适用条件", "0/0 型"})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_confirmations": 0},
        {"min_real_questions": 0},
        {"max_evidence_window": 0},
        {"required_variant_count": -1},
        {"min_day_span": -1},
        {"manual_mastered_credit": -1},
        {"review_intervals_days": ()},
        {"review_intervals_days": (7, 0)},
        # 必须升序，否则复测计划没有意义。
        {"review_intervals_days": (30, 7)},
        # 题型配额必须至少为 1，否则等于没要求。
        {"required_question_types": {"fill_blank": 0}},
        # 未知题型：拼错类型名必须立刻报错，不能静默忽略。
        {"required_question_types": {"multi_select": 1}},
        {"excluded_question_types": frozenset({"essay"})},
    ],
)
def test_invalid_policy_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MasteryPolicy(**kwargs)  # type: ignore[arg-type]


def test_policy_rejects_same_type_required_and_excluded() -> None:
    """同一个题型不能既要求必考又不允许使用，这种配置自相矛盾。"""
    with pytest.raises(ValueError, match="required 与 excluded"):
        MasteryPolicy(
            required_question_types={"calculation": 2},
            excluded_question_types=frozenset({"calculation"}),
        )


def test_single_choice_only_policy_needs_no_calculation_pool() -> None:
    """只考选择题的叶子，题库里没有大题是完全正常的。"""
    policy = MasteryPolicy(
        required_question_types={"single_choice": 3},
        excluded_question_types=frozenset({"fill_blank", "calculation", "proof", "subjective"}),
    )
    # 可用题型只剩选择题。
    assert policy.available_question_types == ("single_choice",)
