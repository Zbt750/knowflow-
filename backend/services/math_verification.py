"""独立数学验证：用 SymPy 确定性计算，不调用 LLM 自评。

支持极限、导数（一阶/二阶/高阶）、隐函数求导、定积分、不定积分、
多元偏导、矩阵行列式/特征值/逆。无法可靠解析时返回 needs_review，
绝不把“未验证”当成“已验证”；rejected 表示独立计算明确判定错误。
"""
from __future__ import annotations

import re

from sympy import (
    E,
    Matrix,
    diff,
    integrate,
    limit,
    simplify,
    symbols,
)
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

X, Y, Z, T = symbols("x y z t")
TRANSFORMS = standard_transformations + (implicit_multiplication_application,)
LOCALS = {"x": X, "y": Y, "z": Z, "t": T, "e": E}


def _normalize(text: str) -> str:
    value = str(text or "")
    value = value.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    for _ in range(6):
        replaced = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", value)
        if replaced == value:
            break
        value = replaced
    value = re.sub(r"\\(sin|cos|tan|cot|sec|csc|ln|exp|log|sqrt|arcsin|arccos|arctan)\s+([a-zA-Z0-9])",
                   r"\\\1(\2)", value)
    value = re.sub(r"\\left|\\right|\\displaystyle|\\,|\\;|\\!|\\ ", "", value)
    # Markdown/LaTeX 行内与行间定界符不是数学表达式的一部分。
    value = value.replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
    value = value.replace("$", "")
    value = re.sub(r"\\(sin|cos|tan|cot|sec|csc|ln|exp|log|sqrt|arcsin|arccos|arctan)",
                   lambda m: {"ln": "log"}.get(m.group(1), m.group(1)), value)
    value = value.replace("^", "**").replace("{", "(").replace("}", ")")
    value = value.replace("→", "->").replace("−", "-").replace("·", "*").replace("×", "*")
    return re.sub(r"\s+", "", value)


def _parse(text: str, extra: dict | None = None):
    normalized = _normalize(text)
    if not normalized:
        return None
    try:
        return parse_expr(normalized, local_dict={**LOCALS, **(extra or {})}, transformations=TRANSFORMS)
    except Exception:
        return None


def _option_value(value):
    text = re.sub(r"^[A-H][\.、\):：]\s*", "", str(value or ""))
    text = re.sub(r"\+?\s*[Cc]\s*$", "", text)
    return _parse(text)


def _finish(computed, options, correct_answer, kind: str) -> dict:
    matches = []
    if isinstance(options, dict):
        for key, value in options.items():
            parsed = _option_value(value)
            if parsed is None:
                continue
            try:
                if simplify(parsed - computed) == 0:
                    matches.append(str(key))
            except Exception:
                continue
    result = {"engine": "sympy", "kind": kind, "computed": str(computed), "matches": matches}
    if len(matches) == 1:
        if str(correct_answer) == matches[0]:
            result["status"] = "verified"
        else:
            result.update(status="rejected", reason="answer_mismatch", expected_option=matches[0])
    elif len(matches) > 1:
        result.update(status="rejected", reason="multiple_equivalent_options")
    else:
        result.update(status="rejected", reason="computed_value_not_in_options")
    return result


def _needs_review(reason: str, kind: str) -> dict:
    return {"status": "needs_review", "engine": "sympy", "kind": kind, "reason": reason}


def _verify_limit(stem: str, options, answer) -> dict | None:
    match = re.search(r"\\lim_\{x\\to\s*([^}]+)\}|lim\s*\[\s*x\s*(?:->|→)\s*([^\]]+)\]", stem)
    if not match:
        return None
    point = _parse(match.group(1) or match.group(2))
    rest = re.split(r"[，,。；;]", stem[match.end():])[0]
    rest = re.sub(r"(?:的值为?|等于|的值是?|结果是?)\s*$", "", rest)
    expression = _parse(rest)
    if point is None or expression is None:
        return _needs_review("unparseable_expression", "limit")
    try:
        return _finish(limit(expression, X, point), options, answer, "limit")
    except Exception as exc:  # noqa: BLE001
        return _needs_review(type(exc).__name__, "limit")


