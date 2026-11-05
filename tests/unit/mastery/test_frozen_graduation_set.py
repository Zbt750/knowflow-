from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from backend.mastery.enums import EventType, EvidenceLevel, MasteryState
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import analyze_gaps, graduation_check
from backend.mastery.selection import QuestionCandidate, select_questions
from backend.mastery.transition import transition
from backend.mastery.types import DomainLearningEvent, Evidence, MasterySnapshot
from tests.unit.mastery.conftest import DAY1, DAY2


def verified(qid: str, *, level=EvidenceLevel.CONFIRMED, when=DAY1,
             assisted=False, category="first_independent_correct") -> Evidence:
    facts = {
        "attempt_id": str(uuid4()), "policy_version": 3,
        "question_provenance": "trusted_practice", "question_content_sha256": "a" * 64,
        "answer_version_sha256": "b" * 64, "answer_verification_event_id": str(uuid4()),
        "answer_provenance": "human_verified", "answer_reliability": "verified",
        "question_content_trust": "verified", "source_status": "not_applicable",
        "grading_capability": "deterministic", "method": "single_choice_v1",
        "assisted": assisted, "assistance_level": "solution" if assisted else "none",
        "confidence": "sure", "sequence_category": category,
        "sequence_version": "attempt-sequence-v1", "result": "right",
        "evidence_reliability": "verified_objective", "bank_scope": "public",
    }
    return Evidence(question_id=qid, level=level, is_variant=False, occurred_at=when,
        source="objective_final", question_type="single_choice", reliability="verified_objective",
        confirmation_facts=facts)


def v3_policy(qids: tuple[str, ...], *, set_version=1, max_window=1) -> MasteryPolicy:
    # Old count/day/type/variant/skill settings deliberately remain severe:
    # the frozen-set graduation layer must ignore them.
    return MasteryPolicy(policy_version=3, graduation_question_ids=qids,
        graduation_set_version=set_version, max_evidence_window=max_window,
        min_confirmations=9, min_real_questions=9,
        required_question_types={"calculation": 5}, required_variant_count=8,
        required_skill_tags=frozenset({"not-a-gate"}), min_day_span=30)


def test_empty_set_never_graduates_even_when_legacy_gates_would_pass():
    p = MasteryPolicy(policy_version=3, graduation_question_ids=(), graduation_set_version=0)
    assert graduation_check((), manual_credit_count=99, manual_confirmed_at=DAY1, policy=p) == (
        False, "graduation_question_set_unconfigured")
    gap = analyze_gaps((), manual_credit_count=0, manual_confirmed_at=None, policy=p)
    assert not gap.can_graduate and gap.items[0].required == 1


def test_unbound_legacy_history_never_graduates_before_explicit_set_transition():
    policy = MasteryPolicy(
        policy_version=2, graduation_binding_pending=True,
        min_confirmations=1, min_real_questions=1, required_variant_count=0,
        min_day_span=0, manual_mastered_credit=0,
    )
    legacy_evidence = (verified(str(uuid4()), when=DAY1), verified(str(uuid4()), when=DAY2))
    assert graduation_check(legacy_evidence, manual_credit_count=0,
        manual_confirmed_at=None, policy=policy) == (
            False, "graduation_set_transition_confirmation_required")
    gap = analyze_gaps(legacy_evidence, manual_credit_count=0,
        manual_confirmed_at=None, policy=policy)
    assert not gap.can_graduate
    assert gap.items[0].key == "graduation-set-transition"
    assert "明确确认" in gap.next_step


def test_only_all_frozen_independent_completions_graduate_and_window_keeps_full_set():
    qids = tuple(str(uuid4()) for _ in range(3))
    policy = v3_policy(qids, max_window=1)
    state = MasterySnapshot(MasteryState.UNSEEN, (), 0, None, None, None, 0, None,
                            assessment_basis="objective_v1")
    for index, qid in enumerate(qids):
        result = transition(state, DomainLearningEvent(EventType.ANSWER_SUBMITTED,
            DAY1 if index < 2 else DAY2, evidence=verified(qid, when=DAY1 if index < 2 else DAY2)), policy)
        state = result.snapshot
        if index < 2:
            assert state.state is not MasteryState.MASTERED
    assert state.state is MasteryState.MASTERED
    assert len(state.evidence_window) == 3  # not truncated to max_evidence_window=1
    assert graduation_check(state.evidence_window, manual_credit_count=0,
        manual_confirmed_at=None, policy=policy) == (True, "graduated")
    gap = analyze_gaps(state.evidence_window, manual_credit_count=0,
        manual_confirmed_at=None, policy=policy)
    assert all(item.satisfied for item in gap.items)


