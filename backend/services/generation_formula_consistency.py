"""Conservative contradiction detector, NOT a general correctness certificate.

Only a single explicit S(x)=... formula in both answers is compared. A proven
counterexample rejects; unsupported text returns unknown, never PASS.
No eval/parse_expr/model judge or unbounded symbolic solve is used.
"""
import ast
import re
from functools import lru_cache
from sympy import Rational, log, exp, sin, cos, simplify, Pow


def _math_delimiters(text):
    # 检查时统一合法数学定界符，不改保存的原文、公式运算或反斜杠命令。
    return re.sub(r'(?<!\\)\\[()\[\]]',lambda match:'$',text)


def _formula(text):
    text=_math_delimiters(text)
    match=re.search(r'(?:\$|^)(?:\s*)[A-Za-z]\(x\)\s*=\s*([^$，。；\n]+)',text)
    return match.group(1).strip() if match else None


def _expression(raw, variables):
    if not raw or len(raw)>400:return None
    text=raw.replace(r'\left','').replace(r'\right','').replace(r'\,','').replace('−','-')
    fraction_command=r'\\(?:dfrac|tfrac|frac)'
    # TeX permits a one-token numerator or denominator without braces. Accept
    # only that bounded form (e.g. \frac1n, \frac{1}n, \frac1{n}); this is not
    # a general TeX parser and leaves compound unbraced operands unknown.
    text=re.sub(fraction_command+r'\s*\{([^{}]+)\}\s*([A-Za-z0-9])',r'((\1)/(\2))',text)
    text=re.sub(fraction_command+r'\s*([A-Za-z0-9])\s*\{([^{}]+)\}',r'((\1)/(\2))',text)
    text=re.sub(fraction_command+r'\s*([A-Za-z0-9])\s*([A-Za-z0-9])',r'((\1)/(\2))',text)
    for _ in range(8):
        old=text
        text=re.sub(r'\\(?:dfrac|tfrac|frac)\{([^{}]+)\}\{([^{}]+)\}',r'((\1)/(\2))',text)
        text=re.sub(r'\^\{([^{}]+)\}',r'^(\1)',text)
        if old==text:break
    text=text.replace(r'\ln','log').replace(r'\cdot','*').replace('^','**')
    text=text.replace('sin(', 'SIN(')
    text=re.sub(r'(?<=[0-9xn)])(?=[xn]|\(|log)', '*', text).replace('SIN(', 'sin(')
    try:
        tree=ast.parse(text.strip(),mode='eval')
        if sum(1 for _ in ast.walk(tree))>90:return None
        def build(node):
            result=build_node(node)
            if result.is_Rational and max(abs(int(result.p)).bit_length(),int(result.q).bit_length())>256:
                raise ValueError('formula_integer_budget')
            if result.count_ops()>60:raise ValueError('formula_operation_budget')
            if any(power.exp.is_Integer and abs(power.exp)>6 for power in result.atoms(Pow)):
                raise ValueError('formula_expanded_power_budget')
            return result
        def build_node(node):
            if isinstance(node,ast.Constant) and type(node.value) is int and abs(node.value)<10000:return Rational(node.value)
            if isinstance(node,ast.Name) and node.id in variables:return variables[node.id]
            if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
                value=build(node.operand);return -value if isinstance(node.op,ast.USub) else value
            if isinstance(node,ast.BinOp):
                a,b=build(node.left),build(node.right)
                if isinstance(node.op,ast.Add):return a+b
                if isinstance(node.op,ast.Sub):return a-b
                if isinstance(node.op,ast.Mult):return a*b
                if isinstance(node.op,ast.Div) and b!=0:return a/b
                if isinstance(node.op,ast.Pow) and b.is_Integer and abs(b)<=6:return a**b
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {'log','exp','sin','cos'} and len(node.args)==1 and not node.keywords:
                a=build(node.args[0])
                if node.func.id!='log' or a.is_positive or a.free_symbols:
                    return {'log':log,'exp':exp,'sin':sin,'cos':cos}[node.func.id](a)
            raise ValueError('outside_bounded_formula_scope')
        value=build(tree.body)
        return value if value.is_finite is not False else None
    except (ValueError,SyntaxError,TypeError,ZeroDivisionError,RecursionError):return None


def _at_point(raw, point):
    return _expression(raw,{'x':point})


