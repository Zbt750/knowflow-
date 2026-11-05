"""Small exact verifiers added from the Phase 4.5I real-output audit.

Every adapter accepts a bounded whole-statement shape. Unsupported variants
remain unsupported; no text is evaluated as Python or SymPy source.
"""
from __future__ import annotations

import re

from backend.services.constant_expression import constant_expression, compare_constant_expressions


def _norm(text: str) -> str:
    value = str(text or "").strip().replace("−", "-").replace("×", "*").replace("·", "*")
    value = value.replace(r"\cdot", "*").replace(r"\times", "*")
    value = value.replace(r"\left", "").replace(r"\right", "")
    value = value.replace(r"\cup", "∪").replace(r"\infty", "∞")
    return re.sub(r"\s+", "", value)


def _integer_representation(value: str):
    """Parse explicitly marked bounded decimal/binary/hex integers only."""
    raw = _norm(value).strip("$").strip("()")
    if len(raw) > 80:
        return None
    sign = -1 if raw.startswith("-") else 1
    unsigned = raw[1:] if raw[:1] in {"+", "-"} else raw
    patterns = ((r"0[bB]([01]+)", 2), (r"([01]+)[bB]", 2), (r"([01]+)₂", 2),
                (r"0[xX]([0-9a-fA-F]+)", 16), (r"([0-9a-fA-F]+)[hH]", 16),
                (r"\d+", 10))
    for pattern, base in patterns:
        match = re.fullmatch(pattern, unsigned)
        if match:
            digits = match.group(1) if match.lastindex else match.group(0)
            try:
                result = sign * int(digits, base)
                return result if abs(result).bit_length() <= 256 else None
            except ValueError:
                return None
    return None


def compare_exact_answer_values(left: str, right: str) -> str:
    """Exact scalar equivalence for bounded numeric, fraction and marked radix forms."""
    comparison = compare_constant_expressions(left, right)
    if comparison != "unknown":
        return comparison
    a, b = _integer_representation(left), _integer_representation(right)
    if a is None or b is None:
        return "unknown"
    return "right" if a == b else "wrong"


def _parse_poly(text: str):
    """Parse a bounded rational polynomial without eval/parse_expr.

    Numeric fractions support exact antiderivative/Taylor claims; arbitrary
    functions, variable denominators and nested symbolic expressions are refused.
    """
    from sympy import Integer, Rational, Symbol

    raw = _norm(text).strip("$").replace("**", "^")
    raw=raw.replace('²','^2').replace('³','^3')
    raw=re.sub(r"\\{1,2}(?:frac|dfrac)\{(\d{1,6})\}\{(\d{1,6})\}",r"\1/\2",raw)
    if raw.startswith("(") and raw.endswith(")") and "(" not in raw[1:-1] and ")" not in raw[1:-1]:
        raw = raw[1:-1]
    raw = re.sub(r"(?<=\d)\*(?=x)", "", raw)
    x = Symbol("x", real=True)
    if not raw or len(raw) > 160:
        return None
    pos, result, terms = 0, Integer(0), 0
    while pos < len(raw):
        sign = 1
        if raw[pos] in "+-":
            sign = -1 if raw[pos] == "-" else 1
            pos += 1
        m = re.match(r"\d+(?:/\d+)?", raw[pos:])
        if m:
            parts=m[0].split('/')
            if any(int(p)>1_000_000 for p in parts) or len(parts)==2 and int(parts[1])==0:return None
            coefficient=Rational(int(parts[0]),int(parts[1]) if len(parts)==2 else 1)
        else:coefficient=Integer(1)
        if m:
            if coefficient > 1_000_000:
                return None
            pos += len(m.group(0))
        has_x = pos < len(raw) and raw[pos] == "x"
        if has_x:
            pos += 1
            exponent = 1
            if pos < len(raw) and raw[pos] == "^":
                m = re.match(r"\^(\d{1,2})", raw[pos:])
                if not m:
                    return None
                exponent = int(m.group(1))
                pos += len(m.group(0))
            if exponent > 12:
                return None
            denominator=re.match(r"/(\d{1,6})",raw[pos:])
            if denominator:
                if not 1<=int(denominator[1])<=1_000_000:return None
                coefficient/=Integer(int(denominator[1]));pos+=len(denominator[0])
            term = coefficient * x**exponent
        else:
            if not m:
                return None
            term = coefficient
        result += sign * term
        terms += 1
        if terms > 16:
            return None
        if pos < len(raw) and raw[pos] not in "+-":
            return None
    return result


def _poly_compare(left: str, right: str) -> str:
    from sympy import simplify

    a, b = _parse_poly(left), _parse_poly(right)
    if a is None or b is None:
        return "unknown"
    delta = simplify(a - b)
    return "right" if delta == 0 else "wrong" if delta.is_zero is False else "unknown"


