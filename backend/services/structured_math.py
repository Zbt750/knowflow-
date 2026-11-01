"""结构化数学题契约：校验题干、结构化表达式、选项、答案的一致性。

模型/生成器提供的结构不能自带 verified；这里独立复核：
- 求导阶数、极限方向、积分上下限与题干一致；
- 结构化表达式必须能在题干中定位；
- 用结构化表达式独立计算，再与选项/答案比对。
无法可靠判断时返回 needs_review；明确矛盾返回 rejected。
"""
from __future__ import annotations

import re

from backend.services import math_verification as mv


def _number(value):
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _norm(text: str) -> str:
    return mv._normalize(str(text or "")).replace("*", "")


def _finish(result, kind: str):
    if result is None:
        return {"status": "needs_review", "engine": "structured", "kind": kind,
                "reason": "structured_expression_not_computable"}
    result = dict(result)
    result["engine"] = "structured"
    return result


def verify_structured(stem: str, structure: dict | None, options, correct_answer) -> dict:
    text = str(stem or "")
    structure = structure or {}
    kind = structure.get("kind")
    expression = (structure.get("mathematical_expression") or structure.get("function_expression")
                  or structure.get("integrand"))
    # 1) 求导阶数与题干一致
    order = structure.get("derivative_order")
    if order is not None:
        order = int(order)
        stem_second = bool(re.search(r"f''|y''|二阶导数|二阶导", text))
        if order >= 2 and not stem_second:
            return {"status": "rejected", "engine": "structured", "kind": "derivative",
                    "reason": "derivative_order_mismatch"}
        if order == 1 and stem_second:
            return {"status": "rejected", "engine": "structured", "kind": "derivative",
                    "reason": "derivative_order_mismatch"}
    # 2) 极限方向
    direction = structure.get("limit_direction")
    if direction in {"left", "right"}:
        if not re.search(r"左极限|右极限|\^\s*[+-]", text):
            return {"status": "rejected", "engine": "structured", "kind": "limit",
                    "reason": "limit_direction_mismatch"}
    # 3) 切线/法线题不能只给导数值
    if structure.get("task") in {"tangent_line", "normal_line"}:
        return {"status": "needs_review", "engine": "structured", "kind": "derivative",
                "reason": "tangent_line_not_supported"}
    # 4) 积分上下限
    bounds = structure.get("integration_bounds")
    if bounds:
        if len(bounds) != 2:
            return {"status": "needs_review", "engine": "structured", "kind": "integral",
                    "reason": "integration_bounds_incomplete"}
        low, high = _number(bounds[0]), _number(bounds[1])
        if low is None or high is None:
            return {"status": "needs_review", "engine": "structured", "kind": "integral",
                    "reason": "integration_bounds_unparseable"}
        if low > high:
            return {"status": "rejected", "engine": "structured", "kind": "integral",
                    "reason": "integration_bounds_reversed"}
    # 5) 结构化表达式必须能在题干中定位
    if expression:
        norm_expression = _norm(expression)
        norm_stem = _norm(text)
        if norm_expression and norm_expression not in norm_stem:
            return {"status": "rejected", "engine": "structured", "kind": kind or "expression",
                    "reason": "expression_stem_mismatch"}
    # 6) 用结构化表达式独立计算
    if kind == "limit" and expression is not None:
        point = structure.get("limit_point")
        pseudo = rf"求 \lim_{{x\to {point}}}{expression} 的值。"
        return _finish(mv._verify_limit(pseudo, options, correct_answer), "limit")
    if kind == "derivative" and expression is not None:
        point = structure.get("evaluation_point")
        order = int(order or 1)
        pseudo = f"设 f(x)={expression}，求 f{chr(39) * order}({point})。"
        return _finish(mv._verify_derivative(pseudo, options, correct_answer), "derivative")
    if kind == "integral" and expression is not None:
        if bounds:
            pseudo = rf"求 \int_{{{bounds[0]}}}^{{{bounds[1]}}} {expression} dx 的值。"
            return _finish(mv._verify_integral(pseudo, options, correct_answer), "integral")
        return {"status": "needs_review", "engine": "structured", "kind": "integral",
                "reason": "indefinite_integral_not_supported"}
    return {"status": "needs_review", "engine": "structured", "kind": kind or "unknown",
            "reason": "structured_contract_incomplete"}