def power_series_conflict(stem, answer, final_value, explanation):
    """独立求解有限 Laurent 系数族，仅提供反证，不授予整题 PASS。

    支持 a_n=sum(c_k*n**k), -1<=k<=4, sum from n=1 to infinity.
    其它起点、参数、乘积、嵌套级数和未解析公式保持 unknown。
    """
    from sympy import Symbol, Poly, diff, cancel
    if len(stem)>4000 or stem.count(r'\sum')!=1:return False
    source=_math_delimiters(stem).replace(r'\displaystyle','').replace(r'\,','')
    match=re.search(r'\\sum_\{n=1\}\^\{\\infty\}(.*?)x(?:\^\{n\}|\^n)(?=\s*\$)',source)
    if not match:return False
    assigned_sum=bool(re.search(r'[A-Za-z]\(x\)\s*=\s*$',source[:match.start()]))
    if not assigned_sum and re.search(r'积分|求导|导数',stem):
        # 不能把积分后的S(x)与未积分的原级数相比较；本求和核验器不支持
        # 该任务时保持未知，既不错误拒绝，也不对积分/导数给出PASS。
        return False
    n=Symbol('n',integer=True,positive=True);x=Symbol('x',real=True)
    coefficient=_expression(match[1].strip() or '1',{'n':n})
    if coefficient is None:return False
    try:
        polynomial=Poly(cancel(coefficient*n),n)
        if polynomial.degree()>5 or not all(c.is_Rational and abs(c)<=1000 for c in polynomial.all_coeffs()):return False
        expected=0;has_polynomial=False
        for (degree,),c in polynomial.terms():
            k=degree-1
            if k==-1:expected-=c*log(1-x)
            else:
                has_polynomial |= c!=0
                term=x/(1-x)
                for _ in range(k):term=x*diff(term,x)
                expected+=c*term
        # 相同的两个错误答案也必须对照题干，而不能互相证明正确。
        for text in (answer,final_value,explanation):
            for point in (Rational(1,3),Rational(1,5)):
                # final_value 通常是裸表达式；不能只核对带 S(x)= 的答案。
                raw = _formula(text) or (text if text is final_value else None)
                parsed=_expression(raw,{'x':point})
                if parsed is not None and simplify(parsed-expected.subs(x,point)).is_zero is False:return True
        # Independently determine both unit-circle endpoints for the supported
        # Laurent-polynomial coefficient family.  With a_n=P(n)/n, P constant
        # gives the alternating harmonic series at -1 (convergent); any
        # nonconstant polynomial term prevents a_n*(-1)^n from tending to 0.
        # At +1, every nonzero supported family diverges (harmonic or larger).
        # This is a bounded endpoint check, not a general radius/domain solver.
        if polynomial.terms():
            expected_left='(' if has_polynomial else '['
            for text in (answer,final_value,explanation):
                text=_math_delimiters(text).replace('−','-').replace(r'\left','').replace(r'\right','')
                claims=re.findall(
                    r'(?:收敛域|收敛区间)(?:为|是|：|:|\s|\$)*([\[(])\s*-1\s*[,，]\s*1\s*([\])])',
                    text)
                if any(left != expected_left or right != ')' for left,right in claims):
                    return True
    except (ValueError,TypeError,ZeroDivisionError):return False
    return False


def answer_formula_conflict(answer, final_value):
    left,right=_formula(answer),_formula(final_value) or final_value
    if not left or not right:return False
    for point in (Rational(1,3),Rational(1,5)):
        a,b=_at_point(left,point),_at_point(right,point)
        if a is not None and b is not None and simplify(a-b).is_zero is False:
            return True
    return False


