from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy import exists, select

from backend.mastery.enums import EvidenceLevel, MasteryState, SelfGrade
from backend.mastery.policy import MasteryPolicy
from backend.mastery.types import Evidence, MasterySnapshot
from backend.models.learning import (
    KpGraduationQuestionSetVersion,
    KpMasteryPolicy,
    KpState,
    KnowledgePoint,
    LearningEvent,
    PracticeItem,
    QuestionAttempt,
)


def evidence_to_storage(evidence: Evidence) -> dict[str, object]:
    # 只存重建窗口必需的字段；时间写成带时区的 ISO 字符串，读回来仍是同一时刻。
    result = {
        "question_id": evidence.question_id,
        "level": evidence.level.value,
        "is_variant": evidence.is_variant,
        "occurred_at": evidence.occurred_at.isoformat(),
        "source": evidence.source,
        # 题型与考法必须入窗口，否则毕业判定无法检查覆盖情况。
        "question_type": evidence.question_type,
        "skill_tags": list(evidence.skill_tags),
        "reliability": evidence.reliability,
    }
    if evidence.confirmation_facts is not None:
        result["confirmation_facts"] = dict(evidence.confirmation_facts)
    return result


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
        reliability=str(payload.get("reliability", "unknown")),
        confirmation_facts=payload.get("confirmation_facts") if isinstance(payload.get("confirmation_facts"), dict) else None,
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
        policy_version=getattr(row, "policy_version", None) or 1,
        required_question_origins=dict(getattr(row, "required_question_origins", None) or {}),
        graduation_question_ids=tuple(str(value) for value in (getattr(row, "graduation_question_ids", None) or [])),
        graduation_set_version=getattr(row, "graduation_set_version", None) or 0,
    )


def policy_for_node(
    db, kp_id: UUID, *, bind_if_unset: bool = False,
    confirm_legacy_set_transition: bool = False, now: datetime | None = None,
    _read_context=None,
) -> MasteryPolicy:
    """Resolve the learner's immutable v3 set binding, or the current set if not started.

    A started learner keeps the set version pinned in KpState while the shared
    policy pointer can publish a newer set for future/unstarted learners.
    Mutating flows call with ``bind_if_unset=True`` on the first real learning
    action; read flows never create state rows.
    """
    if _read_context is not None and (bind_if_unset or confirm_legacy_set_transition):
        raise ValueError("read_policy_context_cannot_bind_learner")
    stored = policy_from_storage(_read_context.policy_rows.get(kp_id)
        if _read_context is not None else db.get(KpMasteryPolicy, kp_id))
    state = (_read_context.states.get(kp_id) if _read_context is not None
             else db.get(KpState, kp_id))
    if state is None and bind_if_unset:
        # Serialize first-state creation across simultaneous first study actions.
        db.scalar(select(KnowledgePoint.id).where(KnowledgePoint.id == kp_id).with_for_update())
        state = db.get(KpState, kp_id)
    if state is None and bind_if_unset:
        state = KpState(kp_id=kp_id)
        db.add(state)
        db.flush()
    # Every actual study action needs a projection, including an unconfigured
    # node. Creating it does not publish a policy or bind a v3 graduation set.
    # Read-only resolution still never creates a row.
    if stored.policy_version != 3 or stored.graduation_set_version <= 0:
        return stored
    pinned = getattr(state, "graduation_set_version", None) if state is not None else None
    binding_status = getattr(state, "graduation_set_binding_status", "unstarted") if state is not None else "unstarted"
    if pinned is None and binding_status == "legacy_history_unbound":
        if confirm_legacy_set_transition:
            if not bind_if_unset:
                raise ValueError("graduation_set_transition_requires_mutating_confirmation")
            if state is None:
                raise ValueError("graduation_set_transition_state_missing")
            # A legacy mastery fact without a trustworthy frozen set cannot be
            # silently reinterpreted as completion of the new set.
            if state.mastered_at is not None or state.state == "mastered":
                raise ValueError("graduation_set_transition_legacy_mastery_requires_review")
            state.graduation_set_version = stored.graduation_set_version
            state.graduation_set_binding_status = "bound"
            state.graduation_set_started_at = now or datetime.now(timezone.utc)
            pinned = state.graduation_set_version
        else:
            # Historical learning stays readable, but cannot be evaluated as
            # completion of a set that did not exist when that learning began.
            return replace(
                stored, policy_version=2, required_question_origins={},
                graduation_question_ids=(), graduation_set_version=0,
                graduation_binding_pending=True,
            )
    if pinned is None:
        has_history = bool(
            (state and (state.state != "unseen" or state.mastered_at is not None
                        or bool(state.evidence_window)))
            or (kp_id in _read_context.activity_ids if _read_context is not None else (
                db.scalar(select(exists().where(QuestionAttempt.kp_id == kp_id)))
                or db.scalar(select(exists().where(LearningEvent.kp_id == kp_id)))
                or db.scalar(select(exists().where(PracticeItem.kp_id == kp_id)))))
        )
        if has_history:
            if binding_status == "legacy_history_unbound":
                return replace(
                    stored, policy_version=2, required_question_origins={},
                    graduation_question_ids=(), graduation_set_version=0,
                    graduation_binding_pending=True,
                )
            # Never silently move a learner with prior activity onto a newer
            # graduation set if a migration/backfill failed to bind them.
            raise ValueError("graduation_set_binding_missing_for_started_learner")
        if bind_if_unset and state is not None:
            state.graduation_set_version = stored.graduation_set_version
            state.graduation_set_binding_status = "bound"
            state.graduation_set_started_at = now or datetime.now(timezone.utc)
        return stored
    version = (_read_context.versions.get((kp_id, pinned)) if _read_context is not None
               else db.get(KpGraduationQuestionSetVersion, (kp_id, pinned)))
    if version is None:
        raise ValueError("graduation_set_binding_missing_version")
    ids = tuple(str(value) for value in version.question_ids)
    expected = sha256(json.dumps(list(ids), ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    if version.question_ids_sha256 != expected or not ids:
        raise ValueError("graduation_set_binding_integrity_error")
    return replace(stored, graduation_question_ids=ids, graduation_set_version=pinned)


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
    row.policy_version = policy.policy_version
    row.required_question_origins = dict(policy.required_question_origins)
    row.graduation_question_ids = list(policy.graduation_question_ids)
    row.graduation_set_version = policy.graduation_set_version
