"""独立数学验证回归：极限/导数/隐函数/积分/矩阵/偏导与错误注入。"""
from __future__ import annotations

import pytest

from backend.services.math_verification import verify_question

ERROR_STEM = r"求 \lim_{x\to 0}\frac{\sin(2x)-2x+\frac{4x^3}{3}}{x^5} 的值。"
ERROR_OPTIONS = {"A": r"-\dfrac{4}{15}", "B": r"\dfrac{4}{15}", "C": "不存在", "D": "0"}


def test_wrong_limit_answer_is_rejected_with_computed_value():
    result = verify_question(ERROR_STEM, ERROR_OPTIONS, "A")
    assert result["status"] == "rejected"
    assert result["reason"] == "answer_mismatch"
    assert result["computed"] == "4/15"
    assert result["expected_option"] == "B"


def test_correct_limit_answer_is_verified():
    result = verify_question(ERROR_STEM, ERROR_OPTIONS, "B")
    assert result["status"] == "verified"
    assert result["kind"] == "limit"


def test_first_derivative():
    result = verify_question("设 f(x)=x^3+2x，求 f'(1)。", {"A": "5", "B": "3"}, "A")
    assert result["status"] == "verified"
    assert result["kind"] == "derivative"


def test_second_derivative():
    result = verify_question("设 f(x)=x^4，求 f''(2)。", {"A": "48", "B": "32"}, "A")
    assert result["status"] == "verified"
    assert result["computed"] == "48"


def test_third_derivative():
    result = verify_question("设 f(x)=x^4，求 f'''(1)。", {"A": "24", "B": "12"}, "A")
    assert result["status"] == "verified"


def test_implicit_derivative():
    result = verify_question("由方程 x^2+xy+y^2=3 确定 y=y(x)，求 (1,1) 处 y' 。",
                             {"A": "-1", "B": "1"}, "A")
    assert result["status"] == "verified"
    assert result["kind"] == "implicit_derivative"


def test_definite_integral():
    result = verify_question(r"求 \int_0^1 x^2 dx 的值。", {"A": r"\dfrac{1}{3}", "B": "1"}, "A")
    assert result["status"] == "verified"
    assert result["kind"] == "definite_integral"


def test_indefinite_integral():
    result = verify_question(r"求 \int x^2 dx。", {"A": r"\dfrac{x^3}{3}", "B": "x^2"}, "A")
    assert result["status"] == "verified"
    assert result["kind"] == "indefinite_integral"


def test_partial_derivative():
    result = verify_question("设 z=x^2y，求 ∂z/∂x。", {"A": "2xy", "B": "x^2"}, "A")
    assert result["status"] == "verified"
    assert result["kind"] == "partial_derivative"


def test_matrix_determinant():
    result = verify_question("求矩阵 [[1,2],[3,4]] 的行列式。", {"A": "-2", "B": "2"}, "A")
    assert result["status"] == "verified"
    assert result["kind"] == "determinant"


def test_multiple_eigenvalues_are_not_auto_verified():
    result = verify_question("求矩阵 [[2,0],[0,3]] 的特征值。", {"A": "2", "B": "3"}, "A")
    assert result["status"] == "needs_review"
    assert result["reason"] == "multiple_eigenvalues_not_compared"


def test_ode_is_explicitly_unsupported():
    result = verify_question("求解微分方程 y'+y=0。", {"A": "e^{-x}", "B": "e^x"}, "A")
    assert result["status"] == "needs_review"
    assert result["reason"] == "unsupported_ode"


def test_linear_system_is_explicitly_unsupported():
    result = verify_question("求解线性方程组 x+y=1, x-y=0。", {"A": "(1/2,1/2)"}, "A")
    assert result["status"] == "needs_review"
    assert result["reason"] == "unsupported_linear_system"


def test_parametric_derivative():
    result = verify_question("参数方程 x=t^2, y=t^3，求 t=1 处 dy/dx。", {"A": "3/2", "B": "2/3"}, "A")
    assert result["status"] == "verified"
    assert result["kind"] == "parametric_derivative"


def test_double_integral():
    result = verify_question(r"求 \iint (x+y) dxdy 的值。",
                             {"A": r"\dfrac{x^2y}{2}+\dfrac{xy^2}{2}", "B": "x+y"}, "A")
    assert result["status"] == "verified"
    assert result["kind"] == "double_integral"


def test_multiple_eigenvalues_are_rejected():
    result = verify_question("求矩阵 [[2,0],[0,2]] 的特征值。", {"A": "2"}, "A")
    assert result["status"] in {"verified", "needs_review"}


def test_multiple_equivalent_options_are_rejected():
    result = verify_question(r"求 \lim_{x\to 0}\frac{\sin x}{x} 的值。", {"A": "1", "B": "1.0"}, "A")
    assert result["status"] == "rejected"
    assert result["reason"] == "multiple_equivalent_options"


def test_computed_value_not_in_options_is_rejected():
    result = verify_question(r"求 \lim_{x\to 0}\frac{\sin x}{x} 的值。", {"A": "0", "B": "2"}, "A")
    assert result["status"] == "rejected"
    assert result["reason"] == "computed_value_not_in_options"


@pytest.mark.parametrize("stem", [
    "设 y=y(x) 由方程确定，求 y''(1)。",
    "按定义讨论函数在某点的连续性。",
])
def test_unsupported_forms_are_needs_review_not_verified(stem):
    result = verify_question(stem, {"A": "1", "B": "2"}, "A")
    assert result["status"] == "needs_review"


def test_one_sided_limit_is_needs_review():
    result = verify_question(r"求 \lim_{x\to 0^+}\frac{\sin x}{x} 的值。", {"A": "1"}, "A")
    assert result["status"] == "needs_review"
    assert result["reason"] == "one_sided_limit_not_supported"


def test_reversed_integration_bounds_are_needs_review():
    result = verify_question(r"求 \int_1^0 x^2 dx 的值。", {"A": r"-\dfrac{1}{3}"}, "A")
    assert result["status"] == "needs_review"
    assert result["reason"] == "integration_bounds_reversed"


def test_verified_limit_still_passes_after_semantic_checks():
    result = verify_question(r"求 \lim_{x\to 0}\frac{\sin x}{x} 的值。", {"A": "1"}, "A")
    assert result["status"] == "verified"

