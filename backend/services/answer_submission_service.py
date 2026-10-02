"""保存不可变作答证据；可靠客观结果通过状态机更新掌握投影。"""
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.learning import PracticeItem, QuestionAttempt, KpState, LearningEvent, KpMasteryPolicy
from backend.schemas.practice import AnswerSubmissionResponse, AnswerSubmissionHistory
from backend.mastery.attempt_sequence import classify_attempt_sequence
from backend.services.answer_grading import grade_final_answer
from backend.services.practice_lock import lock_practice_item
from backend.mastery.enums import EventType
from backend.mastery.evidence import classify_objective_evidence
from backend.mastery.rules import effective_confirmation_count
from backend.mastery.storage import apply_snapshot, snapshot_from_storage, snapshot_to_storage, policy_from_storage, evidence_to_storage
from backend.mastery.transition import transition
from backend.mastery.types import DomainLearningEvent

MAX_ITEM_SUBMISSIONS = 20
MAX_PREVIOUS_QUESTION_RECORDS = 64


def question_content_hash(question) -> str:
    fields = ("stem", "question_type", "options", "correct_answer", "grading_config", "explanation",
              "skill_tags", "is_variant")
    content = {field: getattr(question, field) for field in fields}
    content["kp_id"] = str(question.kp_id)
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def attempt_sort_key(attempt: QuestionAttempt):
    number = (attempt.grading_evidence or {}).get("attempt_number", 0)
    number = number if isinstance(number, int) and number > 0 else 0
    return number, attempt.submitted_at, str(attempt.id)


def item_attempts(db: Session, item_id: UUID) -> list[QuestionAttempt]:
    rows = list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.practice_item_id == item_id)
        .order_by(QuestionAttempt.submitted_at, QuestionAttempt.id)))
    # Test clocks and very fast retries may have equal timestamps. New sequence
    # ordinals are authoritative within an item; legacy timestamps are preserved.
    return sorted(rows, key=attempt_sort_key)


def read_answer_history(db: Session, *, item_id: UUID) -> AnswerSubmissionHistory:
    item = db.get(PracticeItem, item_id)
    if item is None: raise ValueError("practice_item_not_found")
    rows = item_attempts(db, item_id)
    return AnswerSubmissionHistory(practice_item_id=item_id,
        items=[submission_response(a) for a in rows if a.grading_evidence is not None],
        legacy_self_report_count=sum(a.grading_evidence is None for a in rows))


def submission_response(attempt: QuestionAttempt) -> AnswerSubmissionResponse:
    evidence = attempt.grading_evidence or {}
    return AnswerSubmissionResponse(
        attempt_id=attempt.id, practice_item_id=attempt.practice_item_id,
        result=attempt.objective_result, reason=evidence["reason"],
        method=evidence["method"], assisted=evidence["assisted"],
        submitted_at=attempt.submitted_at.astimezone(timezone.utc).isoformat(),
        raw_answer=attempt.raw_answer, selected_option=evidence.get("selected_option"),
        confidence=evidence.get("confidence"), assessment_basis=evidence.get("assessment_basis", "legacy_self_reported"),
        state=attempt.result_state, mastery_reason=attempt.reason_code,
        effective_confirmation_count=evidence.get("effective_confirmation_count", 0),
        basis_changed=evidence.get("basis_changed", False),
        attempt_number=evidence.get("attempt_number"),
        previous_attempt_id=evidence.get("previous_attempt_id"),
        sequence_category=evidence.get("sequence_category"),
        assistance_level=evidence.get("assistance_level"),
        can_retry=evidence.get("can_retry", attempt.objective_result in {"wrong", "unknown"}),
    )


