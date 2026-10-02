"""P2 observed attempt categories, not a claim of proctored independence."""
from typing import Literal

AssistanceLevel = Literal["none", "hint_1", "hint_2", "process_review", "solution"]
AttemptCategory = Literal[
    "first_independent_correct", "self_corrected", "correct_after_ungraded",
    "hint_assisted_correct", "solution_assisted_correct", "process_review_assisted_correct",
    "repeat_correct", "independent_retest_correct", "independent_correct_history_unknown",
    "low_confidence_correct", "incorrect", "unable_to_grade",
]

# Immediate correction after binary feedback cannot supply a new independent
# mastery confirmation. Later fresh-item retests still deduplicate by question.
NON_CONFIRMING_CORRECT = frozenset({
    "self_corrected", "correct_after_ungraded", "hint_assisted_correct",
    "solution_assisted_correct", "process_review_assisted_correct",
    "independent_correct_history_unknown", "low_confidence_correct",
})


def classify_attempt_sequence(*, result: str, verified: bool,
        assistance: AssistanceLevel, confidence: str | None,
        same_item_results: tuple[str, ...] = (), previous_question_results: tuple[str, ...] = (),
        history_unknown: bool = False) -> AttemptCategory:
    if not verified or result not in {"right", "wrong"}:
        return "unable_to_grade"
    if result == "wrong":
        return "incorrect"
    if assistance == "solution": return "solution_assisted_correct"
    if assistance == "process_review": return "process_review_assisted_correct"
    if assistance in {"hint_1", "hint_2"}: return "hint_assisted_correct"
    if confidence in {"guess", "no_idea"}: return "low_confidence_correct"
    if "wrong" in same_item_results: return "self_corrected"
    if same_item_results: return "correct_after_ungraded"
    if history_unknown: return "independent_correct_history_unknown"
    if "right" in previous_question_results: return "repeat_correct"
    if previous_question_results: return "independent_retest_correct"
    return "first_independent_correct"