def _range_pair(value: str):
    raw = _norm(value).strip("$").replace("～", ",").replace("~", ",").replace("至", ",")
    m = re.fullmatch(r"[\[(]([^,]+),([^,]+)[\])]", raw)
    if not m:
        return None
    low, high = constant_expression(m.group(1)), constant_expression(m.group(2))
    if low is None:
        low = _integer_representation(m.group(1))
    if high is None:
        high = _integer_representation(m.group(2))
    if low is None or high is None or low > high:
        return None
    return low, high, raw[0] == "[", raw[-1] == "]"


def _range_stem_bits(compact: str):
    """Recognize only the explicit signed two's-complement range prompt."""
    m = re.fullmatch(
        r"设机器字长为(\d{1,2})位，采用补码表示定点整数，则可表示的十进制整数范围是(?:_{2,}(?:（用闭区间表示）)?|（用闭区间表示）|（(?:)）)[。.]?",
        compact,
    )
    return int(m.group(1)) if m else None


def _interval_set(value: str):
    from sympy import Interval, Union, oo

    raw = _norm(value).strip("$").replace("\u2212", "-")
    parts = raw.split("∪")
    intervals = []
    for part in parts:
        m = re.fullmatch(r"([\[(])([^,]+),([^,]+)([\])])", part)
        if not m:
            return None
        left, right = m.group(2), m.group(3)
        a = -oo if left in {"-∞", "-inf"} else oo if left in {"∞", "+∞", "inf", "+inf"} else constant_expression(left)
        b = -oo if right in {"-∞", "-inf"} else oo if right in {"∞", "+∞", "inf", "+inf"} else constant_expression(right)
        if a is None or b is None:
            return None
        left_open = m.group(1) == "("
        right_open = m.group(4) == ")"
        if a in {-oo, oo} and not left_open or b in {-oo, oo} and not right_open:
            return None
        intervals.append(Interval(a, b, left_open=left_open, right_open=right_open))
    return Union(*intervals)


def _choice_result(q, matches, adapter, proof, option_results=None):
    if option_results is not None and any(result == "unknown" for result in option_results.values()):
        return {"status": "UNKNOWN", "adapter": adapter, "reason": "option_outside_exact_scope", "proof": proof}
    if len(matches) != 1:
        return {"status": "FAIL", "adapter": adapter, "reason": "non_unique_correct_option",
                "matching_options": matches, "proof": proof}
    key = matches[0]
    right = str(q.correct_answer or "").strip().upper() == key
    return {"status": "PASS" if right else "FAIL", "adapter": adapter,
            "reason": "derived_key_matches" if right else "derived_key_conflict",
            "derived_answer": str((q.options or {}).get(key, "")), "derived_key": key,
            "matching_options": matches, "proof": proof}


def _constant_result(q, target, adapter, proof):
    comparison = compare_exact_answer_values(str(q.correct_answer or ""), str(target))
    state = "PASS" if comparison == "right" else "FAIL" if comparison == "wrong" else "UNKNOWN"
    return {"status": state, "adapter": adapter,
            "reason": "derived_key_matches" if state == "PASS" else "derived_key_conflict" if state == "FAIL" else "reference_format_unsupported",
            "derived_answer": str(target), "proof": proof}


def _poly_answer_result(q, target, adapter, proof):
    from sympy import simplify
    if q.question_type == "single_choice":
        results = {}
        matches = []
        for key, value in (q.options or {}).items():
            parsed = _parse_poly(value)
            state = "unknown" if parsed is None else "right" if simplify(parsed - target) == 0 else "wrong"
            results[str(key).strip().upper()] = state
            if state == "right": matches.append(str(key).strip().upper())
        return _choice_result(q, matches, adapter, proof, results)
    parsed = _parse_poly(q.correct_answer)
    comparison = "unknown" if parsed is None else "right" if simplify(parsed - target) == 0 else "wrong"
    state = "PASS" if comparison == "right" else "FAIL" if comparison == "wrong" else "UNKNOWN"
    return {"status": state, "adapter": adapter,
            "reason": "derived_key_matches" if state == "PASS" else "derived_key_conflict" if state == "FAIL" else "reference_format_unsupported",
            "derived_answer": str(target), "proof": proof}


def _numeric_option_result(q, target, adapter, proof):
    if q.question_type == "single_choice":
        from backend.services.quality_verifiers import option_value
        from sympy import simplify

        values = {str(k).strip().upper(): (constant_expression(option_value(v)) or _integer_representation(option_value(v))) for k, v in (q.options or {}).items()}
        if not values or any(value is None for value in values.values()):
            return {"status": "UNKNOWN", "adapter": adapter, "reason": "option_expression_outside_scope", "proof": proof}
        matches = [key for key, value in values.items() if simplify(value - target) == 0]
        return _choice_result(q, matches, adapter, proof, {key: "right" if key in matches else "wrong" for key in values})
    return _constant_result(q, target, adapter, proof)