def _verify_derivative(stem: str, options, answer) -> dict | None:
    definition = re.search(r"(?:设|已知|函数)?\s*f\s*\(\s*x\s*\)\s*=\s*([^，,。;]+)", stem)
    target = re.search(r"f\s*('{1,3})\s*\(\s*(-?\d+(?:\.\d+)?)\s*\)", stem)
    if not definition or not target:
        return None
    expression = _parse(definition.group(1))
    point = _parse(target.group(2))
    if expression is None or point is None:
        return _needs_review("unparseable_expression", "derivative")
    order = len(target.group(1))
    try:
        value = diff(expression, X, order).subs(X, point)
    except Exception as exc:  # noqa: BLE001
        return _needs_review(type(exc).__name__, "derivative")
    return _finish(value, options, answer, "derivative")


def _verify_implicit(stem: str, options, answer) -> dict | None:
    relation = (re.search(r"(?:由)?方程\s*([^，,。;]*?)\s*(?:确定|所确定)", stem)
                or re.search(r"曲线\s*([^，,。;]*?)\s*(?:确定|所确定)", stem))
    if not relation:
        return None
    if re.search(r"切线方程|法线方程|切线为|法线为", stem):
        return _needs_review("tangent_line_equation_not_supported", "implicit")
    expression_text = re.sub(r"^(?:由)?方程", "", relation.group(1)).strip()
    parts = expression_text.split("=")
    if len(parts) != 2:
        return _needs_review("implicit_relation_not_two_sided", "implicit")
    expression = _parse(f"({parts[0]})-({parts[1]})")
    if expression is None:
        return _needs_review("unparseable_expression", "implicit")
    point = re.search(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)", stem)
    if not point:
        return _needs_review("implicit_point_missing", "implicit")
    try:
        derivative = diff(expression, X) * -1 / diff(expression, Y)
        value = derivative.subs({X: _parse(point.group(1)), Y: _parse(point.group(2))})
        if re.search(r"y''|二阶|二阶导", stem):
            value = diff(derivative, X).subs({X: _parse(point.group(1)), Y: _parse(point.group(2))})
    except Exception as exc:  # noqa: BLE001
        return _needs_review(type(exc).__name__, "implicit")
    return _finish(value, options, answer, "implicit_derivative")


def _verify_integral(stem: str, options, answer) -> dict | None:
    if not re.search(r"∫|\\int", stem):
        return None
    bounds = re.search(r"(?:∫|\\int)\s*_\{?([-\w.^]+)\}?\s*\^\{?([-\w.^]+)\}?", stem)
    body = re.split(r"(?:∫|\\int)", stem)[-1]
    body = re.sub(r"^_\{?[-\w.^]+\}?\s*\^\{?[-\w.^]+\}?", "", body)
    body = re.split(r"d\s*x|dx", body)[0]
    expression = _parse(body)
    if expression is None:
        return _needs_review("unparseable_expression", "integral")
    try:
        if bounds:
            value = integrate(expression, (X, _parse(bounds.group(1)), _parse(bounds.group(2))))
            kind = "definite_integral"
        else:
            value = integrate(expression, X)
            kind = "indefinite_integral"
    except Exception as exc:  # noqa: BLE001
        return _needs_review(type(exc).__name__, "integral")
    return _finish(value, options, answer, kind)


def _parse_matrix(stem: str):
    bracket = re.search(r"\[\s*\[.*?\]\s*\]", stem)
    if bracket:
        rows = re.findall(r"\[([^\[\]]+)\]", bracket.group(0))
        try:
            return Matrix([[float(_parse(v)) for v in re.split(r"[, ]+", row.strip()) if v] for row in rows])
        except Exception:
            return None
    return None


def _verify_matrix(stem: str, options, answer) -> dict | None:
    matrix = _parse_matrix(stem)
    if matrix is None:
        return None
    try:
        if re.search(r"行列式|det", stem, re.I):
            return _finish(matrix.det(), options, answer, "determinant")
        if re.search(r"特征值|eigen", stem, re.I):
            values = sorted(matrix.eigenvals().keys(), key=str)
            if len(values) == 1:
                return _finish(values[0], options, answer, "eigenvalue")
            return _needs_review("multiple_eigenvalues_not_compared", "eigenvalue")
        if re.search(r"逆矩阵|求逆|inverse", stem, re.I):
            return _needs_review("matrix_expression_preview", "matrix_inverse")
    except Exception as exc:  # noqa: BLE001
        return _needs_review(type(exc).__name__, "matrix")
    return None


