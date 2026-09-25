"""按毕业缺口选题：把「还缺什么」变成「今天做哪几道题」。

设计要点：
- 唯一的缺口来源是 `analyze_gaps()`：推荐与毕业判定必须基于同一份计算，
  否则会出现「系统推荐了题，做完却不毕业」这种自相矛盾。
- 优先级顺序体现产品意图：先补上次没掌握的题型/考法，再补毕业硬缺口，
  然后才是没练过的题与最久没复测的题。
- 时间预算在选完题后统一裁剪：不会因为某个知识点缺大题，一次塞五六道大题。
- excluded 的题型永不入选。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum

from backend.mastery.enums import EvidenceLevel, TimeBudget, default_minutes
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import (
    GapReport,
    analyze_gaps,
    confirmation_dates,
    covered_skill_tags,
    type_label,
)
from backend.mastery.types import Evidence

# 三档时间预算的总分钟数；与 enums.BUDGET_MINUTES 保持一致。
_BUDGET: dict[str, int] = {
    TimeBudget.LIGHT.value: 45,
    TimeBudget.STANDARD.value: 90,
    TimeBudget.DEEP.value: 120,
}

BUDGET_LABELS: dict[str, str] = {
    TimeBudget.LIGHT.value: "轻量（约 45 分钟）",
    TimeBudget.STANDARD.value: "标准（约 90 分钟）",
    TimeBudget.DEEP.value: "深度（约 120 分钟）",
}


def budget_minutes(budget: str) -> int:
    """未知预算按标准处理，绝不返回 0（否则一道题都选不出来）。"""
    return _BUDGET.get(budget, _BUDGET[TimeBudget.STANDARD.value])


class Priority(IntEnum):
    """知识点内部选题优先级；数字越小越优先。"""

    FAILED_TYPE = 1  # 上次未掌握的题型或考法
    PARTIAL_TYPE = 2  # 上次部分掌握的题型或考法
    REQUIRED_TYPE = 3  # 毕业条件缺少的题型
    REQUIRED_SKILL = 4  # 尚未覆盖的必考考法
    MISSING_VARIANT = 5  # 缺少的真实变式题
    DUE_REVIEW = 6  # 到期复测
    NEVER_PRACTICED = 7  # 从未练习过的题
    STALEST_CONFIRMED = 8  # 最久没有复测的已掌握题


@dataclass(frozen=True)
class QuestionCandidate:
    """一道候选题目；字段刻意只保留选题所需信息，便于纯函数测试。"""

    question_id: str
    question_type: str
    skill_tags: tuple[str, ...]
    is_variant: bool
    estimated_minutes: int
    # 该题最近一次自评（没有则为 None）；用于识别「上次未掌握」与「最久没复测」。
    last_self_grade: str | None = None
    last_practiced_at: datetime | None = None
    # 该题是否已经有有效确认（窗口内出现过）。
    confirmed: bool = False
    # 距上次练习多少天；复测排序与文案会用到。
    days_since_practiced: int | None = None

    @property
    def minutes(self) -> int:
        """题目自带时长优先，缺失时按题型默认值兜底。"""
        return self.estimated_minutes or default_minutes(self.question_type)


@dataclass(frozen=True)
class SelectionItem:
    """入选的一道题：带上它为什么被选中，页面据此解释推荐原因。"""

    question_id: str
    question_type: str
    is_variant: bool
    estimated_minutes: int
    priority: Priority
    reason: str
    # 是否为复测：题库都练过时，复测是唯一能推进毕业的动作。
    is_review: bool = False


@dataclass(frozen=True)
class SelectionResult:
    items: tuple[SelectionItem, ...]
    skipped_over_budget: int
    total_minutes: int
    budget: int

    @property
    def reason(self) -> str:
        """给页面看的整体推荐原因（取最优先的那条）。"""
        return self.items[0].reason if self.items else "当前没有需要补的题"


def _missing_gap_keys(gap: GapReport) -> set[str]:
    """当前还没满足的那些毕业条件项的 key。

    跨天门（`day_span`）必须包含在内：题库练完之后，
    用户能推进的就只剩「再做一次确认把跨度拉开」，
    如果把它排除掉，复测日会一道题都选不出来。
    """
    return {item.key for item in gap.items if not item.satisfied}


def _coverage(
    candidate: QuestionCandidate,
    *,
    missing_keys: set[str],
    policy: MasteryPolicy,
    covered_tags: set[str],
) -> int:
    """这道题能立刻推进多少个还没满足的条件项。

    收益模型刻意区分两类题：
    - **没做过的题**：带来新证据，可推进真实题量、必考题型、必考考法与变式题；
    - **已确认过的题（重做）**：按产品规则「同一题重复掌握只刷新确认时间，
      不增加不同题目数」，所以它唯一能推进的是跨天跨度。

    这样题库耗尽时重做题仍有明确收益，复测日不会无题可选。
    """
    gain = 0
    if candidate.confirmed:
        # 重做旧题：只有跨天门还没满足时才有意义（按规则它不增加不同题数）。
        if "day_span" in missing_keys:
            gain += 1
        return gain

    # 新题才改变「不同真实题数」与题型/考法覆盖。
    if "real_questions" in missing_keys:
        gain += 1
    if f"type:{candidate.question_type}" in missing_keys:
        gain += 1
    if candidate.is_variant and "variant_questions" in missing_keys:
        gain += 1
    fresh = {
        tag
        for tag in candidate.skill_tags
        if tag in policy.required_skill_tags and tag not in covered_tags
    }
    if fresh:
        gain += 1
    return gain


def select_questions(
    policy: MasteryPolicy,
    window: tuple[Evidence, ...],
    candidates: list[QuestionCandidate],
    *,
    manual_credit_count: int = 0,
    manual_confirmed_at: datetime | None = None,
    budget: str = TimeBudget.STANDARD.value,
    limit: int | None = None,
    reference_time: datetime | None = None,
) -> SelectionResult:
    """按毕业缺口逐步补齐选题，并用时间预算裁剪总时长。

    算法：每一轮挑「能推进最多缺口项」的题，把它加入模拟窗口后重算缺口，
    直到缺口补齐、达到上限或预算用尽。这样选题数恰好够补缺口，
    不会出现策略只要求 2 道计算题却选了 3 道的情况。

    `reference_time` 是「现在」：题库练完之后唯一能推进的就是跨天确认，
    而判断重做能否拉开跨度必须知道今天是哪天，因此这个参数是复测日选题的前提。
    """
    total_budget = budget_minutes(budget)
    usable = [item for item in candidates if item.question_type not in policy.excluded_question_types]
    # 模拟重做时用「现在」作为这次确认的时间；没有传入时退回占位时间（不影响新题选题）。
    occurred_at = reference_time or manual_confirmed_at or _epoch()

    simulated = tuple(window)
    items: list[SelectionItem] = []
    spent = 0
    skipped = 0
    remaining = list(usable)

    while remaining:
        if limit is not None and len(items) >= limit:
            break
        gap = analyze_gaps(
            simulated,
            manual_credit_count=manual_credit_count,
            manual_confirmed_at=manual_confirmed_at,
            policy=policy,
        )
        missing = _missing_gap_keys(gap)
        if not missing:
            # 缺口补齐就停：再选只是重复劳动。
            break
        covered = covered_skill_tags(simulated)
        span_before = _span_days(simulated, manual_credit_count, manual_confirmed_at)

        best: tuple[int, int, str, QuestionCandidate] | None = None
        for candidate in remaining:
            gain = _coverage(
                candidate, missing_keys=missing, policy=policy, covered_tags=covered
            )
            if gain <= 0:
                continue
            # 重做旧题时再确认一次「今天是否真的把跨度拉开」，
            # 否则会在同一天反复推荐同一道题却没有实际推进。
            if candidate.confirmed and "day_span" in missing:
                trial = _with_evidence(simulated, candidate, occurred_at)
                if _span_days(trial, manual_credit_count, manual_confirmed_at) <= span_before:
                    continue
            # 收益相同时先选更短的题：更容易塞进预算，也更快拿到反馈。
            key = (gain, -candidate.minutes, candidate.question_id)
            if best is None or key > (best[0], -best[1], best[2]):
                best = (gain, candidate.minutes, candidate.question_id, candidate)

        if best is None:
            # 剩下的题都推进不了缺口了，停。
            break

        gain, cost, _, chosen = best
        if spent + cost > total_budget:
            # 预算不够放这道题就不再硬塞；剩余的题留给下一次学习。
            skipped = len(remaining)
            break

        spent += cost
        items.append(
            SelectionItem(
                question_id=chosen.question_id,
                question_type=chosen.question_type,
                is_variant=chosen.is_variant,
                estimated_minutes=cost,
                priority=_priority_for_chosen(chosen, policy=policy, missing=missing),
                reason=_reason_for(
                    chosen, policy=policy, covered=covered, missing=missing
                ),
                # 重做已确认过的题：页面据此说明「题库已练过，这是复测」。
                is_review=chosen.confirmed,
            )
        )
        # 把它加入模拟窗口，下一轮就能看到缺口已经缩小。
        simulated = _with_evidence(simulated, chosen, occurred_at)
        remaining.remove(chosen)

    return SelectionResult(
        items=tuple(items),
        skipped_over_budget=skipped,
        total_minutes=spent,
        budget=total_budget,
    )


def _with_evidence(
    window: tuple[Evidence, ...], candidate: QuestionCandidate, occurred_at: datetime
) -> tuple[Evidence, ...]:
    """把「这道题已掌握」加入模拟窗口，用于重算缺口。

    窗口本身按 question_id 去重，因此重做旧题只会刷新它的确认时间——
    这与真实状态机的行为一致，模拟结果才可信。
    """
    return (
        *window,
        Evidence(
            question_id=candidate.question_id,
            level=EvidenceLevel.CONFIRMED,
            is_variant=candidate.is_variant,
            occurred_at=occurred_at,
            source="practice_item",
            question_type=candidate.question_type,
            skill_tags=candidate.skill_tags,
        ),
    )


def _span_days(
    window: tuple[Evidence, ...],
    manual_credit_count: int,
    manual_confirmed_at: datetime | None,
) -> int:
    """当前窗口的首尾确认天数差；没有确认时为 0。"""
    dates = confirmation_dates(
        window,
        manual_credit_count=manual_credit_count,
        manual_confirmed_at=manual_confirmed_at,
    )
    return (max(dates) - min(dates)).days if dates else 0


def _epoch() -> datetime:
    """没有传入参考时间时的占位；此时不会用它来判断跨天收益。"""
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _priority_for_chosen(
    chosen: QuestionCandidate, *, policy: MasteryPolicy, missing: set[str]
) -> Priority:
    """入选题目的优先级标签：用于页面解释「为什么推荐这道题」。"""
    if chosen.last_self_grade == "not_mastered":
        return Priority.FAILED_TYPE
    if chosen.last_self_grade == "partial":
        return Priority.PARTIAL_TYPE
    if f"type:{chosen.question_type}" in missing:
        return Priority.REQUIRED_TYPE
    if chosen.is_variant and "variant_questions" in missing:
        return Priority.MISSING_VARIANT
    if chosen.confirmed:
        return Priority.DUE_REVIEW
    if chosen.last_practiced_at is None:
        return Priority.NEVER_PRACTICED
    return Priority.STALEST_CONFIRMED


def _reason_for(
    chosen: QuestionCandidate,
    *,
    policy: MasteryPolicy,
    covered: set[str],
    missing: set[str],
) -> str:
    """给用户看的推荐原因，说明这道题在补什么缺口。"""
    # 「上次未掌握」永远排在最前：这是用户最该看到的信号，与优先级标签保持一致。
    if chosen.last_self_grade == "not_mastered":
        return "上次未掌握，优先重做"
    if chosen.last_self_grade == "partial":
        return "上次部分掌握，再确认一次"

    parts: list[str] = []
    if f"type:{chosen.question_type}" in missing:
        parts.append(f"缺少{type_label(chosen.question_type)}证据")
    if chosen.is_variant and "variant_questions" in missing:
        parts.append("缺少真实变式题")
    fresh = [
        tag
        for tag in chosen.skill_tags
        if tag in policy.required_skill_tags and tag not in covered
    ]
    if fresh:
        parts.append("覆盖考法：" + "、".join(fresh))
    if parts:
        return "；".join(parts)

    # 走到这里说明这道题是在做复测（题库里没有更能补缺口的题了）。
    if chosen.confirmed:
        if "day_span" in missing:
            return "复测：再做一次确认以推进跨天毕业"
        return "复测：巩固已掌握的内容"
    if chosen.last_practiced_at is None:
        return "尚未练习，先熟悉题型"
    return "练习巩固"


def summarize_plan(items: tuple[SelectionItem, ...]) -> dict[str, int]:
    """按题型统计卷子构成，供页面显示「选择题 2 道、填空 2 道…」。"""
    summary: dict[str, int] = {}
    for item in items:
        summary[item.question_type] = summary.get(item.question_type, 0) + 1
    return summary
