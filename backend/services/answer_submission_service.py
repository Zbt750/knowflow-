"""保存不可变作答证据；可靠客观结果通过状态机更新掌握投影。"""
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.learning import PracticeItem, QuestionAttempt, KpState, LearningEvent, KpMasteryPolicy, KnowledgePoint
from backend.schemas.practice import AnswerSubmissionResponse, AnswerSubmissionHistory
from backend.mastery.attempt_sequence import classify_attempt_sequence
from backend.services.answer_grading import AnswerVerdict, grade_practice_final_answer
from backend.services.question_eligibility import question_eligibility
from backend.services.practice_lock import lock_practice_item
from backend.services.question_versions import question_for_practice_item
from backend.mastery.enums import EventType, EvidenceLevel
from backend.mastery.origin_evidence import CONFIRMATION_FACT_FIELDS, policy_confirmation_window
from backend.services.answer_verification import answer_version_sha256
from backend.mastery.evidence import classify_objective_evidence
from backend.mastery.rules import effective_confirmation_count
from backend.mastery.storage import apply_snapshot, snapshot_from_storage, snapshot_to_storage, policy_for_node, evidence_to_storage
from backend.mastery.transition import transition
from backend.mastery.types import DomainLearningEvent

MAX_ITEM_SUBMISSIONS = 20
MAX_PREVIOUS_QUESTION_RECORDS = 64


def _scoped_question_history(other, content_hash: str):
    """Retain uncertain first retests, then use a newly observed version boundary.

    An incompatible old receipt stays immutable and nonconfirming. Once a
    later, fully tracked current-version attempt exists, it can establish the
    context of a *future* independent retest; old incompatible rows must not
    make every future attempt permanently history-unknown.
    """
    bounded = other[:MAX_PREVIOUS_QUESTION_RECORDS]
    compatible = [a for a in bounded
        if (a.grading_evidence or {}).get("question_content_sha256") == content_hash]
    prefix = []
    for attempt in bounded:
        if (attempt.grading_evidence or {}).get("question_content_sha256") != content_hash:
            break
        prefix.append(attempt)
    excluded = bounded[len(prefix):]
    boundary = False
    if prefix and excluded and all(a.submitted_at is not None for a in excluded):
        latest_excluded = max(a.submitted_at for a in excluded)
        for attempt in prefix:
            receipt = attempt.grading_evidence or {}
            if (type(receipt.get("version")) is int and 4 <= receipt["version"] <= 6
                    and receipt.get("grading_input_version") == "bounded-final-input-v2"
                    and receipt.get("sequence_version") == "attempt-sequence-v1"
                    and type(receipt.get("assisted")) is bool
                    and receipt.get("assistance_level") in {"none", "hint_1", "hint_2", "solution", "process_review"}
                    and receipt.get("result") == attempt.objective_result
                    and attempt.submitted_at is not None and attempt.submitted_at > latest_excluded):
                boundary = True
                break
    unknown = (len(other) > MAX_PREVIOUS_QUESTION_RECORDS
        or (len(compatible) != len(other) and not boundary))
    return (prefix if boundary else compatible), unknown, (len(excluded) if boundary else 0)


def _question_content_snapshot(question, *, trust_tz=None, normalize_trust_timestamps: bool) -> dict[str, object]:
    fields = ("stem", "question_type", "options", "correct_answer", "grading_config", "explanation",
              "skill_tags", "is_variant")
    content = {field: getattr(question, field) for field in fields}
    content["kp_id"] = str(question.kp_id)
    if getattr(question, "bank_scope", "public") == "personal" or getattr(question,"generation_batch_id",None):
        content["personal_bank_binding"] = {"scope": question.bank_scope, "batch_id": str(question.generation_batch_id)}
    trust_fields = ("question_provenance", "content_trust", "source_status", "answer_provenance",
        "answer_reliability", "answer_verification_event_id", "content_reviewed_by", "content_reviewed_at",
        "answer_reviewed_by", "answer_reviewed_at")
    trust_snapshot = {}
    for field in trust_fields:
        value = getattr(question, field)
        if isinstance(value, datetime):
            if normalize_trust_timestamps and value.tzinfo is not None:
                value = value.astimezone(timezone.utc)
            elif trust_tz is not None and value.tzinfo is not None:
                value = value.astimezone(trust_tz)
            value = value.isoformat()
        trust_snapshot[field] = value
    content["trust_snapshot"] = trust_snapshot
    return content


