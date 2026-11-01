"""Small independently derived problem verifiers, not student-answer graders.

Only whole-statement allowlisted forms are accepted. Unsupported problems are
NOT_APPLICABLE, never sampled into a proof or inferred from a year/question ID.
"""
import re
from backend.services.constant_expression import constant_expression, compare_constant_expressions

VERSION = "bounded-problem-verifiers-v17"


def option_value(raw):
    # Legacy Markdown list separator, recorded as a formatting issue by caller.
    return re.sub(r"\n-\s*$", "", str(raw)).strip()


def _constant_choice(q, target, adapter, proof):
    from sympy import simplify
    values = {k: constant_expression(option_value(v)) for k, v in (q.options or {}).items()}
    if any(v is None for v in values.values()) or not values:
        return {"status": "UNKNOWN", "adapter": adapter, "reason": "option_expression_outside_scope", "proof": proof}
    matches = [k for k,v in values.items() if simplify(v-target) == 0]
    if len(matches) != 1:
        return {"status": "FAIL", "adapter": adapter, "reason": "non_unique_correct_option", "matching_options": matches, "proof": proof}
    expected = matches[0]
    return {"status": "PASS" if q.correct_answer.strip().upper() == expected else "FAIL", "adapter": adapter,
            "reason": "derived_key_matches" if q.correct_answer.strip().upper() == expected else "derived_key_conflict",
            "derived_answer": expected, "matching_options": matches, "proof": proof}


