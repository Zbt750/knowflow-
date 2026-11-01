"""Validate future versioned confirmations against immutable receipts/current trust.

Read projections only; historical receipts and stored mastery are never backfilled.
"""
from dataclasses import replace
from datetime import timezone
from uuid import UUID
from sqlalchemy import select

from backend.mastery.origin_evidence import CONFIRMATION_FACT_FIELDS, policy_confirmation_window
from backend.mastery.storage import snapshot_from_storage
from backend.mastery.enums import MasteryState
from backend.mastery.rules import graduation_check
from backend.models.learning import Question, QuestionAttempt, KnowledgePoint
from backend.services.answer_verification import answer_version_sha256
from backend.services.question_eligibility import question_eligibility
from backend.services.question_versions import question_for_attempt


def _same_identifier(left, right) -> bool:
    """Compare UUID identifiers across the JSON/ORM serialization boundary.

    SQL JSON receipts store identifiers as strings after reload, while the live
    ORM eligibility projection may expose UUID objects. In-memory comparisons
    alone can therefore accept a receipt which is rejected after a new session.
    """
    if left is None or right is None:
        return left is right
    try:
        return UUID(str(left)) == UUID(str(right))
    except (ValueError, TypeError, AttributeError):
        return str(left) == str(right)


def current_policy_snapshot(db, state, policy, *, _read_context=None):
    snapshot = snapshot_from_storage(state)
    if policy.policy_version == 3 and state.graduation_set_started_at is not None:
        start = state.graduation_set_started_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        snapshot = replace(snapshot, evidence_window=tuple(
            item for item in snapshot.evidence_window
            if (item.occurred_at.replace(tzinfo=timezone.utc)
                if item.occurred_at.tzinfo is None else item.occurred_at) >= start
        ))
    if policy.policy_version == 1:
        return snapshot
    if policy.policy_version == 3:
        from backend.services.graduation_question_set import assert_frozen_set_integrity
        assert_frozen_set_integrity(db, policy, kp_id=state.kp_id, _read_context=_read_context)
    candidates = policy_confirmation_window(snapshot.evidence_window, policy)
    if len(candidates) > 200:
        candidates = ()
    parsed = []
    for evidence in candidates:
        try:
            parsed.append((evidence, UUID(evidence.question_id), UUID(str(evidence.confirmation_facts["attempt_id"]))))
        except (ValueError, TypeError, KeyError):
            continue
    attempts = {a.id: a for a in db.scalars(select(QuestionAttempt).where(
        QuestionAttempt.id.in_([aid for _,_,aid in parsed]), QuestionAttempt.kp_id == state.kp_id))} if parsed else {}
    node = db.get(KnowledgePoint, state.kp_id) if parsed else None
    from backend.services.answer_submission_service import question_content_hash_matches
    valid = []
    for evidence, qid, aid in parsed:
        attempt = attempts.get(aid)
        if attempt is None:
            continue
        try:
            q = question_for_attempt(db, attempt)
        except ValueError:
            continue
        if q is None or q.id != qid or q.kp_id != state.kp_id:
            continue
        saved, facts = attempt.grading_evidence or {}, evidence.confirmation_facts
        eligibility = question_eligibility(q, node)
        auto_class = q.current_auto_review.qualification_class if eligibility.auto_review_current else None
        class_bound = (saved.get("auto_review_qualification_class") is None
            and saved.get("version") == 5
            or saved.get("auto_review_qualification_class") == facts.get("auto_review_qualification_class") == auto_class)
        if saved.get("version") == 6:
            class_bound = (auto_class == "exam_variant"
                and saved.get("auto_review_qualification_class") == facts.get("auto_review_qualification_class") == auto_class)
        auto_receipt = (saved.get("version") in {5,6} and eligibility.auto_review_current and class_bound
            and _same_identifier(saved.get("auto_review_event_id"), eligibility.auto_review_event_id)
            and saved.get("auto_review_version") == eligibility.auto_review_version
            and saved.get("auto_review_snapshot_sha256") == eligibility.auto_review_snapshot_sha256
            and _same_identifier(facts.get("auto_review_event_id"), eligibility.auto_review_event_id)
            and facts.get("auto_review_version") == eligibility.auto_review_version
            and facts.get("auto_review_snapshot_sha256") == eligibility.auto_review_snapshot_sha256)
        human_receipt = (saved.get("version") == 4 and not eligibility.auto_review_current
            and _same_identifier(facts.get("answer_verification_event_id"), eligibility.answer_verification_event_id))
        if (eligibility.practice_eligible and eligibility.evidence_capability == "verified_objective"
            and attempt.question_id == q.id and attempt.exam_reference_id is None and attempt.self_grade is None
            and attempt.objective_result == "right" and attempt.submitted_at == evidence.occurred_at
            and (auto_receipt or human_receipt)
            and evidence.question_type == q.question_type and evidence.is_variant == q.is_variant
            and evidence.skill_tags == tuple(q.skill_tags or [])
            and saved.get("question_type") == evidence.question_type
            and saved.get("is_variant") == evidence.is_variant
            and saved.get("skill_tags") == list(evidence.skill_tags)
            and all(saved.get(key) == facts.get(key) for key in CONFIRMATION_FACT_FIELDS)
            and facts["question_provenance"] == q.question_provenance
            and question_content_hash_matches(facts["question_content_sha256"], q)
            and facts["answer_version_sha256"] == answer_version_sha256(q)
            and (auto_receipt or _same_identifier(
                facts["answer_verification_event_id"], eligibility.answer_verification_event_id))):
            valid.append(evidence)
    if policy.policy_version == 3:
        required = set(policy.graduation_question_ids)
        # Keep all valid completions in the frozen set. This set is capped at
        # 200 items; the rolling practice window is not allowed to evict them.
        valid = [evidence for evidence in valid if evidence.question_id in required]
    projected=replace(snapshot, evidence_window=tuple(valid), manual_credit_count=0, manual_confirmed_at=None)
    if projected.state is MasteryState.MASTERED:
        satisfied,_=graduation_check(projected.evidence_window,manual_credit_count=0,
            manual_confirmed_at=None,policy=policy)
        trust_changed = len(valid) < len(candidates)
        if policy.policy_version == 3:
            # Graduation is a durable historical fact. A later wrong answer,
            # new question, or ordinary current projection change must not
            # revoke an already objective-v1 graduation. Legacy self-reported
            # mastery is not a graduation fact under the frozen-set rule.
            was_objectively_graduated = (snapshot.assessment_basis == "objective_v1"
                and snapshot.mastered_at is not None)
            if was_objectively_graduated:
                return replace(projected, state=MasteryState.MASTERED,
                    mastered_at=snapshot.mastered_at)
            pending=bool(set(projected.pending_review_question_ids)
                         & set(policy.graduation_question_ids))
            if not satisfied or trust_changed:
                projected=replace(projected,state=MasteryState.STUCK if pending else
                    MasteryState.CONSOLIDATING if valid else MasteryState.UNSEEN,
                    mastered_at=None,
                    next_review_at=projected.next_review_at if pending else None)
        elif not satisfied or projected.pending_review_question_ids:
            # Read-only current evaluation. The historical KpState and immutable
            # receipts remain unchanged even when their current trust is gone.
            pending=bool(projected.pending_review_question_ids)
            projected=replace(projected,state=MasteryState.STUCK if pending else
                MasteryState.CONSOLIDATING if valid else MasteryState.UNSEEN,
                mastered_at=None,next_review_at=projected.next_review_at if pending else None)
    return projected