def test_assisted_correct_is_learning_only_until_a_later_independent_attempt():
    qid = str(uuid4())
    policy = v3_policy((qid,))
    initial = MasterySnapshot(MasteryState.UNSEEN, (), 0, None, None, None, 0, None,
                              assessment_basis="objective_v1")
    assisted = transition(initial, DomainLearningEvent(EventType.ANSWER_SUBMITTED, DAY1,
        evidence=verified(qid, level=EvidenceLevel.PARTIAL, assisted=True,
                          category="solution_assisted_correct")), policy)
    assert assisted.snapshot.evidence_window == ()
    assert assisted.snapshot.state is not MasteryState.MASTERED
    independent = transition(assisted.snapshot, DomainLearningEvent(EventType.ANSWER_SUBMITTED,
        DAY2, evidence=verified(qid, when=DAY2, category="repeat_correct")), policy)
    assert independent.snapshot.state is MasteryState.MASTERED
    assert independent.snapshot.evidence_window[0].question_id == qid


def test_later_wrong_answer_schedules_review_without_erasing_completed_question_or_graduation():
    qids = (str(uuid4()), str(uuid4()))
    policy = v3_policy(qids)
    first = transition(MasterySnapshot(MasteryState.UNSEEN, (), 0, None, None, None, 0, None,
        assessment_basis="objective_v1"), DomainLearningEvent(EventType.ANSWER_SUBMITTED,
        DAY1, evidence=verified(qids[0])), policy).snapshot
    wrong = replace(verified(qids[0], level=EvidenceLevel.FAILURE, when=DAY2),
                    confirmation_facts={"result": "wrong"})
    after_wrong = transition(first, DomainLearningEvent(EventType.ANSWER_SUBMITTED,
        DAY2, evidence=wrong), policy).snapshot
    assert {item.question_id for item in after_wrong.evidence_window} == {qids[0]}
    assert qids[0] in after_wrong.pending_review_question_ids
    finished = transition(after_wrong, DomainLearningEvent(EventType.ANSWER_SUBMITTED,
        DAY2, evidence=verified(qids[1], when=DAY2)), policy).snapshot
    assert finished.state is MasteryState.MASTERED
    post_grad_wrong = transition(finished, DomainLearningEvent(EventType.ANSWER_SUBMITTED,
        DAY2, evidence=replace(wrong, question_id=str(uuid4()))), policy).snapshot
    assert post_grad_wrong.state is MasteryState.MASTERED
    assert post_grad_wrong.mastered_at == finished.mastered_at


def test_adaptive_remediation_is_available_without_becoming_a_graduation_gate():
    required_id = str(uuid4())
    extra_id = str(uuid4())
    policy = v3_policy((required_id,))
    completed_required = verified(required_id)
    selection = select_questions(
        policy,
        (completed_required,),
        [
            QuestionCandidate(
                question_id=required_id,
                question_type="single_choice",
                skill_tags=(),
                is_variant=False,
                estimated_minutes=5,
                confirmed=True,
            ),
            QuestionCandidate(
                question_id=extra_id,
                question_type="fill_blank",
                skill_tags=(),
                is_variant=True,
                estimated_minutes=5,
                last_self_grade="not_mastered",
            ),
        ],
        limit=2,
        reference_time=DAY2,
    )
    assert [item.question_id for item in selection.items] == [extra_id]
    assert selection.items[0].reason == "上次未掌握，优先重做"
    # The selection projection for the extra question is not part of the set.
    assert graduation_check((completed_required, verified(extra_id)), manual_credit_count=0,
        manual_confirmed_at=None, policy=policy) == (True, "graduated")