def submit_answer(db: Session, *, item_id: UUID, raw_answer: str | None,
                  selected_option: str | None, idempotency_key: str,
                  now: datetime, confidence: str | None = None,
                  expected_previous_attempt_id: UUID | None = None) -> AnswerSubmissionResponse:
    item = lock_practice_item(db, item_id)
    old = db.scalar(select(QuestionAttempt).where(QuestionAttempt.idempotency_key == idempotency_key))
    if old is not None:
        if old.practice_item_id != item_id or old.grading_evidence is None:
            raise ValueError("idempotency_key_conflict")
        saved = old.grading_evidence
        normalized = raw_answer.strip() if raw_answer and raw_answer.strip() else None
        if (old.raw_answer != normalized or saved.get("selected_option") != selected_option
                or saved.get("confidence") != confidence
                or saved.get("expected_previous_attempt_id") != (str(expected_previous_attempt_id) if expected_previous_attempt_id else None)):
            raise ValueError("idempotency_key_conflict")
        return submission_response(old)
    question = item.question
    if question is None:
        raise ValueError("external_exam_has_no_embedded_answer")
    history = item_attempts(db, item_id)
    previous = history[-1] if history else None
    content_hash = question_content_hash(question)
    if expected_previous_attempt_id is not None:
        if (previous is None or previous.id != expected_previous_attempt_id
                or previous.grading_evidence is None or item.completed_at is None):
            raise ValueError("answer_attempt_conflict")
        if previous.objective_result not in {"wrong", "unknown"}:
            raise ValueError("answer_retry_not_allowed")
        prior_hash = previous.grading_evidence.get("question_content_sha256")
        if prior_hash and prior_hash != content_hash:
            raise ValueError("answer_question_changed")
    elif item.completed_at is not None:
        raise ValueError("practice_item_already_assessed")
    if len(history) >= MAX_ITEM_SUBMISSIONS:
        raise ValueError("answer_attempt_limit")
    # Lock before cross-item reads: two fresh items of this knowledge point cannot
    # both classify against a stale history while waiting to update the same state.
    state = db.scalar(select(KpState).where(KpState.kp_id == item.kp_id).with_for_update())
    if state is None:
        raise ValueError("kp_state_not_found")
    # Bounded cross-item history; incompatible/legacy records cannot be invented
    # into a known first independent success. No answer text goes to the Agent.
    other = list(db.scalars(select(QuestionAttempt).where(
        QuestionAttempt.question_id == question.id, QuestionAttempt.practice_item_id != item_id)
        .order_by(QuestionAttempt.submitted_at.desc(), QuestionAttempt.id.desc())
        .limit(MAX_PREVIOUS_QUESTION_RECORDS + 1)))
    compatible = [a for a in other[:MAX_PREVIOUS_QUESTION_RECORDS]
        if (a.grading_evidence or {}).get("question_content_sha256") == content_hash]
    history_unknown = (len(other) > MAX_PREVIOUS_QUESTION_RECORDS
        or len(compatible) != len(other)
        or any(a.grading_evidence is None for a in history))
    assistance = "solution" if item.answer_revealed_at is not None else "process_review" if db.scalar(
        select(LearningEvent.id).where(LearningEvent.source_id == item.id,
            LearningEvent.event_type == EventType.AI_PROCESS_REVIEWED.value).limit(1)) is not None else "none"
    verdict = grade_final_answer(
        question_type=question.question_type, config=question.grading_config,
        answer=raw_answer, selected_option=selected_option,
        expected=question.correct_answer, options=question.options,
    )
    evidence = {
        "version": 3, "sequence_version": "attempt-sequence-v1", "method": verdict.method, "reason": verdict.reason,
        "grading_input_version": "bounded-final-input-v2",
        "assisted": assistance != "none", "assistance_level": assistance,
        "attempt_number": len(history) + 1,
        "previous_attempt_id": str(previous.id) if previous else None,
        "expected_previous_attempt_id": str(expected_previous_attempt_id) if expected_previous_attempt_id else None,
        "question_content_sha256": content_hash, "history_unknown": history_unknown,
        "can_retry": verdict.result in {"wrong", "unknown"} and len(history) + 1 < MAX_ITEM_SUBMISSIONS,
        "answer_revealed_at": item.answer_revealed_at.isoformat() if item.answer_revealed_at else None,
        "selected_option": selected_option,
        "question_role": question.question_role,
        "confidence": confidence,
        "grading_config": question.grading_config,
        "reference_answer": question.correct_answer,
        "observation_scope": "tracked_interface_not_proctored",
    }
    category = classify_attempt_sequence(result=verdict.result,
        verified=(question.grading_config or {}).get("verified") is True,
        assistance=assistance, confidence=confidence,
        same_item_results=tuple(a.objective_result for a in history if a.grading_evidence is not None),
        previous_question_results=tuple(a.objective_result for a in compatible),
        history_unknown=history_unknown)
    evidence["sequence_category"] = category
    before = snapshot_from_storage(state)
    objective_evidence = classify_objective_evidence(
        result=verdict.result, verified=(question.grading_config or {}).get("verified") is True,
        assisted=evidence["assisted"], question_id=str(question.id),
        is_variant=question.is_variant, occurred_at=now, question_type=question.question_type,
        skill_tags=tuple(question.skill_tags or ()),
        confidence=confidence,
        sequence_category=category,
    )
    event = DomainLearningEvent(EventType.ANSWER_SUBMITTED, now, evidence=objective_evidence,
                               payload={"confidence": confidence, "assisted": evidence["assisted"], "sequence_category": category})
    result = transition(before, event, policy_from_storage(db.get(KpMasteryPolicy, item.kp_id)))
    evidence["assessment_basis"] = result.snapshot.assessment_basis
    evidence["effective_confirmation_count"] = effective_confirmation_count(
        result.snapshot.evidence_window, manual_credit_count=result.snapshot.manual_credit_count,
    )
    evidence["basis_changed"] = before.assessment_basis != result.snapshot.assessment_basis
    if evidence["basis_changed"]:
        evidence["previous_mastery_snapshot"] = {
            **snapshot_to_storage(before, "basis_changed"),
            "evidence_window": [evidence_to_storage(e) for e in before.evidence_window],
            "node_self_grade": before.node_self_grade.value if before.node_self_grade else None,
            "manual_confirmed_at": before.manual_confirmed_at.isoformat() if before.manual_confirmed_at else None,
        }
    apply_snapshot(state, result.snapshot)
    attempt = QuestionAttempt(
        practice_item_id=item.id, question_id=question.id, kp_id=item.kp_id,
        raw_answer=raw_answer.strip() if raw_answer and raw_answer.strip() else None,
        self_grade=None, objective_result=verdict.result, grading_evidence=evidence,
        idempotency_key=idempotency_key, submitted_at=now,
        result_state=result.snapshot.state.value, reason_code=result.reason_code,
        next_review_at=result.snapshot.next_review_at,
    )
    db.add(attempt)
    db.flush()
    db.add(LearningEvent(
        kp_id=item.kp_id, source_id=attempt.id, event_type="answer_submitted",
        evidence_level=objective_evidence.level.value,
        payload={"result": verdict.result, **evidence, **snapshot_to_storage(result.snapshot, result.reason_code)},
        occurred_at=now, idempotency_key=f"answer:{idempotency_key}",
    ))
    item.completed_at = now
    db.flush()
    remaining = db.scalar(select(PracticeItem.id).where(
        PracticeItem.plan_id == item.plan_id, PracticeItem.completed_at.is_(None),
    ).limit(1))
    if remaining is None:
        item.plan.status = "completed"
    return submission_response(attempt)


def record_answer_reveal(db: Session, *, item_id: UUID, now: datetime) -> None:
    item = db.scalar(select(PracticeItem).where(PracticeItem.id == item_id).with_for_update())
    if item is None:
        raise ValueError("practice_item_not_found")
    if item.question is None:
        raise ValueError("external_exam_has_no_embedded_answer")
    if item.answer_revealed_at is None:
        item.answer_revealed_at = now