def question_content_snapshot(question) -> dict[str, object]:
    """Return the canonical content/trust payload used by new receipts."""
    return _question_content_snapshot(question, normalize_trust_timestamps=True)


def _question_content_digest(content: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str).encode()).hexdigest()


def question_content_hash(question) -> str:
    return _question_content_digest(question_content_snapshot(question))


def question_content_hash_matches(saved_hash: object, question) -> bool:
    """Validate canonical v2 hashes and legacy v1 timestamp representations.

    PostgreSQL timestamptz preserves an instant, not the original UTC offset.
    Older receipts hashed the offset as displayed by the submitting session,
    so a receipt created before an insert/commit could be rejected after reload.
    Legacy compatibility changes only the timestamp representation; all actual
    question content and trust fields remain bound to the digest.
    """
    if not isinstance(saved_hash, str):
        return False
    candidates = {question_content_hash(question)}
    candidates.add(_question_content_digest(_question_content_snapshot(
        question, normalize_trust_timestamps=False)))
    for zone in (timezone.utc, ZoneInfo("Asia/Shanghai")):
        candidates.add(_question_content_digest(_question_content_snapshot(
            question, trust_tz=zone, normalize_trust_timestamps=False)))
    return saved_hash in candidates


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
    from backend.services.grading_basis import submission_grading_basis
    evidence = attempt.grading_evidence or {}
    return AnswerSubmissionResponse(
        attempt_id=attempt.id, practice_item_id=attempt.practice_item_id,
        question_version_id=attempt.question_version_id,
        result=attempt.objective_result, reason=evidence["reason"],
        method=evidence["method"], assisted=evidence["assisted"],
        submitted_at=attempt.submitted_at.astimezone(timezone.utc).isoformat(),
        raw_answer=attempt.raw_answer, selected_option=evidence.get("selected_option"),
        confidence=evidence.get("confidence"), assessment_basis=submission_grading_basis(evidence),
        mastery_assessment_basis=evidence.get("mastery_assessment_basis", evidence.get("assessment_basis", "legacy_self_reported")),
        state=attempt.result_state, mastery_reason=attempt.reason_code,
        effective_confirmation_count=evidence.get("effective_confirmation_count", 0),
        basis_changed=evidence.get("basis_changed", False),
        attempt_number=evidence.get("attempt_number"),
        previous_attempt_id=evidence.get("previous_attempt_id"),
        sequence_category=evidence.get("sequence_category"),
        assistance_level=evidence.get("assistance_level"),
        # 历史作答仍按原证据读取；当前产品不允许原位重交同一个练习实例。
        can_retry=False,
        reference_result=evidence.get("reference_result"),
        feedback_notice=evidence.get("feedback_notice"),
    )


