"""One fail-closed decision for entering new practice, independent of answer source."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from backend.mastery.enums import QuestionType

from backend.models.learning import KnowledgePoint, Question
from backend.services.answer_grading import available_grading_method, available_practice_grading_method
from backend.services.answer_consistency import has_current_answer_attestation
from backend.services.answer_verification import current_answer_verification
from backend.services.question_attestation import has_current_source_attestation


KNOWN_QUESTION_TYPES = {kind.value for kind in QuestionType if kind is not QuestionType.EXTERNAL_EXAM}
_ELIGIBILITY_CACHE_MAX = 16384
_ELIGIBILITY_CACHE: OrderedDict[tuple, "QuestionEligibility"] = OrderedDict()
_ELIGIBILITY_CACHE_LOCK = RLock()


@dataclass(frozen=True)
class QuestionEligibility:
    question_provenance: str
    content_trust: str
    source_status: str
    answer_provenance: str
    answer_reliability: str
    mapping_status: str
    source_attestation_current: bool
    answer_attestation_current: bool
    answer_verification_current: bool
    answer_verification_type: str | None
    answer_verification_event_id: str | None
    practice_eligible: bool
    grading_capability: str
    evidence_capability: str
    answer_comparison_method: str | None
    verified_grading_method: str | None
    blocking_reasons: tuple[str, ...]
    teaching_use: str | None = None
    objective_feedback_eligible: bool = False
    presentation_label: str | None = None
    explanation_label: str | None = None
    teaching_rule_version: str | None = None
    bank_scope: str = "public"
    auto_review_current: bool = False
    auto_review_event_id: str | None = None
    auto_review_version: str | None = None
    auto_review_snapshot_sha256: str | None = None

    def public_dict(self) -> dict:
        result = self.__dict__.copy()
        result["blocking_reasons"] = list(self.blocking_reasons)
        return result


def legacy_question_eligibility(question: Question, node: KnowledgePoint | None = None,
                                 *, auto_review_events: dict | None = None) -> QuestionEligibility:
    """Practice eligibility is not a claim that an AI answer is authoritative."""
    provenance = getattr(question, "question_provenance", "legacy_unknown") or "legacy_unknown"
    trust = getattr(question, "content_trust", "unreviewed") or "unreviewed"
    source_status = getattr(question, "source_status", "unknown") or "unknown"
    answer_provenance = getattr(question, "answer_provenance", "unknown") or "unknown"
    answer_reliability = getattr(question, "answer_reliability", "unknown") or "unknown"
    config = question.grading_config if isinstance(question.grading_config, dict) else {}
    expected = question.correct_answer
    options = question.options
    reasons: list[str] = []

    if not question.is_active:
        reasons.append("inactive")
    if getattr(question, "is_hidden", False):
        reasons.append("hidden")
    # A current source binding is independent of the content-review tier. Human
    # review of the same full Question must not erase its exact source mapping.
    source_binding_current = has_current_source_attestation(question)
    source_attested = trust == "source_attested" and source_binding_current
    content_human_verified = trust == "verified" and bool(question.content_reviewed_by and question.content_reviewed_at)
    answer_verification = current_answer_verification(question)
    answer_verification_current = answer_verification is not None
    from backend.services.auto_question_review import current_auto_review
    auto_review = current_auto_review(question, node, events=auto_review_events)
    auto_review_current = auto_review is not None
    answer_attested = (answer_provenance == "ai_generated"
        and answer_reliability == "ai_generated_consistent"
        and has_current_answer_attestation(question))
    generation_record = config.get("generation") if isinstance(config.get("generation"),dict) else {}
    server_generated_personal = (getattr(question,"bank_scope","public")=="personal"
        and answer_provenance=="server_generated" and answer_reliability=="unverified"
        and generation_record.get("version") in {"bounded-question-generation-v10","bounded-question-generation-v9","bounded-question-generation-v8"}
        and generation_record.get("generation_mode") in {"deterministic_fast","ai_enhanced"})
    if not content_human_verified and not source_attested and not auto_review_current:
        reasons.append("content_not_verified")
    if provenance not in {"real_exam", "trusted_practice", "ai_generated_practice"}:
        reasons.append("question_provenance_unknown")
    if provenance == "real_exam" and not (
        source_status == "verified" and content_human_verified
        or source_status == "verified" and auto_review_current
        or source_status == "traceable" and auto_review_current
        or source_status == "traceable" and source_attested
    ):
        reasons.append("exam_source_not_verified")
    elif provenance == "trusted_practice" and not (
        source_status == "verified" and content_human_verified
        or source_status == "traceable" and source_attested
        or source_status == "not_applicable"
    ):
        reasons.append("practice_source_not_traceable")
    elif provenance == "ai_generated_practice" and not (
        source_status == "not_applicable"
        or (source_status == "traceable" and auto_review_current
            and auto_review.qualification_class == "exam_variant")
    ):
        reasons.append("generated_question_source_invalid")
    if not isinstance(question.stem, str) or len(question.stem.strip()) < 5:
        reasons.append("question_content_incomplete")
    if question.question_type == "single_choice":
        if not isinstance(options, dict) or len(options) < 2 or any(not str(k).strip() or not isinstance(v, str) or not v.strip() for k, v in options.items()):
            reasons.append("choice_options_incomplete")
        elif not isinstance(expected, str) or expected.strip().upper() not in {str(k).strip().upper() for k in options}:
            reasons.append("choice_answer_invalid")
    elif isinstance(options, dict) and any(not isinstance(v, str) or not v.strip() for v in options.values()):
        reasons.append("question_content_incomplete")
    if not isinstance(expected, str) or not expected.strip():
        reasons.append("answer_missing")
    if not isinstance(question.explanation, str) or not question.explanation.strip():
        reasons.append("explanation_missing")
    if answer_provenance not in {"verified_reference", "human_verified", "ai_generated", "auto_verified"} and not server_generated_personal:
        reasons.append("answer_provenance_unknown")
    if answer_provenance in {"verified_reference", "human_verified"} and (
        answer_reliability != "verified" or not answer_verification_current
    ):
        reasons.append("answer_verification_missing_or_stale")
    if answer_provenance == "ai_generated" and answer_reliability not in {
        "model_generated", "unverified", "ai_generated_consistent", "ai_disagreement"
    }:
        reasons.append("ai_answer_reliability_unknown")
    if answer_provenance == "auto_verified" and not auto_review_current:
        reasons.append("auto_answer_review_missing_or_stale")
    if answer_provenance == "server_generated" and not server_generated_personal:
        reasons.append("server_generated_answer_requires_current_personal_binding")
    if question.question_type not in KNOWN_QUESTION_TYPES:
        reasons.append("practice_mode_unknown")

    mapping_status = "missing"
    if node is not None:
        if not node.is_active:
            mapping_status = "inactive"
            reasons.append("mapping_inactive")
        elif not node.is_assessable:
            mapping_status = "not_assessable"
            reasons.append("mapping_not_assessable")
        # current_auto_review(question, node) has already validated the full,
        # hash-bound mapping receipt, including these exact reference-topic
        # fields. Re-reading audit_snapshot here is both redundant and can
        # trigger one deferred JSON SELECT per question on homepage reads.
        elif node.is_reference_only and auto_review_current and (
            auto_review.qualification_class == "exam_curated"
        ):
            mapping_status = "source_attested_reference_topic"
        elif node.is_reference_only and auto_review_current and (
            auto_review.qualification_class in {"development_original", "exam_variant"}
        ):
            # A Codex-authored public original/variant may practice against an
            # exact bound reference-topic leaf. Its own generation record and
            # automatic review prove the mapping; exam-origin quotas still
            # come exclusively from real_exam evidence in the unchanged policy.
            mapping_status = "auto_reviewed_reference_topic"
        elif node.is_reference_only and source_binding_current and (
            source_attested or (content_human_verified and provenance == "real_exam"
                and source_status == "verified")
        ):
            # A reference-only leaf normally represents an external pointer.
            # A full Question may be practiced only when its own stable source
            # identity, pack fingerprint, and exact node code were attested.
            mapping_status = "source_attested_reference_topic"
        elif node.is_reference_only:
            mapping_status = "reference_only"
            reasons.append("reference_only_mapping")
        else:
            mapping_status = "assessable_leaf"
    else:
        reasons.append("mapping_missing")

    trusted_answer = (answer_provenance in {"verified_reference", "human_verified"}
        and answer_reliability == "verified" and answer_verification_current)
    trusted_auto_answer = (answer_provenance == "auto_verified" and answer_reliability == "verified"
                           and auto_review_current)
    trusted_answer = trusted_answer or trusted_auto_answer
    verified_method = (available_grading_method(question_type=question.question_type,
        config=config, expected=expected, options=options)
        if trusted_answer else None)
    answer_ready = (
        (content_human_verified or source_attested or auto_review_current)
        and (
            trusted_answer and (content_human_verified or auto_review_current)
            or (answer_provenance == "ai_generated" and (
                content_human_verified and answer_reliability in {"model_generated", "unverified", "ai_generated_consistent"}
                or source_attested and answer_attested
            ))
    ) or server_generated_personal
    )
    comparison_method = available_practice_grading_method(question_type=question.question_type,
        config=config, expected=expected, options=options,
        answer_provenance=answer_provenance, content_trust=trust,
        answer_reliability=answer_reliability) if answer_ready else None
    if verified_method:
        grading_capability = "deterministic"
    elif comparison_method and not comparison_method.startswith("ai_generated_"):
        grading_capability = "final_answer_limited"
    elif comparison_method and comparison_method.startswith("ai_generated_"):
        # The comparison operation is mechanical, but the reference itself is
        # AI-authored; do not describe the overall grading as deterministic.
        grading_capability = "final_answer_limited"
    elif question.question_type in {"proof", "discussion", "program", "subjective", "calculation"}:
        grading_capability = "process_review_only"
    else:
        grading_capability = "unsupported"
    # A known process-review/self-assessment mode is sufficient for practice.
    # It is not a machine-grade and never upgrades evidence capability.
    if grading_capability == "unsupported":
        reasons.append("grading_or_practice_mode_unsupported")

    # A public AI-original question becomes a formal strict-question candidate
    # only through its current version-bound automatic review event. Imported
    # reviewer strings alone must not bypass the H audit gate. The graduation
    # thresholds and evidence state machine remain unchanged.
    ai_original_gate = provenance != "ai_generated_practice" or auto_review_current
    if (trusted_answer and (content_human_verified or auto_review_current) and verified_method
            and provenance in {"real_exam", "trusted_practice", "ai_generated_practice"}
            and ai_original_gate):
        evidence_capability = "verified_objective"
    elif source_attested and answer_attested and comparison_method:
        evidence_capability = "ai_consistent_objective"
    elif answer_provenance == "ai_generated" and comparison_method:
        evidence_capability = "ai_low_reliability"
    elif grading_capability == "process_review_only":
        evidence_capability = "process_review_not_objective_evidence"
    else:
        evidence_capability = "self_report_only"

    return QuestionEligibility(
        question_provenance=provenance,
        content_trust=trust,
        source_status=source_status,
        answer_provenance=answer_provenance,
        answer_reliability=answer_reliability,
        mapping_status=mapping_status,
        source_attestation_current=source_binding_current,
        answer_attestation_current=answer_attested,
        answer_verification_current=answer_verification_current,
        answer_verification_type=(answer_verification.verification_type if answer_verification else
                                  "auto_verified" if auto_review else None),
        answer_verification_event_id=str(answer_verification.id) if answer_verification else None,
        practice_eligible=not reasons,
        grading_capability=grading_capability,
        evidence_capability=evidence_capability,
        answer_comparison_method=comparison_method,
        verified_grading_method=verified_method,
        blocking_reasons=tuple(dict.fromkeys(reasons)),
        auto_review_current=auto_review_current,
        auto_review_event_id=str(auto_review.id) if auto_review else None,
        auto_review_version=auto_review.review_version if auto_review else None,
        auto_review_snapshot_sha256=auto_review.question_snapshot_sha256 if auto_review else None,
    )


def _eligibility_cache_key(question: Question, node: KnowledgePoint | None,
                           teaching_enabled: bool | None,
                           auto_review_events: dict | None) -> tuple | None:
    """Bind a process-local static eligibility result to immutable row versions.

    Learner mastery, attempts, scheduling, and plan state are deliberately not
    part of QuestionEligibility. Public versioned question and receipt rows are
    immutable; all mutable admission pointers and node mapping state are bound
    below. Dirty, detached, personal, and unversioned objects fail closed and
    use the original evaluator.
    """
    if (getattr(question, "bank_scope", "public") != "public"
            or getattr(question, "generation_batch_id", None)
            or getattr(question, "current_version_id", None) is None):
        return None
    question_state = getattr(question, "_sa_instance_state", None)
    if question_state is None or question_state.modified:
        return None
    if node is None:
        node_key = None
    else:
        node_state = getattr(node, "_sa_instance_state", None)
        if node_state is None or node_state.modified:
            return None
        node_key = (node.id, node.code, node.subject, bool(node.is_active),
            bool(node.is_assessable), bool(node.is_reference_only), bool(getattr(node, "children", None)))

    try:
        from sqlalchemy.orm import object_session
        from sqlalchemy.orm.attributes import NO_VALUE
        session = object_session(question)
    except Exception:
        return None
    if session is None:
        return None

    def immutable_event_key(pointer_name: str, relationship_name: str, provided=None):
        pointer = getattr(question, pointer_name, None)
        if pointer is None:
            return None
        event = provided
        if event is None:
            try:
                event = question_state.attrs[relationship_name].loaded_value
            except Exception:
                return NO_VALUE
            if event is NO_VALUE:
                return NO_VALUE
        event_state = getattr(event, "_sa_instance_state", None)
        if event_state is None or event_state.modified:
            return NO_VALUE
        if event.id != pointer:
            return ("mismatch", event.id)
        if relationship_name == "current_auto_review":
            return (event.id, event.question_id, event.event_type, event.review_version,
                event.qualification_class, event.question_snapshot_sha256,
                event.answer_sha256, event.audit_sha256)
        return (event.id, event.question_id, event.event_type, event.verification_type,
            event.answer_sha256, event.verifier, event.created_at)

    auto_event = None
    if auto_review_events is not None:
        auto_event = auto_review_events.get(str(getattr(question, "auto_review_event_id", None)))
    auto_key = immutable_event_key("auto_review_event_id", "current_auto_review", auto_event)
    if auto_key is NO_VALUE:
        return None
    answer_key = immutable_event_key("answer_verification_event_id", "current_answer_verification")
    if answer_key is NO_VALUE:
        return None

    # The engine object distinguishes isolated databases even when their
    # Question UUIDs happen to overlap. It stays bounded by the LRU below.
    try:
        bind = session.get_bind()
    except Exception:
        return None
    return (
        bind, question.id, question.current_version_id, question.updated_at,
        question.kp_id, question.question_type, question.question_provenance,
        question.content_trust, question.source_status, question.answer_provenance,
        question.answer_reliability, question.content_reviewed_by, question.content_reviewed_at,
        question.answer_reviewed_by, question.answer_reviewed_at,
        question.source_attestation_key, question.source_attestation_sha256,
        question.answer_attestation_key, question.answer_attestation_sha256,
        question.answer_verification_event_id, question.auto_review_event_id,
        question.is_active, question.is_hidden, question.bank_scope,
        question.generation_batch_id, auto_key, answer_key, node_key, teaching_enabled,
    )


def _remember_eligibility(key: tuple, result: QuestionEligibility) -> None:
    with _ELIGIBILITY_CACHE_LOCK:
        _ELIGIBILITY_CACHE[key] = result
        _ELIGIBILITY_CACHE.move_to_end(key)
        while len(_ELIGIBILITY_CACHE) > _ELIGIBILITY_CACHE_MAX:
            _ELIGIBILITY_CACHE.popitem(last=False)


def public_eligibility_cache_ready(bind, *, minimum_entries: int = 512) -> bool:
    """Return whether this database has enough warm immutable decisions.

    Callers use this only to choose between a first-read/full-load path and a
    warm/narrow-load path. A cache miss on the narrow path is still reloaded
    with the full Question and re-evaluated by the original fail-closed rules.
    """
    with _ELIGIBILITY_CACHE_LOCK:
        return sum(1 for key in _ELIGIBILITY_CACHE if key and key[0] is bind) >= minimum_entries


def cached_question_eligibility(question: Question, node: KnowledgePoint | None = None,
                                *, teaching_enabled: bool | None = None,
                                auto_review_events: dict | None = None) -> QuestionEligibility | None:
    """Return a clean, version-bound cached decision without evaluating content.

    This is for read paths that deliberately load only static eligibility key
    columns. A missing, dirty, detached, personal, or stale object returns
    ``None`` so the caller can load the complete record and use the ordinary
    evaluator.
    """
    key = _eligibility_cache_key(question, node, teaching_enabled, auto_review_events)
    if key is None:
        return None
    with _ELIGIBILITY_CACHE_LOCK:
        cached = _ELIGIBILITY_CACHE.get(key)
        if cached is not None:
            _ELIGIBILITY_CACHE.move_to_end(key)
        return cached


def _question_eligibility_uncached(question: Question, node: KnowledgePoint | None = None,
                                   *, teaching_enabled: bool | None = None,
                                   auto_review_events: dict | None = None) -> QuestionEligibility:
    """Serve one formal public bank and the separate personal practice bank.

    Historical release/teaching flags remain in old records for audit but no
    longer provide an alternate public-practice admission path.
    """
    baseline = legacy_question_eligibility(question, node, auto_review_events=auto_review_events)
    if getattr(question, "bank_scope", "public") == "personal" or getattr(question, "generation_batch_id", None):
        from backend.services.personal_question_general import current_general_binding
        if current_general_binding(question, node):
            from dataclasses import replace
            from backend.services.question_quality import TEACHING_RULE_VERSION
            admitted = bool(question.is_active and not question.is_hidden)
            return replace(baseline, practice_eligible=admitted, bank_scope="personal",
                evidence_capability="personal_practice_only", verified_grading_method=None,
                grading_capability="process_review_only" if admitted else "unsupported",
                answer_comparison_method=None, auto_review_current=False, auto_review_event_id=None,
                auto_review_version=None, auto_review_snapshot_sha256=None,
                blocking_reasons=() if admitted else ("hidden_or_inactive",),
                objective_feedback_eligible=False, teaching_rule_version=TEACHING_RULE_VERSION,
                teaching_use="REFERENCE_ONLY", presentation_label="个人 AI 练习", explanation_label="AI参考解析")
    if baseline.auto_review_current:
        return baseline
    if getattr(question, "bank_scope", "public") == "personal" or getattr(question, "generation_batch_id", None):
        from dataclasses import replace
        from backend.services.question_generation import current_generation_binding
        from backend.services.question_quality import audit_teaching_question, TEACHING_RULE_VERSION
        binding = current_generation_binding(question, node)
        quality = audit_teaching_question(question, node, baseline=baseline) if binding else {}
        admitted = bool(binding and question.is_active and not question.is_hidden and quality.get("objective_grading_eligible"))
        # Scope wins over forged provenance, authority events or grader stamps.
        return replace(baseline, practice_eligible=admitted,
            bank_scope="personal",
            evidence_capability="personal_practice_only", verified_grading_method=None,
            grading_capability="final_answer_limited" if admitted else "unsupported",
            answer_comparison_method=quality.get("comparison_method") if admitted else None,
            blocking_reasons=() if admitted else ("personal_generation_binding_invalid",),
            teaching_rule_version=TEACHING_RULE_VERSION, objective_feedback_eligible=admitted,
            teaching_use="PERSONAL_PRACTICE", presentation_label="个人 AI 练习", explanation_label="参考解析")
    if baseline.practice_eligible and baseline.evidence_capability == "verified_objective":
        return baseline
    from dataclasses import replace
    return replace(baseline, practice_eligible=False, grading_capability="unsupported",
        evidence_capability="archive_only", answer_comparison_method=None, verified_grading_method=None,
        blocking_reasons=tuple(dict.fromkeys((*baseline.blocking_reasons, "public_formal_review_required"))),
        teaching_use=None, objective_feedback_eligible=False, teaching_rule_version=None,
        presentation_label="历史资料记录", explanation_label=None)


def question_eligibility(question: Question, node: KnowledgePoint | None = None,
                         *, teaching_enabled: bool | None = None,
                         auto_review_events: dict | None = None) -> QuestionEligibility:
    key = _eligibility_cache_key(question, node, teaching_enabled, auto_review_events)
    if key is not None:
        with _ELIGIBILITY_CACHE_LOCK:
            cached = _ELIGIBILITY_CACHE.get(key)
            if cached is not None:
                _ELIGIBILITY_CACHE.move_to_end(key)
                return cached
    result = _question_eligibility_uncached(question, node,
        teaching_enabled=teaching_enabled, auto_review_events=auto_review_events)
    if key is not None:
        _remember_eligibility(key, result)
    return result


def is_practice_eligible(question: Question, node: KnowledgePoint | None = None) -> bool:
    return question_eligibility(question, node).practice_eligible
