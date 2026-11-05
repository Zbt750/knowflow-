from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.phase45hs_verifiers import problem, explanation

PACK = Path(__file__).resolve().parents[2] / "storage/question-intake/phase45hx-20261010/phase45hx-math2-2016-v1.json"


@pytest.mark.skipif(not PACK.exists(), reason="Private source payload not distributed")
@pytest.mark.parametrize("index", range(3))
def test_transcribed_math_and_wrong_or_ambiguous_candidates(index):
    row = json.loads(PACK.read_text(encoding="utf-8"))["questions"][index]
    q = SimpleNamespace(**{key: row[key] for key in ("stem", "question_type", "options", "correct_answer")})
    verified = problem(q)
    assert verified["status"] == "PASS", verified
    assert len(explanation(q, verified)[0]) > 50
    wrong = deepcopy(q)
    wrong.correct_answer = next(key for key in q.options if key != q.correct_answer)
    assert problem(wrong)["status"] == "FAIL"
    ambiguous = deepcopy(q)
    other = next(key for key in q.options if key != q.correct_answer)
    ambiguous.options[other] = q.options[q.correct_answer]
    assert problem(ambiguous)["status"] == "FAIL"
    changed = deepcopy(q)
    changed.stem += "并且满足另一未给出的条件。"
    assert problem(changed) is None


def inverse_question(k):
    return SimpleNamespace(question_type="single_choice", correct_answer="B" if k > 0 else "C",
        options={"A": "①收敛，②收敛", "B": "①收敛，②发散", "C": "①发散，②收敛", "D": "①发散，②发散"},
        stem=(rf"反常积分 ① $\int_{{-\infty}}^{{0}}\frac{{1}}{{x^2}}e^{{{k}/x}}\,dx$，"
              rf"② $\int_{{0}}^{{+\infty}}\frac{{1}}{{x^2}}e^{{{k}/x}}\,dx$ 的敛散性为（）。"))


@pytest.mark.parametrize("k", [-7, -2, -1, 1, 2, 7])
def test_unseen_inverse_exponential_coefficients_and_one_sided_endpoints(k):
    q = inverse_question(k)
    result = problem(q)
    assert result["status"] == "PASS"
    assert result["proof"]["convergent"] == [k > 0, k < 0]
    assert result["proof"]["primitive_derivative_checked"]
    assert result["proof"]["integral_values"][0 if k > 0 else 1] == str(Fraction(1, abs(k)))
    q.correct_answer = "A"
    assert problem(q)["status"] == "FAIL"


def test_changed_integrands_and_out_of_scope_coefficients_are_not_accepted():
    assert problem(inverse_question(0))["status"] == "UNKNOWN"
    assert problem(inverse_question(21))["status"] == "UNKNOWN"
    q = inverse_question(2)
    q.stem = q.stem.replace("e^{2/x}", "e^{3/x}", 1)
    assert problem(q)["status"] == "UNKNOWN"
    q = inverse_question(2)
    q.stem = q.stem.replace("x^2", "x^3")
    assert problem(q) is None
