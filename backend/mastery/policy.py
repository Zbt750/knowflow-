"""Versioned per-node mastery policy.

v1/v2 preserve historical semantics. v3 graduates a node when every question
in its frozen, versioned graduation set has a valid completion receipt.
Learning-plan spacing, variants, and remedial questions remain separate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import get_args
from uuid import UUID

from backend.mastery.enums import QuestionType
from backend.schemas.question_trust import QuestionProvenance

LEGACY_POLICY_FIELDS = (
    "min_confirmations", "min_real_questions", "required_question_types",
    "excluded_question_types", "required_skill_tags", "required_variant_count",
    "min_day_span", "manual_mastered_credit", "review_intervals_days",
    "max_evidence_window", "note",
)
VERSIONED_POLICY_FIELDS = (*LEGACY_POLICY_FIELDS, "policy_version", "required_question_origins")
GRADUATION_SET_FIELDS = ("graduation_question_ids", "graduation_set_version")
# Storage/validation safety bound, not a learning quota. A release may include
# every approved public question of a substantial topic without the old 20 cap.
MAX_GRADUATION_SET_SIZE = 200


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
    policy_version: int = 1
    # Deprecated compatibility field. Historical v2 policies may still carry
    # a real_exam quota until a guarded data migration clears it. Runtime
    # graduation and supply decisions must not treat this as a requirement.
    required_question_origins: dict[str, int] = field(default_factory=dict)
    # v3's finite, frozen formal-question set. New bank items never expand it.
    graduation_question_ids: tuple[str, ...] = ()
    graduation_set_version: int = 0
    # Runtime-only fail-closed projection for legacy activity that has no
    # provable historical set. Never persisted into the shared policy row.
    graduation_binding_pending: bool = False

    def __post_init__(self) -> None:
        if type(self.policy_version) is not int or self.policy_version not in {1, 2, 3}:
            raise ValueError("未知掌握策略版本")
        if self.policy_version == 1 and self.required_question_origins:
            raise ValueError("旧策略版本不能包含来源配额")
        if self.policy_version == 3 and self.required_question_origins:
            raise ValueError("v3 冻结题目集策略不能包含来源配额")
        if self.policy_version in {2, 3} and "external_exam" in self.required_question_types:
            raise ValueError("新策略版本不能把外部原卷引用作为毕业题型")
        if type(self.graduation_set_version) is not int or self.graduation_set_version < 0:
            raise ValueError("毕业题目集合版本必须是非负整数")
        if type(self.graduation_binding_pending) is not bool:
            raise ValueError("毕业题集切换状态必须是布尔值")
        if any(not isinstance(qid, str) or not qid.strip() for qid in self.graduation_question_ids):
            raise ValueError("毕业题目集合包含空题目ID")
        try:
            normalized_ids = tuple(str(UUID(qid)) for qid in self.graduation_question_ids)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("毕业题目集合必须使用有效题目UUID") from exc
        if normalized_ids != self.graduation_question_ids:
            raise ValueError("毕业题目集合UUID必须使用规范格式")
        if len(set(self.graduation_question_ids)) != len(self.graduation_question_ids):
            raise ValueError("毕业题目集合不能包含重复题目")
        if len(self.graduation_question_ids) > MAX_GRADUATION_SET_SIZE:
            raise ValueError(f"毕业题目集合不能超过 {MAX_GRADUATION_SET_SIZE} 道题")
        if bool(self.graduation_question_ids) != (self.graduation_set_version > 0):
            raise ValueError("毕业题目集合与集合版本必须同时配置")
        if self.policy_version != 3 and (self.graduation_question_ids or self.graduation_set_version):
            raise ValueError("只有 v3 策略可以配置冻结毕业题目集合")
        origins = set(get_args(QuestionProvenance)) - {"legacy_unknown"}
        if set(self.required_question_origins) - origins:
            raise ValueError("未知题目来源配额")
        if any(type(n) is not int or n < 1 for n in self.required_question_origins.values()):
            raise ValueError("来源配额必须是正整数")
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
        """本知识点允许使用的题型。外部原卷任务必须由策略显式启用。"""
        return tuple(
            item.value
            for item in QuestionType
            if item.value not in self.excluded_question_types
            and (self.policy_version in {2, 3} or item not in {QuestionType.DISCUSSION, QuestionType.PROGRAM}
                 or item.value in self.required_question_types)
            and (
                item.value != QuestionType.EXTERNAL_EXAM.value
                or item.value in self.required_question_types
            )
        )

    @property
    def total_required_question_count(self) -> int:
        """题型配额要求的题目总数下限。"""
        # Source identity is descriptive, never a graduation quota.
        return sum(self.required_question_types.values())
