"""Bounded calculus checks for recoverable historical question forms.

Expressions are constructed from fixed mathematical structures and bounded
integer parameters. No candidate text is evaluated or passed to a parser.
Source authenticity and redistribution rights are handled separately.
"""
import re

SOLVERS = frozenset({"hx_infinitesimal_orders_v1", "hx_piecewise_primitive_v1",
    "hx_inverse_exponential_improper_v1"})


def problem(q, text):
    from sympy import Symbol, Rational, cos, sqrt, log, exp, diff, simplify, limit, oo
    from backend.services.phase45hs_verifiers import choice, value
    x = Symbol("x", positive=True)
    if text == (r'设a_1=x(\cos\sqrt{x}-1),a_2=\sqrt{x}\ln(1+\sqrt[3]{x}),a_3=\sqrt[3]{x+1}-1。'
            r'当x\to0^+时,以上三个无穷小量按照从低阶到高阶的排序是（）。'):
        expressions = [x * (cos(sqrt(x)) - 1), sqrt(x) * log(1 + x ** Rational(1, 3)),
            (1 + x) ** Rational(1, 3) - 1]
        orders = [Rational(2), Rational(5, 6), Rational(1)]
        coefficients = [limit(expression / x ** order, x, 0, dir="+")
            for expression, order in zip(expressions, orders)]
        if any(coefficient.is_finite is not True or coefficient == 0 for coefficient in coefficients):
            return {"status": "UNKNOWN", "adapter": "hx_infinitesimal_orders_v1", "reason": "nonzero_order_limit_not_proved"}
        target = tuple(index + 1 for index in sorted(range(3), key=orders.__getitem__))
        def compare(raw):
            match = re.fullmatch(r'a_?([123]),a_?([123]),a_?([123])', value(raw))
            return tuple(map(int, match.groups())) == target if match else None
        return choice(q, "hx_infinitesimal_orders_v1", str(target), {
            "parameters": {"expressions": [str(e) for e in expressions], "direction": "0+"},
            "goal": "increasing_infinitesimal_orders", "orders": [str(e) for e in orders],
            "nonzero_limit_coefficients": [str(e) for e in coefficients], "ordered_indices": list(target)}, compare)
    if text == (r'已知函数f(x)=\begin{cases}2(x-1),&x<1\\\lnx,&x\ge1\end{cases},'
            r'则f(x)的一个原函数是（）。'):
        if q.question_type != "single_choice":
            return {"status": "UNKNOWN", "adapter": "hx_piecewise_primitive_v1", "reason": "primitive_options_required"}
        form = (r'F\(x\)=\\begin\{cases\}\(x-1\)\^2([+-]\d{1,2})?,&x<1'
            r'\\\\x\(\\lnx([+-]\d{1,2})\)([+-]\d{1,2})?,&x\\ge1\\end\{cases\}')
        outcomes, checks = {}, {}
        for key, raw in (q.options or {}).items():
            match = re.fullmatch(form, value(raw))
            if not match:
                outcomes[value(raw)] = None
                checks[key] = {"supported": False}
                continue
            left_c, shift, right_c = (int(match[1] or 0), int(match[2]), int(match[3] or 0))
            left, right = (x - 1) ** 2 + left_c, x * (log(x) + shift) + right_c
            derivatives = (simplify(diff(left, x) - 2 * (x - 1)) == 0,
                simplify(diff(right, x) - log(x)) == 0)
            at_join = [left.subs(x, 1), right.subs(x, 1)]
            slope_join = [diff(left, x).subs(x, 1), diff(right, x).subs(x, 1)]
            accepted = all(derivatives) and at_join[0] == at_join[1] and slope_join == [0, 0]
            outcomes[value(raw)] = bool(accepted)
            checks[key] = {"supported": True, "derivatives_match": list(derivatives),
                "join_values": [str(v) for v in at_join], "join_derivatives": [str(v) for v in slope_join],
                "valid_primitive": bool(accepted)}
        return choice(q, "hx_piecewise_primitive_v1", "piecewise_continuous_primitive", {
            "parameters": {"function": ["2*(x-1), x<1", "log(x), x>=1"], "join": 1},
            "goal": "primitive_derivative_and_join", "option_checks": checks,
            "constant_relation": "right_constant=left_constant+1"}, lambda raw: outcomes.get(value(raw)))
    inverse_form = (r'反常积分①\\int_\{-\\infty\}\^\{0\}\\frac\{1\}\{x\^2\}e\^\{([+-]?\d{1,2})/x\}\\,dx,'
        r'②\\int_\{0\}\^\{\+\\infty\}\\frac\{1\}\{x\^2\}e\^\{([+-]?\d{1,2})/x\}\\,dx的敛散性为（）。')
    match = re.fullmatch(inverse_form, text)
    if match:
        x = Symbol("x", real=True)
        k = int(match[1])
        if k != int(match[2]) or not 1 <= abs(k) <= 20:
            return {"status": "UNKNOWN", "adapter": "hx_inverse_exponential_improper_v1", "reason": "coefficient_scope_or_integrand_mismatch"}
        primitive = -exp(k / x) / k
        if simplify(diff(primitive, x) - exp(k / x) / x ** 2) != 0:
            return {"status": "UNKNOWN", "adapter": "hx_inverse_exponential_improper_v1", "reason": "primitive_derivative_check_failed"}
        endpoints = [limit(primitive, x, -oo), limit(primitive, x, 0, dir="-"),
            limit(primitive, x, 0, dir="+"), limit(primitive, x, oo)]
        convergent = [all(v.is_finite is True for v in endpoints[:2]), all(v.is_finite is True for v in endpoints[2:])]
        def compare(raw):
            parsed = re.fullmatch(r'①(收敛|发散),②(收敛|发散)', value(raw))
            return [state == "收敛" for state in parsed.groups()] == convergent if parsed else None
        return choice(q, "hx_inverse_exponential_improper_v1", str(convergent), {
            "parameters": {"k": k, "integrand": str(exp(k / x) / x ** 2)},
            "goal": "two_improper_integral_convergence", "primitive": str(primitive),
            "primitive_derivative_checked": True, "endpoint_limits": [str(v) for v in endpoints],
            "integral_values": [str(endpoints[1] - endpoints[0]) if convergent[0] else "DIVERGENT",
                str(endpoints[3] - endpoints[2]) if convergent[1] else "DIVERGENT"],
            "convergent": convergent}, compare)
    return None


