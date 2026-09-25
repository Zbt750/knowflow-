from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.mastery.enums import EventType, MasteryState, SelfGrade
from backend.mastery.rules import effective_confirmation_count
from backend.mastery.storage import (
    apply_snapshot,
    policy_from_storage,
    snapshot_from_storage,
    snapshot_to_storage,
)
from backend.mastery.transition import transition
from backend.mastery.types import DomainLearningEvent, MasterySnapshot
from backend.models.learning import (
    KnowledgePoint,
    KpMasteryPolicy,
    KpState,
    LearningEvent,
)


@dataclass(frozen=True)
class NodeAssessmentResult:
    state: MasteryState
    reason_code: str
    next_review_at: datetime | None
    effective_count: int


def _result(snapshot: MasterySnapshot, reason_code: str) -> NodeAssessmentResult:
    return NodeAssessmentResult(
        snapshot.state,
        reason_code,
        snapshot.next_review_at,
        effective_confirmation_count(
            snapshot.evidence_window, manual_credit_count=snapshot.manual_credit_count
        ),
    )


def assess_knowledge_node(
    session: Session,
    *,
    kp_id: UUID,
    self_grade: SelfGrade,
    idempotency_key: str,
    now: datetime,
) -> NodeAssessmentResult:
    """叶子节点的整体自评；贡献透明基础证据，不伪造题目作答。"""
    # 先锁叶子和投影；父节点只能聚合，不能在这里领取基础证据。
    kp = session.scalar(
        select(KnowledgePoint).where(KnowledgePoint.id == kp_id).with_for_update()
    )
    if kp is None:
        raise ValueError("knowledge_point_not_found")
    if not kp.is_assessable:
        raise ValueError("node_not_assessable")
    state = session.scalar(select(KpState).where(KpState.kp_id == kp_id).with_for_update())
    if state is None:
        raise ValueError("kp_state_not_found")

    # 节点自评没有 QuestionAttempt 可以承载幂等键，所以用事件表的唯一约束兜底。
    event_key = f"node:{idempotency_key}"
    existing = session.scalar(
        select(LearningEvent).where(LearningEvent.idempotency_key == event_key)
    )
    if existing is not None:
        # 同一次点击的重试：不再叠加基础证据，直接回读当前投影与上次的原因码。
        snapshot = snapshot_from_storage(state)
        return _result(
            snapshot, str(existing.payload.get("reason_code", "node_self_assessment_replayed"))
        )

    # 按这个叶子自己的策略判定：基础确认只帮助有效确认数，不能替代真实题与题型覆盖。
    policy = policy_from_storage(session.get(KpMasteryPolicy, kp_id))
    event = DomainLearningEvent(
        event_type=EventType.NODE_SELF_ASSESSED, occurred_at=now, self_grade=self_grade
    )
    result = transition(snapshot_from_storage(state), event, policy)
    apply_snapshot(state, result.snapshot)
    session.add(
        LearningEvent(
            kp_id=kp_id,
            source_id=None,  # 节点自评没有对应的 QuestionAttempt。
            event_type=event.event_type.value,
            evidence_level=None,  # 基础证据不进证据窗口，它单独计数。
            payload=snapshot_to_storage(result.snapshot, result.reason_code),
            occurred_at=now,
            idempotency_key=event_key,
        )
    )
    return _result(result.snapshot, result.reason_code)