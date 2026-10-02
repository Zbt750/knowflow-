from __future__ import annotations

from datetime import datetime

from backend.mastery.enums import EvidenceLevel, MasteryState, SelfGrade
from backend.mastery.policy import MasteryPolicy
from backend.mastery.types import Evidence, MasterySnapshot
from backend.models.learning import KpMasteryPolicy, KpState


def evidence_to_storage(evidence: Evidence) -> dict[str, object]:
    # 只存重建窗口必需的字段；时间写成带时区的 ISO 字符串，读回来仍是同一时刻。
    return {
        "question_id": evidence.question_id,
        "level": evidence.level.value,
        "is_variant": evidence.is_variant,
        "occurred_at": evidence.occurred_at.isoformat(),
        "source": evidence.source,
        # 题型与考法必须入窗口，否则毕业判定无法检查覆盖情况。
        "question_type": evidence.question_type,
        "skill_tags": list(evidence.skill_tags),
    }


def evidence_from_storage(payload: dict[str, object]) -> Evidence:
    # 枚举用值构造而不是取下标：库里出现未知值时立刻报错，不静默降级成弱证据。
    question_id = payload["question_id"]
    raw_tags = payload.get("skill_tags") or ()
    return Evidence(
        question_id=str(question_id) if question_id is not None else None,
        level=EvidenceLevel(str(payload["level"])),
        is_variant=bool(payload["is_variant"]),
        occurred_at=datetime.fromisoformat(str(payload["occurred_at"])),
        source=str(payload.get("source", "practice_item")),
        # 升级前写入的证据没有这两个字段：给出稳定默认值，读旧数据不会崩。
        question_type=str(payload.get("question_type", "fill_blank")),
        skill_tags=tuple(str(tag) for tag in raw_tags),
    )


def snapshot_from_storage(state: KpState) -> MasterySnapshot:
    """把一行 kp_states 读成纯领域快照。"""
    return MasterySnapshot(
        state=MasteryState(state.state),
        evidence_window=tuple(evidence_from_storage(item) for item in state.evidence_window),
        review_stage=state.review_stage,
        next_review_at=state.next_review_at,
        mastered_at=state.mastered_at,
        node_self_grade=SelfGrade(state.node_self_grade) if state.node_self_grade else None,
        manual_credit_count=state.manual_credit_count,
        manual_confirmed_at=state.manual_confirmed_at,
        assessment_basis=getattr(state, "assessment_basis", "legacy_self_reported"),
        pending_review_question_ids=tuple(getattr(state, "pending_review_question_ids", None) or ()),
    )


def apply_snapshot(state: KpState, snapshot: MasterySnapshot) -> None:
    """把快照写回投影行；只写状态字段，不动主键与 created_at / updated_at。"""
    state.state = snapshot.state.value
    state.evidence_window = [evidence_to_storage(item) for item in snapshot.evidence_window]
    state.review_stage = snapshot.review_stage
    state.next_review_at = snapshot.next_review_at
    state.mastered_at = snapshot.mastered_at
    state.node_self_grade = snapshot.node_self_grade.value if snapshot.node_self_grade else None
    state.manual_credit_count = snapshot.manual_credit_count
    state.manual_confirmed_at = snapshot.manual_confirmed_at
    state.assessment_basis = snapshot.assessment_basis
    state.pending_review_question_ids = list(snapshot.pending_review_question_ids)


def snapshot_to_storage(snapshot: MasterySnapshot, reason_code: str) -> dict[str, object]:
    """learning_events.payload 的稳定结构；事件是不可变事实，必须能独立读懂。"""
    return {
        "state": snapshot.state.value,
        "assessment_basis": snapshot.assessment_basis,
        "pending_review_question_ids": list(snapshot.pending_review_question_ids),
        "reason_code": reason_code,
        "evidence_window_size": len(snapshot.evidence_window),
        "manual_credit_count": snapshot.manual_credit_count,
        "review_stage": snapshot.review_stage,
        "next_review_at": snapshot.next_review_at.isoformat() if snapshot.next_review_at else None,
        "mastered_at": snapshot.mastered_at.isoformat() if snapshot.mastered_at else None,
    }


# --------------------------------------------------------------------------- #
# 每知识点毕业策略
# --------------------------------------------------------------------------- #


def policy_from_storage(row: KpMasteryPolicy | None) -> MasteryPolicy:
    """把一行 kp_mastery_policies 读成纯领域策略。

    没有单独配置的叶子使用 `MasteryPolicy()` 的默认值——
    「尚未配置」不该等价于「无法毕业」，也不该等价于「随便毕业」。
    """
    if row is None:
        return MasteryPolicy()
    return MasteryPolicy(
        min_confirmations=row.min_confirmations,
        min_real_questions=row.min_real_questions,
        required_question_types=dict(row.required_question_types or {}),
        excluded_question_types=frozenset(row.excluded_question_types or []),
        required_skill_tags=frozenset(row.required_skill_tags or []),
        required_variant_count=row.required_variant_count,
        min_day_span=row.min_day_span,
        manual_mastered_credit=row.manual_mastered_credit,
        review_intervals_days=tuple(row.review_intervals_days or (7, 15, 30)),
        max_evidence_window=row.max_evidence_window,
        note=row.note,
    )


def policy_to_storage(policy: MasteryPolicy, row: KpMasteryPolicy) -> None:
    """把纯领域策略写回 ORM 行（不动主键）。"""
    row.min_confirmations = policy.min_confirmations
    row.min_real_questions = policy.min_real_questions
    row.required_question_types = dict(policy.required_question_types)
    row.excluded_question_types = sorted(policy.excluded_question_types)
    row.required_skill_tags = sorted(policy.required_skill_tags)
    row.required_variant_count = policy.required_variant_count
    row.min_day_span = policy.min_day_span
    row.manual_mastered_credit = policy.manual_mastered_credit
    row.review_intervals_days = list(policy.review_intervals_days)
    row.max_evidence_window = policy.max_evidence_window
    row.note = policy.note
