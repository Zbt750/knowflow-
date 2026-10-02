from datetime import datetime, timezone
import pytest

from backend.mastery.attempt_sequence import classify_attempt_sequence, NON_CONFIRMING_CORRECT
from backend.mastery.evidence import classify_objective_evidence
from backend.mastery.enums import EvidenceLevel


@pytest.mark.parametrize("args,expected", [
    ({}, "first_independent_correct"),
    ({"same_item_results": ("wrong",)}, "self_corrected"),
    ({"same_item_results": ("wrong", "wrong")}, "self_corrected"),
    ({"same_item_results": ("unknown",)}, "correct_after_ungraded"),
    ({"assistance": "solution", "same_item_results": ("wrong",)}, "solution_assisted_correct"),
    ({"assistance": "process_review"}, "process_review_assisted_correct"),
    ({"assistance": "hint_1"}, "hint_assisted_correct"),
    ({"assistance": "hint_2"}, "hint_assisted_correct"),
    ({"previous_question_results": ("right",)}, "repeat_correct"),
    ({"previous_question_results": ("wrong",)}, "independent_retest_correct"),
    ({"previous_question_results": ("unknown",)}, "independent_retest_correct"),
    ({"history_unknown": True}, "independent_correct_history_unknown"),
    ({"confidence": "guess"}, "low_confidence_correct"),
    ({"confidence": "no_idea"}, "low_confidence_correct"),
    ({"result": "wrong", "assistance": "solution"}, "incorrect"),
    ({"result": "unknown"}, "unable_to_grade"),
    ({"verified": False}, "unable_to_grade"),
])
def test_sequence_categories(args, expected):
    defaults = dict(result="right", verified=True, assistance="none", confidence=None)
    assert classify_attempt_sequence(**(defaults | args)) == expected


@pytest.mark.parametrize("category", sorted(NON_CONFIRMING_CORRECT))
def test_nonindependent_success_is_not_a_mastery_confirmation(category):
    evidence = classify_objective_evidence(result="right", verified=True, assisted=False,
        question_id="q", is_variant=False, occurred_at=datetime.now(timezone.utc),
        question_type="fill_blank", sequence_category=category)
    assert evidence.level == EvidenceLevel.PARTIAL


@pytest.mark.parametrize("category", ["first_independent_correct", "repeat_correct", "independent_retest_correct"])
def test_observed_fresh_success_can_confirm_with_existing_deduplication(category):
    evidence = classify_objective_evidence(result="right", verified=True, assisted=False,
        question_id="q", is_variant=False, occurred_at=datetime.now(timezone.utc),
        question_type="fill_blank", sequence_category=category)
    assert evidence.level == EvidenceLevel.CONFIRMED