def explanation(q, independent):
    adapter = independent.get("adapter")
    if independent.get("status") != "PASS" or adapter not in SOLVERS:
        return None
    proof = independent["proof"]
    if adapter == "hx_infinitesimal_orders_v1":
        text = (f"分别计算三个表达式除以 x 的相应幂后的右侧极限，阶数为 {proof['orders']}，"
            f"非零有限系数为 {proof['nonzero_limit_coefficients']}。因此三个量分别等价于 -x²/2、x^(5/6)、x/3。"
            "对 x→0+，非零常数不改变阶数，指数越小阶越低；5/6<1<2，故从低阶到高阶为 a₂、a₃、a₁")
    elif adapter == "hx_piecewise_primitive_v1":
        option_reasons = []
        for key, check in proof["option_checks"].items():
            if not all(check["derivatives_match"]):
                reason = "分段求导不能得到题设函数"
            elif check["join_values"][0] != check["join_values"][1]:
                reason = f"在 x=1 左右函数值分别为 {check['join_values'][0]} 和 {check['join_values'][1]}，不连续"
            else:
                reason = "两段导数正确，且接点连续、左右导数均为0"
            option_reasons.append(f"{key} 项{reason}")
        text = ("分段积分得左段 (x−1)²+C₁，右段 x ln x−x+C₂。原函数在接点 x=1 必须连续，"
            "所以 C₂=C₁+1；两侧导数在接点都为0，与 f(1)=0 一致。逐项求导并检查接点："
            + "；".join(option_reasons))
    else:
        states = ["收敛" if flag else "发散" for flag in proof["convergent"]]
        limits = [v.replace("-oo", "−∞").replace("oo", "+∞") for v in proof["endpoint_limits"]]
        k = proof["parameters"]["k"]
        formula = rf"$F(x)=-\frac{{e^{{{k}/x}}}}{{{k}}}$"
        finite_values = "；".join(f"积分{'①' if index == 0 else '②'}值为 {value}"
            for index, value in enumerate(proof["integral_values"]) if value != "DIVERGENT")
        text = (f"原函数为 {formula}，其导数等于被积函数。"
            f"按 −∞、0−、0+、+∞ 的顺序，原函数极限依次为 {limits}。"
            f"每个反常积分分别要求自己的两个端点极限有限，故①{states[0]}，②{states[1]}；"
            f"{finite_values}。不能用跨越0的整体端点代入或正负两侧相消替代各自的反常积分判定")
    return text + "。因此答案为 " + str(independent["derived_answer"]) + "。", {"adapter": adapter, "proof": proof}