def _criterion(value: str):
    """Return convergence truth at p=0,1,2 for a bounded p-integral claim."""
    text = _norm(value).replace("≤", "<=").replace("≥", ">=").replace("≦", "<=").replace("≧", ">=")
    if re.search(r"(?:对)?所有(?:实数)?p(?:都|均)收敛", text):
        return (True, True, True)
    if re.search(r"(?:对)?所有(?:实数)?p(?:都|均)发散", text):
        return (False, False, False)
    # Concise final answers such as ``p>1`` state the convergence set for
    # this one explicitly supported p-test family. Evaluate that set at the
    # same representative values used below; do not generalize to arbitrary
    # parameterized integrals.
    compact = re.fullmatch(r"p(>=|<=|>|<)1(?:当且仅当)?(?:收敛)?", text)
    if compact:
        operator = compact.group(1)
        return tuple({">": sample > 1, ">=": sample >= 1,
                      "<": sample < 1, "<=": sample <= 1}[operator]
                     for sample in (0, 1, 2))
    clauses = re.findall(r"p(>=|<=|>|<)1(?:时)?(收敛|发散)", text)
    if len(clauses) < 2:
        return None
    result = []
    for sample in (0, 1, 2):
        claims = []
        for operator, outcome in clauses:
            condition = {">": sample > 1, ">=": sample >= 1, "<": sample < 1, "<=": sample <= 1}[operator]
            if condition:
                claims.append(outcome == "收敛")
        if len(claims) != 1:
            return None
        result.append(claims[0])
    return tuple(result)


def _criterion_verdict(value: str, expected=(False, False, True)):
    """Decide a bounded p-test claim when it is falsifiable from p=0,1,2.

    A false partial claim (for example, convergence for p>=1) can be rejected
    by its counterexample at p=1. An incomplete but not-yet-contradicted claim
    remains unknown; it is never promoted to true merely because samples look
    plausible.
    """
    # Complete iff statements are compared as sets, rather than accepted on
    # a few sampled parameters. Only this exact p-test has this convergence set.
    from sympy import Interval, FiniteSet, S, oo
    text = _norm(value).replace("≤", "<=").replace("≥", ">=")
    if re.fullmatch(r"(?:对)?(?:任意|所有)(?:实数)?p(?:都|均)收敛", text):
        return False
    claim = re.fullmatch(r"(当且仅当|仅当)(.+?)(?:时)?收敛", text)
    if claim:
        condition = claim[2]
        interval = None
        simple = re.fullmatch(r"p(>=|<=|>|<|=)(-?\d{1,3})", condition)
        bounded = re.fullmatch(r"(-?\d{1,3})(<=|<)p(<=|<)(-?\d{1,3})", condition)
        if simple:
            op, bound = simple[1], int(simple[2])
            interval = (Interval(bound, oo, left_open=op == ">") if op in {">", ">="} else
                Interval(-oo, bound, right_open=op == "<") if op in {"<", "<="} else FiniteSet(bound))
        elif bounded:
            interval = Interval(int(bounded[1]), int(bounded[4]),
                left_open=bounded[2] == "<", right_open=bounded[3] == "<")
        if interval is None:
            return None
        actual = Interval(1, oo, left_open=True)
        if claim[1] == "当且仅当":
            return interval == actual
        # A necessary-only claim can be refuted, but is not sufficient evidence
        # of a complete convergence criterion even when it contains the true set.
        return False if actual.is_subset(interval) is False else None
    vector = _criterion(value)
    if vector is not None:
        return vector == expected
    text = _norm(value).replace("≤", "<=").replace("≥", ">=").replace("≦", "<=").replace("≧", ">=")
    clauses = re.findall(r"p(>=|<=|>|<)1(?:时)?(收敛|发散)", text)
    if not clauses:
        return None
    complete = True
    for index, sample in enumerate((0, 1, 2)):
        claims = []
        for operator, outcome in clauses:
            condition = {">": sample > 1, ">=": sample >= 1,
                         "<": sample < 1, "<=": sample <= 1}[operator]
            if condition:
                claims.append(outcome == "收敛")
        if len(claims) != 1:
            complete = False
        if any(claim != expected[index] for claim in claims):
            return False
    return True if complete else None


