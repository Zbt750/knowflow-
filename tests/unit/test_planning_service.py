"""每日推荐的分层与理由测试。

锁住六条已确认的优先级，以及两条容易被改错的细节：
- 同层内按「距上次练习的天数」排序（久未练习的靠前）；
- 推荐理由必须来自真实毕业缺口，而不是笼统的状态码。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.mastery.enums import MasteryState
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import analyze_gaps
from backend.mastery.types import Evidence
from backend.mastery.enums import EvidenceLevel
from backend.services.planning_service import (
    GoalCandidate,
    GoalLayer,
    compute_goal_score,
    select_daily_goals,
)

NOW = datetime(2026, 1, 10, 2, tzinfo=timezone.utc)
DAY_EARLIER = NOW - timedelta(days=3)


def goal(
    kp_id: str,
    *,
    state: MasteryState = MasteryState.UNSEEN,
    next_review_at: datetime | None = None,
    last_practiced_at: datetime | None = None,
    last_self_grade: str | None = None,
    has_evidence: bool = False,
) -> GoalCandidate:
    return GoalCandidate(
        kp_id=kp_id,
        state=state,
        next_review_at=next_review_at,
        last_practiced_at=last_practiced_at,
        last_self_grade=last_self_grade,
        has_evidence=has_evidence,
    )


def test_not_mastered_is_the_highest_layer() -> None:
    score, reason = compute_goal_score(
        goal("a", state=MasteryState.STUCK, last_self_grade="not_mastered"), NOW
    )
    assert reason == "not_mastered"
    assert int(score) == 100 - int(GoalLayer.NOT_MASTERED)


def evidence(
    question_id: str, *, question_type: str = "fill_blank", variant: bool = False
) -> Evidence:
    """构造一条已确认证据，用于验证推荐理由来自真实缺口。"""
    return Evidence(
        question_id=question_id,
        level=EvidenceLevel.CONFIRMED,
        is_variant=variant,
        occurred_at=NOW,
        source="practice_item",
        question_type=question_type,
    )


def test_not_mastered_wins_over_due_review() -> None:
    """已确认的冲突规则：上次未掌握 + 正好到复测日 → 按「未掌握」处理。"""
    candidate = goal(
        "a",
        state=MasteryState.STUCK,
        last_self_grade="not_mastered",
        next_review_at=NOW - timedelta(days=1),  # 复测日已到
    )
    _, reason = compute_goal_score(candidate, NOW)
    assert reason == "not_mastered"


def test_due_review_is_second_layer() -> None:
    score, reason = compute_goal_score(
        goal("a", state=MasteryState.MASTERED, next_review_at=NOW - timedelta(days=1)), NOW
    )
    assert reason == "overdue_review"
    assert int(score) == 100 - int(GoalLayer.DUE_REVIEW)


def test_partial_mastery_is_third_layer() -> None:
    score, reason = compute_goal_score(goal("a", last_self_grade="partial"), NOW)
    assert reason == "partial_mastery"
    assert int(score) == 100 - int(GoalLayer.PARTIAL)


def test_insufficient_evidence_is_fourth_layer() -> None:
    score, reason = compute_goal_score(
        goal("a", state=MasteryState.CONSOLIDATING, has_evidence=True), NOW
    )
    assert reason == "insufficient_evidence"
    assert int(score) == 100 - int(GoalLayer.INSUFFICIENT_EVIDENCE)


def test_never_started_is_fifth_layer() -> None:
    score, reason = compute_goal_score(goal("a", state=MasteryState.UNSEEN), NOW)
    assert reason == "preview"
    assert int(score) == 100 - int(GoalLayer.NEVER_STARTED)


def test_consolidating_is_last_layer() -> None:
    score, reason = compute_goal_score(
        goal("a", state=MasteryState.MASTERED, has_evidence=True), NOW
    )
    assert reason == "consolidating"
    assert int(score) == 100 - int(GoalLayer.CONSOLIDATING)


def test_layers_never_overlap() -> None:
    """层级必须严格分开：低层的最高分也要低于高层的最低分。"""
    ordered = [
        goal("l1", last_self_grade="not_mastered"),
        goal("l2", state=MasteryState.MASTERED, next_review_at=NOW - timedelta(days=1)),
        goal("l3", last_self_grade="partial"),
        goal("l4", state=MasteryState.CONSOLIDATING, has_evidence=True),
        goal("l5", state=MasteryState.UNSEEN),
        goal("l6", state=MasteryState.MASTERED, has_evidence=True),
    ]
    scores = [compute_goal_score(c, NOW)[0] for c in ordered]
    for higher, lower in zip(scores, scores[1:]):
        assert higher > lower, f"层级分数没有严格分开: {scores}"


def test_within_layer_older_practice_ranks_higher() -> None:
    """同层内久未练习的排前面。"""
    stale = goal(
        "stale", state=MasteryState.UNSEEN, last_practiced_at=NOW - timedelta(days=30)
    )
    fresh = goal(
        "fresh", state=MasteryState.UNSEEN, last_practiced_at=NOW - timedelta(days=1)
    )
    assert compute_goal_score(stale, NOW)[0] > compute_goal_score(fresh, NOW)[0]


def test_select_daily_goals_sorts_by_layer_then_stability() -> None:
    candidates = [
        goal("never", state=MasteryState.UNSEEN),
        goal("failed", last_self_grade="not_mastered"),
        goal("partial", last_self_grade="partial"),
        goal("due", state=MasteryState.MASTERED, next_review_at=NOW - timedelta(days=2)),
    ]
    selected = select_daily_goals(candidates, NOW)
    assert [item.kp_id for item in selected] == ["failed", "due", "partial", "never"]


def test_select_daily_goals_respects_limit() -> None:
    candidates = [goal(f"kp-{index}", state=MasteryState.UNSEEN) for index in range(10)]
    assert len(select_daily_goals(candidates, NOW)) == 6
    assert len(select_daily_goals(candidates, NOW, limit=3)) == 3


def test_recommendation_carries_real_gap_next_step() -> None:
    """推荐理由必须来自真实缺口，而不是笼统的状态码。"""
    policy = MasteryPolicy(
        min_confirmations=3,
        min_real_questions=3,
        required_question_types={"single_choice": 1, "fill_blank": 2},
    )
    window = (evidence("q1", question_type="single_choice"),)
    gap = analyze_gaps(
        window, manual_credit_count=0, manual_confirmed_at=None, policy=policy
    )
    selected = select_daily_goals(
        [goal("kp-a", state=MasteryState.CONSOLIDATING, has_evidence=True)],
        NOW,
        policies={"kp-a": policy},
        gaps={"kp-a": gap},
    )
    assert selected[0].next_step
    assert "填空题" in selected[0].next_step
    assert selected[0].missing_types == ("fill_blank",)
    assert selected[0].gap_summary