def verify_problem(q):
    from backend.services.phase45hx_exam_verifiers import verify_problem as hx_exam_problem
    exam_result = hx_exam_problem(q)
    if exam_result is not None:
        return exam_result
    from backend.services.phase45hs_verifiers import problem
    historical=problem(q)
    if historical is not None:return historical
    # C6 may select only a registered, inert presentation prefix. Strip that
    # wrapper before whole-statement parsing; arbitrary model-authored wording
    # remains outside verifier scope.
    from backend.services.personal_question_families import strip_registered_wording
    canonical_stem, _wording_id = strip_registered_wording(q.stem or "")
    if canonical_stem != str(q.stem or "").strip():
        from types import SimpleNamespace
        q = SimpleNamespace(stem=canonical_stem, question_type=q.question_type,
            options=q.options, correct_answer=q.correct_answer)
    text = str(q.stem or "").strip()
    compact = re.sub(r"\s+", "", text).replace("−", "-")
    generated = _teaching_family_verifier(q,compact)
    if generated is not None: return generated
    phase45i = __import__("backend.services.phase45i_quality_verifiers", fromlist=["verify_problem"]).verify_problem(q, compact)
    if phase45i is not None: return phase45i
    phase45d = _phase45d_verifiers(q, compact)
    if phase45d is not None: return phase45d
    added = _pilot_verifiers(q, compact)
    if added is not None: return added
    # This exact integral family has a primitive whose derivative and both
    # improper endpoints can be verified. The result is not numeric sampling.
    integral_forms = {
        "计算∫_0^∞ln(1+x)/(1+x)²dx。", "计算∫_0^∞ln(1+x)/(1+x)^2dx。",
        r"计算$\int_0^{+\infty}\frac{\ln(1+x)}{(1+x)^2}\,dx$。",
        r"计算$\int_0^\infty\frac{\ln(1+x)}{(1+x)^2}dx$。",
    }
    if compact in integral_forms and q.question_type in {"fill_blank", "calculation"}:
        from sympy import Symbol, log, diff, simplify, limit, oo
        x = Symbol("x", nonnegative=True)
        f = log(1+x)/(1+x)**2
        primitive = -(log(1+x)+1)/(1+x)
        derivative_ok = simplify(diff(primitive,x)-f) == 0
        low, high = limit(primitive,x,0,dir="+"), limit(primitive,x,oo)
        if not derivative_ok or high.is_finite is not True:
            return {"status":"ERROR","adapter":"log1p_improper_integral_v1","reason":"internal_derivation_check_failed"}
        answer = str(high-low)
        result = compare_constant_expressions(q.correct_answer, answer)
        return {"status":"PASS" if result == "right" else "FAIL" if result == "wrong" else "UNKNOWN",
            "adapter":"log1p_improper_integral_v1", "reason":"derived_key_matches" if result == "right" else "derived_key_conflict" if result == "wrong" else "reference_format_unsupported",
            "derived_answer":answer,"proof":{"assumptions":"x >= 0; exact stated log1p/(1+x)^2 integral",
                "primitive_derivative_checked":True,"lower_limit":str(low),"upper_limit":str(high),
                "scope":"standard answer for this stored statement only; source fidelity separate"}}
    full_tree = re.fullmatch(r"非空完全二叉树所有叶在同层[，,]且每个非叶(?:结点|节点)有2个孩子[；;]若叶数为k[，,]求总(?:结点|节点)数[。.]?",compact)
    if full_tree and q.question_type == "single_choice":
        canonical = {}
        for key, raw in (q.options or {}).items():
            value = re.sub(r"\s+", "",option_value(raw)).strip("$").replace("−","-").replace("×","*")
            canonical[key] = value
        correct = [k for k,v in canonical.items() if v in {"2k-1","2*k-1"}]
        supported = {"2k-1","2*k-1","2k","2*k","k²","k^2","2^k-1"}
        if any(v not in supported for v in canonical.values()):
            return {"status":"UNKNOWN","adapter":"full_binary_tree_edges_v1","reason":"option_formula_outside_scope"}
        if len(correct) != 1:
            return {"status":"FAIL","adapter":"full_binary_tree_edges_v1","reason":"non_unique_correct_option","matching_options":correct}
        right = q.correct_answer.strip().upper() == correct[0]
        return {"status":"PASS" if right else "FAIL","adapter":"full_binary_tree_edges_v1",
            "reason":"derived_key_matches" if right else "derived_key_conflict","derived_answer":correct[0],
            "matching_options":correct,"proof":{"identity":"n-1=2*n2; n=k+n2 => n=2*k-1",
                "premises":"nonempty tree; every nonleaf has exactly two children; k leaves",
                "other_options":"other supported formulae fail for admissible k=4; samples reject them, do not prove the true identity"}}
    storage_index = re.fullmatch(
        r"在按1开始下标顺序存储[、,]共有(\d{1,5})个结点的完全二叉树中[，,]结点i=(\d{1,5})的(双亲|左孩子|右孩子)下标是多少[？?。.]?", compact)
    if storage_index and q.question_type in {"single_choice", "fill_blank", "calculation"}:
        node_count, index = int(storage_index[1]), int(storage_index[2])
        relation = storage_index[3]
        if not 1 <= node_count <= 10000 or not 1 <= index <= node_count:
            return {"status":"NOT_APPLICABLE", "adapter":"phase45d_complete_tree_storage_index_v1", "reason":"node_index_outside_bound"}
        if relation == "双亲":
            if index == 1:
                return {"status":"NOT_APPLICABLE", "adapter":"phase45d_complete_tree_storage_index_v1", "reason":"root_has_no_parent"}
            target = index // 2
        else:
            target = 2*index if relation == "左孩子" else 2*index+1
            if target > node_count:
                return {"status":"NOT_APPLICABLE", "adapter":"phase45d_complete_tree_storage_index_v1", "reason":"requested_child_does_not_exist"}
        proof={"node_count":node_count,"index":index,"relation":relation,
            "indexing":"1-based sequential storage","derived_index":target,
            "rules":{"parent":"floor(i/2)","left_child":"2i","right_child":"2i+1"}}
        if q.question_type == "single_choice":
            return _constant_choice(q,target,"phase45d_complete_tree_storage_index_v1",proof)
        return _derived_constant(q,target,"phase45d_complete_tree_storage_index_v1",proof)
    numeric_full_tree = re.fullmatch(
        r"非空二叉树每个非叶结点恰有2个孩子[，,]叶结点数为k[，,]若k=(\d{1,4})[，,]求总结点数[。?]", compact)
    if numeric_full_tree and q.question_type in {"single_choice", "fill_blank", "calculation"}:
        leaves = int(numeric_full_tree.group(1))
        if not 1 <= leaves <= 5000:
            return {"status":"NOT_APPLICABLE", "adapter":"phase45d_full_tree_count_v1", "reason":"leaf_count_outside_bound"}
        target = 2*leaves-1
        proof = {"nonleaf_nodes":leaves-1,"leaf_nodes":leaves,"total_nodes":target,
                 "identity":"n-1=2*n2 and n=k+n2, hence n=2k-1"}
        if q.question_type == "single_choice":
            return _constant_choice(q, target, "phase45d_full_tree_count_v1", proof)
        return _derived_constant(q, target, "phase45d_full_tree_count_v1", proof)
    complete = re.fullmatch(r"(?:一棵|某)?(?:有|含有|共有)(\d{1,5})个(?:结点|节点)的完全二叉树[，,]其叶(?:结点|节点)(?:数|个数)(?:为多少|为|是)[？?。.]?",compact)
    if complete and q.question_type in {"single_choice", "fill_blank", "calculation"}:
        n = int(complete.group(1))
        if not 1 <= n <= 10000:
            return {"status":"NOT_APPLICABLE","adapter":"complete_tree_index_v1","reason":"node_count_outside_bound"}
        from sympy import Integer
        leaves = sum(2*i > n for i in range(1,n+1))
        proof={"n":n,"algorithm":"1-based indices; node i is a leaf iff 2*i > n","enumeration_complete":True}
        if q.question_type == "single_choice":
            return _constant_choice(q,Integer(leaves),"complete_tree_index_v1",proof)
        return _derived_constant(q,Integer(leaves),"complete_tree_index_v1",proof)
    calc = re.fullmatch(r"(?:计算|求)(?:式)?\s*(.+?)\s*(?:的值|的结果)?\s*(?:是|为)?\s*[（(]\s*[）)]\s*[。.]?",text)
    if calc is None:
        calc = re.fullmatch(r"(?:计算|Compute)\s*(.+?)\s*(?:的值)?[。.]?",text)
    if calc and q.question_type in {"single_choice","fill_blank","calculation"}:
        target = constant_expression(calc.group(1))
        if target is not None:
            proof = {"scope":"entire bounded constant expression extracted from statement",
                     "arithmetic":"exact rational/constants, no free variables, no eval"}
            if q.question_type == "single_choice":
                return _constant_choice(q,target,"bounded_constant_problem_v1",proof)
            from sympy import simplify
            reference = constant_expression(q.correct_answer)
            difference = simplify(reference-target) if reference is not None else None
            verdict = "unknown" if difference is None else "right" if difference==0 else "wrong" if difference.is_zero is False else "unknown"
            return {"status":"PASS" if verdict == "right" else "FAIL" if verdict == "wrong" else "UNKNOWN",
                    "adapter":"bounded_constant_problem_v1","reason":"derived_key_matches" if verdict == "right" else "derived_key_conflict" if verdict == "wrong" else "reference_format_unsupported",
                    "derived_answer":str(target),"proof":proof}
    return {"status":"NOT_APPLICABLE","adapter":None,"reason":"statement_outside_allowlisted_verifier_scope"}