def _verify_partial(stem: str, options, answer) -> dict | None:
    definition = re.search(r"z\s*=\s*([^，,。;]+)", stem)
    target = re.search(r"∂\s*z\s*/\s*∂\s*([xyz])|z\s*_\s*([xyz])", stem)
    if not definition or not target:
        return None
    expression = _parse(definition.group(1))
    variable = target.group(1) or target.group(2)
    if expression is None:
        return _needs_review("unparseable_expression", "partial_derivative")
    try:
        value = diff(expression, {"x": X, "y": Y, "z": Z}[variable])
    except Exception as exc:  # noqa: BLE001
        return _needs_review(type(exc).__name__, "partial_derivative")
    return _finish(value, options, answer, "partial_derivative")


def _verify_parametric(stem: str, options, answer) -> dict | None:
    if not re.search(r"参数方程|dy/dx|d\^2y/dx\^2", stem):
        return None
    x_match = re.search(r"x\s*=\s*([^,，;。]+)", stem)
    y_match = re.search(r"y\s*=\s*([^,，;。]+)", stem)
    if not x_match or not y_match:
        return None
    xt, yt = _parse(x_match.group(1)), _parse(y_match.group(1))
    if xt is None or yt is None:
        return _needs_review("unparseable_expression", "parametric_derivative")
    try:
        value = diff(yt, T) / diff(xt, T)
        point = re.search(r"t\s*=\s*(-?\d+(?:\.\d+)?)", stem)
        if point:
            value = value.subs(T, _parse(point.group(1)))
    except Exception as exc:  # noqa: BLE001
        return _needs_review(type(exc).__name__, "parametric_derivative")
    return _finish(value, options, answer, "parametric_derivative")


def _verify_multiple_integral(stem: str, options, answer) -> dict | None:
    if not re.search(r"∫∫|\\iint", stem):
        return None
    body = re.split(r"∫∫|\\iint", stem)[-1]
    body = re.split(r"d\s*x\s*d\s*y|dxdy", body)[0]
    expression = _parse(body)
    if expression is None:
        return _needs_review("unparseable_expression", "double_integral")
    try:
        value = integrate(integrate(expression, X), Y)
    except Exception as exc:  # noqa: BLE001
        return _needs_review(type(exc).__name__, "double_integral")
    return _finish(value, options, answer, "double_integral")


DETECTORS = (_verify_limit, _verify_derivative, _verify_implicit, _verify_integral,
             _verify_parametric, _verify_multiple_integral, _verify_matrix, _verify_partial)


def verify_question(stem: str, options, correct_answer) -> dict:
    text = str(stem or "")
    # 语义前置检查：单侧极限/上下限倒置不能被当成普通双侧极限或定积分。
    if re.search(r"左极限|右极限|0\s*\^?\s*[+-]|x\s*→\s*\d+\s*\^?\s*[+-]|x\\to\s*\d+\s*\^?\s*[+-]", text):
        return {"status": "needs_review", "engine": "sympy", "kind": "limit",
                "reason": "one_sided_limit_not_supported"}
    bounds = re.search(r"(?:∫|\\int)\s*_\{?([-\d.]+)\}?\s*\^\{?([-\d.]+)\}?", text)
    if bounds:
        try:
            if float(bounds.group(1)) > float(bounds.group(2)):
                return {"status": "needs_review", "engine": "sympy", "kind": "integral",
                        "reason": "integration_bounds_reversed"}
        except ValueError:
            pass
    tested = []
    for detector in DETECTORS:
        try:
            result = detector(text, options, correct_answer)
        except Exception as exc:  # noqa: BLE001
            tested.append(f"{detector.__name__}:{type(exc).__name__}")
            continue
        if result is not None:
            result["verifier"] = detector.__name__
            return result
    if re.search(r"微分方程|y'\s*[+\-=]|y''", text):
        return {"status": "needs_review", "engine": "sympy", "kind": "ode",
                "reason": "unsupported_ode", "tested": tested}
    if re.search(r"线性方程组|方程组", text):
        return {"status": "needs_review", "engine": "sympy", "kind": "linear_system",
                "reason": "unsupported_linear_system", "tested": tested}
    return {"status": "needs_review", "engine": "sympy",
            "reason": "unsupported_expression", "tested": tested}


def verify_versions(questions) -> dict:
    output = {}
    for question in questions:
        output[str(getattr(question, "id", ""))] = verify_question(
            getattr(question, "stem", ""), getattr(question, "options", None),
            getattr(question, "correct_answer", None))
    return output
