from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from backend.mastery.enums import EventType, EvidenceLevel, MasteryState, SelfGrade
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import graduation_check, update_evidence_window
from backend.mastery.types import DomainLearningEvent, MasterySnapshot, TransitionResult


def _next_review(occurred_at: datetime, stage: int, policy: MasteryPolicy) -> tuple[int, datetime]:
    # stage 指向本次将使用的间隔下标；最后一档后保持最后一个间隔。
    safe_stage = min(stage, len(policy.review_intervals_days) - 1)
    return safe_stage, occurred_at + timedelta(days=policy.review_intervals_days[safe_stage])


def _not_graduated_state(snapshot: MasterySnapshot) -> MasteryState:
    # 窗口或自评基础证据存在时，表示用户已在积累确认；否则仍未开始有效学习。
    return (
        MasteryState.CONSOLIDATING
        if snapshot.evidence_window or snapshot.manual_credit_count
        else MasteryState.UNSEEN
    )


def _try_graduate(snapshot: MasterySnapshot, occurred_at: datetime, policy: MasteryPolicy) -> TransitionResult:
    graduated, reason = graduation_check(
        snapshot.evidence_window,
        manual_credit_count=snapshot.manual_credit_count,
        manual_confirmed_at=snapshot.manual_confirmed_at,
        policy=policy,
    )
    if not graduated:
        updated = replace(
            snapshot, state=_not_graduated_state(snapshot), next_review_at=None, mastered_at=None
        )
        return TransitionResult(updated, reason, updated != snapshot)

    stage, next_review_at = _next_review(occurred_at, 0, policy)
    updated = replace(
        snapshot,
        state=MasteryState.MASTERED,
        review_stage=stage,
        next_review_at=next_review_at,
        mastered_at=occurred_at,
    )
    return TransitionResult(updated, "graduated", updated != snapshot)


def transition(
    current: MasterySnapshot,
    event: DomainLearningEvent,
    policy: MasteryPolicy,
) -> TransitionResult:
    """状态机唯一入口：输入当前投影与一个领域事件，输出新投影与原因码。"""
    # 显式重置不删除历史事件，只清空当前投影。
    if event.event_type is EventType.STATE_RESET:
        updated = MasterySnapshot(MasteryState.UNSEEN, (), 0, None, None, None, 0, None)
        return TransitionResult(updated, "state_reset", updated != current)

    # 叶子节点整体自评：贡献透明基础证据，不伪造 QuestionAttempt。
    if event.event_type is EventType.NODE_SELF_ASSESSED:
        assert event.self_grade is not None
        if event.self_grade is SelfGrade.NOT_MASTERED:
            updated = replace(
                current,
                state=MasteryState.STUCK,
                evidence_window=(),
                next_review_at=None,
                mastered_at=None,
                node_self_grade=SelfGrade.NOT_MASTERED,
                manual_credit_count=0,
                manual_confirmed_at=None,
            )
            return TransitionResult(updated, "node_not_mastered", updated != current)
        if event.self_grade is SelfGrade.PARTIAL:
            # 只去掉基础确认，既往真实确认窗口与练习历史都保留。
            updated = replace(
                current,
                node_self_grade=SelfGrade.PARTIAL,
                manual_credit_count=0,
                manual_confirmed_at=None,
            )
            return _try_graduate(updated, event.occurred_at, policy)
        if event.self_grade is SelfGrade.MASTERED:
            # 恰好写入 policy.manual_mastered_credit（=2）个基础确认，绝不写成两条作答。
            updated = replace(
                current,
                node_self_grade=SelfGrade.MASTERED,
                manual_credit_count=policy.manual_mastered_credit,
                manual_confirmed_at=event.occurred_at,
            )
            return _try_graduate(updated, event.occurred_at, policy)
        return TransitionResult(current, "node_self_assessment_skipped", False)

    # 一题的自评；没有证据的浏览/跳过不改变状态。
    if event.event_type is not EventType.QUESTION_SELF_ASSESSED or event.evidence is None:
        return TransitionResult(current, "no_state_evidence", False)

    evidence = event.evidence
    if evidence.level is EvidenceLevel.FAILURE:
        # 真正未掌握同时取消“我整体掌握”的基础额度，避免旧自评覆盖新失败。
        updated = replace(
            current,
            state=MasteryState.STUCK,
            evidence_window=(),
            next_review_at=None,
            mastered_at=None,
            node_self_grade=SelfGrade.NOT_MASTERED,
            manual_credit_count=0,
            manual_confirmed_at=None,
        )
        return TransitionResult(updated, "not_mastered", updated != current)

    if evidence.level is not EvidenceLevel.CONFIRMED:
        # partial / weak 完整记录在历史表，但不影响当前毕业累计。
        return TransitionResult(current, "no_confirmed_evidence", False)

    window = update_evidence_window(
        current.evidence_window, evidence, max_size=policy.max_evidence_window
    )
    updated = replace(current, evidence_window=window)

    # 已毕业后继续确认一题，只刷新该题最近确认时间；不覆盖毕业时间和复测计划。
    if current.state is MasteryState.MASTERED:
        return TransitionResult(updated, "mastery_already_confirmed", updated != current)

    return _try_graduate(updated, event.occurred_at, policy)