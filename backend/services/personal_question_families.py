"""Versioned registry of personal-question families with bounded solvers.

This registry is deliberately keyed by canonical knowledge-point codes, not
display-name keywords. A model call is allowed only when the exact node,
question type, and canonical stem contract are all registered.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import random
import re


VERSION = "personal-question-family-registry-v3"
PROBLEM_SPEC_VERSION = "personal-problem-spec-v2"
PROBLEM_SPEC_VERIFIER_VERSION = "personal-problem-spec-verifier-v2"

SAFE_WORDING_PREFIXES = {
    "direct": "",
    "guided": "请先辨认本题适用的知识规则，再根据题目条件作答：",
    "condition_first": "请根据以下给定条件完成题目：",
}

TEACHING_FOCI = ("method", "common_pitfall", "self_check")

# Higher cognitive levels are offered only where the solver-backed spec really
# changes the task structure, not merely the number written in the stem.
SUPPORTED_DIFFICULTIES = {
    "power_derivative": frozenset({"basic", "improved", "comprehensive"}),
    "power_integral": frozenset({"basic", "improved", "comprehensive"}),
    "page_replacement_faults": frozenset({"basic", "improved", "comprehensive"}),
    "binary_float": frozenset({"basic", "improved", "comprehensive"}),
}

_PITFALLS = {
    "power_derivative": "常见检查：逐项求导时，幂指数要减1，系数要乘原指数。",
    "power_integral": "常见检查：上下限代入后，结果应为上限原函数值减下限原函数值。",
    "improper_integral_parameter": "常见检查：临界参数要单独检查，不能只看远离边界时的情形。",
    "exp_limit": "常见检查：保留分子中首个未消去项，再与分母阶数比较。",
    "determinant_2x2": "常见检查：按主对角线乘积减去副对角线乘积，顺序不要颠倒。",
    "complete_tree": "常见检查：先确认题目说的是完全二叉树，再区分叶结点和非叶结点。",
    "signed_range": "常见检查：n位补码的正负端点不对称，负端点的绝对值多1。",
    "binary_float": "常见检查：分别读出符号、阶码和尾数，再依题目指定的IEEE 754格式还原。",
    "binary_search_steps": "常见检查：题目问的是成功查找还是失败查找，以及比较次数还是层数。",
    "page_replacement_faults": "常见检查：FIFO看装入先后，LRU看最近一次访问时间。",
}

_SELF_CHECKS = {
    "power_derivative": "自检：对结果逐项求导或代入题目指定点，确认每一项都对应原函数。",
    "power_integral": "自检：把原函数代入两个端点，并检查积分区间方向。",
    "improper_integral_parameter": "自检：把临界参数代回原积分，单独核对边界是否收敛。",
    "exp_limit": "自检：检查展开保留的最低非零阶与分母阶数一致。",
    "determinant_2x2": "自检：交换两列后行列式应变号，可用来检查乘积顺序。",
    "complete_tree": "自检：把结点数代回叶结点计数规则，检查奇数与偶数情形。",
    "signed_range": "自检：确认区间含有2^n个编码，并且两端均包含。",
    "binary_float": "自检：把得到的符号、有效数和阶码代回格式定义。",
    "binary_search_steps": "自检：只在题目声明的成功查找范围内核对最深比较路径。",
    "page_replacement_faults": "自检：逐次访问并更新页框状态，命中不计缺页。",
}


@dataclass(frozen=True)
class FamilySpec:
    family_id: str
    subject: str
    node_codes: tuple[str, ...]
    question_types: tuple[str, ...]
    stem_template: str
    parameter_bounds: str
    solver: str
    choice_check: str
    answer_comparer: str
    explanation_checks: str
    unsupported: str
    adapters: tuple[str, ...]


@dataclass(frozen=True)
class ProblemSpec:
    """Server-authored, independently solved instance for one bounded family."""

    family_id: str
    subject: str
    knowledge_node_code: str
    question_type: str
    difficulty: str
    parameters: dict
    constraints: dict
    canonical_problem: str
    canonical_answer: str
    options: dict[str, str] | None
    grading_method: str
    verification_metadata: dict
    generation_seed: str
    spec_version: str = PROBLEM_SPEC_VERSION

    def as_dict(self) -> dict:
        return {
            "family_id": self.family_id,
            "subject": self.subject,
            "knowledge_node_code": self.knowledge_node_code,
            "question_type": self.question_type,
            "difficulty": self.difficulty,
            "parameters": self.parameters,
            "constraints": self.constraints,
            "canonical_problem": self.canonical_problem,
            "canonical_answer": self.canonical_answer,
            "options": self.options,
            "grading_method": self.grading_method,
            "verification_metadata": self.verification_metadata,
            "generation_seed": self.generation_seed,
            "spec_version": self.spec_version,
        }


FAMILIES: dict[str, FamilySpec] = {
    "power_derivative": FamilySpec(
        "power_derivative", "数学二", ("math.exam.de439863790e",),
        ("single_choice", "fill_blank"),
        "设函数f(x)={整数系数的一元多项式}，求f'(x)。",
        "次数1–12；至多16项；整数系数绝对值≤1,000,000。",
        "对整段显式多项式使用精确符号求导；系数与次数有界。",
        "逐项解析A-D多项式并与导数比较，必须恰好一个相等项。",
        "填空答案解析为同一有界多项式。",
        "final_value须等价于独立导数；可选steps只写可精确计算的数值等式。",
        "复合函数、分段函数、隐函数、参数求导及非多项式不支持。",
        ("phase45i_polynomial_derivative_v1", "phase45i_polynomial_derivative_value_v1"),
    ),
    "power_integral": FamilySpec(
        "power_integral", "数学二", ("math.exam.c431f98f817c",),
        ("single_choice", "fill_blank"),
        "计算定积分：∫_a^b {整数系数的一元多项式} dx = ______。",
        "端点绝对值≤100且a<b；次数≤12；至多16项；系数绝对值≤1,000,000。",
        "对显式有界整数多项式作精确原函数积分并代入有界整数端点。",
        "数值选项须全部可精确解析且恰好一项等于积分值。",
        "填空用精确有理数/有限小数比较。",
        "final_value须与独立积分值一致；可选steps只写可精确计算的数值等式。",
        "无理/三角/分段被积函数、无穷区间或未声明变量不支持。",
        ("phase45i_polynomial_definite_integral_v1",),
    ),
    "improper_integral_parameter": FamilySpec(
        "improper_integral_parameter", "数学二", ("math.exam.fd2f9e3739d9",),
        ("single_choice",),
        "关于含参数p的反常积分I(p)=∫_e^{+∞} dx/[x(ln x)^p]，下列结论正确的是（ ）。",
        "固定积分族；四个选项须表达互斥且完备的收敛条件，覆盖p=0、1、2边界检查。",
        "令t=ln x归约到∫_1^∞t^(-p)dt，推出收敛当且仅当p>1。",
        "对每个条件选项作有界反例检查，并要求恰好一个真命题。",
        "填空答案仅支持该积分族的p阈值条件。",
        "final_value须等价于p>1；步骤限于可核验的数值/等式。",
        "其他被积函数、下限、对数幂结构及一般参数积分不支持。",
        ("phase45i_log_improper_integral_p_test_v1",),
    ),
    "exp_limit": FamilySpec(
        "exp_limit", "数学二", ("math.exam.c5c672022b7f",),
        ("single_choice", "fill_blank"),
        r"计算极限：\lim_{x\to 0}\frac{e^{a x}-1-a x}{x^2}=____。",
        "整数a∈[1,100]；不得改变趋近点、分子消去项或分母阶数。",
        "用精确二阶泰勒系数求极限a²/2。",
        "数值选项精确解析并检查恰好一个正确选项。",
        "填空答案使用精确整数、分数或等价有限小数。",
        "final_value须与a²/2一致；可选steps只写精确常数算术。",
        "其他指数/对数/三角极限、不同阶数或非零趋近点不支持。",
        ("phase45i_exp_second_order_limit_v1",),
    ),
    "determinant_2x2": FamilySpec(
        "determinant_2x2", "数学二", ("math.exam.f4e5ed0360ea",),
        ("single_choice", "fill_blank"),
        "计算二阶行列式，其中第一行是a、b，第二行是c、d。",
        "矩阵必须为2×2，四个显式整数元素绝对值≤1,000。",
        "精确计算ad−bc。",
        "数值选项精确解析并检查恰好一个正确选项。",
        "填空答案使用精确整数。",
        "final_value须与ad−bc一致；可选steps只写精确整数乘加。",
        "符号矩阵、不等式、参数矩阵、三阶及以上行列式不支持。",
        ("phase45i_determinant_2x2_numeric_v1",),
    ),
    "complete_tree": FamilySpec(
        "complete_tree", "408", ("cs408.ds.topic.1efaf3d00b50",),
        ("single_choice", "fill_blank"),
        "一棵完全二叉树共有n个结点，则其叶子结点数为（ ）。",
        "整数n∈[1,1,000,000]；按层序顺序存储且根编号为1。",
        "叶数n−floor(n/2)，等价于ceil(n/2)。",
        "数值选项精确解析并检查恰好一个正确选项。",
        "填空答案使用精确整数。",
        "final_value须与独立叶数一致；步骤仅写可精确计算的整数式。",
        "满/完全二叉树以外的树、不同存储/编号约定及需要拓扑图的题目不支持。",
        ("phase45i_complete_tree_leaf_count_v1", "phase45d_complete_tree_storage_index_v1"),
    ),
    "signed_range": FamilySpec(
        "signed_range", "408", ("cs408.co.topic.324b03e7b481",),
        ("single_choice", "fill_blank"),
        "设机器字长为n位，采用补码表示定点整数，则可表示的十进制整数范围是____（用闭区间表示）。",
        "整数n∈[2,64]；明确是有符号二进制补码，不得混用原码/反码/移码。",
        "精确给出[-2^(n-1), 2^(n-1)-1]。",
        "每个选项的端点和闭区间符号均解析，恰好一个范围匹配。",
        "填空答案按有序闭区间精确比较。",
        "final_value须与独立边界一致；可选steps只写精确整数幂。",
        "编码解码、溢出、定点小数及其他编码规则不支持。",
        ("phase45i_twos_complement_range_v1", "twos_complement_range_v1"),
    ),
    "binary_float": FamilySpec(
        "binary_float", "408", ("cs408.co.topic.89cfd05c8418",),
        ("single_choice", "fill_blank"),
        "某IEEE 754单精度浮点数的32位十六进制表示为H，求其表示的十进制真值。",
        "H恰为8个十六进制数位；只生成有限正规数，可含正负号；指数全1（Inf/NaN）和次正规数不作为生题目标。答案按精确有理数比较。",
        "按binary32符号、阶码、尾数精确解码为有理数。",
        "有限十进制/分数选项精确比较，恰好一个正确选项。",
        "填空按精确有理数比较；不得按浮点容差掩盖表示错误。",
        "final_value须与精确解码值一致；可选steps限于十进制整数/分数算术。",
        "binary64、十六进制转储字节序不明、指数全1、非零次正规数及过长分数答案不支持自动接纳。",
        ("phase45i_ieee754_binary32_hex_v1",),
    ),
    "binary_search_steps": FamilySpec(
        "binary_search_steps", "408", ("cs408.ds.topic.8b04b55a0408",),
        ("single_choice", "fill_blank"),
        "对长度为n的升序有序表进行折半查找，若所有查找均成功，则查找成功时最多需要比较的关键字个数是（ ）。",
        "整数n∈[1,1,000,000]；明确所有查找均成功；只问最大成功比较次数。",
        "使用成功判定树高度ceil(log2(n+1))，等价于n.bit_length()。",
        "数值选项精确解析并检查恰好一个正确选项。",
        "填空答案使用精确整数。",
        "final_value须与独立比较次数一致；步骤只写可核验整数式。",
        "失败查找、特定目标路径、非标准mid取法及比较操作细节不支持。",
        ("phase45i_binary_search_max_success_v1", "phase45d_binary_search_steps_v1"),
    ),
    "page_replacement_faults": FamilySpec(
        "page_replacement_faults", "408", ("cs408.os.topic.006da51a6b0f",),
        ("single_choice", "fill_blank"),
        "采用LRU页面置换算法，内存有m个页框且初始为空，访问序列为以逗号分隔的页号整数，求缺页次数？",
        "算法仅LRU或FIFO；页框1–8个；访问序列2–40个非负整数页号；明确初始为空。",
        "逐次模拟页框状态；FIFO按装入先后淘汰，LRU按最近访问次序淘汰。",
        "数值选项精确解析并检查恰好一个正确选项。",
        "填空答案使用精确整数。",
        "final_value须与独立模拟缺页数一致；可选steps只写精确计数。",
        "OPT、工作集/时钟算法、缺页率、初始非空页框或页表状态题不支持。",
        ("phase45d_page_replacement_v1",),
    ),
}


BY_NODE_CODE: dict[str, FamilySpec] = {
    code: spec for spec in FAMILIES.values() for code in spec.node_codes
}


def resolve_family(node_code: str | None, question_type: str | None = None) -> FamilySpec | None:
    spec = BY_NODE_CODE.get(str(node_code or ""))
    if not spec or question_type is not None and question_type not in spec.question_types:
        return None
    return spec


def contract_for(spec: FamilySpec, *, node_code: str, question_type: str, difficulty: str) -> dict:
    if node_code not in spec.node_codes or question_type not in spec.question_types:
        raise ValueError("family_contract_scope_mismatch")
    if difficulty not in {"basic", "improved", "comprehensive"}:
        raise ValueError("family_contract_difficulty_invalid")
    stem_template = spec.stem_template
    if spec.family_id == "power_derivative" and question_type == "fill_blank":
        stem_template = "已知函数f(x)={整数系数的一元多项式}，求f'(t)的值，其中t为有界整数。"
    return {
        "registry_version": VERSION,
        "family_id": spec.family_id,
        "subject": spec.subject,
        "node_code": node_code,
        "question_type": question_type,
        "difficulty": difficulty,
        "canonical_stem_template": stem_template,
        "difficulty_guidance": {
            "basic": "使用范围内最直接的一个计算/判断；避免隐藏条件。",
            "improved": "仍留在同一可验证题族内，可调整参数并使用常见误区设计干扰项。",
            "comprehensive": "仅增加同一题族内的组合条件或干扰项辨析；不得引入注册范围之外的新定理或算法约定。",
        }[difficulty],
        "parameter_bounds": spec.parameter_bounds,
        "independent_solver": spec.solver,
        "single_choice_uniqueness": spec.choice_check,
        "fill_answer_comparison": spec.answer_comparer,
        "explanation_validation": spec.explanation_checks,
        "unsupported_boundaries": spec.unsupported,
    }


def validate_contract(request: dict) -> FamilySpec | None:
    """Validate server-issued family metadata before reserving model budget."""
    node = request.get("node") or {}
    spec = resolve_family(node.get("code"), request.get("question_type"))
    if not spec or request.get("family") != spec.family_id:
        return None
    try:
        expected = contract_for(spec, node_code=node.get("code"),
            question_type=request.get("question_type"), difficulty=request.get("difficulty"))
    except (TypeError, ValueError):
        return None
    return spec if request.get("family_contract") == expected else None


def _seeded(seed: str) -> random.Random:
    return random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16))


def render_problem_spec(spec: ProblemSpec, wording_id: str = "direct") -> str:
    """Apply only registered, semantics-preserving presentation scaffolds."""
    if wording_id not in SAFE_WORDING_PREFIXES:
        raise ValueError("problem_spec_wording_unsupported")
    return SAFE_WORDING_PREFIXES[wording_id] + spec.canonical_problem


def strip_registered_wording(stem: str) -> tuple[str, str]:
    """Return the exact canonical tail only for a known inert wrapper."""
    value = str(stem or "").strip()
    for wording_id, prefix in SAFE_WORDING_PREFIXES.items():
        if prefix and value.startswith(prefix):
            return value[len(prefix):].strip(), wording_id
    return value, "direct"


def teaching_module(spec: ProblemSpec, focus_id: str) -> str:
    if focus_id not in TEACHING_FOCI:
        raise ValueError("problem_spec_teaching_focus_unsupported")
    if focus_id == "method":
        return spec.verification_metadata["explanation"]
    if focus_id == "common_pitfall":
        return _PITFALLS[spec.family_id]
    return _SELF_CHECKS[spec.family_id]


def learning_focus_from_progress(progress) -> dict:
    """Reduce real progress to a small non-answer-bearing selection signal."""
    status = getattr(progress, "status", None) if progress is not None else None
    mapping = {
        "NOT_STARTED": ("foundation", "先从基础题开始"),
        "NEEDS_CONSOLIDATION": ("consolidate", "优先巩固近期可靠错误涉及的能力"),
        "RETEST_RECOMMENDED": ("delayed_retest", "优先安排稍后可独立复测的变式"),
        "IMPROVING": ("transfer", "选择同知识点的不同参数或题面表达继续验证"),
        "STABLE_PRACTICE": ("spaced_review", "选择间隔复习或同题族内稍有变化的练习"),
        "PRACTICING": ("practice", "沿当前知识点继续练习"),
    }
    key, instruction = mapping.get(status, ("foundation", "先从基础题开始"))
    # Counts are a bounded, non-answer-bearing summary. Never send historical
    # answers, question text, or raw attempt notes to the generator.
    return {"status": status or "NOT_STARTED", "focus": key, "selection_instruction": instruction,
        "observed_attempt_count": int(getattr(progress, "observed_attempt_count", 0) or 0) if progress else 0,
        "distinct_question_count": int(getattr(progress, "distinct_question_count", 0) or 0) if progress else 0,
        "reliable_wrong_count": int(getattr(progress, "reliable_wrong_count", 0) or 0) if progress else 0,
        "assisted_correct_count": int(getattr(progress, "assisted_correct_question_count", 0) or 0) if progress else 0}


def candidate_profile(spec: ProblemSpec) -> str:
    """Describe checked structural dimensions without exposing the answer."""
    p = spec.parameters
    if spec.family_id == "power_derivative":
        return f"显式多项式，最高次数{max(p['coefficients'])}，含{len(p['coefficients'])}项"
    if spec.family_id == "power_integral":
        return f"多项式定积分，次数{max(p['coefficients'])}，区间长度{p['upper']-p['lower']}"
    if spec.family_id == "page_replacement_faults":
        return f"{p['algorithm']}，{p['frames']}个页框，访问{len(p['references'])}次"
    if spec.family_id == "binary_float":
        return f"binary32有限正规数，符号位{p['sign']}，尾数字段类别{p['fraction_bits']}"
    return "同一已注册题族中的不同合法参数实例"


def supports_difficulty(spec: FamilySpec, difficulty: str) -> bool:
    return difficulty == "basic" or difficulty in SUPPORTED_DIFFICULTIES.get(spec.family_id, ())


def _format_fraction(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _format_polynomial(coefficients: dict[int, int]) -> str:
    terms = []
    for power in sorted(coefficients, reverse=True):
        coefficient = int(coefficients[power])
        if not coefficient:
            continue
        absolute = abs(coefficient)
        variable = "x" if power == 1 else f"x^{power}" if power else ""
        body = ("" if absolute == 1 and variable else str(absolute)) + variable
        terms.append(("-" if coefficient < 0 else "+") + body)
    if not terms:
        return "0"
    return terms[0].lstrip("+") + "".join(terms[1:])


def _numeric_options(answer: str, rng: random.Random) -> tuple[dict[str, str], str]:
    from backend.services.constant_expression import constant_expression
    target = constant_expression(answer)
    if target is None:
        raise ValueError("problem_spec_answer_not_exact_numeric")
    offsets = [1, -1, 2, -2, 3, -3, 4, -4]
    rng.shuffle(offsets)
    distractors = []
    for offset in offsets:
        candidate = target + offset
        rendered = _format_fraction(Fraction(int(candidate.p), int(candidate.q)))
        if rendered != answer and rendered not in distractors:
            distractors.append(rendered)
        if len(distractors) == 3:
            break
    values = [answer, *distractors]
    rng.shuffle(values)
    options = dict(zip("ABCD", values))
    key = next(label for label, value in options.items() if value == answer)
    return options, key


def _range_options(low: int, high: int, rng: random.Random) -> tuple[dict[str, str], str]:
    correct = f"[{low},{high}]"
    variants = [f"[{low - 1},{high}]", f"[{low},{high + 1}]", f"[{low + 1},{high}]"]
    rng.shuffle(variants)
    values = [correct, *variants]
    rng.shuffle(values)
    options = dict(zip("ABCD", values))
    return options, next(label for label, value in options.items() if value == correct)


def _poly_options(derivative: dict[int, int], rng: random.Random) -> tuple[dict[str, str], str]:
    target = dict(derivative)
    candidates = []
    for power in (0, 1, 2):
        for delta in (1, -1, 2, -2):
            changed = dict(target)
            changed[power] = changed.get(power, 0) + delta
            rendered = _format_polynomial(changed)
            if rendered != _format_polynomial(target) and rendered not in candidates:
                candidates.append(rendered)
    rng.shuffle(candidates)
    correct = _format_polynomial(target)
    values = [correct, *candidates[:3]]
    rng.shuffle(values)
    options = dict(zip("ABCD", values))
    return options, next(label for label, value in options.items() if value == correct)


def _page_faults(algorithm: str, frames: int, references: list[int]) -> tuple[int, list[dict]]:
    resident: list[int] = []
    trace = []
    misses = 0
    for page in references:
        hit = page in resident
        evicted = None
        if not hit:
            misses += 1
            if len(resident) == frames:
                evicted = resident.pop(0)
            resident.append(page)
        elif algorithm == "LRU":
            resident.remove(page)
            resident.append(page)
        trace.append({"page": page, "hit": hit, "evicted": evicted, "frames_after": list(resident)})
    return misses, trace


def build_problem_spec(*, node_code: str, question_type: str, difficulty: str, seed: str) -> ProblemSpec:
    """Build a server-owned, solvable instance; no model-authored answer is trusted."""
    spec = resolve_family(node_code, question_type)
    if not spec:
        raise ValueError("problem_spec_family_unsupported")
    if difficulty not in {"basic", "improved", "comprehensive"}:
        raise ValueError("problem_spec_difficulty_invalid")
    if not supports_difficulty(spec, difficulty):
        raise ValueError("problem_spec_difficulty_unsupported_for_family")
    rng = _seeded(seed)
    parameters: dict = {}
    constraints: dict = {"answer_source": "server_solver", "stem_policy": "exact_spec_conditions"}
    options: dict[str, str] | None = None
    answer = ""
    explanation = ""
    adapter_expected = None
    if spec.family_id == "power_derivative":
        degree = {"basic": 3, "improved": 4, "comprehensive": 5}[difficulty]
        coefficients = {degree: rng.choice([-4, -3, -2, 2, 3, 4])}
        coefficients.update({power: rng.randint(-5, 5) for power in range(degree - 1, -1, -1)})
        coefficients.setdefault(1, rng.choice([-5, -3, -2, 2, 3, 5]))
        polynomial = _format_polynomial(coefficients)
        derivative = {p - 1: coefficient * p for p, coefficient in coefficients.items() if p}
        derivative_text = _format_polynomial(derivative)
        if question_type == "single_choice":
            problem = f"设函数f(x)={polynomial}，求f'(x)。"
            options, answer = _poly_options(derivative, rng)
            result_value = derivative_text
            adapter_expected = "phase45i_polynomial_derivative_v1"
            explanation = f"对多项式逐项求导，得到f'(x)={derivative_text}。"
        else:
            point = rng.randint(-3, 3)
            value = sum(coef * (point ** power) for power, coef in derivative.items())
            problem = f"已知函数f(x)={polynomial}，求f'({point})的值。"
            answer = str(value)
            result_value = answer
            adapter_expected = "phase45i_polynomial_derivative_value_v1"
            explanation = f"先逐项求导得f'(x)={derivative_text}，再代入x={point}，结果为{value}。"
        parameters = {"coefficients": coefficients, "derivative_coefficients": derivative,
                      "polynomial": polynomial, "derivative": derivative_text}
    elif spec.family_id == "power_integral":
        a = rng.randint(-2, 1); b = rng.randint(a + 1, min(a + 4, 4))
        degree = {"basic": 2, "improved": 3, "comprehensive": 4}[difficulty]
        coefficients = {degree: rng.randint(1, 4)}
        coefficients.update({power: rng.randint(-3, 3) for power in range(degree - 1, -1, -1)})
        polynomial = _format_polynomial(coefficients)
        value = Fraction(0)
        for power, coefficient in coefficients.items():
            value += Fraction(coefficient * (b ** (power + 1) - a ** (power + 1)), power + 1)
        answer = _format_fraction(value)
        problem = f"计算定积分：∫_{a}^{b} {polynomial} dx =____。"
        if question_type == "single_choice": options, answer = _numeric_options(answer, rng)
        result_value = _format_fraction(value)
        adapter_expected = "phase45i_polynomial_definite_integral_v1"
        explanation = f"逐项积分后代入上下限x={a}与x={b}，精确计算得{result_value}。"
        parameters = {"lower": a, "upper": b, "coefficients": coefficients,
                      "polynomial": polynomial, "primitive_coefficients": {p + 1: Fraction(c, p + 1).__str__() for p, c in coefficients.items()}}
    elif spec.family_id == "improper_integral_parameter":
        problem = "关于含参数p的反常积分I(p)=∫_e^{+∞}dx/[x(lnx)^p]，下列结论正确的是（ ）"
        claims = ["p>1", "p≥1", "p<1", "对所有实数p都收敛"]
        rng.shuffle(claims)
        options = dict(zip("ABCD", claims))
        answer = next(k for k, v in options.items() if v == "p>1")
        result_value = "p>1"
        adapter_expected = "phase45i_log_improper_integral_p_test_v1"
        explanation = "令t=ln x，则积分化为∫_1^∞t^(-p)dt；幂积分在且仅在p>1时收敛。"
        parameters = {"lower_endpoint": "e", "upper_endpoint": "+∞", "parameter": "p"}
    elif spec.family_id == "exp_limit":
        a = rng.randint(1, 10)
        if question_type == "single_choice":
            problem = rf"计算极限：\lim_{{x\to 0}}\frac{{e^{{{a}x}}-1-{a}x}}{{x^2}} 的值是（ ）。"
        else:
            problem = rf"计算极限：\lim_{{x\to 0}}\frac{{e^{{{a}x}}-1-{a}x}}{{x^2}}=____。"
        value = Fraction(a * a, 2)
        result_value = _format_fraction(value)
        answer = result_value
        adapter_expected = "phase45i_exp_second_order_limit_v1"
        if question_type == "single_choice": options, answer = _numeric_options(result_value, rng)
        explanation = f"由指数函数在0点的二阶展开，二次项系数为a²/2；代入a={a}得{result_value}。"
        parameters = {"a": a, "limit_point": 0, "denominator_power": 2}
    elif spec.family_id == "determinant_2x2":
        matrix = [[rng.randint(-9, 9) for _ in range(2)] for _ in range(2)]
        a, b = matrix[0]; c, d = matrix[1]
        value = a * d - b * c
        problem = f"计算二阶行列式，其中第一行是{a}、{b}，第二行是{c}、{d}。"
        result_value = str(value); answer = result_value
        adapter_expected = "phase45i_determinant_2x2_numeric_v1"
        if question_type == "single_choice": options, answer = _numeric_options(result_value, rng)
        explanation = f"二阶行列式按ad-bc计算：{a}×{d}-{b}×{c}={value}。"
        parameters = {"matrix": matrix}
    elif spec.family_id == "complete_tree":
        n = rng.randint(1, 999)
        value = (n + 1) // 2
        problem = f"一棵完全二叉树共有{n}个结点，则其叶子结点数为（ ）"
        result_value = str(value); answer = result_value
        adapter_expected = "phase45i_complete_tree_leaf_count_v1"
        if question_type == "single_choice": options, answer = _numeric_options(result_value, rng)
        explanation = f"层序顺序存储时，编号大于floor(n/2)的结点为叶子，叶子数n-floor(n/2)={value}。"
        parameters = {"node_count": n, "indexing": "1-based-level-order"}
    elif spec.family_id == "signed_range":
        bits = rng.randint(4, 16)
        low, high = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
        result_value = f"[{low},{high}]"; answer = result_value
        problem = f"设机器字长为{bits}位，采用补码表示定点整数，则可表示的十进制整数范围是____（用闭区间表示）"
        adapter_expected = "phase45i_twos_complement_range_v1"
        if question_type == "single_choice": options, answer = _range_options(low, high, rng)
        explanation = f"n位补码范围为[-2^(n-1),2^(n-1)-1]；代入n={bits}得到{result_value}。"
        parameters = {"bits": bits, "minimum": low, "maximum": high}
    elif spec.family_id == "binary_float":
        exponent_range = {"basic": (127, 132), "improved": (124, 133), "comprehensive": (120, 136)}[difficulty]
        exponent = rng.randint(*exponent_range)
        fraction_bits = rng.choice([0, 1 << 22, 1 << 21, (1 << 22) + (1 << 20)])
        sign = 1 if difficulty != "basic" and rng.random() < 0.5 else 0
        word = (sign << 31) | (exponent << 23) | fraction_bits
        significand = (1 << 23) + fraction_bits
        exponent_shift = exponent - 127
        scale = Fraction(1 << exponent_shift, 1) if exponent_shift >= 0 else Fraction(1, 1 << -exponent_shift)
        value = (-1 if sign else 1) * Fraction(significand, 1 << 23) * scale
        result_value = _format_fraction(value); answer = result_value
        hex_word = f"{word:08X}"
        problem = f"某IEEE754单精度浮点数的32位十六进制表示为{hex_word}，求其表示的十进制真值。"
        adapter_expected = "phase45i_ieee754_binary32_hex_v1"
        if question_type == "single_choice": options, answer = _numeric_options(result_value, rng)
        explanation = f"拆分符号位、阶码和尾数，按binary32规格解码得到精确真值{result_value}。"
        parameters = {"hex_word": hex_word, "sign": sign, "exponent_bits": exponent,
                      "fraction_bits": fraction_bits, "classification": "normal"}
    elif spec.family_id == "binary_search_steps":
        n = rng.randint(2, 999)
        value = n.bit_length()
        problem = f"对长度为{n}的升序有序表进行折半查找，若所有查找均成功，则查找成功时最多需要比较的关键字个数是（ ）"
        result_value = str(value); answer = result_value
        adapter_expected = "phase45i_binary_search_max_success_v1"
        if question_type == "single_choice": options, answer = _numeric_options(result_value, rng)
        explanation = f"成功查找的最大比较次数为ceil(log2(n+1))，等价于n的二进制位数；本题结果为{value}。"
        parameters = {"length": n, "max_successful_comparisons": value}
    elif spec.family_id == "page_replacement_faults":
        algorithm = rng.choice(["FIFO", "LRU"])
        frame_range, reference_range = {
            "basic": ((2, 2), (7, 10)),
            "improved": ((2, 3), (11, 15)),
            "comprehensive": ((3, 4), (16, 22)),
        }[difficulty]
        frames = rng.randint(*frame_range)
        references = [rng.randint(0, 7) for _ in range(rng.randint(*reference_range))]
        value, trace = _page_faults(algorithm, frames, references)
        seq = ",".join(map(str, references))
        problem = f"采用{algorithm}页面置换算法，内存有{frames}个页框且初始为空，访问序列为{seq}，求缺页次数？"
        result_value = str(value); answer = result_value
        adapter_expected = "phase45d_page_replacement_v1"
        if question_type == "single_choice": options, answer = _numeric_options(result_value, rng)
        explanation = f"按{algorithm}规则逐次模拟访问序列，累计缺页{value}次。"
        parameters = {"algorithm": algorithm, "frames": frames, "references": references}
        constraints["independent_trace"] = trace
    else:
        raise ValueError("problem_spec_family_unsupported")

    constraints["difficulty_realization"] = {
        "power_derivative": "polynomial_degree_and_term_count",
        "power_integral": "polynomial_degree_and_interval_evaluation",
        "page_replacement_faults": "algorithm_state_sequence_length_and_frame_count",
        "binary_float": "signed_value_exponent_and_significand",
    }.get(spec.family_id, "basic_structure_only; numeric_parameter_variation_is_not_claimed_as_higher_cognitive_difficulty")

    if question_type == "fill_blank" and options is not None:
        raise ValueError("problem_spec_fill_blank_options_invalid")
    if question_type == "single_choice" and (not options or set(options) != set("ABCD") or not answer in options):
        raise ValueError("problem_spec_choice_invalid")
    from types import SimpleNamespace
    from backend.services.quality_verifiers import verify_problem
    canonical_q = SimpleNamespace(stem=problem, question_type=question_type, options=options, correct_answer=answer)
    independent = verify_problem(canonical_q)
    if not independent or independent.get("status") != "PASS" or independent.get("adapter") != adapter_expected:
        raise ValueError(f"problem_spec_independent_verification_failed:{spec.family_id}:{independent}")
    verification_metadata = {
        "verifier_version": PROBLEM_SPEC_VERIFIER_VERSION,
        "adapter": independent["adapter"],
        "proof": independent.get("proof"),
        "solver_result": result_value,
        "explanation": explanation,
        "explanation_authority": "server_computed_from_verified_problem_spec",
    }
    return ProblemSpec(
        family_id=spec.family_id, subject=spec.subject, knowledge_node_code=node_code,
        question_type=question_type, difficulty=difficulty, parameters=parameters,
        constraints=constraints, canonical_problem=problem, canonical_answer=answer,
        options=options, grading_method="single_choice" if question_type == "single_choice" else
            "range_final" if spec.family_id == "signed_range" else "numeric_final",
        verification_metadata=verification_metadata, generation_seed=seed,
    )


def verify_problem_spec_candidate(*, stem: str, spec: ProblemSpec, wording_id: str = "direct") -> dict:
    """Re-run the registered independent checker and bind all server-owned facts."""
    from types import SimpleNamespace
    from backend.services.quality_verifiers import verify_problem
    expected_stem = render_problem_spec(spec, wording_id)
    if re.sub(r"\s+", "", str(stem or "")) != re.sub(r"\s+", "", expected_stem):
        return {"status": "FAIL", "reason": "problem_spec_condition_drift"}
    candidate = SimpleNamespace(stem=stem, question_type=spec.question_type,
                                options=spec.options, correct_answer=spec.canonical_answer)
    result = verify_problem(candidate)
    expected = spec.verification_metadata
    if result.get("status") != "PASS" or result.get("adapter") != expected.get("adapter"):
        return {"status": "FAIL", "reason": "problem_spec_reverification_failed", "result": result}
    if result.get("proof") != expected.get("proof"):
        return {"status": "FAIL", "reason": "problem_spec_proof_drift", "result": result}
    return {"status": "PASS", "adapter": result["adapter"], "proof": result.get("proof"),
            "derived_answer": result.get("derived_answer")}
