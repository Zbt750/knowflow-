from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from backend.mastery.enums import EvidenceLevel, EventType, MasteryState, SelfGrade


@dataclass(frozen=True)
class Evidence:
    # 只保存题目毕业判断所需的轻量事实；完整练习历史在 QuestionAttempt 中。
    question_id: str | None
    level: EvidenceLevel
    is_variant: bool
    occurred_at: datetime
    source: str  # "practice_item"；不根据 automatic/manual/chat 来源改变毕业规则。
    # 作答形式（选择/填空/计算/证明/主观）；题型覆盖检查依赖它。
    question_type: str = "fill_blank"
    # 这道题覆盖的考法标签；必考考法覆盖检查依赖它。
    skill_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainLearningEvent:
    # 状态机输入，不携带 SQLAlchemy 或 HTTP 对象。
    event_type: EventType
    occurred_at: datetime
    self_grade: SelfGrade | None = None
    evidence: Evidence | None = None
    payload: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True)
class MasterySnapshot:
    # KpState 的纯领域投影；一个快照只描述“当前这一个叶子知识点”。
    # 故意不放 kp_id：纯函数可复用，调用方自己知道在处理哪个叶子。
    state: MasteryState
    evidence_window: tuple[Evidence, ...]
    review_stage: int
    next_review_at: datetime | None
    mastered_at: datetime | None
    node_self_grade: SelfGrade | None
    manual_credit_count: int
    manual_confirmed_at: datetime | None
    assessment_basis: str = "legacy_self_reported"
    pending_review_question_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransitionResult:
    snapshot: MasterySnapshot
    reason_code: str
    changed: bool
