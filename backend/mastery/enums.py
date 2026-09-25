from __future__ import annotations

from enum import Enum, StrEnum


class MasteryState(str, Enum):
    """可考核叶子节点的当前状态投影。

    与产品规则中的三个可见态一一对应：未学（unseen）、确认累积中（consolidating）、
    卡住（stuck）、已毕业（mastered）。
    """

    UNSEEN = "unseen"
    CONSOLIDATING = "consolidating"
    STUCK = "stuck"
    MASTERED = "mastered"


class SelfGrade(str, Enum):
    """用户对一道题或一个叶子节点的自评。"""

    MASTERED = "mastered"
    PARTIAL = "partial"
    NOT_MASTERED = "not_mastered"
    SKIP = "skip"


class EventType(str, Enum):
    """写入 learning_events 的领域事件类型。"""

    QUESTION_SELF_ASSESSED = "question_self_assessed"
    NODE_SELF_ASSESSED = "node_self_assessed"
    CONTENT_VIEWED = "content_viewed"
    FOLLOWUP_ASKED = "followup_asked"
    REVIEW_PASSED = "review_passed"
    REVIEW_FAILED = "review_failed"
    STATE_RESET = "state_reset"


class EvidenceLevel(str, Enum):
    """一条证据对毕业累计的作用级别。"""

    CONFIRMED = "confirmed"
    PARTIAL = "partial"
    WEAK = "weak"
    FAILURE = "failure"


class QuestionType(StrEnum):
    """题目作答形式。它决定「怎么答」，与 question_role（学习作用）互不替代。"""

    SINGLE_CHOICE = "single_choice"
    FILL_BLANK = "fill_blank"
    CALCULATION = "calculation"
    PROOF = "proof"
    SUBJECTIVE = "subjective"


class QuestionRole(StrEnum):
    """题目在学习中的作用。"""

    BASIC = "basic"
    TYPICAL = "typical"
    VARIANT = "variant"
    COMPREHENSIVE = "comprehensive"


class TimeBudget(StrEnum):
    """生成练习卷前用户选择的时间预算。"""

    LIGHT = "light"
    STANDARD = "standard"
    DEEP = "deep"


# 各题型默认预计耗时（分钟）。
# 题目自带 estimated_minutes 时以题目为准；缺失时用这张表兜底。
DEFAULT_MINUTES_BY_TYPE: dict[str, int] = {
    QuestionType.SINGLE_CHOICE.value: 3,
    QuestionType.FILL_BLANK.value: 5,
    QuestionType.CALCULATION.value: 12,
    QuestionType.PROOF.value: 20,
    QuestionType.SUBJECTIVE.value: 20,
}

# 三档时间预算的总分钟数。
BUDGET_MINUTES: dict[str, int] = {
    TimeBudget.LIGHT.value: 45,
    TimeBudget.STANDARD.value: 90,
    TimeBudget.DEEP.value: 120,
}


def default_minutes(question_type: str) -> int:
    """题型缺失预计耗时时使用默认值。"""
    return DEFAULT_MINUTES_BY_TYPE.get(question_type, 5)