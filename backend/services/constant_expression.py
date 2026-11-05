"""Bounded constant arithmetic, built from AST nodes without eval/parse_expr.

Only rational numbers, pi, e, sqrt and arithmetic are supported. Variables,
conditions, units, matrices and multi-part answers are deliberately excluded.
"""
import ast
import re
from functools import lru_cache
from sympy import E, pi, Rational, sqrt, simplify


def constant_expression(text: str | None):
    if type(text) is str and len(text) <= 160:
        return _cached_constant_expression(text)
    return _compute_constant_expression(text)


@lru_cache(maxsize=8192)
def _cached_constant_expression(text: str):
    # SymPy expressions are immutable; the full input string is the cache key.
    return _compute_constant_expression(text)


def _compute_constant_expression(text: str | None):
    if not text or len(text) > 160:
        return None
    value = text.strip().replace("−", "-").replace("π", "pi")
    if value.startswith("$") and value.endswith("$"):
        value = value[1:-1]
    for latex, plain in ((r"\left", ""), (r"\right", ""), (r"\pi", "pi"),
                         (r"\cdot", "*"), (r"\times", "*")):
        value = value.replace(latex, plain)
    # Expand innermost TeX groups; bounded nesting, no executable parser.
    for _ in range(6):
        prior = value
        value = re.sub(r"\\(?:dfrac|tfrac|frac)\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", value)
        value = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", value)
        value = re.sub(r"\^\{([^{}]+)\}", r"^(\1)", value)
        if prior == value:
            break
    value = value.replace("^", "**")
    value = re.sub(r"(?<=[0-9)])\s*(?=pi\b|e\b|sqrt\(|\()", "*", value)
    value = re.sub(r"(?<=\))\s*(?=[0-9])", "*", value)
    try:
        tree = ast.parse(value.strip(), mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 48:
            return None

        def build(node):
            result = build_node(node)
            if result.is_Rational and (abs(int(result.p)).bit_length() > 256 or int(result.q).bit_length() > 256):
                raise ValueError
            if result.count_ops() > 24:
                raise ValueError
            return result

        def build_node(node):
            if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
                literal = ast.get_source_segment(value.strip(), node)
                if not literal or not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", literal) or len(literal) > 12:
                    raise ValueError
                return Rational(literal)
            if isinstance(node, ast.Name) and node.id in {"pi", "e", "E"}:
                return pi if node.id == "pi" else E
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                result = build(node.operand)
                return result if isinstance(node.op, ast.UAdd) else -result
            if isinstance(node, ast.BinOp):
                left, right = build(node.left), build(node.right)
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
                if isinstance(node.op, ast.Div):
                    if right == 0: raise ValueError
                    return left / right
                if isinstance(node.op, ast.Pow) and right.is_Integer and abs(right) <= 6:
                    if left == 0 and right <= 0: raise ValueError
                    return left ** right
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "sqrt" and len(node.args) == 1 and not node.keywords):
                argument = build(node.args[0])
                if argument.is_nonnegative is not True: raise ValueError
                return sqrt(argument)
            raise ValueError

        result = build(tree.body)
        if result.is_finite is not True or result.count_ops() > 24:
            return None
        return result
    except (ValueError, SyntaxError, TypeError, ZeroDivisionError, OverflowError, RecursionError):
        return None


def compare_constant_expressions(answer: str | None, expected: str | None) -> str:
    actual, target = constant_expression(answer), constant_expression(expected)
    if actual is None or target is None:
        return "unknown"
    difference = simplify(actual - target)
    if difference == 0:
        return "right"
    return "wrong" if difference.is_zero is False else "unknown"