def _phase45d_verifiers(q, compact):
    """Small exact-verifier families for the bounded Phase 4.5D foundation pilot.

    Each adapter accepts a complete, explicit statement form only.  It proves
    the stored answer for that form; it does not verify historical provenance,
    redistribution rights, or a student's broader mastery.
    """
    import re
    from fractions import Fraction
    if q.question_type not in {"single_choice", "fill_blank", "calculation"}:
        return None

    # 2x2 determinant with all four signed integer entries stated explicitly.
    match = re.fullmatch(
        r"计算二阶行列式D=\|ab;cd\|，其中a=(-?\d{1,3})，b=(-?\d{1,3})，c=(-?\d{1,3})，d=(-?\d{1,3})[。.]?", compact)
    if match:
        a, b, c, d = map(int, match.groups())
        target = a*d-b*c
        proof = {"adapter_scope":"2x2 determinant with explicit integer entries", "matrix":[[a,b],[c,d]],
                 "formula":"ad-bc", "derived_value":target}
        if q.question_type == "single_choice":
            return _constant_choice(q, target, "phase45d_determinant_2x2_v1", proof)
        return _derived_constant(q, target, "phase45d_determinant_2x2_v1", proof)

    # Nonsingular 2x2 linear system, positive integer coefficients and explicit
    # right-hand sides; solution is independently recovered by Cramer's rule.
    match = re.fullmatch(
        r"解方程组：(-?\d{1,3})x\+(-?\d{1,3})y=(-?\d{1,4})；(-?\d{1,3})x\+(-?\d{1,3})y=(-?\d{1,4})[。.]?(求\(x,y\)|求x的值)[。.]?", compact)
    if match and q.question_type in {"single_choice", "fill_blank", "calculation"}:
        a, b, e, c, d, f = map(int, match.groups()[:6])
        asks_pair = match.group(7) == "求(x,y)"
        determinant = a*d-b*c
        if determinant == 0:
            return {"status":"FAIL", "adapter":"phase45d_linear_system_2x2_v1", "reason":"singular_system"}
        x = Fraction(e*d-b*f, determinant)
        y = Fraction(a*f-e*c, determinant)
        def fmt(value):
            return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
        expected = f"({fmt(x)},{fmt(y)})"
        proof = {"coefficients":[[a,b],[c,d]], "right_hand_side":[e,f], "determinant":determinant,
            "solution":[fmt(x),fmt(y)], "method":"Cramer's rule; exact rational arithmetic"}
        if q.question_type in {"fill_blank", "calculation"}:
            if asks_pair:
                return {"status":"NOT_APPLICABLE", "adapter":"phase45d_linear_system_2x2_v1", "reason":"pair_answer_has_no_safe_final_comparer"}
            return _derived_constant(q,x,"phase45d_linear_system_2x2_v1",proof)
        if not asks_pair:
            return {"status":"NOT_APPLICABLE", "adapter":"phase45d_linear_system_2x2_v1", "reason":"question_type_and_requested_value_mismatch"}
        values = {}
        for key, raw in (q.options or {}).items():
            normalized = re.sub(r"\s+", "", option_value(raw)).replace("（", "(").replace("）", ")")
            values[key] = normalized
        matches = [key for key, value in values.items() if value == expected]
        return _derived_choice(q, matches, "phase45d_linear_system_2x2_v1", proof)

    # Binary search comparison count.  Indexing, interval and midpoint rule are
    # part of the stem to avoid implementation-convention ambiguity.
    match = re.fullmatch(
        r"在升序数组\[([0-9,]+)\]中，按1起始下标执行二分查找：初始low=1、high=n，mid=floor\(\(low\+high\)/2\)，使用闭区间[，,]目标值为(-?\d{1,5})且保证存在[；;]求成功前的关键字比较次数[？?。.]?", compact)
    if match:
        values = [int(part) for part in match.group(1).split(",")]
        target = int(match.group(2))
        if not values or len(values) > 63 or values != sorted(set(values)) or target not in values:
            return {"status":"FAIL", "adapter":"phase45d_binary_search_steps_v1", "reason":"invalid_search_fixture"}
        low, high, trace = 0, len(values)-1, []
        while low <= high:
            middle = (low+high)//2
            trace.append({"index_1_based":middle+1, "value":values[middle]})
            if values[middle] == target: break
            if values[middle] < target: low = middle+1
            else: high = middle-1
        proof = {"array_length":len(values), "target":target, "compared":trace,
                 "indexing":"1-based in statement; 0-based internal translation", "midpoint":"floor((low+high)/2)",
                 "closed_interval":True}
        if q.question_type=="single_choice": return _constant_choice(q, len(trace), "phase45d_binary_search_steps_v1", proof)
        return _derived_constant(q,len(trace),"phase45d_binary_search_steps_v1",proof)

    # FIFO/LRU page replacement, explicitly initialized empty.
    match = re.fullmatch(
        r"采用(FIFO|LRU)页面置换算法，内存有([1-8])个页框且初始为空，访问序列为([0-9,]+)，求缺页次数[？?。.]?", compact)
    if match:
        algorithm, capacity, raw_refs = match.groups()
        refs = [int(part) for part in raw_refs.split(",")]
        if len(refs) < 2 or len(refs) > 40:
            return {"status":"NOT_APPLICABLE", "adapter":"phase45d_page_replacement_v1", "reason":"reference_string_outside_bound"}
        frames, misses, trace = [], 0, []
        for page in refs:
            if page not in frames:
                misses += 1
                if len(frames) >= int(capacity): frames.pop(0)
                frames.append(page)
                trace.append({"page":page,"fault":True,"frames":list(frames)})
            else:
                if algorithm == "LRU":
                    frames.remove(page); frames.append(page)
                trace.append({"page":page,"fault":False,"frames":list(frames)})
        proof={
            "algorithm":algorithm, "capacity":int(capacity), "references":refs,
            "fault_count":misses, "trace":trace,
            "replacement_order":"FIFO arrival order" if algorithm == "FIFO" else "least-recently-used at front"}
        if q.question_type=="single_choice": return _constant_choice(q, misses, "phase45d_page_replacement_v1", proof)
        return _derived_constant(q,misses,"phase45d_page_replacement_v1",proof)

    # Traditional IPv4 usable-host count: network and broadcast addresses are
    # excluded; /31 and /32 are deliberately outside this verifier.
    match = re.fullmatch(
        r"某IPv4子网前缀长度为/(\d{1,2})，按排除网络地址和广播地址的普通子网规则，可分配主机地址数是多少[？?。.]?", compact)
    if match:
        prefix = int(match.group(1))
        if not 1 <= prefix <= 30:
            return {"status":"NOT_APPLICABLE", "adapter":"phase45d_subnet_host_count_v1", "reason":"prefix_outside_conventional_subnet_bound"}
        count = 2**(32-prefix)-2
        proof={
            "prefix_length":prefix, "host_bits":32-prefix, "formula":"2^(32-prefix)-2",
            "assumption":"conventional subnet; network and broadcast excluded"}
        if q.question_type=="single_choice": return _constant_choice(q, count, "phase45d_subnet_host_count_v1", proof)
        return _derived_constant(q,count,"phase45d_subnet_host_count_v1",proof)

    # FCFS mean waiting time with all arrival times zero, no context switching.
    match = re.fullmatch(
        r"所有进程到达时间均为0，按给定顺序采用FCFS调度，运行时间依次为([1-9][0-9]*(?:,[1-9][0-9]*){1,7})，平均等待时间是多少[？?。.]?", compact)
    if match and q.question_type in {"fill_blank", "calculation"}:
        bursts = [int(part) for part in match.group(1).split(",")]
        waiting = sum(sum(bursts[:index]) for index in range(len(bursts)))
        target = Fraction(waiting, len(bursts))
        proof = {"algorithm":"FCFS", "all_arrival_times":0, "burst_times":bursts,
                 "waiting_times":[sum(bursts[:index]) for index in range(len(bursts))],
                 "total_waiting_time":waiting, "process_count":len(bursts), "mean_waiting_time":str(target)}
        return _derived_constant(q, target, "phase45d_fcfs_waiting_time_v1", proof)

    # Parameterized improper integral with its domain made explicit. For a>-2,
    # integral = ln(1+a/2); m>1 gives the unique a=2(m-1).
    match = re.fullmatch(
        r"设积分∫_1\^∞a/\[x\(2x\+a\)\]dx=ln\((\d{1,2})\)，且a>-2，求a[。?]", compact)
    if match and q.question_type in {"fill_blank", "calculation"}:
        m = int(match.group(1))
        if not 2 <= m <= 99:
            return {"status":"NOT_APPLICABLE", "adapter":"phase45d_improper_integral_parameter_v1", "reason":"log_target_outside_bound"}
        target = 2*(m-1)
        proof = {"integrand":"a/[x(2x+a)]", "interval":"[1,+infinity)", "domain":"a>-2",
                 "primitive":"ln(x)-ln(2x+a)", "integral":"ln(1+a/2)",
                 "target":"ln(m)", "derived_parameter":target, "uniqueness":"strict monotonicity for a>-2"}
        return _derived_constant(q, target, "phase45d_improper_integral_parameter_v1", proof)

    # Signed n-bit subtraction result only (overflow is not requested), so a
    # numeric blank can be graded exactly without hiding the OF concept.
    match = re.fullmatch(
        r"假设(2|4|8|16)位字长计算机中，带符号整数x、y的补码分别为`\[x\]补=([0-9A-F]{1,4})H`、`\[y\]补=([0-9A-F]{1,4})H`，计算x-y并按\d+位补码解释，所得带符号整数为多少[？?。.]?", compact)
    if match and q.question_type in {"fill_blank", "calculation"}:
        bits, xs, ys=int(match.group(1)),int(match.group(2),16),int(match.group(3),16)
        modulus=1<<bits
        if max(xs,ys)>=modulus:
            return {"status":"UNKNOWN","adapter":"phase45d_signed_subtract_value_v1","reason":"encoding_outside_declared_word_size"}
        signed=lambda raw:raw-modulus if raw>=modulus//2 else raw
        x,y=signed(xs),signed(ys); exact=x-y
        wrapped=exact%modulus; wrapped=wrapped-modulus if wrapped>=modulus//2 else wrapped
        return _derived_constant(q,wrapped,"phase45d_signed_subtract_value_v1",{
            "bits":bits,"x":x,"y":y,"exact_difference":exact,"wrapped_signed":wrapped,
            "overflow":not -modulus//2<=exact<modulus//2,
            "scope":"only requested signed result; overflow reasoning shown in explanation, not graded"})

    # Signed fixed-point decoding with the interpretation convention stated
    # directly in the stem. Hex/binary parsing is bounded to at most 16 bits.
    original = re.fullmatch(
        r"按原码解释（最高位为符号位、其余位表示绝对值）[，,]字长为(\d{1,2})位[，,]编码([01]+)表示的十进制整数是多少[？?。.]?", compact)
    ones = re.fullmatch(
        r"按反码解释（正数编码同原码、负数由正数码逐位取反）[，,]字长为(\d{1,2})位[，,]编码([01]+)表示的十进制整数是多少[？?。.]?", compact)
    biased = re.fullmatch(
        r"按移码解释（真值=无符号编码值-2\^\(n-1\)）[，,]字长为(\d{1,2})位[，,]编码([01]+)表示的十进制整数是多少[？?。.]?", compact)
    encoding = original or ones or biased
    if encoding and q.question_type in {"fill_blank", "calculation"}:
        bits, raw = int(encoding[1]), encoding[2]
        if not 2 <= bits <= 16 or len(raw) != bits:
            return {"status":"NOT_APPLICABLE", "adapter":"phase45d_fixed_point_decode_v1", "reason":"word_size_or_encoding_length_outside_bound"}
        unsigned = int(raw,2)
        if original:
            magnitude = unsigned & ((1 << (bits-1))-1)
            target = -magnitude if raw[0] == "1" else magnitude
            mode = "sign_magnitude"
        elif ones:
            magnitude = ((1 << (bits-1))-1) ^ (unsigned & ((1 << (bits-1))-1)) if raw[0] == "1" else unsigned
            target = -magnitude if raw[0] == "1" else magnitude
            mode = "ones_complement"
        else:
            bias = 1 << (bits-1)
            target = unsigned - bias
            mode = "biased_code"
        return _derived_constant(q,target,"phase45d_fixed_point_decode_v1",{
            "encoding":mode,"bits":bits,"raw_bits":raw,"unsigned_value":unsigned,
            "interpreted_value":target,"convention":"explicitly stated in problem stem"})
    return None


