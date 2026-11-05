"""Compute on demand from current objective window and immutable receipts; no writes."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import select, tuple_, case, Integer
from backend.models.learning import Question, QuestionAttempt, KpState, KpMasteryPolicy
from backend.mastery.storage import policy_for_node, evidence_to_storage
from backend.services.policy_evidence_service import current_policy_snapshot
from backend.mastery.capability import CapabilityQuestion, CapabilityAttempt, project_capabilities
from backend.services.answer_grading import available_grading_method
from backend.services.answer_submission_service import question_content_hash_matches
from backend.services.question_eligibility import question_eligibility
from backend.services.answer_verification import answer_version_sha256
from backend.mastery.learning_progress import ProgressAttempt, project_learning_progress
from backend.schemas.capability import GraduationProgress, GraduationQuestionStatus
from backend.services.evidence_pool import _content_identity
from backend.services.question_versions import question_for_attempt
from backend.services.policy_evidence_service import _same_identifier

RECENT_LIMIT = 100
CONFIRMATION_LIMIT = 200
INDEPENDENT_CATEGORIES = frozenset({"first_independent_correct", "independent_retest_correct", "repeat_correct"})


def _uuid(value):
    try: return UUID(str(value))
    except (ValueError, TypeError, AttributeError): return None


def _auto_verified_progress_receipt(attempt, question, node, trust):
    """Read v5/v6 evidence against its bound immutable content, never mint credit.

    Uses the same eligibility, hash and auto-review bindings as the existing
    policy evidence reader. Right/wrong reliability is distinct from independence
    and graduation; those continue to use the sequence and validated snapshot.
    """
    s = attempt.grading_evidence if isinstance(attempt.grading_evidence, dict) else {}
    if not (question and trust and type(s.get("version")) is int and s["version"] in {5, 6}
            and getattr(question, "bank_scope", None) == s.get("bank_scope") == "public"
            and not getattr(question, "generation_batch_id", None) and not s.get("generation_batch_id")
            and trust.practice_eligible and trust.auto_review_current
            and trust.evidence_capability == s.get("evidence_capability") == s.get("evidence_reliability") == "verified_objective"
            and attempt.self_grade is None and attempt.exam_reference_id is None
            and attempt.question_id == question.id and attempt.kp_id == question.kp_id == node.id
            and _same_identifier(attempt.question_version_id, getattr(question, "version_id", None))
            and attempt.question_version_id is not None
            and s.get("attempt_id") == str(attempt.id) and s.get("result") == attempt.objective_result
            and s.get("result") in {"right", "wrong"}
            and s.get("answer_reliability") == trust.answer_reliability == "verified"
            and s.get("grading_capability") == trust.grading_capability == "deterministic"
            and s.get("question_content_trust") == question.content_trust == "auto_verified"
            and s.get("answer_provenance") == question.answer_provenance == "auto_verified"
            and s.get("question_provenance") == question.question_provenance
            and s.get("question_type") == question.question_type
            and s.get("is_variant") == question.is_variant
            and s.get("skill_tags") == list(question.skill_tags or [])
            and question_content_hash_matches(s.get("question_content_sha256"), question)
            and s.get("answer_version_sha256") == answer_version_sha256(question)
            and s.get("method") in {"single_choice_v1", "exact_numeric_v1", "exact_logarithm_v1", "exact_constant_v1"}
            and _same_identifier(s.get("auto_review_event_id"), trust.auto_review_event_id)
            and s.get("auto_review_version") == trust.auto_review_version
            and s.get("auto_review_snapshot_sha256") == trust.auto_review_snapshot_sha256):
        return False
    category = question.current_auto_review.qualification_class
    if s["version"] == 6:
        return category == s.get("auto_review_qualification_class") == "exam_variant"
    return s.get("auto_review_qualification_class") in {None, category}


def read_capability_profile(db, node, *, questions=None, now=None):
    if node is None or not node.is_active or not node.is_assessable:
        return None  # Parent nodes never acquire a second, invented mastery truth.
    rows = list(questions) if questions is not None else list(db.scalars(
        select(Question).where(Question.kp_id == node.id, Question.is_active.is_(True))))
    facts = [CapabilityQuestion(q.id, q.question_type, q.question_role, q.is_variant,
        bool(available_grading_method(question_type=q.question_type, config=q.grading_config,
            expected=q.correct_answer, options=q.options)), tuple(q.skill_tags or ())) for q in rows]
    by_id = {q.id: q for q in rows}
    state = db.get(KpState, node.id)
    attempt_number = QuestionAttempt.grading_evidence["attempt_number"].as_string()
    sequence_order = case((attempt_number.op("~")(r"^[0-9]{1,2}$"), attempt_number.cast(Integer)), else_=0)
    recent = list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id == node.id)
        .order_by(QuestionAttempt.submitted_at.desc(), sequence_order.desc(), QuestionAttempt.id).limit(RECENT_LIMIT + 1)))
    pairs = set()
    confirmation_entries = []
    window = (state.evidence_window or []) if state and state.assessment_basis == "objective_v1" else []
    policy = policy_for_node(db, node.id)
    graduation_snapshot = None
    if state and policy.policy_version in {2, 3}:
        graduation_snapshot = current_policy_snapshot(db, state, policy)
        window = [evidence_to_storage(e) for e in graduation_snapshot.evidence_window]
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
            try:
                q = question_for_attempt(db, a)
            except ValueError:
                continue
            if q is None:
                continue
            live_question = by_id.get(q.id)
            if (a.objective_result == "right" and a.self_grade is None and a.exam_reference_id is None
                    and saved.get("sequence_version") == "attempt-sequence-v1"
                    and saved.get("assessment_basis") == "objective_v1"
                    and saved.get("sequence_category") in INDEPENDENT_CATEGORIES
                    and saved.get("assisted") is False and saved.get("confidence") not in {"guess", "no_idea"}
                    and question_content_hash_matches(saved.get("question_content_sha256"), q)
                    and live_question is not None
                    and question_content_hash_matches(saved.get("question_content_sha256"), live_question)):
                confirmed.add(q.id)
                valid_receipt_pairs.add((q.id, a.submitted_at))
                # P2 hashed type/variant/tags but not role. Never use a later role
                # edit to relabel an old basic success as application evidence.
                if live_question.is_variant or saved.get("question_role") == live_question.question_role:
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
    eligibility = {q.id: question_eligibility(q, node) for q in rows}
    observations = []
    for a in recent[:RECENT_LIMIT]:
        saved = a.grading_evidence if isinstance(a.grading_evidence, dict) else {}
        try:
            q = question_for_attempt(db, a)
        except ValueError:
            q = None
        trust = question_eligibility(q, node) if q is not None else None
        # Current trust never backfills old receipts. Reliable errors, like
        # correct confirmations, require an actual at-submission v4 binding.
        reliable = bool(q and trust and trust.practice_eligible and trust.evidence_capability == "verified_objective"
            and saved.get("version") == 4 and saved.get("evidence_reliability") == "verified_objective"
            and saved.get("answer_reliability") == "verified" and saved.get("grading_capability") == "deterministic"
            and question_content_hash_matches(saved.get("question_content_sha256"), q)
            and saved.get("answer_version_sha256") == answer_version_sha256(q)
            and saved.get("answer_verification_event_id") == trust.answer_verification_event_id
            and saved.get("attempt_id") == str(a.id) and saved.get("result") == a.objective_result
            and saved.get("question_content_trust") == "verified"
            and saved.get("question_provenance") == q.question_provenance
            and saved.get("answer_provenance") in {"human_verified", "verified_reference"}
            and saved.get("method") in {"single_choice_v1", "exact_numeric_v1", "exact_logarithm_v1"}
            and a.self_grade is None and a.exam_reference_id is None)
        reliable = reliable or _auto_verified_progress_receipt(a, q, node, trust)
        number = saved.get("attempt_number")
        observations.append(ProgressAttempt(
            str(a.question_id) if a.question_id else None, str(a.practice_item_id), a.submitted_at, a.objective_result,
            number=number if type(number) is int else 0,
            assisted=saved.get("assisted") if type(saved.get("assisted")) is bool else None,
            assistance_level=saved.get("assistance_level"), category=saved.get("sequence_category"),
            sequence_version=saved.get("sequence_version"), history_unknown=saved.get("history_unknown"),
            reliable_current=reliable, strict_current_confirmation=reliable and (a.question_id, a.submitted_at) in valid_receipt_pairs,
            content_identity=_content_identity(q) if q else None,
            skill_tags=tuple(t for t in (q.skill_tags or ()) if t != node.name) if q else ()))
    profile.learning_progress = project_learning_progress(observations,
        practice_count=sum(e.practice_eligible for e in eligibility.values()),
        history_truncated=len(recent) > RECENT_LIMIT or lookup_truncated,
        required_tags=policy.required_skill_tags)
    from backend.services.post_graduation_service import read_post_practice
    profile.post_graduation=read_post_practice(db,node,now=now,questions=rows,attempts=recent)
    if policy.policy_version == 3:
        configured = bool(policy.graduation_set_version and policy.graduation_question_ids)
        required_ids = [_uuid(value) for value in policy.graduation_question_ids]
        required_ids = [value for value in required_ids if value is not None]
        # `window` above is a storage-shaped list used by the legacy capability
        # projection. Graduation progress must use the validated Evidence objects
        # from the current snapshot, not that unrelated serialization variable.
        graduation_window = graduation_snapshot.evidence_window if graduation_snapshot else ()
        completed_ids = {str(e.question_id) for e in graduation_window
                         if e.question_id and e.level.value == "confirmed"}
        attempted_ids = set()
        if required_ids:
            attempted_ids = {str(value) for value in db.scalars(select(QuestionAttempt.question_id)
                .where(QuestionAttempt.kp_id == node.id,
                    QuestionAttempt.question_id.in_(required_ids))).all() if value is not None}
        question_states = []
        for ordinal, question_id in enumerate(required_ids, start=1):
            qid = str(question_id)
            status = ("COMPLETED" if qid in completed_ids else
                      "IN_PROGRESS" if qid in attempted_ids else "NOT_STARTED")
            question_states.append(GraduationQuestionStatus(question_id=question_id,
                ordinal=ordinal, status=status))
        profile.graduation_progress = GraduationProgress(
            configured=configured,
            graduated=bool(graduation_snapshot and graduation_snapshot.mastered_at is not None),
            graduated_at=graduation_snapshot.mastered_at.isoformat()
                if graduation_snapshot and graduation_snapshot.mastered_at else None,
            completed_question_count=sum(item.status == "COMPLETED" for item in question_states),
            required_question_count=len(question_states),
            questions=question_states,
        )
    return profile
