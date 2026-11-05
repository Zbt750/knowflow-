from dataclasses import replace
from datetime import timedelta

import pytest

from backend.mastery.enums import EvidenceLevel, EventType, MasteryState, SelfGrade
from backend.mastery.evidence import classify_objective_evidence
from backend.mastery.policy import MasteryPolicy
from backend.mastery.transition import transition
from backend.mastery.types import DomainLearningEvent, MasterySnapshot
from backend.mastery.selection import QuestionCandidate, select_questions
from tests.unit.mastery.conftest import DAY1, DAY2, DAY3


def empty():
    return MasterySnapshot(MasteryState.UNSEEN, (), 0, None, None, None, 0, None)


def policy(**kwargs):
    return MasteryPolicy(**{ "min_confirmations": 2, "min_real_questions": 2,
        "required_variant_count": 0, "min_day_span": 0, **kwargs })


def event(q="q1", result="right", assisted=False, when=DAY1, confidence=None, verified=True):
    evidence = classify_objective_evidence(result=result, verified=verified, assisted=assisted,
        question_id=q, is_variant=False, occurred_at=when, question_type="fill_blank", confidence=confidence)
    return DomainLearningEvent(EventType.ANSWER_SUBMITTED, when, evidence=evidence,
                               payload={"assisted": assisted, "confidence": confidence})


@pytest.mark.parametrize("result,verified,assisted,confidence,level", [
    ("right", True, False, None, EvidenceLevel.CONFIRMED),
    ("right", True, True, "certain", EvidenceLevel.PARTIAL),
    ("right", True, False, "guess", EvidenceLevel.PARTIAL),
    ("wrong", True, False, "certain", EvidenceLevel.FAILURE),
    ("right", False, False, "certain", EvidenceLevel.WEAK),
    ("unknown", True, False, None, EvidenceLevel.WEAK),
])
def test_evidence_strength(result, verified, assisted, confidence, level):
    assert event(result=result, verified=verified, assisted=assisted, confidence=confidence).evidence.level is level


def test_correct_confirmation_and_duplicate_question():
    first = transition(empty(), event(), policy()).snapshot
    assert first.assessment_basis == "objective_v1" and len(first.evidence_window) == 1
    assert first.state is MasteryState.CONSOLIDATING
    again = transition(first, event(when=DAY2), policy()).snapshot
    assert len(again.evidence_window) == 1


def test_wrong_preserves_other_questions_and_blocks_graduation_until_retest():
    first = transition(empty(), event(), policy()).snapshot
    mastered = transition(first, event("q2"), policy()).snapshot
    assert mastered.state is MasteryState.MASTERED
    wrong = transition(mastered, event("q2", "wrong", when=DAY2), policy()).snapshot
    assert wrong.state is MasteryState.STUCK
    assert [e.question_id for e in wrong.evidence_window] == ["q1"]
    assert wrong.pending_review_question_ids == ("q2",)
    other = transition(wrong, event("q3", when=DAY2), policy()).snapshot
    assert len(other.evidence_window) == 2 and other.state is MasteryState.STUCK
    assisted = transition(other, event("q2", assisted=True, when=DAY2), policy()).snapshot
    assert assisted.pending_review_question_ids == ("q2",)
    recovered = transition(assisted, event("q2", when=DAY3), policy()).snapshot
    assert recovered.pending_review_question_ids == () and recovered.state is MasteryState.MASTERED


def test_unknown_does_not_change_legacy_state():
    current = replace(empty(), state=MasteryState.MASTERED, manual_credit_count=2)
    assert transition(current, event(result="unknown"), policy()).snapshot == current


@pytest.mark.parametrize("kind", [EventType.PRACTICE_SELF_REPORTED, EventType.NODE_SELF_REPORTED])
@pytest.mark.parametrize("grade", [SelfGrade.MASTERED, SelfGrade.PARTIAL, SelfGrade.NOT_MASTERED])
@pytest.mark.parametrize("basis", ["legacy_self_reported", "objective_v1"])
def test_new_feedback_preserves_all_existing_evidence_and_review(kind, grade, basis):
    current = replace(transition(empty(), event(), policy()).snapshot, assessment_basis=basis,
                      manual_credit_count=2 if basis == "legacy_self_reported" else 0,
                      pending_review_question_ids=("q2",))
    result = transition(current, DomainLearningEvent(kind, DAY2, self_grade=grade), policy())
    assert result.reason_code == "self_feedback_only"
    assert replace(result.snapshot, node_self_grade=current.node_self_grade) == current


@pytest.mark.parametrize("kind", [EventType.NODE_SELF_ASSESSED, EventType.QUESTION_SELF_ASSESSED])
@pytest.mark.parametrize("grade", [SelfGrade.MASTERED, SelfGrade.NOT_MASTERED])
def test_self_report_cannot_graduate_or_reset_objective_state(kind, grade):
    current = transition(empty(), event(), policy()).snapshot
    feedback = DomainLearningEvent(kind, DAY2, self_grade=grade, evidence=event().evidence)
    result = transition(current, feedback, policy())
    assert result.reason_code == "self_feedback_only"
    assert result.snapshot.evidence_window == current.evidence_window
    assert result.snapshot.manual_credit_count == 0
    assert result.snapshot.state is MasteryState.CONSOLIDATING


def test_cross_day_requirement_still_applies():
    current = transition(empty(), event(), policy(min_day_span=2)).snapshot
    same_day = transition(current, event("q2"), policy(min_day_span=2)).snapshot
    assert same_day.state is MasteryState.CONSOLIDATING
    later = transition(same_day, event("q2", when=DAY3), policy(min_day_span=2)).snapshot
    assert later.state is MasteryState.MASTERED


def test_review_due_pass_advances_schedule():
    p = policy(min_confirmations=1, min_real_questions=1)
    current = transition(empty(), event(), p).snapshot
    result = transition(current, event(when=DAY1 + timedelta(days=7)), p)
    assert result.reason_code == "objective_review_passed"
    assert result.snapshot.review_stage == 1
    assert result.snapshot.mastered_at == current.mastered_at


def test_pending_question_prioritized_over_more_coverage():
    pending = QuestionCandidate("pending", "fill_blank", (), False, 5, pending_objective_review=True)
    other = QuestionCandidate("new", "fill_blank", ("method",), True, 3)
    selected = select_questions(policy(), (), [other, pending], limit=1)
    assert selected.items[0].question_id == "pending"