def selected_option_conflicts_nonfinite_final(selected_option, final_value):
    """Reject a finite selected choice when the declared result is non-finite.

    This checks only an explicit contradiction between two answer fields. It
    does not decide whether the limit itself converges, nor certify any other
    part of the question. Ambiguous/non-numeric options and inconclusive prose
    remain outside this guard.
    """
    if not selected_option or not final_value:
        return False
    normalized = _math_delimiters(str(selected_option)).strip()
    if normalized.startswith("$") and normalized.endswith("$"):
        normalized = normalized[1:-1]
    from backend.services.constant_expression import constant_expression
    value = constant_expression(normalized)
    if value is None:
        value = _expression(normalized, {})
    if value is None or value.is_finite is not True or value.free_symbols:
        return False

    claim = _math_delimiters(str(final_value)).replace("−", "-").lower()
    # The final_value field is the declared conclusion, so only explicit
    # assertions count. Negative/uncertain wording is deliberately excluded.
    patterns = (
        r"(?<!并)(?<!不)(?<!非)(?:原)?极限\s*(?:不存在|发散)",
        r"(?<!不)(?<!未)(?:原)?极限[^。；;]{0,16}(?<!不)(?<!未)(?:不存在|发散)",
        r"(?<!并)(?<!不)(?<!非)(?:不存在|发散)[^。；;]{0,12}(?:有限值|有限答案)",
        r"(?<!不)(?<!未)(?:发散到|趋于(?:正|负)?\s*无穷|趋于\s*[+-]?\s*(?:\\infty|∞))",
        r"(?:极限|结果|答案|l)\s*(?:为|是|=)\s*[+-]?\s*(?:\\infty|∞|无穷(?:大)?)",
        r"\b(?:does not exist|diverges|infinite)\b",
    )
    return any(re.search(pattern, claim) for pattern in patterns)


def product_integral_limit_conflict(stem, final_value):
    """Reject provably finite answers for x*f(x)-int_0^x f over x^3.

    This adapter is limited to the exact expression shape and local derivative
    data used by the Taylor argument. Unsupported variants remain unknown;
    this check never certifies an answer as correct.
    """
    from sympy import Rational, simplify
    source=_math_delimiters(stem or "").replace(r"\displaystyle", "")
    source=re.sub(r"\s+", "", source)
    if not (re.search(r"xf\(x\)-\\int_0\^xf\(t\)", source)
            and re.search(r"\\(?:dfrac|tfrac|frac)\{[^{}]*\}\{x\^3\}", source)):
        return False
    first=re.search(r"f'\(0\)=([+-]?\d+(?:/\d+)?)",source)
    second=re.search(r"f''\(0\)=([+-]?\d+(?:/\d+)?)",source)
    if not first or not second:
        return False
    try:
        f1,f2=Rational(first.group(1)),Rational(second.group(1))
        claimed_text=_math_delimiters(final_value or "").strip().strip("$")
        claimed=_expression(claimed_text,{})
        if claimed is None:
            return False
        if f1 != 0:
            # The numerator has (f'(0)/2)x^2+O(x^3), so division by x^3
            # cannot have the asserted finite two-sided value.
            return True
        return simplify(claimed-f2/3).is_zero is False
    except (ValueError,TypeError,ZeroDivisionError):
        return False


def bounded_calculus_check(stem, answer, final_value, explanation, options=None, selected_option=None):
    # Version admission and read eligibility share immutable content. Avoid
    # redoing symbolic series for every card/availability read; never share a
    # mutable diagnostic object with persisted grading metadata.
    from copy import deepcopy
    option_items=tuple(sorted((options or {}).items()))
    return deepcopy(_bounded_calculus_check(stem,answer,final_value,explanation,option_items,selected_option))


