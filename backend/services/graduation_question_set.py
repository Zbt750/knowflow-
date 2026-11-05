"""Explicit, immutable per-node question-set freezing for graduation policy v3.

This is a guarded content-operations service, not an automatic migration: the
caller must supply a reviewed finite set. It never selects questions by count
or adds future bank entries implicitly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.mastery.policy import MAX_GRADUATION_SET_SIZE, MasteryPolicy
from backend.mastery.storage import policy_from_storage, policy_to_storage
from backend.models.learning import (
    KpGraduationQuestionSetVersion,
    KpMasteryPolicy,
    KnowledgePoint,
    Question,
    QuestionVersion,
)
from backend.services.question_eligibility import question_eligibility
from backend.services.question_identity import duplicate_findings


def question_set_sha256(question_ids: list[str] | tuple[str, ...]) -> str:
    payload = json.dumps(list(question_ids), ensure_ascii=False, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def question_version_set_sha256(version_ids: list[str] | tuple[str, ...]) -> str:
    payload = json.dumps(list(version_ids), ensure_ascii=False, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def freeze_graduation_question_set(
    db: Session,
    *,
    kp_id: UUID,
    question_ids: list[UUID],
    reason: str,
    now: datetime | None = None,
) -> KpMasteryPolicy:
    """Freeze the first validated public objective set for a leaf.

    Existing v1/v2 graduation rules are not changed unless this explicit
    operation succeeds. Existing frozen sets cannot be silently replaced.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("graduation_set_reason_required")
    if not question_ids:
        raise ValueError("graduation_question_set_empty")
    if len(question_ids) > MAX_GRADUATION_SET_SIZE:
        raise ValueError("graduation_question_set_too_large")
    if any(not isinstance(value, UUID) for value in question_ids):
        raise ValueError("graduation_question_id_invalid")
    if len(set(question_ids)) != len(question_ids):
        raise ValueError("graduation_question_set_duplicate_id")

    node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.id == kp_id).with_for_update())
    if node is None or not node.is_active:
        raise ValueError("knowledge_point_not_found")
    # ``is_reference_only`` describes how a knowledge-tree topic entered the
    # tree; it is not, by itself, proof that a fully attested public question
    # cannot be used there.  The per-question eligibility check below is the
    # authoritative guard: for reference-only leaves it requires a current,
    # exact-node source binding or current automatic review before allowing a
    # trusted deterministic objective question into the frozen set.
    if not node.is_assessable:
        raise ValueError("knowledge_point_not_assessable")

    policy_row = db.scalar(select(KpMasteryPolicy).where(KpMasteryPolicy.kp_id == kp_id).with_for_update())
    if policy_row is None:
        policy_row = KpMasteryPolicy(kp_id=kp_id)
        db.add(policy_row)
        db.flush()
    existing = db.scalar(select(KpGraduationQuestionSetVersion).where(
        KpGraduationQuestionSetVersion.kp_id == kp_id).limit(1))
    if existing is not None or policy_row.graduation_set_version or policy_row.graduation_question_ids:
        raise ValueError("graduation_question_set_already_frozen")

    ordered_ids = [str(value) for value in question_ids]
    rows = list(db.scalars(select(Question).where(Question.id.in_(question_ids))
        .order_by(Question.id).with_for_update()))
    by_id = {row.id: row for row in rows}
    if set(by_id) != set(question_ids):
        raise ValueError("graduation_question_not_found")
    for qid in question_ids:
        question = by_id[qid]
        if question.kp_id != kp_id:
            raise ValueError("graduation_question_wrong_node")
        if (not question.is_active or question.is_hidden or question.bank_scope != "public"
                or question.generation_batch_id is not None):
            raise ValueError("graduation_question_not_public_active")
        eligibility = question_eligibility(question, node)
        if (not eligibility.practice_eligible
                or eligibility.evidence_capability != "verified_objective"
                or eligibility.grading_capability != "deterministic"):
            raise ValueError("graduation_question_not_trusted_objective")

    # Fail closed for known exact/algorithmic duplicates and very close cases.
    selected = [by_id[qid] for qid in question_ids]
    for index, question in enumerate(selected):
        findings = duplicate_findings(question, selected[index + 1:])
        if findings["matches"]:
            raise ValueError("graduation_question_set_contains_duplicate")
        if findings["uncertain_similar"]:
            raise ValueError("graduation_question_set_duplicate_uncertain")

    old = policy_from_storage(policy_row)
    if "external_exam" in old.required_question_types:
        raise ValueError("graduation_policy_has_external_exam_type")
    upgraded = MasteryPolicy(
        min_confirmations=old.min_confirmations,
        min_real_questions=old.min_real_questions,
        required_question_types=dict(old.required_question_types),
        excluded_question_types=old.excluded_question_types,
        required_skill_tags=old.required_skill_tags,
        required_variant_count=old.required_variant_count,
        min_day_span=old.min_day_span,
        manual_mastered_credit=old.manual_mastered_credit,
        review_intervals_days=old.review_intervals_days,
        max_evidence_window=old.max_evidence_window,
        note=old.note,
        policy_version=3,
        required_question_origins={},
        graduation_question_ids=tuple(ordered_ids),
        graduation_set_version=1,
    )
    policy_to_storage(upgraded, policy_row)
    db.add(KpGraduationQuestionSetVersion(
        kp_id=kp_id,
        set_version=1,
        question_ids=ordered_ids,
        question_ids_sha256=question_set_sha256(ordered_ids),
        question_version_ids=[str(by_id[qid].current_version_id) for qid in question_ids],
        question_version_ids_sha256=question_version_set_sha256(
            [str(by_id[qid].current_version_id) for qid in question_ids]),
        reason=reason.strip(),
        created_at=now or datetime.now(timezone.utc),
    ))
    db.flush()
    return policy_row


