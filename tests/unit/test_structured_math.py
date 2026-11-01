"""结构化数学契约错误注入：10 类不应被误判 verified 的情况。"""
from __future__ import annotations

import pytest

from backend.services.structured_math import verify_structured

STEM_LIMIT = r"求 \lim_{x\to 0}\frac{\sin(2x)}{x} 的值。"
OPTIONS = {"A": "2", "B": "1", "C": "0", "D": "不存在"}


def test_consistent_limit_structure_verifies():
    result = verify_structured(STEM_LIMIT, {
        "kind": "limit", "limit_point": 0, "mathematical_expression": r"\frac{\sin(2x)}{x}",
        "limit_direction": "both"}, OPTIONS, "A")
    assert result["status"] == "verified"


def test_expression_stem_mismatch_is_rejected():
    result = verify_structured(STEM_LIMIT, {
        "kind": "limit", "limit_point": 0,
        "mathematical_expression": r"\frac{\sin(3x)}{x}", "limit_direction": "both"}, OPTIONS, "A")
    assert result["status"] == "rejected"
    assert result["reason"] in {"expression_stem_mismatch", "answer_mismatch"}


def test_second_derivative_request_but_first_order_structure():
    stem = "设 f(x)=x^4，求 f''(2)。"
    result = verify_structured(stem, {
        "kind": "derivative", "function_expression": "x^4", "derivative_order": 1,
        "evaluation_point": 2}, {"A": "32", "B": "48"}, "A")
    assert result["status"] == "rejected"
    assert result["reason"] == "derivative_order_mismatch"


def test_right_limit_without_direction_in_stem():
    stem = r"求 \lim_{x\to 0}\frac{\sin x}{x} 的值。"
    result = verify_structured(stem, {
        "kind": "limit", "limit_point": 0, "mathematical_expression": r"\frac{\sin x}{x}",
        "limit_direction": "right"}, {"A": "1"}, "A")
    assert result["status"] == "rejected"
    assert result["reason"] == "limit_direction_mismatch"


def test_reversed_integration_bounds():
    stem = r"求 \int_1^0 x^2 dx 的值。"
    result = verify_structured(stem, {
        "kind": "integral", "integrand": "x^2", "integration_bounds": [1, 0]},
        {"A": "1/3"}, "A")
    assert result["status"] == "rejected"
    assert result["reason"] == "integration_bounds_reversed"


def test_tangent_line_is_needs_review():
    stem = "由方程 x^2+xy+y^2=3 确定 y=y(x)，求 (1,1) 处切线方程。"
    result = verify_structured(stem, {
        "kind": "derivative", "function_expression": "x^2+xy+y^2=3", "derivative_order": 1,
        "evaluation_point": [1, 1], "task": "tangent_line"}, {"A": "y=-x+2"}, "A")
    assert result["status"] == "needs_review"
    assert result["reason"] == "tangent_line_not_supported"


def test_answer_letter_mismatch_is_rejected():
    stem = r"求 \lim_{x\to 0}\frac{\sin(2x)}{x} 的值。"
    result = verify_structured(stem, {
        "kind": "limit", "limit_point": 0, "mathematical_expression": r"\frac{\sin(2x)}{x}",
        "limit_direction": "both"}, OPTIONS, "B")
    assert result["status"] == "rejected"
    assert result["reason"] == "answer_mismatch"


def test_multiple_equivalent_options_are_rejected():
    stem = r"求 \lim_{x\to 0}\frac{\sin x}{x} 的值。"
    result = verify_structured(stem, {
        "kind": "limit", "limit_point": 0, "mathematical_expression": r"\frac{\sin x}{x}",
        "limit_direction": "both"}, {"A": "1", "B": "1.0"}, "A")
    assert result["status"] == "rejected"
    assert result["reason"] == "multiple_equivalent_options"


def test_incomplete_contract_is_needs_review():
    result = verify_structured(STEM_LIMIT, {"kind": "limit"}, OPTIONS, "A")
    assert result["status"] == "needs_review"


def test_matrix_dimension_mismatch_is_not_verified():
    stem = "求矩阵 [[1,2],[3,4]] 的行列式。"
    result = verify_structured(stem, {"kind": "determinant", "mathematical_expression": "[[1,2,3],[4,5,6]]"},
                               {"A": "-2"}, "A")
    assert result["status"] != "verified"


@pytest.mark.parametrize("coefficient", [1, 3, 4, 5, 6, 7, 8])
def test_changed_expression_coefficient_is_rejected(coefficient):
    stem = r"求 \lim_{x\to 0}\frac{\sin(2x)}{x} 的值。"
    result = verify_structured(stem, {
        "kind": "limit", "limit_point": 0,
        "mathematical_expression": rf"\frac{{\sin({coefficient}x)}}{{x}}", "limit_direction": "both"},
        OPTIONS, "A")
    assert result["status"] != "verified"


@pytest.mark.parametrize("point", [1, 2, 3, 4])
def test_changed_limit_point_is_rejected(point):
    stem = r"求 \lim_{x\to 0}\frac{\sin(2x)}{x} 的值。"
    result = verify_structured(stem, {
        "kind": "limit", "limit_point": point,
        "mathematical_expression": r"\frac{\sin(2x)}{x}", "limit_direction": "both"},
        OPTIONS, "A")
    assert result["status"] != "verified"


@pytest.mark.parametrize("order", [2, 3])
def test_changed_derivative_order_is_rejected(order):
    stem = "设 f(x)=x^4，求 f'(2)。"
    result = verify_structured(stem, {
        "kind": "derivative", "function_expression": "x^4", "derivative_order": order,
        "evaluation_point": 2}, {"A": "32", "B": "48"}, "A")
    assert result["status"] == "rejected"


@pytest.mark.parametrize("bounds", [[1, 0], [2, 1], [3, 2], [5, 4]])
def test_reversed_bounds_variants_are_rejected(bounds):
    stem = rf"求 \int_{{{bounds[0]}}}^{{{bounds[1]}}} x^2 dx 的值。"
    result = verify_structured(stem, {
        "kind": "integral", "integrand": "x^2", "integration_bounds": bounds}, {"A": "1"}, "A")
    assert result["status"] == "rejected"


@pytest.mark.parametrize("answer", ["B", "C", "D"])
def test_wrong_answer_letters_are_rejected(answer):
    stem = r"求 \lim_{x\to 0}\frac{\sin(2x)}{x} 的值。"
    result = verify_structured(stem, {
        "kind": "limit", "limit_point": 0, "mathematical_expression": r"\frac{\sin(2x)}{x}",
        "limit_direction": "both"}, OPTIONS, answer)
    assert result["status"] == "rejected"