def verify_explanation_step(expression: str, value: str) -> str:
    """Check allowlisted exact arithmetic / bounded assertions; no eval."""
    raw = _norm(expression).strip("$").replace("^", "**")
    expected = _norm(value).strip("$")
    if not raw or not expected or len(raw) > 160:
        return "unknown"
    if raw in {"lne", "ln(e)"}:
        return compare_constant_expressions("1", expected)
    m = re.fullmatch(r"floor\((-?\d{1,9})/(-?\d{1,9})\)", raw)
    if m:
        numerator, denominator = int(m.group(1)), int(m.group(2))
        if denominator == 0:
            return "wrong"
        if denominator < 0:
            return "unknown"
        return compare_constant_expressions(str(numerator // denominator), expected)
    # For successful binary search, 2^(d-1) < n <= 2^d implies depth d.
    m = re.fullmatch(r"(\d{1,9})<(\d{1,9})<=(\d{1,9})", raw)
    if m:
        lower, middle, upper = map(int, m.groups())
        if not lower < middle <= upper:
            return "wrong"
        depth = upper.bit_length() - 1
        if depth < 1 or lower != 1 << (depth - 1) or upper != 1 << depth:
            return "unknown"
        return compare_constant_expressions(str(depth), expected)
    import ast
    from fractions import Fraction

    normalized = raw.replace("×", "*").replace("·", "*").replace(r"\cdot", "*").replace(r"\times", "*")
    normalized = normalized.replace("^", "**")

    def exact(text):
        tree = ast.parse(text, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 48:
            raise ValueError("expression_too_large")
        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) is int and abs(node.value) <= 10**9:
                return Fraction(node.value)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                result = visit(node.operand)
                return result if isinstance(node.op, ast.UAdd) else -result
            if isinstance(node, ast.BinOp):
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
                if isinstance(node.op, ast.Div) and right: return left / right
                if isinstance(node.op, ast.Pow) and right.denominator == 1 and abs(right.numerator) <= 16:
                    if left == 0 and right <= 0: raise ValueError("undefined_power")
                    return left ** right.numerator
            raise ValueError("unsupported_expression")
        return visit(tree.body)

    try:
        # A single equality is accepted only when both sides evaluate exactly
        # and the right side also equals the separately reported step value.
        equality = re.fullmatch(r"(.+?)=(?!=)(.+)", normalized)
        actual = exact(equality.group(1)) if equality else exact(normalized)
        if equality and actual != exact(equality.group(2)):
            return "wrong"
        return "right" if actual == exact(expected) else "wrong"
    except (SyntaxError, ValueError, ZeroDivisionError, RecursionError):
        return "unknown"


def _answer_final_consistent(final_value: str, selected_value: str, independent: dict) -> str:
    from backend.services.quality_verifiers import option_value

    scalar = compare_exact_answer_values(final_value, selected_value)
    if scalar == "right" or _norm(final_value) == _norm(option_value(selected_value)):
        return "right"
    if scalar == "wrong" and _integer_representation(final_value) is not None and _integer_representation(selected_value) is not None:
        return "wrong"
    adapter = independent.get("adapter")
    if adapter == "phase45i_log_improper_integral_p_test_v1":
        expected = _criterion_verdict(selected_value)
        final = _criterion_verdict(final_value)
        if expected is True and final is True:
            return "right"
        # A concise answer such as “p>1” denotes the convergence threshold for
        # this exact integral only; it is equivalent to the fully worded option.
        compact = _norm(final_value).replace("≤", "<=")
        if expected is True and re.fullmatch(r"p>1(?:时收敛)?", compact):
            return "right"
        if expected is True and re.fullmatch(r"p(?:>=|<=|>|<)1", compact):
            return "wrong"
        return "wrong" if final is not None else "unknown"
    if adapter == "phase45i_quadratic_determinant_inequality_v1":
        left, right = _interval_set(final_value), _interval_set(selected_value)
        if left is None or right is None:
            return "unknown"
        return "right" if left == right else "wrong"
    if adapter == "phase45i_twos_complement_range_v1":
        left, right = _range_pair(final_value), _range_pair(selected_value)
        if left is None or right is None:
            return "unknown"
        return "right" if left == right else "wrong"
    if adapter == "phase45i_polynomial_derivative_v1":
        return _poly_compare(final_value, selected_value)
    if independent.get("derived_answer") is not None:
        return compare_constant_expressions(final_value, str(independent["derived_answer"]))
    return "unknown"


def final_value_matches(q, final_value: str, independent: dict) -> str:
    if q.question_type == "single_choice":
        label = str(final_value or "").strip().upper()
        correct_key = str(q.correct_answer or "").strip().upper()
        if label in (q.options or {}):
            return "right" if label == correct_key else "wrong"
        selected = (q.options or {}).get(correct_key)
        if selected is None:
            return "wrong"
        return _answer_final_consistent(final_value, str(selected), independent)
    adapter = independent.get("adapter")
    if adapter == "phase45i_twos_complement_range_v1":
        left, right = _range_pair(final_value), _range_pair(str(q.correct_answer or ""))
        return "right" if left is not None and left == right else "wrong" if left is not None and right is not None else "unknown"
    if adapter in {"phase45i_polynomial_derivative_v1"}:
        return _poly_compare(final_value, q.correct_answer)
    return compare_constant_expressions(final_value, q.correct_answer)


def verify_narrative_claims(q, independent):
    """Check bounded key claims against the independently derived solution.

    This is deliberately not a general natural-language proof checker. Unknown
    claims remain explicit; no model consistency is used as mathematical evidence.
    """
    from sympy import diff, Symbol, simplify
    text=_norm(q.explanation)
    adapter=(independent or {}).get('adapter') or ''
    proof=(independent or {}).get('proof') or {}
    checks=[]
    if 'polynomial_derivative' in adapter:
        for match in re.finditer(r"f'\(x\)=([^，。；]+)",text):
            claimed=_parse_poly(match[1])
            actual=_parse_poly(str(proof.get('derivative','')))
            if claimed is not None and actual is not None:
                checks.append('right' if simplify(claimed-actual)==0 else 'wrong')
    if adapter=='phase45i_polynomial_definite_integral_v1':
        actual=_parse_poly(str(proof.get('integrand','')))
        for match in re.finditer(r"(?:F\(x\)=|原函数(?:为|是))([^，。；]+)",text):
            primitive=_parse_poly(match[1])
            if primitive is not None and actual is not None:
                checks.append('right' if simplify(diff(primitive,Symbol('x',real=True))-actual)==0 else 'wrong')
    if adapter=='phase45i_log_improper_integral_p_test_v1':
        # Explicitly asserted convergence thresholds must agree with the p-test.
        for match in re.finditer(r"p(>=|<=|>|<|=)1(?:时)?收敛",text):
            checks.append('right' if match[1]=='>' else 'wrong')
    if adapter=='phase45i_exp_second_order_limit_v1':
        normalized=text.replace('\\\\frac','\\frac')
        expansion=re.search(r"e\^\{"+str(proof.get('a'))+r"x\}=(.+?)\+o\(x\^2\)",normalized)
        if expansion:
            polynomial=_parse_poly(expansion[1]);x=Symbol('x',real=True);a=proof['a']
            if polynomial is not None:
                from sympy import Rational
                checks.append('right' if simplify(polynomial-(1+a*x+Rational(a*a,2)*x*x))==0 else 'wrong')
    if adapter in {'phase45d_determinant_2x2_v1','phase45i_determinant_2x2_numeric_v1'}:
        formula=re.search(r'ad([+-])bc',text)
        if formula:checks.append('right' if formula[1]=='-' else 'wrong')
        elif '主对角线乘积减副对角线乘积' in text:checks.append('right')
    if adapter=='phase45i_complete_tree_leaf_count_v1':
        formula=re.search(r'(?:n|结点数)([+-])(?:floor\(n/2\)|⌊n/2⌋)',text)
        if formula:checks.append('right' if formula[1]=='-' else 'wrong')
    if adapter=='phase45i_twos_complement_range_v1':
        for pattern,key in ((r'(?:负数(?:下界|最小)(?:为)?|下界为)([^，。；]+)','minimum'),
                (r'(?:非负数上界为|正数最大为|上界为)([^，。；]+)','maximum')):
            for claim in re.finditer(pattern,text):
                if '=' in claim[1]:
                    compared=compare_exact_answer_values(claim[1].rsplit('=',1)[1],str(proof[key]))
                    if compared!='unknown':checks.append(compared)
    if adapter=='phase45i_binary_search_max_success_v1':
        chain=re.search(r'2\^(\d+)=([0-9]+)<([0-9]+)(?:≤|<=)2\^(\d+)=([0-9]+)',text)
        if chain:
            lowexp,lower,middle,highexp,upper=map(int,chain.groups())
            valid=(lowexp<=20 and highexp<=20 and lower==2**lowexp and upper==2**highexp
                and middle==proof.get('length',proof.get('n',0))+1 and lower<middle<=upper)
            checks.append('right' if valid else 'wrong')
    if adapter=='phase45i_ieee754_binary32_hex_v1':
        sign=re.search(r"符号位为([01])",text)
        if sign:
            checks.append('right' if int(sign[1])==(0 if proof.get('sign')==1 else 1) else 'wrong')
        exponent=re.search(r"(?:实际指数(?:为)?|实际指数)\s*(-?\d+)",text)
        if exponent and proof.get('classification')=='normal':
            checks.append('right' if int(exponent[1])==proof['exponent_bits']-127 else 'wrong')
    if adapter=='phase45d_page_replacement_v1':
        algorithm=proof.get('algorithm')
        if algorithm=='LRU' and ('淘汰最先进入' in text or '先进先出' in text):
            checks.append('wrong')
        if algorithm=='FIFO' and '淘汰最久未被访问' in text:
            checks.append('wrong')
        if algorithm=='LRU' and '淘汰最久未被访问' in text:checks.append('right')
        if algorithm=='FIFO' and '先进先出' in text:checks.append('right')
        faults=re.search(r'发生缺页的访问依次为([0-9,、]+)',text)
        if faults:
            values=[int(v) for v in re.split('[,、]',faults[1])]
            actual=[row['page'] for row in proof.get('trace',[]) if row['fault']]
            checks.append('right' if values==actual else 'wrong')
    return {'status':'FAIL' if 'wrong' in checks else 'PASS' if checks else 'NOT_APPLICABLE',
        'checked_claim_count':len(checks),'scope':'bounded explicit derivative/primitive/threshold/sign/algorithm claims'}


def verify_problem(q, compact: str):
    """Return an exact result for explicitly supported Phase 4.5I families."""
    from sympy import Symbol, diff, integrate, limit, exp, simplify, solve_univariate_inequality, S, oo

    x = Symbol("x", real=True)
    kind = q.question_type
    if kind not in {"single_choice", "fill_blank", "calculation"}:
        return None

    # Evaluate the derivative of a complete bounded integer polynomial at an
    # explicitly stated integer point. This covers numeric fill answers
    # without relying on symbolic-formula equivalence in the learner grader.
    m = re.fullmatch(r"已知函数f\(x\)=(.+)，求f'\((-?\d{1,4})\)的值[。.]?", compact)
    parameter_point = re.fullmatch(r"已知函数f\(x\)=(.+)，求f'\(t\)的值，其中t=(-?\d{1,4})[。.]?", compact)
    m = m or parameter_point
    if m:
        poly = _parse_poly(m.group(1))
        if poly is None:
            return {"status": "UNKNOWN", "adapter": "phase45i_polynomial_derivative_value_v1", "reason": "polynomial_outside_bound"}
        point = int(m.group(2))
        target = simplify(diff(poly, x).subs(x, point))
        proof = {"polynomial": str(poly), "point": point,
                 "derivative": str(simplify(diff(poly, x))), "derived_value": str(target),
                 "method": "exact derivative then integer substitution"}
        return _numeric_option_result(q, target, "phase45i_polynomial_derivative_value_v1", proof)

    # Derivative of an explicitly provided bounded integer polynomial.
    m = re.fullmatch(r"设函数f\(x\)=(.+)，求f'\(x\)[。.]?", compact)
    if m:
        poly = _parse_poly(m.group(1))
        if poly is None:
            return {"status": "UNKNOWN", "adapter": "phase45i_polynomial_derivative_v1", "reason": "polynomial_outside_bound"}
        target = simplify(diff(poly, x))
        return _poly_answer_result(q, target, "phase45i_polynomial_derivative_v1", {
            "statement": "differentiate the entire explicitly stated polynomial term by term",
            "polynomial": str(poly), "derivative": str(target), "variable": "x", "degree_bound": 12,
        })

    # Definite integral of a bounded integer polynomial over finite integer bounds.
    integral_stem = str(q.stem or "").strip().replace("−", "-")
    m = re.fullmatch(r"计算定积分：?∫_(\{?-?\d{1,3}\}?)\^(\{?-?\d{1,3}\}?)\s+(.+?)\s*dx\s*=\s*(?:_{2,}|[?？])?[。.]?", integral_stem)
    if m:
        if any(part.count('{') != part.count('}') for part in (m[1],m[2])):
            return {"status":"UNKNOWN","adapter":"phase45i_polynomial_definite_integral_v1","reason":"malformed_integral_bounds"}
        low, high = int(m.group(1).strip('{}')), int(m.group(2).strip('{}'))
        poly = _parse_poly(m.group(3))
        if poly is None or max(abs(low), abs(high)) > 100:
            return {"status": "UNKNOWN", "adapter": "phase45i_polynomial_definite_integral_v1", "reason": "integral_outside_bound"}
        target = simplify(integrate(poly, (x, low, high)))
        return _numeric_option_result(q, target, "phase45i_polynomial_definite_integral_v1", {
            "integrand": str(poly), "interval": [low, high], "method": "exact polynomial antiderivative",
            "derived_value": str(target),
        })

    # The p-test substitution t=ln(x) is valid only for this explicit lower
    # endpoint and denominator form; nearby-looking integrals are not inferred.
    if re.fullmatch(r"关于含参数p的反常积分I\(p\)=∫_e\^\{?\+∞\}?dx/\[x\(lnx\)\^p\]，下列结论正确的是（(?:)）[。.]?", compact):
        expected = (False, False, True)
        if kind == "single_choice":
            outcomes = {str(key).strip().upper(): _criterion_verdict(value, expected) for key, value in (q.options or {}).items()}
            if not outcomes or any(value is None for value in outcomes.values()):
                return {"status": "UNKNOWN", "adapter": "phase45i_log_improper_integral_p_test_v1", "reason": "convergence_claim_outside_scope"}
            matches = [key for key, value in outcomes.items() if value]
            return _choice_result(q, matches, "phase45i_log_improper_integral_p_test_v1", {
                "substitution": "t=ln(x), dt=dx/x", "transformed_integral": "∫_1^∞ t^(-p) dt",
                "converges_iff": "p>1", "sample_truth_table": {"p=0": False, "p=1": False, "p=2": True},
            }, {key: "right" if value else "wrong" for key, value in outcomes.items()})
        if re.fullmatch(r"p>1(?:当且仅当)?", _norm(q.correct_answer)):
            return {"status": "PASS", "adapter": "phase45i_log_improper_integral_p_test_v1",
                    "reason": "derived_key_matches", "derived_answer": "p>1",
                    "proof": {"substitution": "t=ln(x)", "converges_iff": "p>1"}}
        return {"status": "UNKNOWN", "adapter": "phase45i_log_improper_integral_p_test_v1", "reason": "reference_condition_outside_scope"}

    # Second-order exponential limit. Match the original bounded TeX form so
    # nested braces are not flattened into an ambiguous expression.
    limit_stem = _norm(q.stem)
    for command in ('lim','to','frac'):
        limit_stem=limit_stem.replace('\\\\'+command,'\\'+command)
    m = re.fullmatch(r"计算极限：?\\lim_\{x\\to\s*0\}\\frac\{e\^\{(\d{1,3})x\}-1-\1x\}\{x\^2\}(?:=_{2,}|的值是（\s*）)[。.]?", limit_stem)
    if m:
        a = int(m.group(1))
        if not 1 <= a <= 100:
            return {"status": "UNKNOWN", "adapter": "phase45i_exp_second_order_limit_v1", "reason": "coefficient_outside_bound"}
        target = simplify(limit((exp(a*x) - 1 - a*x) / x**2, x, 0))
        return _numeric_option_result(q, target, "phase45i_exp_second_order_limit_v1", {
            "form": "(e^(a*x)-1-a*x)/x^2", "a": a, "method": "exact second-order Taylor coefficient",
            "derived_value": str(target),
        })

    # Explicit 2x2 determinant quadratic inequality; interval syntax must be
    # understood for every option before a unique-choice PASS is possible.
    m = re.fullmatch(r"关于实数x的不等式det\[\[x,(-?\d{1,3})\],\[(-?\d{1,3}),x([+-]\d{1,3})?\]\]>(=?)0的解集是（(?:)）[。.]?", compact)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        c = int(m.group(3) or 0)
        sign = ">=" if m.group(4) else ">"
        polynomial = simplify(x * (x + c) - a * b)
        solution = solve_univariate_inequality(polynomial >= 0 if sign == ">=" else polynomial > 0, x, relational=False)
        if kind != "single_choice":
            return {"status": "UNKNOWN", "adapter": "phase45i_quadratic_determinant_inequality_v1", "reason": "set_answer_requires_choices"}
        options = {str(key).strip().upper(): _interval_set(value) for key, value in (q.options or {}).items()}
        if not options or any(value is None for value in options.values()):
            return {"status": "UNKNOWN", "adapter": "phase45i_quadratic_determinant_inequality_v1", "reason": "interval_option_outside_scope"}
        matches = [key for key, value in options.items() if value == solution]
        return _choice_result(q, matches, "phase45i_quadratic_determinant_inequality_v1", {
            "matrix": [["x", a], [b, f"x{c:+d}" if c else "x"]], "determinant": str(polynomial),
            "inequality": sign, "solution_set": str(solution),
        }, {key: "right" if value == solution else "wrong" for key, value in options.items()})

    # Complete binary tree leaf count from its sequential-array index range.
    m = re.fullmatch(r"一棵完全二叉树共有(\d{1,7})个结点，则其叶(?:子)?结点数为（(?:)）[。.]?", compact)
    if m:
        n = int(m.group(1))
        if not 1 <= n <= 1_000_000:
            return {"status": "UNKNOWN", "adapter": "phase45i_complete_tree_leaf_count_v1", "reason": "node_count_outside_bound"}
        target = (n + 1) // 2
        return _numeric_option_result(q, target, "phase45i_complete_tree_leaf_count_v1", {
            "nodes": n, "last_nonleaf_index": n // 2, "leaf_count": n - n // 2,
            "proof": "in 1-based level-order storage, indices floor(n/2)+1..n are exactly the leaves",
        })

    # Signed two's-complement range, requiring the stated representation.
    bits = _range_stem_bits(compact)
    if bits is not None:
        if not 2 <= bits <= 64:
            return {"status": "UNKNOWN", "adapter": "phase45i_twos_complement_range_v1", "reason": "word_size_outside_bound"}
        low, high = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
        target = (constant_expression(str(low)), constant_expression(str(high)), True, True)
        proof = {"bits": bits, "minimum": low, "maximum": high, "formula": "[-2^(n-1), 2^(n-1)-1]"}
        if kind == "single_choice":
            from backend.services.quality_verifiers import option_value
            options = {str(key).strip().upper(): _range_pair(option_value(value)) for key, value in (q.options or {}).items()}
            if not options or any(value is None for value in options.values()):
                return {"status": "UNKNOWN", "adapter": "phase45i_twos_complement_range_v1", "reason": "range_option_outside_scope"}
            matches = [key for key, value in options.items() if value == target]
            return _choice_result(q, matches, "phase45i_twos_complement_range_v1", proof,
                                  {key: "right" if value == target else "wrong" for key, value in options.items()})
        answer = _range_pair(q.correct_answer)
        if answer is None:
            return {"status": "UNKNOWN", "adapter": "phase45i_twos_complement_range_v1", "reason": "range_answer_outside_scope"}
        state = "PASS" if answer == target else "FAIL"
        return {"status": state, "adapter": "phase45i_twos_complement_range_v1",
                "reason": "derived_key_matches" if state == "PASS" else "derived_key_conflict",
                "derived_answer": f"[{low},{high}]", "proof": proof}

    # Maximum successful comparisons in a binary-search decision tree. Only
    # the explicit all-successful-search statement is accepted; failed-search
    # depth and comparison conventions are deliberately out of scope.
    m = re.fullmatch(r"对长度为(\d{1,7})的升序有序表进行折半查找，若所有查找均成功，则查找成功时最多需要比较的关键字个数是（(?:)）[。.]?", compact)
    if m:
        n = int(m.group(1))
        if not 1 <= n <= 1_000_000:
            return {"status": "UNKNOWN", "adapter": "phase45i_binary_search_max_success_v1", "reason": "list_length_outside_bound"}
        comparisons = n.bit_length()
        return _numeric_option_result(q, comparisons, "phase45i_binary_search_max_success_v1", {
            "length": n, "max_successful_comparisons": comparisons,
            "proof": "a balanced binary search decision tree with n keys has minimum possible height ceil(log2(n+1))",
            "scope": "successful searches only; unsuccessful-search comparison convention excluded",
        })

    # Direct 2x2 determinant calculation using an explicit two-row statement.
    # Integers are bounded and every entry is supplied in the question itself.
    m = re.fullmatch(
        r"计算二阶行列式，其中第一行是(-?\d{1,3})、(-?\d{1,3})，第二行是(-?\d{1,3})、(-?\d{1,3})[。.]?",
        compact,
    )
    if m:
        a, b, c, d = map(int, m.groups())
        target = a * d - b * c
        return _numeric_option_result(q, target, "phase45i_determinant_2x2_numeric_v1", {
            "matrix": [[a, b], [c, d]], "formula": "ad-bc", "derived_value": target,
        })

    # Exact IEEE-754 binary32 decoding for a fully stated 8-hex-digit word.
    # Finite normal and subnormal values are represented as Fractions; NaN and
    # infinities are deliberately not assigned a numeric-answer comparison.
    m = re.fullmatch(
        r"某IEEE754单精度浮点数的32位十六进制表示为([0-9A-F]{8})，求其表示的十进制真值(?:是多少)?[？?.。]?",
        compact,
    )
    if m:
        from fractions import Fraction

        raw = int(m.group(1), 16)
        sign = -1 if raw >> 31 else 1
        exponent = (raw >> 23) & 0xFF
        fraction = raw & ((1 << 23) - 1)
        if exponent == 0xFF:
            return {"status": "NOT_APPLICABLE", "adapter": "phase45i_ieee754_binary32_hex_v1",
                    "reason": "infinity_or_nan_has_no_supported_finite_scalar_answer"}
        if exponent == 0:
            significand = fraction
            power = -126 - 23
            classification = "subnormal" if fraction else "zero"
        else:
            significand = (1 << 23) | fraction
            power = exponent - 127 - 23
            classification = "normal"
        magnitude = Fraction(significand * (1 << power), 1) if power >= 0 else Fraction(significand, 1 << -power)
        target = sign * magnitude
        return _numeric_option_result(q, target, "phase45i_ieee754_binary32_hex_v1", {
            "hex_word": m.group(1), "sign": sign, "exponent_bits": exponent,
            "fraction_bits": fraction, "classification": classification,
            "exact_value": str(target), "binary32_bias": 127,
            "normal_formula": "(-1)^s * (1 + fraction/2^23) * 2^(exponent-127)",
            "subnormal_formula": "(-1)^s * (fraction/2^23) * 2^-126",
        })

    return None
