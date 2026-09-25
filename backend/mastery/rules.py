from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.mastery.enums import EvidenceLevel
from backend.mastery.policy import MasteryPolicy
from backend.mastery.types import Evidence

SHANGHAI = ZoneInfo("Asia/Shanghai")  # 依赖 tzdata：Windows 与 slim 镜像没有 IANA 时区库


def update_evidence_window(
    current: tuple[Evidence, ...],
    evidence: Evidence,
    *,
    max_size: int,
) -> tuple[Evidence, ...]:
    # 用户明确“未掌握”会重置本轮毕业累计。
    if evidence.level is EvidenceLevel.FAILURE:
        return ()

    # 部分掌握、跳过不影响已有确认窗口。
    if evidence.level is not EvidenceLevel.CONFIRMED:
        return current

    # 同一题只保留最近一次已掌握确认；不会靠反复点击同题刷不同题数。
    by_question: dict[str | None, Evidence] = {item.question_id: item for item in current}
    by_question[evidence.question_id] = evidence
    newest_first = sorted(by_question.values(), key=lambda item: item.occurred_at, reverse=True)
    return tuple(newest_first[:max_size])


def _day(value: datetime):
    return value.astimezone(SHANGHAI).date()


def confirmation_dates(
    window: tuple[Evidence, ...],
    *,
    manual_credit_count: int = 0,
    manual_confirmed_at: datetime | None = None,
) -> list[date]:
    """贡献毕业判定的全部上海日期，已升序排序。

    状态机的跨天门与页面的 first/last/day_span 展示必须共用这一个实现：
    若页面只算 evidence_window 而状态机还算 manual_confirmed_at，
    用户点过“我已掌握”后会看到 day_span=0，但状态机认为跨度已足够，两套口径互相矛盾。
    """
    dates = [_day(item.occurred_at) for item in window]
    if manual_credit_count > 0 and manual_confirmed_at is not None:
        dates.append(_day(manual_confirmed_at))
    return sorted(dates)


def effective_confirmation_count(window: tuple[Evidence, ...], *, manual_credit_count: int) -> int:
    """有效确认数 = 窗口内真实题目确认数 + 节点整体自评的透明基础证据数。

    第 07 篇的 AssessmentResponse 和知识树页都读这个数字，
    所以它必须只有一个实现：窗口本身只会含 CONFIRMED 证据。
    """
    return len(window) + manual_credit_count


def type_counts(window: tuple[Evidence, ...]) -> dict[str, int]:
    """窗口内每种题型覆盖了多少道不同真实题。"""
    counts: dict[str, int] = {}
    for item in window:
        counts[item.question_type] = counts.get(item.question_type, 0) + 1
    return counts


def covered_skill_tags(window: tuple[Evidence, ...]) -> set[str]:
    """窗口内已经考过的考法标签集合。"""
    tags: set[str] = set()
    for item in window:
        tags.update(item.skill_tags)
    return tags


def graduation_check(
    window: tuple[Evidence, ...],
    *,
    manual_credit_count: int,
    manual_confirmed_at: datetime | None,
    policy: MasteryPolicy,
) -> tuple[bool, str]:
    """按该知识点自己的策略判断能否毕业。

    判定顺序刻意从「最基础的事实」到「最细的覆盖」：
    数量不够时说“确认不足”，而不是先抱怨缺某道大题——这样原因码对用户更有指导性。
    """
    # 1) 有效确认数 = 窗口内真实确认数 + 节点整体自评的透明基础确认数。
    if (
        effective_confirmation_count(window, manual_credit_count=manual_credit_count)
        < policy.min_confirmations
    ):
        return False, "insufficient_confirmed_evidence"

    # 2) 不同真实题目数：基础确认不能替代真实作答。
    if len(window) < policy.min_real_questions:
        return False, "insufficient_real_questions"

    # 3) 必考题型覆盖：每种 required 题型都要达到自己的配额。
    counts = type_counts(window)
    for question_type, required in policy.required_question_types.items():
        if counts.get(question_type, 0) < required:
            return False, f"missing_question_type:{question_type}"

    # 4) 真实变式题数量。
    if sum(item.is_variant for item in window) < policy.required_variant_count:
        return False, "missing_real_variant"

    # 5) 必考考法覆盖：已考标签必须覆盖要求的全部标签。
    if policy.required_skill_tags:
        missing_tags = policy.required_skill_tags - covered_skill_tags(window)
        if missing_tags:
            return False, f"missing_skill_tag:{sorted(missing_tags)[0]}"

    # 6) 跨天确认：首尾有效确认的上海日期相差至少 min_day_span 天。
    dates = confirmation_dates(
        window,
        manual_credit_count=manual_credit_count,
        manual_confirmed_at=manual_confirmed_at,
    )
    if not dates or (max(dates) - min(dates)).days < policy.min_day_span:
        return False, "insufficient_day_span"

    return True, "graduated"


# --------------------------------------------------------------------------- #
# 缺口分析：推荐算法、题库校验与页面展示共用的唯一实现
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GapItem:
    """一条毕业条件的当前进度。

    `key` 是稳定机器码，页面按它决定图标与分组，不解析中文。
    """

    key: str
    label: str
    current: int
    required: int
    satisfied: bool


