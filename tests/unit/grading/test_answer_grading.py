import pytest

from backend.services.answer_grading import grade_numeric_final_answer


@pytest.mark.parametrize("answer,expected,result", [
    ("0.5", "1/2", "right"), ("−2", "-2.0", "right"),
    ("2/4", "0.5", "right"), ("0.333", "1/3", "wrong"),
    ("2", "3", "wrong"), ("", "2", "unknown"),
    ("1/0", "2", "unknown"), ("sqrt(4)", "2", "unknown"),
    ("2 cm", "2", "unknown"), ("x=2", "2", "unknown"),
    ("__import__('os').system('echo unsafe')", "2", "unknown"),
    ("2", "x+1", "unknown"), ("9" * 129, "2", "unknown"),
])
def test_numeric_answer_boundaries(answer, expected, result):
    assert grade_numeric_final_answer(answer=answer, expected=expected, verified=True).result == result


def test_unverified_answer_never_graded():
    verdict = grade_numeric_final_answer(answer="2", expected="2", verified=False)
    assert verdict.result == "unknown"
    assert verdict.reason == "answer_not_verified"
