"""Compute on demand from current objective window and immutable receipts; no writes."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import select, tuple_
from backend.models.learning import Question, QuestionAttempt, KpState
from backend.mastery.capability import CapabilityQuestion, CapabilityAttempt, project_capabilities
from backend.services.answer_grading import available_grading_method
from backend.services.answer_submission_service import question_content_hash

RECENT_LIMIT = 100
CONFIRMATION_LIMIT = 200
INDEPENDENT_CATEGORIES = frozenset({"first_independent_correct", "independent_retest_correct", "repeat_correct"})


def _uuid(value):
    try: return UUID(str(value))
    except (ValueError, TypeError, AttributeError): return None


def read_capability_profile(db, node, *, questions=None):
    if node is None or not node.is_active or not node.is_assessable:
        return None  # Parent nodes never acquire a second, invented mastery truth.
    rows = list(questions) if questions is not None else list(db.scalars(
        select(Question).where(Question.kp_id == node.id, Question.is_active.is_(True))))
    facts = [CapabilityQuestion(q.id, q.question_type, q.question_role, q.is_variant,
        bool(available_grading_method(question_type=q.question_type, config=q.grading_config,
            expected=q.correct_answer, options=q.options)), tuple(q.skill_tags or ())) for q in rows]
    by_id = {q.id: q for q in rows}
    state = db.get(KpState, node.id)
    recent = list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id == node.id)
        .order_by(QuestionAttempt.submitted_at.desc(), QuestionAttempt.id).limit(RECENT_LIMIT + 1)))
    pairs = set()
    confirmation_entries = []
    window = (state.evidence_window or []) if state and state.assessment_basis == "objective_v1" else []
    for entry in window:
        if not isinstance(entry, dict) or entry.get("source") != "objective_final" or entry.get("level") != "confirmed": continue
        qid = _uuid(entry.get("question_id"))
        try: instant = datetime.fromisoformat(str(entry.get("occurred_at")))
        except ValueError: instant = None
        pair = (qid, instant) if instant is not None and instant.tzinfo is not None else None
        confirmation_entries.append(pair)
        if qid in by_id and pair is not None: pairs.add(pair)
    receipts = list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id == node.id,
        tuple_(QuestionAttempt.question_id, QuestionAttempt.submitted_at).in_(list(pairs)))
        .order_by(QuestionAttempt.submitted_at.desc(), QuestionAttempt.id).limit(CONFIRMATION_LIMIT + 1))) if pairs else []
    confirmed = set()
    valid_receipt_pairs = set()
    transfer_confirmed = set()
    lookup_truncated = len(receipts) > CONFIRMATION_LIMIT
    # Conservatively refuse confirmation if a bounded lookup was incomplete.
    if not lookup_truncated:
        for a in receipts:
            saved = a.grading_evidence or {}
            q = by_id[a.question_id]
            if (a.objective_result == "right" and a.self_grade is None and a.exam_reference_id is None
                    and saved.get("sequence_version") == "attempt-sequence-v1"
                    and saved.get("assessment_basis") == "objective_v1"
                    and saved.get("sequence_category") in INDEPENDENT_CATEGORIES
                    and saved.get("assisted") is False and saved.get("confidence") not in {"guess", "no_idea"}
                    and saved.get("question_content_sha256") == question_content_hash(q)):
                confirmed.add(q.id)
                valid_receipt_pairs.add((q.id, a.submitted_at))
                # P2 hashed type/variant/tags but not role. Never use a later role
                # edit to relabel an old basic success as application evidence.
                if q.is_variant or saved.get("question_role") == q.question_role:
                    transfer_confirmed.add(q.id)
    pending = {_uuid(value) for value in (state.pending_review_question_ids or [])} if state and state.assessment_basis == "objective_v1" else set()
    pending.discard(None)
    profile = project_capabilities(subject=node.subject, questions=facts,
        recent_attempts=[CapabilityAttempt(a.question_id, a.objective_result,
            (a.grading_evidence or {}).get("assisted"), (a.grading_evidence or {}).get("sequence_category")) for a in recent[:RECENT_LIMIT]],
        confirmed_ids=confirmed, transfer_confirmed_ids=transfer_confirmed,
        pending_ids=pending, history_truncated=len(recent) > RECENT_LIMIT)
    profile.confirmation_lookup_truncated = lookup_truncated
    # Count rejected confirmation entries, not weak/failure entries or repeated
    # valid receipts for one question (the dimension itself still deduplicates).
    profile.excluded_confirmation_count = sum(pair not in valid_receipt_pairs for pair in confirmation_entries)
    return profile
