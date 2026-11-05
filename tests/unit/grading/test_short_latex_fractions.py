"""Bounded TeX formatting support, not a symbolic equivalence evaluator."""
import pytest
from backend.services.answer_grading import available_grading_method, grade_numeric_final_answer


@pytest.mark.parametrize("answer", [r"\frac14", r"$-\frac14$", r"\dfrac 1 4", r"\tfrac14", r"+\frac14"])
def test_single_digit_fraction_exactly_compares(answer):
    expected = "-1/4" if "-" in answer else "1/4"
    assert grade_numeric_final_answer(answer=answer, expected=expected, verified=True).result == "right"
    assert grade_numeric_final_answer(answer=expected, expected=answer, verified=True).result == "right"


@pytest.mark.parametrize("answer", [r"\frac10", r"\frac123", r"\frac1x", r"\frac-14", r"\frac14+1", r"\frac14x", r"\frac{1}4", r"\frac١٤"])
def test_ambiguous_or_unsupported_short_fractions_stay_unknown(answer):
    assert grade_numeric_final_answer(answer=answer, expected="1/4", verified=True).result == "unknown"


def test_short_fraction_does_not_bypass_review_or_use_approximation():
    assert grade_numeric_final_answer(answer=r"\frac13", expected="1/3", verified=False).reason == "answer_not_verified"
    assert grade_numeric_final_answer(answer="0.333", expected=r"\frac13", verified=True).result == "wrong"
    assert available_grading_method(question_type="fill_blank", config={"verified": False, "method": "numeric_final"},
        expected=r"$-\frac14$", options=None) is None
