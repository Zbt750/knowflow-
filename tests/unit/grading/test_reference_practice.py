import pytest
from backend.services.answer_grading import grade_practice_final_answer, available_grading_method
from backend.services.constant_expression import constant_expression, compare_constant_expressions

CONFIG = {"verified": False, "method": None, "provenance": {
    "content_status": "source_transcribed", "source": {"source_type": "exam"}}}


@pytest.mark.parametrize("answer,expected,result", [
    ("-2pi", r"$-2\pi$", "right"), ("-pi", r"$-2\pi$", "wrong"),
    ("sqrt(2)/2", r"$\frac{\sqrt{2}}{2}$", "right"),
    ("1/sqrt(2)", "sqrt(2)/2", "right"), ("e", "$e$", "right"),
    ("0.5", "1/2", "right"), ("x/x", "1", "unknown"),
    ("sqrt(-1)", "1", "unknown"), ("1/0", "1", "unknown"),
])
def test_bounded_constant_comparison(answer, expected, result):
    assert compare_constant_expressions(answer, expected) == result


@pytest.mark.parametrize("text", ["__import__('os').system('whoami')", "pi.__class__", "10**1000000",
    "(999999999999**6)**6", "sqrt(x)", "[1,2]", "2j", "1e100", "sqrt(2,3)", "True", "0**-1"])
def test_expression_parser_rejects_code_and_unbounded_inputs(text):
    assert constant_expression(text) is None


@pytest.mark.parametrize("chosen,result", [("A", "right"), ("B", "wrong"), ("X", "unknown")])
def test_practice_choice_uses_key_without_claiming_verified(chosen, result):
    verdict = grade_practice_final_answer(question_type="single_choice", config=CONFIG,
        answer=None, selected_option=chosen, expected="A", options={"A": "甲", "B": "乙"})
    assert verdict.result == result
    assert verdict.method == "reference_single_choice_v1"
    assert available_grading_method(question_type="single_choice", config=CONFIG,
        expected="A", options={"A": "甲", "B": "乙"}) is None
    assert CONFIG["verified"] is False and CONFIG["method"] is None