def assert_frozen_set_integrity(db: Session, policy: MasteryPolicy, *, kp_id: UUID, _read_context=None) -> None:
    """Ensure the live policy points to its immutable, hash-bound set record."""
    if policy.policy_version != 3 or not policy.graduation_set_version:
        return
    row = (_read_context.versions.get((kp_id, policy.graduation_set_version)) if _read_context is not None
           else db.get(KpGraduationQuestionSetVersion, (kp_id, policy.graduation_set_version)))
    ids = list(policy.graduation_question_ids)
    if (row is None or row.question_ids != ids
            or row.question_ids_sha256 != question_set_sha256(ids)
            or not row.question_version_ids
            or len(row.question_version_ids) != len(ids)
            or row.question_version_ids_sha256 != question_version_set_sha256(row.question_version_ids)):
        raise ValueError("graduation_question_set_integrity_error")
    if _read_context is not None:
        version_by_id = _read_context.content_versions
    else:
        versions = list(db.scalars(select(QuestionVersion).where(
            QuestionVersion.id.in_([UUID(v) for v in row.question_version_ids]))))
        version_by_id = {str(version.id): version for version in versions}
    if any(version_by_id.get(str(version_id)) is None
           or version_by_id[str(version_id)].question_id != UUID(qid)
           for qid, version_id in zip(ids, row.question_version_ids)):
        raise ValueError("graduation_question_set_version_binding_error")


def publish_all_public_question_set_version(
    db: Session, *, kp_id: UUID, question_ids: list[UUID],
    expected_set_version: int, expected_set_sha256: str,
    publication_key: str, reason: str, now: datetime | None = None,
) -> tuple[KpMasteryPolicy, dict]:
    """Explicitly append a release containing every current formal public item.

    This operation is called by a reviewed content batch, never implicitly by
    ordinary question creation. It changes neither an old set-version row nor
    learner attempts, receipts, states or historical graduation facts.
    """
    if not publication_key or not reason.strip():
        raise ValueError("graduation_publication_key_and_reason_required")
    if not question_ids or len(question_ids) > MAX_GRADUATION_SET_SIZE:
        raise ValueError("graduation_question_set_empty_or_too_large")
    if any(not isinstance(qid, UUID) for qid in question_ids) or len(set(question_ids)) != len(question_ids):
        raise ValueError("graduation_question_set_invalid_or_duplicate_id")
    node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.id == kp_id).with_for_update())
    policy_row = db.scalar(select(KpMasteryPolicy).where(KpMasteryPolicy.kp_id == kp_id).with_for_update())
    if node is None or not node.is_active or not node.is_assessable or node.children:
        raise ValueError("graduation_publication_requires_concrete_leaf")
    if policy_row is None or policy_row.policy_version != 3 or not policy_row.graduation_set_version:
        raise ValueError("graduation_publication_requires_existing_v3_set")
    old = policy_from_storage(policy_row)
    assert_frozen_set_integrity(db, old, kp_id=kp_id)
    previous = db.get(KpGraduationQuestionSetVersion, (kp_id, expected_set_version))
    if previous is None or previous.question_ids_sha256 != expected_set_sha256:
        raise ValueError("graduation_publication_previous_hash_mismatch")
    ordered_ids = [str(qid) for qid in question_ids]
    rows = list(db.scalars(select(Question).where(Question.kp_id == kp_id,
        Question.bank_scope == "public", Question.generation_batch_id.is_(None))
        .order_by(Question.id).with_for_update()))
    formal = {}
    for question in rows:
        eligibility = question_eligibility(question, node)
        if (eligibility.practice_eligible and eligibility.evidence_capability == "verified_objective"
                and eligibility.grading_capability == "deterministic"):
            formal[question.id] = question
    if set(question_ids) != set(formal):
        raise ValueError("graduation_publication_must_include_all_formal_public_questions")
    selected = [formal[qid] for qid in question_ids]
    for index, question in enumerate(selected):
        duplicates = duplicate_findings(question, selected[index + 1:])
        if duplicates["matches"] or duplicates["uncertain_similar"]:
            raise ValueError("graduation_publication_duplicate_or_unresolved_similarity")
    marker = f"public-release:{publication_key}: {reason.strip()}"
    current_version = db.get(KpGraduationQuestionSetVersion, (kp_id, old.graduation_set_version))
    if (old.graduation_set_version == expected_set_version + 1 and current_version.reason == marker
            and list(old.graduation_question_ids) == ordered_ids):
        return policy_row, {"status": "NOOP", "set_version": old.graduation_set_version,
            "question_count": len(ordered_ids)}
    if old.graduation_set_version != expected_set_version:
        raise ValueError("graduation_publication_version_conflict")
    new_version = expected_set_version + 1
    if db.get(KpGraduationQuestionSetVersion, (kp_id, new_version)) is not None:
        raise ValueError("graduation_publication_next_version_already_exists")
    db.add(KpGraduationQuestionSetVersion(kp_id=kp_id, set_version=new_version,
        question_ids=ordered_ids, question_ids_sha256=question_set_sha256(ordered_ids),
        question_version_ids=[str(formal[qid].current_version_id) for qid in question_ids],
        question_version_ids_sha256=question_version_set_sha256(
            [str(formal[qid].current_version_id) for qid in question_ids]),
        reason=marker, created_at=now or datetime.now(timezone.utc)))
    policy_row.graduation_question_ids = ordered_ids
    policy_row.graduation_set_version = new_version
    db.flush()
    return policy_row, {"status": "PUBLISHED", "old_set_version": expected_set_version,
        "set_version": new_version, "question_count": len(ordered_ids),
        "all_formal_public_questions_included": True, "learner_history_modified": False}