@lru_cache(maxsize=512)
def _bounded_calculus_check(stem, answer, final_value, explanation, option_items, selected_option=None):
    """Check one unambiguous scalar calculus fragment, never certify a whole item.

    Zero-centred limits with bounded rational/analytic expressions; polynomial
    derivative-at-zero and polynomial integrals from0 to1. Other syntax is
    UNKNOWN. No eval, arbitrary LaTeX parser, solve, numerical guess or model.
    """
    from sympy import Symbol, Poly, series, diff, integrate, Function
    from sympy.polys.polyerrors import PolynomialError
    from backend.services.constant_expression import constant_expression
    unknown = {"status": "UNKNOWN", "reason": "outside_bounded_calculus_scope", "whole_question_verified": False}
    options=dict(option_items)
    if not stem or len(stem)>4000:
        return unknown
    source=_math_delimiters(stem).replace(r'\displaystyle','').replace(r'\,','')
    x=Symbol('x', real=True)
    def parse(raw):
        raw=re.sub(r'\\(sin|cos)\s+x\b',r'\1(x)',raw)
        raw=re.sub(r'e\^\{([^{}]+)\}',r'exp(\1)',raw)
        raw=re.sub(r'e\^([x])',r'exp(\1)',raw)
        raw=raw.replace(r'\exp','exp').replace(r'\sin','sin').replace(r'\cos','cos')
        value=_expression(raw,{'x':x})
        if value is None:return None
        # Analytic elementary functions of low-degree polynomials only. This
        # excludes essential singularities, nested transcendental functions,
        # logs at zero/branch cuts, and expensive unrestricted limit solving.
        for function in value.atoms(Function):
            try:
                argument=Poly(function.args[0],x)
                if argument.degree()>3 or any(not c.is_Rational or abs(c)>100 for c in argument.all_coeffs()):return None
                at_zero=argument.eval(0)
                if (function.func==log and at_zero!=1) or (function.func in {exp,sin,cos} and at_zero!=0):return None
            except (ValueError,TypeError,PolynomialError):return None
        return value
    try:
        limits=re.findall(r'\\lim_\{x\\to\s*0\}\s*([^$]+)',source)
        derivative=re.search(r'f\(x\)\s*=\s*([^$]+)\$.*?(?:f\s*\x27\(0\)|在\s*\$?x=0\$?\s*处.*?导数)',source)
        integral=re.search(r'\\int_0\^1\s*(.*?)\s*(?:\\mathrm\{d\}x|dx)(?=\s*\$)',source)
        expected=None;kind=None
        if len(limits)==1 and source.count(r'\lim')==1:
            expression=parse(limits[0].rstrip('。 .'))
            if expression is None:return unknown
            expansion=series(expression,x,0,7).removeO().expand()
            # Only a finite, unambiguous constant limit is claimed here.
            if any(p.exp.is_negative for p in expansion.atoms(Pow) if p.base==x):return unknown
            expected=expansion.subs(x,0);kind='analytic_limit_at_zero'
        elif derivative:
            expression=parse(derivative.group(1))
            if expression is None:return unknown
            polynomial=Poly(expression,x)
            if polynomial.degree()>6:return unknown
            expected=diff(expression,x).subs(x,0);kind='polynomial_derivative_at_zero'
        elif integral:
            expression=parse(integral.group(1))
            if expression is None:return unknown
            polynomial=Poly(expression,x)
            if polynomial.degree()>6:return unknown
            expected=integrate(expression,(x,0,1));kind='polynomial_integral_zero_to_one'
        if expected is None or expected.is_finite is not True or expected.free_symbols:return unknown
        result={"status":"CONSISTENT_FRAGMENT", "kind":kind,"expected":str(expected),
            "whole_question_verified":False,"checked_claims":[]}
        option_values_known=True
        if options:
            parsed=[constant_expression(v) for v in options.values()]
            if all(v is not None for v in parsed):
                labels=list(options)
                matching=[label for label,value in zip(labels,parsed)
                    if simplify(value-expected).is_zero is True]
                if not matching:
                    return {**result,"status":"CONFLICT","issue":"options_missing_mathematical_answer"}
                if len(matching)>1:
                    return {**result,"status":"CONFLICT","issue":"multiple_options_match_mathematical_answer"}
                if selected_option and matching[0] != selected_option:
                    return {**result,"status":"CONFLICT","issue":"selected_option_conflicts_with_mathematical_answer"}
                result["option_check"]={"status":"PASS","matching_option":matching[0]}
            else:
                # Some choices cannot be interpreted by the bounded constant
                # parser. Do not imply that the choice set was checked merely
                # because the stem and final scalar could be checked.
                option_values_known=False
                result["option_check"]={"status":"UNKNOWN","reason":"option_outside_bounded_constant_scope"}
        claims=[('answer',answer),('final_value',final_value)]
        claims.extend(('explanation_conclusion',m) for m in re.findall(
            r'(?:原极限|极限|最终结果|答案)(?:为|是|等于)\s*\$([^$]+)\$',explanation or ''))
        for label,raw in claims:
            value=constant_expression(raw)
            if value is None:continue
            result['checked_claims'].append(label)
            if simplify(value-expected).is_zero is False:
                return {**result,"status":"CONFLICT","issue":"statement_"+label+"_conflict"}
        # An expression alone being supported is not validation of an unparsed answer.
        if 'answer' not in result['checked_claims'] or 'final_value' not in result['checked_claims']:
            return unknown
        if not option_values_known:
            return {**unknown,"reason":"option_outside_bounded_constant_scope",
                "kind":kind,"expected":str(expected),"checked_claims":result['checked_claims'],
                "option_check":result['option_check']}
        return result
    except (ValueError,TypeError,NotImplementedError,ZeroDivisionError,RecursionError,PolynomialError):
        return unknown