def submit_answer(db: Session, *, item_id: UUID, raw_answer: str | None,
                  selected_option: Any | None, idempotency_key: str,
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
    question = question_for_practice_item(db, item)
    if question is None:
        raise ValueError("external_exam_has_no_embedded_answer")
    from backend.services.answer_grading import validate_submission_input
    validate_submission_input(question_type=question.question_type, selected_option=selected_option, options=question.options)
    history = item_attempts(db, item_id)
    previous = history[-1] if history else None
    content_hash = question_content_hash(question)
    eligibility = question_eligibility(question, db.get(KnowledgePoint, item.kp_id))
    # 幂等重放已在上方返回。新的提交不能重写本次答案；后续复习须另建练习实例。
    if item.completed_at is not None or any(a.grading_evidence is not None for a in history):
        raise ValueError("practice_item_already_assessed")
    if expected_previous_attempt_id is not None:
        raise ValueError("answer_attempt_conflict")
    if len(history) >= MAX_ITEM_SUBMISSIONS:
        raise ValueError("answer_attempt_limit")
    # Lock before cross-item reads: two fresh items of this knowledge point cannot
    # both classify against a stale history while waiting to update the same state.
    state = db.scalar(select(KpState).where(KpState.kp_id == item.kp_id).with_for_update())
    if state is None:
        # Bootstrap only a genuinely absent row. Existing projections must be
        # read under their row lock before resolving policy, so a concurrent
        # submission cannot reuse a stale identity-map snapshot.
        policy_for_node(db, item.kp_id, bind_if_unset=True, now=now)
        state = db.scalar(select(KpState).where(KpState.kp_id == item.kp_id)
            .with_for_update().execution_options(populate_existing=True))
    if state is None:
        raise ValueError("kp_state_not_found")
    active_policy = policy_for_node(db, item.kp_id, bind_if_unset=True, now=now)
    # Bounded cross-item history; incompatible/legacy records cannot be invented
    # into a known first independent success. No answer text goes to the Agent.
    other = list(db.scalars(select(QuestionAttempt).where(
        QuestionAttempt.question_id == question.id, QuestionAttempt.practice_item_id != item_id)
        .order_by(QuestionAttempt.submitted_at.desc(), QuestionAttempt.id.desc())
        .limit(MAX_PREVIOUS_QUESTION_RECORDS + 1)))
    compatible, history_unknown, excluded_prior_versions = _scoped_question_history(other, content_hash)
    history_unknown = history_unknown or any(a.grading_evidence is None for a in history)
    assistance = "solution" if item.answer_revealed_at is not None else "process_review" if db.scalar(
        select(LearningEvent.id).where(LearningEvent.source_id == item.id,
            LearningEvent.event_type == EventType.AI_PROCESS_REVIEWED.value).limit(1)) is not None else "none"
    from backend.services.learning_qa_service import qa_assistance_for_item
    qa_level = qa_assistance_for_item(db, item, now)
    priority = {"none":0,"hint_1":1,"hint_2":2,"process_review":3,"solution":4}
    if priority[qa_level] > priority[assistance]: assistance = qa_level
    ancestor_id = item.retry_source_id
    while ancestor_id is not None:
        ancestor = db.get(PracticeItem, ancestor_id)
        if ancestor is None: raise ValueError('practice_item_not_found')
        ancestor_attempts = item_attempts(db, ancestor.id)
        if ancestor.answer_revealed_at or any((a.grading_evidence or {}).get('assisted') for a in ancestor_attempts):
            assistance = 'solution'  # conservative inheritance; never upgrade assisted retries
        ancestor_id = ancestor.retry_source_id
    if eligibility.practice_eligible:
        verdict = grade_practice_final_answer(
            question_type=question.question_type, config=question.grading_config,
            answer=raw_answer, selected_option=selected_option,
            expected=question.correct_answer, options=question.options,
            answer_provenance=question.answer_provenance, content_trust=question.content_trust,
            answer_reliability=question.answer_reliability,
        )
    else:
        verdict = AnswerVerdict("unknown", "question_not_practice_eligible", "untrusted_reference_v1")
    reference_result = None
    feedback_notice = None
    if eligibility.teaching_rule_version and eligibility.practice_eligible:
        if not eligibility.objective_feedback_eligible:
            reference_result = verdict.result
            blank = not (raw_answer and raw_answer.strip()) and not (selected_option and selected_option.strip())
            verdict = AnswerVerdict("unknown", "not_answered" if blank else "reference_answer_not_reliably_verified", "teaching_reference_v2")
            feedback_notice = "仅供对照参考，暂不支持可靠自动判题。"
        elif eligibility.evidence_capability != "verified_objective":
            feedback_notice = "当前题面的答案已在限定范围内独立验证；本次反馈不计入严格毕业确认。"
    verified_objective = eligibility.evidence_capability == "verified_objective"
    ai_consistent_objective = eligibility.evidence_capability == "ai_consistent_objective"
    personal_observation = eligibility.bank_scope == "personal" and eligibility.objective_feedback_eligible
    public_observation = eligibility.evidence_capability == 'public_practice_only' and eligibility.objective_feedback_eligible
    evidence_reliability = ("verified_objective" if verified_objective else
        "personal_practice_observation" if personal_observation else
        "public_practice_observation" if public_observation else
        "ai_consistent_objective" if ai_consistent_objective else
        "process_review" if eligibility.grading_capability == "process_review_only" else "ungradable")
    attempt_id = uuid4()
    evidence = {
        "version": (6 if eligibility.auto_review_current
            and question.current_auto_review.qualification_class == "exam_variant"
            and eligibility.source_status == "traceable"
            else 5 if eligibility.auto_review_current else 4),
        "sequence_version": "attempt-sequence-v1", "method": verdict.method, "reason": verdict.reason,
        "grading_input_version": "bounded-final-input-v2",
        "assisted": assistance != "none", "assistance_level": assistance,
        "attempt_number": len(history) + 1,
        "previous_attempt_id": str(previous.id) if previous else None,
        "expected_previous_attempt_id": str(expected_previous_attempt_id) if expected_previous_attempt_id else None,
        "question_content_sha256": content_hash, "history_unknown": history_unknown,
        "history_scope_version": "current_content_prefix_v1",
        "prior_history_excluded_count": excluded_prior_versions,
        "can_retry": False,
        "answer_revealed_at": item.answer_revealed_at.isoformat() if item.answer_revealed_at else None,
        "selected_option": selected_option,
        "question_role": question.question_role,
        "question_type": question.question_type, "is_variant": question.is_variant,
        "skill_tags": list(question.skill_tags or []),
        "confidence": confidence,
        "grading_config": question.grading_config,
        "reference_answer": question.correct_answer,
        "observation_scope": "tracked_interface_not_proctored",
        "question_provenance": eligibility.question_provenance,
        "bank_scope": question.bank_scope or "public",
        "generation_batch_id": str(question.generation_batch_id) if question.generation_batch_id else None,
        "question_content_trust": eligibility.content_trust,
        "source_status": eligibility.source_status,
        "answer_provenance": eligibility.answer_provenance,
        "answer_reliability": eligibility.answer_reliability,
        "grading_capability": eligibility.grading_capability,
        "evidence_capability": eligibility.evidence_capability,
        "evidence_reliability": evidence_reliability,
        "source_attestation_key": question.source_attestation_key,
        "source_attestation_sha256": question.source_attestation_sha256,
        "answer_attestation_key": question.answer_attestation_key,
        "answer_attestation_sha256": question.answer_attestation_sha256,
        "answer_verification_event_id": eligibility.answer_verification_event_id,
        "answer_verification_type": eligibility.answer_verification_type,
        "auto_review_event_id": eligibility.auto_review_event_id,
        "auto_review_version": eligibility.auto_review_version,
        "auto_review_snapshot_sha256": eligibility.auto_review_snapshot_sha256,
        "auto_review_qualification_class": (question.current_auto_review.qualification_class
            if eligibility.auto_review_current else None),
        "attempt_id": str(attempt_id), "policy_version": active_policy.policy_version,
        "answer_version_sha256": answer_version_sha256(question), "result": verdict.result,
        "teaching_rule_version": eligibility.teaching_rule_version,
        "teaching_use": eligibility.teaching_use,
        "reference_result": reference_result, "feedback_notice": feedback_notice,
    }
    category = classify_attempt_sequence(result=verdict.result,
        # Sequence describes observed completion/assistance, not graduation
        # authority. Only verified_objective below can create strong evidence.
        verified=verified_objective or ai_consistent_objective or personal_observation or public_observation,
        assistance=assistance, confidence=confidence,
        same_item_results=tuple(a.objective_result for a in history if a.grading_evidence is not None),
        previous_question_results=tuple(a.objective_result for a in compatible),
        history_unknown=history_unknown, evidence_reliability=evidence_reliability)
    evidence["sequence_category"] = category
    before = snapshot_from_storage(state)
    objective_evidence = classify_objective_evidence(
        result=verdict.result, verified=verified_objective,
        assisted=evidence["assisted"], question_id=str(question.id),
        is_variant=question.is_variant, occurred_at=now, question_type=question.question_type,
        skill_tags=tuple(question.skill_tags or ()),
        confidence=confidence,
        sequence_category=category,
        evidence_reliability=evidence_reliability,
        confirmation_facts={key: evidence.get(key) for key in CONFIRMATION_FACT_FIELDS},
    )
    event = DomainLearningEvent(EventType.ANSWER_SUBMITTED, now, evidence=objective_evidence,
                               payload={"confidence": confidence, "assisted": evidence["assisted"], "sequence_category": category})
    from backend.services.policy_evidence_service import current_policy_snapshot
    evaluation_before = (current_policy_snapshot(db, state, active_policy)
        if objective_evidence.level is not EvidenceLevel.WEAK else before)
    result = transition(evaluation_before, event, active_policy)
    evidence["assessment_basis"] = result.snapshot.assessment_basis
    from backend.services.grading_basis import submission_grading_basis
    evidence["grading_basis"] = submission_grading_basis(evidence)
    evidence["mastery_assessment_basis"] = result.snapshot.assessment_basis
    count_snapshot = (current_policy_snapshot(db, state, active_policy)
        if active_policy.policy_version in {2, 3} and objective_evidence.level is EvidenceLevel.WEAK else result.snapshot)
    evidence["effective_confirmation_count"] = effective_confirmation_count(
        policy_confirmation_window(count_snapshot.evidence_window, active_policy),
        manual_credit_count=0 if active_policy.policy_version in {2, 3} else count_snapshot.manual_credit_count,
    )
    if (evaluation_before.evidence_window != before.evidence_window
            or evaluation_before.manual_credit_count != before.manual_credit_count):
        # A future user submission may legitimately refresh the projection. Keep
        # its exact previous window in the new immutable receipt; do not infer a
        # historical policy version or certify old provenance.
        evidence["policy_projection_revalidated"] = True
        evidence["previous_policy_projection"] = {
            **snapshot_to_storage(before, "policy_projection_revalidated"),
            "evidence_window": [evidence_to_storage(e) for e in before.evidence_window],
            "historical_policy_version": "not_stored",
        }
    evidence["basis_changed"] = before.assessment_basis != result.snapshot.assessment_basis
    if evidence["basis_changed"]:
        evidence["previous_mastery_snapshot"] = {
            **snapshot_to_storage(before, "basis_changed"),
            "evidence_window": [evidence_to_storage(e) for e in before.evidence_window],
            "node_self_grade": before.node_self_grade.value if before.node_self_grade else None,
            "manual_confirmed_at": before.manual_confirmed_at.isoformat() if before.manual_confirmed_at else None,
        }
    apply_snapshot(state, result.snapshot)
    # NB-08：仅“题型/判分方式不受支持”时拒绝写入；个人题 verified=false 属
    # answer_not_verified，应保留为参考作答（unknown，不计掌握度/毕业证据）。
    if getattr(verdict, "method", None) == "unsupported_v1" and getattr(verdict, "reason", None) == "unsupported_question":
        raise AppError("answer_grading_unsupported", status_code=422)
    attempt = QuestionAttempt(
        id=attempt_id,
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
    if remaining is None and item.plan is not None:
        item.plan.status = "completed"
    return submission_response(attempt)


def record_answer_reveal(db: Session, *, item_id: UUID, now: datetime) -> None:
    item = db.scalar(select(PracticeItem).where(PracticeItem.id == item_id).with_for_update())
    if item is None:
        raise ValueError("practice_item_not_found")
    if question_for_practice_item(db, item) is None:
        raise ValueError("external_exam_has_no_embedded_answer")
    if item.answer_revealed_at is None:
        item.answer_revealed_at = now
