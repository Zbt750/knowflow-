"""每知识点毕业策略。

设计要点：
- 毕业不再只看题目总数，而是同时看「真实题量 / 必考题型 / 必考考法 / 变式题 / 跨天」。
- 策略按知识点配置：只考客观题的叶子不必练大题，只考大题的叶子不必做选择题。
- `question_type`（作答形式）与 `question_role`（学习作用）互不替代，
  因此策略只约束题型与考法，不约束角色。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.mastery.enums import QuestionType


@dataclass(frozen=True)
class MasteryPolicy:
    """一个叶子的毕业门槛。默认值即「尚未单独配置」时的通用基线。"""

    # 有效确认数下限 = 窗口内真实确认数 + 基础确认数。
    min_confirmations: int = 3
    # 不同真实题目数下限；节点整体自评的基础确认不能替代它。
    min_real_questions: int = 3
    # 题型配额：{question_type: 至少几道不同真实题}。
    required_question_types: dict[str, int] = field(default_factory=dict)
    # 该知识点不使用的题型：推荐与组卷都不会选它们。
    excluded_question_types: frozenset[str] = frozenset()
    # 必考考法标签：至少覆盖这么多个（从已确认题目出现过的标签里算）。
    required_skill_tags: frozenset[str] = frozenset()
    required_variant_count: int = 1
    min_day_span: int = 2
    manual_mastered_credit: int = 2
    review_intervals_days: tuple[int, ...] = (7, 15, 30)
    max_evidence_window: int = 20
    note: str | None = None

    def __post_init__(self) -> None:
        positive = (
            self.min_confirmations,
            self.min_real_questions,
            self.max_evidence_window,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("掌握策略中的数量必须大于 0")
        if self.required_variant_count < 0:
            raise ValueError("变式题数量不能为负")
        if self.min_day_span < 0:
            raise ValueError("跨天要求不能为负")
        if self.manual_mastered_credit < 0:
            raise ValueError("基础确认数量不能为负")
        if not self.review_intervals_days or any(day <= 0 for day in self.review_intervals_days):
            raise ValueError("复测间隔必须是非空正整数")
        if tuple(sorted(self.review_intervals_days)) != self.review_intervals_days:
            raise ValueError("复测间隔必须升序排列")
        # 「既不使用又要求必考」是自相矛盾的配置，必须在加载时就拒绝。
        conflict = self.excluded_question_types & set(self.required_question_types)
        if conflict:
            raise ValueError(f"题型不能同时 required 与 excluded：{sorted(conflict)}")
        known = {item.value for item in QuestionType}
        unknown = (set(self.required_question_types) | set(self.excluded_question_types)) - known
        if unknown:
            raise ValueError(f"未知题型：{sorted(unknown)}")
        if any(count < 1 for count in self.required_question_types.values()):
            raise ValueError("题型配额必须至少为 1")

    # ------------------------------------------------------------------ #
    # 派生属性：缺口分析、题库校验与页面展示共用，避免各处各算一遍。
    # ------------------------------------------------------------------ #

    @property
    def available_question_types(self) -> tuple[str, ...]:
        """本知识点允许使用的题型（排除 excluded 之后）。"""
        return tuple(
            item.value for item in QuestionType if item.value not in self.excluded_question_types
        )

    @property
    def total_required_question_count(self) -> int:
        """题型配额要求的题目总数下限。"""
        return sum(self.required_question_types.values())