def _derived_constant(q, target, adapter, proof):
    from sympy import simplify
    reference=constant_expression(q.correct_answer)
    delta=simplify(reference-target) if reference is not None else None
    status="UNKNOWN" if delta is None or delta.is_zero is None else "PASS" if delta==0 else "FAIL"
    return {"status":status,"adapter":adapter,"reason":"derived_key_matches" if status=="PASS" else
        "derived_key_conflict" if status=="FAIL" else "reference_format_unsupported",
        "derived_answer":str(target),"proof":proof}


def _pilot_verifiers(q, compact):
    """Whole-statement forms observed in B3; no question-ID answer lookup."""
    if q.question_type=="fill_blank" and compact == r"$f(x,y)$可微，且$df(0,0)=\pidx+3dy,g(x)=f(\lnx,\sin\pix)$，计算$g'(1)=\underline{\quad\quad\quad\quad}$.":
        from sympy import pi
        return _derived_constant(q,-2*pi,"chain_differential_v1",{
            "premises":"differentiable f; partial derivatives at (0,0): pi and 3",
            "chain_rule":"ln(1)=sin(pi)=0; g'(1)=pi*1+3*pi*cos(pi)=-2*pi"})
    if q.question_type in {"fill_blank","single_choice"} and compact == r"已知$f(x)=x^2(e^x-1)$，求$f^{(5)}(1)$。":
        from sympy import Symbol,exp,diff,E
        x=Symbol("x",real=True); target=diff(x**2*(exp(x)-1),x,5).subs(x,1)
        proof={
            "order":5,"point":1,"rule":"exact repeated differentiation of entire stated expression",
            "crosscheck":"Leibniz: (x^2+10*x+20)*exp(x) at 1 =31*e"}
        return _constant_choice(q,target,"polynomial_exponential_derivative_v1",proof) if q.question_type=="single_choice" else _derived_constant(q,target,"polynomial_exponential_derivative_v1",proof)
    if q.question_type=="fill_blank" and compact == r"设$\int_1^{+\infty}\frac{a}{x(2x+a)}\,dx=\ln2$，则$a=$____。":
        from sympy import Integer
        return _derived_constant(q,Integer(2),"rational_improper_parameter_v1",{
            "domain":"a>-2; a<=-2 has endpoint/interior singularity",
            "primitive":"log(x)-log(2*x+a); derivative=a/(x*(2*x+a))",
            "endpoint_value":"log(1+a/2); strictly increasing on a>-2",
            "unique_solution":"log(1+a/2)=log(2) => a=2"})
    if q.question_type=="single_choice" and compact=="下列数中不能由IEEE754二进制浮点格式精确表示的是？":
        from fractions import Fraction
        values={}
        for key,value in (q.options or {}).items():
            raw=option_value(value).strip("$")
            if not re.fullmatch(r"[+-]?\d{1,6}(?:\.\d{1,6})?",raw): return {"status":"UNKNOWN","adapter":"binary_rational_v1","reason":"option_expression_outside_scope"}
            f=Fraction(raw); d=f.denominator
            # Dyadic alternatives within single-precision magnitude/significand
            # bounds; non-dyadic numbers cannot be exact at any binary precision.
            if d&(d-1)==0 and (abs(f.numerator).bit_length()>24 or d.bit_length()>24):
                return {"status":"UNKNOWN","adapter":"binary_rational_v1","reason":"precision_bound_not_verified"}
            values[key]={"denominator":d,"finite_binary":d&(d-1)==0}
        matches=[k for k,v in values.items() if not v["finite_binary"]]
        return _derived_choice(q,matches,"binary_rational_v1",{"rational_denominator_test":values})
    numeric_range=re.fullmatch(r"(\d{1,2})位补码所能表示的(最小|最大)整数是多少[？?。.]?",compact)
    if numeric_range and q.question_type in {"fill_blank", "calculation"}:
        bits=int(numeric_range[1])
        if not 2<=bits<=64:
            return {"status":"NOT_APPLICABLE","adapter":"twos_complement_range_v1","reason":"word_size_outside_bound"}
        low,high=-(1<<(bits-1)),(1<<(bits-1))-1
        target=low if numeric_range[2]=="最小" else high
        return _derived_constant(q,target,"twos_complement_range_v1",{
            "bits":bits,"minimum":low,"maximum":high,
            "requested_endpoint":"minimum" if numeric_range[2]=="最小" else "maximum",
            "reason":"signed n-bit value = -b(n-1)*2^(n-1)+lower bits"})
    if q.question_type=="single_choice" and re.fullmatch(r"(\d{1,2})位补码所能表示的整数范围是[（(][）)][。.]?",compact):
        bits=int(re.match(r"\d+",compact)[0])
        if not 2<=bits<=64: return {"status":"NOT_APPLICABLE","adapter":None,"reason":"word_size_outside_bound"}
        low,high=-(1<<(bits-1)),(1<<(bits-1))-1
        pairs={}
        from sympy import Integer
        for key,value in (q.options or {}).items():
            parts=re.split(r"～|~",option_value(value).strip("$"))
            if len(parts)!=2: return {"status":"UNKNOWN","adapter":"twos_complement_range_v1","reason":"range_format_outside_scope"}
            def range_value(v):
                raw=v.replace("−","-").replace(" ","")
                m=re.fullmatch(r"(-?)2\^(\d{1,2})(-1)?",raw)
                if not m or not 0<=int(m[2])<=64: return None
                return Integer((-1 if m[1] else 1)*(1<<int(m[2]))-(1 if m[3] else 0))
            pairs[key]=[range_value(v) for v in parts]
            if any(v is None for v in pairs[key]): return {"status":"UNKNOWN","adapter":"twos_complement_range_v1","reason":"range_format_outside_scope"}
        return _derived_choice(q,[k for k,p in pairs.items() if p==[Integer(low),Integer(high)]],"twos_complement_range_v1",
            {"bits":bits,"minimum":low,"maximum":high,"reason":"signed n-bit value = -b(n-1)*2^(n-1)+lower bits"})
    form=re.fullmatch(r"假设(\d{1,2})位字长计算机中，带符号整数x、y的补码分别为`\[x\]补=([0-9A-F]{1,4})H`、`\[y\]补=([0-9A-F]{1,4})H`，通过补码加减运算器得到x-y的值及OF标志分别为[：:]",compact)
    if form and q.question_type=="single_choice":
        bits=int(form[1]); modulus=1<<bits if 2<=bits<=16 else 0
        xs,ys=int(form[2],16),int(form[3],16)
        if not modulus or max(xs,ys)>=modulus: return {"status":"UNKNOWN","adapter":"twos_complement_subtract_v1","reason":"word_size_or_encoding_invalid"}
        signed=lambda v:v-modulus if v>=modulus//2 else v
        x,y=signed(xs),signed(ys); exact=x-y; wrapped=signed(exact%modulus)
        overflow=int(not -modulus//2<=exact<modulus//2)
        matches=[]
        for k,v in (q.options or {}).items():
            m=re.fullmatch(r"([+-]?\d{1,6})[，,]([01])",re.sub(r"\s+","",option_value(v)))
            if m is None: return {"status":"UNKNOWN","adapter":"twos_complement_subtract_v1","reason":"option_expression_outside_scope"}
            if (int(m[1]),int(m[2]))==(wrapped,overflow): matches.append(k)
        return _derived_choice(q,matches,"twos_complement_subtract_v1",{"bits":bits,"x":x,"y":y,"exact_difference":exact,"wrapped_signed":wrapped,"OF":overflow})
    return None


def _derived_choice(q,matches,adapter,proof):
    if len(matches)!=1:
        return {"status":"FAIL","adapter":adapter,"reason":"non_unique_correct_option","matching_options":matches,"proof":proof}
    right=q.correct_answer.strip().upper()==matches[0]
    return {"status":"PASS" if right else "FAIL","adapter":adapter,"reason":"derived_key_matches" if right else "derived_key_conflict",
            "derived_answer":matches[0],"matching_options":matches,"proof":proof}


def _teaching_family_verifier(q,text):
    from sympy import Rational,Symbol,diff,exp,limit,sin,log
    if q.question_type not in {"single_choice","fill_blank","calculation"}: return None
    m=re.fullmatch(r"求函数f\(x\)=x\^(\d)在x=([1-5])处的导数[。.]?",text)
    if m and 1<=int(m[1])<=5:
        n,t=map(int,m.groups()); x=Symbol("x",real=True); target=diff(x**n,x).subs(x,t)
        proof={"family":"power_derivative","n":n,"point":t,"formula":"n*x^(n-1)","derived_value":str(target)}
    else:
        m=re.fullmatch(r"计算∫_0\^([1-5])x\^([1-5])dx[。.]?",text)
        if m:
            b,n=map(int,m.groups()); target=Rational(b**(n+1),n+1)
            proof={"family":"power_integral","degree":n,"bounds":[0,b],"primitive":"x^(n+1)/(n+1)","derived_value":str(target)}
        else:
            m=re.fullmatch(r"求极限lim\(x→0\)\(e\^\(([1-5])\*x\)-1\)/x[。.]?",text)
            if m:
                a=int(m[1]); x=Symbol("x",real=True); target=limit((exp(a*x)-1)/x,x,0)
                proof={"family":"exp_limit","form":"(exp(a*x)-1)/x","coefficient":a,"domain":"punctured neighborhood of 0","derived_value":str(target)}
            else:
                m=re.fullmatch(r"求极限lim\(x→0\)sin\(([1-5])\*x\)/x[。.]?",text)
                if m:
                    a=int(m[1]); x=Symbol("x",real=True); target=limit(sin(a*x)/x,x,0)
                    proof={"family":"exp_limit","form":"sin(a*x)/x","coefficient":a,"domain":"punctured neighborhood of 0","derived_value":str(target)}
                else:
                    m=re.fullmatch(r"求极限lim\(x→0\)ln\(1\+([1-5])\*x\)/x[。.]?",text)
                    if not m:return None
                    a=int(m[1]); x=Symbol("x",real=True); target=limit(log(1+a*x)/x,x,0)
                    proof={"family":"exp_limit","form":"ln(1+a*x)/x","coefficient":a,"domain":"x near 0 with 1+a*x>0","derived_value":str(target)}
    return _constant_choice(q,target,"teaching_family_v1",proof) if q.question_type=="single_choice" else _derived_constant(q,target,"teaching_family_v1",proof)