@dataclass(frozen=True)
class GapReport:
    """一个叶子的完整毕业缺口报告。"""

    items: tuple[GapItem, ...]
    reasons: tuple[str, ...]
    missing_types: tuple[str, ...]
    missing_skill_tags: tuple[str, ...]

    @property
    def can_graduate(self) -> bool:
        return all(item.satisfied for item in self.items)

    @property
    def next_step(self) -> str:
        """给用户看的「下一步」；按判定优先级给出最有指导性的一条。"""
        return self.reasons[0] if self.reasons else "已满足全部毕业条件"


# 题型机器码 → 页面文案。只在这里映射一次。
_TYPE_LABELS: dict[str, str] = {
    "single_choice": "选择题",
    "fill_blank": "填空题",
    "calculation": "计算大题",
    "proof": "证明题",
    "subjective": "主观题",
}


def type_label(question_type: str) -> str:
    return _TYPE_LABELS.get(question_type, question_type)


def analyze_gaps(
    window: tuple[Evidence, ...],
    *,
    manual_credit_count: int,
    manual_confirmed_at: datetime | None,
    policy: MasteryPolicy,
) -> GapReport:
    """逐条算出毕业条件的进度，并给出还缺什么。"""
    counts = type_counts(window)
    confirmations = effective_confirmation_count(
        window, manual_credit_count=manual_credit_count
    )
    real_questions = len(window)
    variants = sum(item.is_variant for item in window)
    covered = covered_skill_tags(window)
    missing_tags = sorted(policy.required_skill_tags - covered)

    items: list[GapItem] = [
        GapItem(
            "effective_confirmations",
            "有效确认",
            confirmations,
            policy.min_confirmations,
            confirmations >= policy.min_confirmations,
        ),
        GapItem(
            "real_questions",
            "真实题目",
            real_questions,
            policy.min_real_questions,
            real_questions >= policy.min_real_questions,
        ),
    ]

    # 必考题型逐项列出；excluded 的题型不出现在报告里（用户不需要关心）。
    missing_types: list[str] = []
    for question_type, required in policy.required_question_types.items():
        current = counts.get(question_type, 0)
        if current < required:
            missing_types.append(question_type)
        items.append(
            GapItem(
                f"type:{question_type}",
                type_label(question_type),
                current,
                required,
                current >= required,
            )
        )

    items.append(
        GapItem(
            "variant_questions",
            "变式题",
            variants,
            policy.required_variant_count,
            variants >= policy.required_variant_count,
        )
    )
    if policy.required_skill_tags:
        items.append(
            GapItem(
                "skill_tags",
                "考法覆盖",
                len(policy.required_skill_tags) - len(missing_tags),
                len(policy.required_skill_tags),
                not missing_tags,
            )
        )

    dates = confirmation_dates(
        window,
        manual_credit_count=manual_credit_count,
        manual_confirmed_at=manual_confirmed_at,
    )
    span = (max(dates) - min(dates)).days if dates else 0
    items.append(
        GapItem("day_span", "跨天确认", span, policy.min_day_span, span >= policy.min_day_span)
    )

    # 「下一步」的原因按「越具体越先说」排序：
    # 用户最需要知道的是「还缺哪类题／哪类考法」，而不是抽象的确认数。
    reasons: list[str] = []
    for question_type in missing_types:
        need = policy.required_question_types[question_type] - counts.get(question_type, 0)
        reasons.append(f"完成 {need} 道{type_label(question_type)}")
    if missing_tags:
        reasons.append("覆盖考法：" + "、".join(missing_tags))
    if variants < policy.required_variant_count:
        reasons.append(f"完成 {policy.required_variant_count - variants} 道真实变式题")
    if real_questions < policy.min_real_questions:
        reasons.append(
            f"再完成 {policy.min_real_questions - real_questions} 道真实题（不重复同一道题）"
        )
    if confirmations < policy.min_confirmations:
        reasons.append(
            f"有效确认还差 {policy.min_confirmations - confirmations} 个"
            "（节点整体自评最多贡献 "
            f"{policy.manual_mastered_credit} 个基础确认）"
        )
    if dates and (max(dates) - min(dates)).days < policy.min_day_span:
        reasons.append(
            f"跨天确认还差 {policy.min_day_span - (max(dates) - min(dates)).days} 天（不能当天毕业）"
        )
    elif not dates and policy.min_day_span > 0:
        reasons.append("先形成第一条有效确认")

    return GapReport(
        items=tuple(items),
        reasons=tuple(reasons),
        missing_types=tuple(missing_types),
        missing_skill_tags=tuple(missing_tags),
    )


def pool_capacity_check(policy: MasteryPolicy, pool: dict[str, int]) -> bool:
    """题库是否足以满足该知识点自己的毕业策略。

    `pool` 是「题型 → 该题型可用题目数」。excluded 的题型不参与检查——
    明确不考大题的叶子没有大题是正常的。
    """
    for question_type, required in policy.required_question_types.items():
        if pool.get(question_type, 0) < required:
            return False
    return True