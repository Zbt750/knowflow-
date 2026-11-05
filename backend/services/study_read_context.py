"""Request-local preloading for study reads; never cache learner state globally.

All policy decisions still go through policy_for_node. The context only supplies
the exact rows/activity facts that the single-node path would query separately.
"""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.models.learning import (
    KpMasteryPolicy, KpState, KpGraduationQuestionSetVersion,
    LearningEvent, PracticeItem, Question, QuestionAttempt, QuestionVersion,
)


def question_read_options():
    return (selectinload(Question.current_auto_review),
            selectinload(Question.current_answer_verification))


@dataclass
class PolicyReadContext:
    policy_rows: dict
    states: dict
    versions: dict
    activity_ids: set
    # Immutable member identity pairs, not full question bodies/audit JSON.
    content_versions: dict


def load_policy_read_context(db, kp_ids) -> PolicyReadContext:
    ids = set(kp_ids)
    if not ids:
        return PolicyReadContext({}, {}, {}, set(), {})
    rows = {row.kp_id: row for row in db.scalars(
        select(KpMasteryPolicy).where(KpMasteryPolicy.kp_id.in_(ids)))}
    states = {row.kp_id: row for row in db.scalars(
        select(KpState).where(KpState.kp_id.in_(ids)))}
    versions = {(row.kp_id, row.set_version): row for row in db.scalars(
        select(KpGraduationQuestionSetVersion).where(KpGraduationQuestionSetVersion.kp_id.in_(ids)))}
    activity = select(QuestionAttempt.kp_id).where(QuestionAttempt.kp_id.in_(ids)).union(
        select(LearningEvent.kp_id).where(LearningEvent.kp_id.in_(ids)),
        # An unstarted item in a materialized DailyPlan is not a learning
        # action and cannot require a historical graduation-set binding.
        # Completed legacy items remain visible activity evidence.
        select(PracticeItem.kp_id).where(PracticeItem.kp_id.in_(ids),
            PracticeItem.completed_at.is_not(None)))
    activity_ids = set(db.scalars(activity))
    # Integrity validation still checks every hash and question/version pairing.
    # Preloading their rows must not substitute for that validation.
    version_ids = set()
    for version in versions.values():
        for value in version.question_version_ids or ():
            try:
                version_ids.add(UUID(str(value)))
            except (ValueError, TypeError):
                pass  # the existing integrity check will reject invalid members
    content_versions = {str(row.id): row for row in db.execute(
        select(QuestionVersion.id, QuestionVersion.question_id).where(
            QuestionVersion.id.in_(version_ids)))} if version_ids else {}
    return PolicyReadContext(rows, states, versions, activity_ids, content_versions)


def policies_for_nodes(db, kp_ids, *, include_missing=False):
    from backend.mastery.storage import policy_for_node
    ids = set(kp_ids)
    context = load_policy_read_context(db, ids)
    return ({kp_id: policy_for_node(db, kp_id, _read_context=context)
             for kp_id in (ids if include_missing else context.policy_rows)}, context)
