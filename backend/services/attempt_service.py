from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.mastery.enums import EventType, MasteryState, SelfGrade
from backend.mastery.policy import MasteryPolicy
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
    ExamQuestionReference,
    KpMasteryPolicy,
    KpState,
    LearningEvent,
    PracticeItem,
    QuestionAttempt,
)
from backend.services.practice_lock import lock_practice_item


@dataclass(frozen=True)
class AssessmentResult:
    # 路由只需要序列化这个小对象，不要拿 ORM 对象到处传。
    state: MasteryState
    reason_code: str
    next_review_at: datetime | None
    effective_count: int


def _count(snapshot: MasterySnapshot) -> int:
    # 页面显示的“有效确认数”只有这一个算法，测试也读它。
    return effective_confirmation_count(
        snapshot.evidence_window, manual_credit_count=snapshot.manual_credit_count
    )


def objective_result_for(*, selected_option: str | None, correct_answer: str | None) -> str:
    """选择题的客观结果。

    只在「用户明确选了选项」且「题目有标准答案」时才判定 right/wrong；
    填空题、纸笔大题、主观题以及未作答一律是 unknown——这些题无法可靠机器判分，
    绝不能用字符串包含之类猜测冒充判分。
    这个结果只是复盘参考，不参与掌握度与毕业判定（那只看 self_grade）。
    """
    if selected_option is None or correct_answer is None:
        return "unknown"
    chosen = selected_option.strip().upper()
    expected = correct_answer.strip().upper()
    if not chosen or not expected:
        return "unknown"
    return "right" if chosen == expected else "wrong"


def assess_practice_item(
    session: Session,
    *,
    item_id: UUID,
    raw_answer: str | None,
    self_grade: SelfGrade,
    idempotency_key: str,
    now: datetime,
    selected_option: str | None = None,
) -> AssessmentResult:
    """提交一次用户自评；重复 key 返回原结果，首次请求一次性完成三表写入。"""
    old_attempt = session.scalar(
        select(QuestionAttempt).where(QuestionAttempt.idempotency_key == idempotency_key)
    )
    if old_attempt is not None:
        if old_attempt.practice_item_id != item_id or old_attempt.grading_evidence is not None:
            raise ValueError("idempotency_key_conflict")
        # 前端网络超时重试时不再创建第二条历史，也不能再次累计毕业确认。
        state = session.get(KpState, old_attempt.kp_id)
        count = _count(snapshot_from_storage(state)) if state is not None else 0
        return AssessmentResult(
            MasteryState(old_attempt.result_state),
            old_attempt.reason_code,
            old_attempt.next_review_at,
            count,
        )

    # 先锁队列项和投影：同一题的重复提交必须串行，否则两次请求会同时读到旧窗口。
    item = lock_practice_item(session, item_id)
    # 等待锁期间另一请求可能已提交；重新查幂等记录，避免同 key 重试变成冲突。
    repeated = session.scalar(select(QuestionAttempt).where(QuestionAttempt.idempotency_key == idempotency_key))
    if repeated is not None:
        if repeated.practice_item_id != item_id or repeated.grading_evidence is not None:
            raise ValueError("idempotency_key_conflict")
        state = session.get(KpState, repeated.kp_id)
        return AssessmentResult(MasteryState(repeated.result_state), repeated.reason_code,
                                repeated.next_review_at, _count(snapshot_from_storage(state)) if state else 0)
    if item.completed_at is not None:
        # 幂等重试已在函数开头按同 key 返回；换一个 key 再交同一题不是“重做”，必须拒绝。
        raise ValueError("practice_item_already_assessed")
    kp_state = session.scalar(
        select(KpState).where(KpState.kp_id == item.kp_id).with_for_update()
    )
    if kp_state is None:
        raise ValueError("kp_state_not_found")

    if self_grade is SelfGrade.SKIP:
        # skip 是用户的“先不记这题”：不写任何一张表，把当前进度原样返回给页面。
        snapshot = snapshot_from_storage(kp_state)
        return AssessmentResult(snapshot.state, "skipped", snapshot.next_review_at, _count(snapshot))

    question = item.question  # 普通题的题干、答案与题型。
    reference: ExamQuestionReference | None = item.exam_reference
    if question is None and reference is None:
        raise ValueError("practice_item_source_missing")
    # This endpoint is self-report only; even a selected option is not a verified
    # machine verdict. The answer-submission endpoint owns objective grading.
    objective_result = "unknown"
    attempt = QuestionAttempt(
        practice_item_id=item.id,
        question_id=question.id if question is not None else None,
        exam_reference_id=reference.id if reference is not None else None,
        kp_id=item.kp_id,
        # 用户输入只供练习历史回看；空白统一存 None，且绝不参与掌握度与毕业计算。
        raw_answer=raw_answer.strip() if raw_answer and raw_answer.strip() else None,
        objective_result=objective_result,
        self_grade=self_grade.value,
        idempotency_key=idempotency_key,
        submitted_at=now,
        result_state="pending",  # flush 前满足 NOT NULL；下面会写入真实 transition 结果。
        reason_code="pending",
        next_review_at=None,
    )
    session.add(attempt)
    session.flush()  # 拿到 attempt.id，供 LearningEvent 的 source_id 审计关联。

    # 复用投影事务，但自述不构造旧规则的 CONFIRMED 证据。
    policy = policy_from_storage(session.get(KpMasteryPolicy, item.kp_id))
    event = DomainLearningEvent(
        event_type=EventType.PRACTICE_SELF_REPORTED, occurred_at=now, self_grade=self_grade
    )
    result = transition(snapshot_from_storage(kp_state), event, policy)

    # kp_states 是当前投影；learning_events 是可审计事实。二者和 attempt 同一事务提交。
    apply_snapshot(kp_state, result.snapshot)
    item.completed_at = now
    item.latest_self_grade = self_grade.value
    # 必须先 flush：本会话是 autoflush=False，否则下面的查询看不到刚刚赋值的 completed_at，
    # 会把这道刚做完的题自己查回来（remaining 永不为 None），
    # 于是 daily_plans.status 永远停在 active，总结页不可达、已完成的卷还能继续追加题。
    session.flush()
    remaining = session.scalar(
        select(PracticeItem.id).where(
            PracticeItem.plan_id == item.plan_id, PracticeItem.completed_at.is_(None)
        )
    )
    if remaining is None:
        item.plan.status = "completed"  # 当前计划没有待做题时，后端统一切换总结页状态。
    session.add(
        LearningEvent(
            kp_id=item.kp_id,
            source_id=attempt.id,
            event_type=event.event_type.value,
            evidence_level="weak",
            payload=snapshot_to_storage(result.snapshot, result.reason_code),
            occurred_at=now,  # NOT NULL；事件时间必须显式写，不能靠数据库默认值。
            idempotency_key=f"attempt:{idempotency_key}",  # 事件也只允许写一次。
        )
    )
    attempt.result_state = result.snapshot.state.value
    attempt.reason_code = result.reason_code
    attempt.next_review_at = result.snapshot.next_review_at
    return AssessmentResult(
        result.snapshot.state,
        result.reason_code,
        result.snapshot.next_review_at,
        _count(result.snapshot),
    )
