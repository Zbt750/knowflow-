from __future__ import annotations

from datetime import datetime

from backend.mastery.enums import EvidenceLevel, SelfGrade
from backend.mastery.types import Evidence


def classify_evidence(
    *,
    self_grade: SelfGrade,
    question_id: str,
    is_variant: bool,
    occurred_at: datetime,
    question_type: str = "fill_blank",
    skill_tags: tuple[str, ...] = (),
    source: str = "practice_item",
) -> Evidence:
    """把一次用户自评映射成状态机证据；objective_result 不参与这里。

    `question_type` 与 `skill_tags` 必须一起记入证据，否则毕业判定无法检查
    「题型是否覆盖」和「考法是否覆盖」。
    """
    # 跨天毕业依赖真实学习日；没有时区会导致不同机器得到不同日期。
    if occurred_at.tzinfo is None:
        raise ValueError("occurred_at 必须带时区")

    # 已掌握是唯一进入毕业窗口的题目证据。
    if self_grade is SelfGrade.MASTERED:
        level = EvidenceLevel.CONFIRMED
    # 部分掌握要留给历史页面查看，但它相当于“本题不提供毕业确认”。
    elif self_grade is SelfGrade.PARTIAL:
        level = EvidenceLevel.PARTIAL
    # 未掌握明确打断本轮累计；不是因为机器判错，而是用户的最终学习判断。
    elif self_grade is SelfGrade.NOT_MASTERED:
        level = EvidenceLevel.FAILURE
    else:
        # skip 不改状态，只保留为弱记录；调用方选择根本不写 attempt。
        level = EvidenceLevel.WEAK

    return Evidence(
        question_id=question_id,
        level=level,
        is_variant=is_variant,
        occurred_at=occurred_at,
        source=source,
        question_type=question_type,
        skill_tags=tuple(skill_tags),
    )
