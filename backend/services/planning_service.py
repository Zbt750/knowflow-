"""每日推荐的知识点层打分。

优先级（已与使用者确认）：

1. 上次标记为「未掌握」
2. 已到复测日期
3. 存在「部分掌握」记录
4. 正在学习但毕业证据不足
5. 从未学习的新知识点
6. 巩固中但尚未到复测日期

同层内按「距上次练习的天数」排序：越久没碰越靠前（遗忘越久越该捡起来）。

冲突规则：一个知识点既「上次未掌握」又「正好到复测日」时，按第 1 层处理——
「做错了」比「到点了」更紧急。

推荐理由不再是笼统的状态码，而是直接复用 `analyze_gaps()` 的真实缺口，
这样「推荐 → 组卷 → 毕业判定」是同一份计算，用户不会遇到
「系统说缺填空，做完却不毕业」。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum

from backend.mastery.enums import MasteryState
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import GapReport


class GoalLayer(IntEnum):
    """推荐层级；数字越小越优先。"""

    NOT_MASTERED = 1
    DUE_REVIEW = 2
    PARTIAL = 3
    INSUFFICIENT_EVIDENCE = 4
    NEVER_STARTED = 5
    CONSOLIDATING = 6


# 层级 → 稳定理由码。页面按码映射中文，不解析文案。
LAYER_REASON_CODES: dict[GoalLayer, str] = {
    GoalLayer.NOT_MASTERED: "not_mastered",
    GoalLayer.DUE_REVIEW: "overdue_review",
    GoalLayer.PARTIAL: "partial_mastery",
    GoalLayer.INSUFFICIENT_EVIDENCE: "insufficient_evidence",
    GoalLayer.NEVER_STARTED: "preview",
    GoalLayer.CONSOLIDATING: "consolidating",
}

# 层级 → 页面中文说明。
LAYER_LABELS: dict[GoalLayer, str] = {
    GoalLayer.NOT_MASTERED: "上次未掌握",
    GoalLayer.DUE_REVIEW: "复测日已到",
    GoalLayer.PARTIAL: "上次部分掌握",
    GoalLayer.INSUFFICIENT_EVIDENCE: "毕业证据不足",
    GoalLayer.NEVER_STARTED: "尚未开始",
    GoalLayer.CONSOLIDATING: "巩固中",
}


@dataclass(frozen=True)
class GoalCandidate:
    # 只拿推荐真正需要的数据，避免推荐函数耦合 SQLAlchemy ORM。
    kp_id: str
    state: MasteryState
    next_review_at: datetime | None
    last_practiced_at: datetime | None
    flag_reason: str | None = None
    # 最近一次自评（来自该知识点最近的练习记录），用于识别未掌握 / 部分掌握。
    last_self_grade: str | None = None
    # 窗口内是否有真实确认，或有节点整体自评的基础确认。
    has_evidence: bool = False
    has_pending_objective_review: bool = False


@dataclass(frozen=True)
class SelectedGoal:
    kp_id: str
    score: float
    reason: str  # 稳定层级码，页面可映射为中文。
    # 以下三项来自 analyze_gaps：直接告诉用户「还缺什么」。
    next_step: str = ""
    missing_types: tuple[str, ...] = ()
    gap_summary: tuple[tuple[str, int, int], ...] = ()


def _resolve_layer(candidate: GoalCandidate, now: datetime) -> GoalLayer | None:
    """判断知识点落在哪一层；返回 None 表示不该推荐。"""
    # 1 上次未掌握：比「到复测日」更紧急，所以排在前面（冲突规则的落点）。
    if candidate.has_pending_objective_review or candidate.last_self_grade == "not_mastered":
        return GoalLayer.NOT_MASTERED
    # 2 已到复测日期。
    if candidate.next_review_at is not None and candidate.next_review_at <= now:
        return GoalLayer.DUE_REVIEW
    # 3 上次部分掌握：保存了历史但不构成毕业证据。
    if candidate.last_self_grade == "partial":
        return GoalLayer.PARTIAL
    # 4 正在学习但毕业证据不足：有证据、尚未毕业。
    if candidate.has_evidence and candidate.state is not MasteryState.MASTERED:
        return GoalLayer.INSUFFICIENT_EVIDENCE
    # 5 从未学习。
    if not candidate.has_evidence and candidate.state is MasteryState.UNSEEN:
        return GoalLayer.NEVER_STARTED
    # 6 巩固中但尚未到复测日期（已毕业且没到期）。
    if candidate.state is MasteryState.MASTERED:
        return GoalLayer.CONSOLIDATING
    # 其余情况（例如卡住但没有失败记录）归入「证据不足」，避免漏掉用户。
    return GoalLayer.INSUFFICIENT_EVIDENCE


def compute_goal_score(
    candidate: GoalCandidate,
    now: datetime,
    *,
    policy: MasteryPolicy | None = None,
    gap: GapReport | None = None,
) -> tuple[float, str]:
    """给一个候选知识点打分并给出层级理由码。

    分数约定：整数部分是层级（100 - 层号），小数部分是「距上次练习天数」的归一化值。
    这样既保证严格分层，又让同层内隔得最久的排在最前面。
    """
    layer = _resolve_layer(candidate, now)
    if layer is None:
        return 0.0, "not_selected"

    # 同层内按间隔天数排序；没有练习记录的当作刚接触，排在同层最后。
    days = 0.0
    if candidate.last_practiced_at is not None:
        delta = (now - candidate.last_practiced_at).total_seconds() / 86400.0
        days = max(0.0, delta)
    # 归一化到 [0, 1)，绝不超过 1，否则会跨到下一层。
    fraction = min(days, 999.0) / 1000.0
    return (100.0 - int(layer)) + fraction, "objective_review" if candidate.has_pending_objective_review else LAYER_REASON_CODES[layer]


def select_daily_goals(
    candidates: list[GoalCandidate],
    now: datetime,
    *,
    limit: int = 6,
    policies: dict[str, MasteryPolicy] | None = None,
    gaps: dict[str, GapReport] | None = None,
) -> list[SelectedGoal]:
    """返回不超过 limit 个有理由的建议；它不创建计划，也不自动出题。"""
    policies = policies or {}
    gaps = gaps or {}
    selected: list[SelectedGoal] = []
    for candidate in candidates:
        score, reason = compute_goal_score(
            candidate,
            now,
            policy=policies.get(candidate.kp_id),
            gap=gaps.get(candidate.kp_id),
        )
        if score <= 0:
            continue
        report = gaps.get(candidate.kp_id)
        selected.append(
            SelectedGoal(
                kp_id=candidate.kp_id,
                score=score,
                reason=reason,
                next_step="复测最近答错的题" if candidate.has_pending_objective_review else report.next_step if report else "",
                missing_types=report.missing_types if report else (),
                gap_summary=(
                    tuple((item.key, item.current, item.required) for item in report.items)
                    if report
                    else ()
                ),
            )
        )

    # 同分按 kp_id 排序，保证同一份数据库状态不会随机换推荐顺序。
    return sorted(selected, key=lambda item: (-item.score, item.kp_id))[:limit]
