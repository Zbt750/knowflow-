from types import SimpleNamespace

import pytest

from backend.services.quality_verifiers import VERSION, verify_problem
from backend.services.phase45i_quality_verifiers import verify_explanation_step, final_value_matches, compare_exact_answer_values


def q(stem, answer, *, kind="fill_blank", options=None):
    return SimpleNamespace(stem=stem, correct_answer=answer, question_type=kind, options=options or {})


@pytest.mark.parametrize(("question", "expected_adapter"), [
    (q("设函数 f(x)=2x^6-5x^3+x，求 f'(x)。", "A", kind="single_choice", options={
        "A":"12x^5-15x^2+1", "B":"12x^5-15x^2", "C":"12x^6-15x^3+1", "D":"2x^5-5x^2+1"}), "phase45i_polynomial_derivative_v1"),
    (q("计算定积分：∫_0^2 3x^2 dx = ______。", "8"), "phase45i_polynomial_definite_integral_v1"),
    (q("关于含参数 p 的反常积分 I(p)=∫_e^{+∞} dx/[x(ln x)^p]，下列结论正确的是（ ）。", "A", kind="single_choice", options={
        "A":"p>1时收敛，p≤1时发散", "B":"所有p均收敛", "C":"p≥1时收敛", "D":"所有p均发散"}), "phase45i_log_improper_integral_p_test_v1"),
    (q(r"计算极限：\lim_{x\to 0}\frac{e^{3x}-1-3x}{x^2}=______。", "9/2"), "phase45i_exp_second_order_limit_v1"),
    (q("关于实数 x 的不等式 det[[x,2],[3,x-1]] > 0 的解集是（ ）。", "C", kind="single_choice", options={
        "A":"(-2,3)", "B":"(-∞,-2]∪[3,∞)", "C":"(-∞,-2)∪(3,∞)", "D":"(-∞,3)"}), "phase45i_quadratic_determinant_inequality_v1"),
    (q("一棵完全二叉树共有 1000 个结点，则其叶子结点数为（ ）。", "B", kind="single_choice", options={
        "A":"499", "B":"500", "C":"501", "D":"512"}), "phase45i_complete_tree_leaf_count_v1"),
    (q("设机器字长为8位，采用补码表示定点整数，则可表示的十进制整数范围是________（用闭区间表示）。", "[-128, 127]"), "phase45i_twos_complement_range_v1"),
    (q("对长度为 11 的升序有序表进行折半查找，若所有查找均成功，则查找成功时最多需要比较的关键字个数是（ ）。", "4"), "phase45i_binary_search_max_success_v1"),
])
def test_real_phase45i_families_are_independently_supported(question, expected_adapter):
    result = verify_problem(question)
    assert VERSION == "bounded-problem-verifiers-v19"
    assert result["status"] == "PASS", result
    assert result["adapter"] == expected_adapter


def test_answer_option_conflict_and_ambiguous_choice_are_rejected():
    wrong = q("设函数 f(x)=2x^6-5x^3+x，求 f'(x)。", "B", kind="single_choice", options={
        "A":"12x^5-15x^2+1", "B":"12x^5-15x^2", "C":"12x^6-15x^3+1", "D":"2x^5-5x^2+1"})
    ambiguous = q("设函数 f(x)=2x^6-5x^3+x，求 f'(x)。", "A", kind="single_choice", options={
        "A":"12x^5-15x^2+1", "B":"12x^5-15x^2+1", "C":"12x^6-15x^3+1", "D":"2x^5-5x^2+1"})
    assert verify_problem(wrong)["status"] == "FAIL"
    assert verify_problem(ambiguous)["reason"] == "non_unique_correct_option"


@pytest.mark.parametrize("bad_stem", [
    "计算定积分：∫_0^2 x^2 dx = ______。",  # changed integrand, answer 8 is wrong
    "计算定积分：∫_0^2 3x^2 + g(x) dx = ______。",  # unspecified term/condition
    "关于实数 x 的不等式 det[[x,2],[3,x-1]] > 0 讨论其图像。",  # unsupported task type
])
def test_changed_conditions_or_nonmatching_task_never_auto_pass(bad_stem):
    result = verify_problem(q(bad_stem, "8"))
    assert result is None or result["status"] != "PASS"


def test_nearby_but_unsupported_integral_is_not_given_p_test_proof():
    result = verify_problem(q("关于含参数 p 的反常积分 I(p)=∫_2^{+∞} dx/[x(ln x)^p]，下列结论正确的是（ ）。", "A",
        kind="single_choice", options={"A":"p>1时收敛，p≤1时发散", "B":"所有p均收敛", "C":"p≥1时收敛", "D":"所有p均发散"}))
    assert result is None or result["status"] != "PASS"


def test_binary_search_step_checks_truth_and_reported_depth():
    assert verify_explanation_step("8 < 11 <= 16", "4") == "right"
    assert verify_explanation_step("8 < 11 <= 16", "3") == "wrong"
    assert verify_explanation_step("8 < 7 <= 16", "4") == "wrong"


def test_floor_step_is_exact_and_bounded():
    assert verify_explanation_step("floor(1000/2)", "500") == "right"
    assert verify_explanation_step("floor(1000/2)", "501") == "wrong"
    assert verify_explanation_step("floor(1000/0)", "0") == "wrong"


def test_log_substitution_fact_and_unrecognized_expression():
    assert verify_explanation_step("ln e", "1") == "right"
    assert verify_explanation_step("ln e", "2") == "wrong"
    assert verify_explanation_step("f(x)=unknown", "0") == "unknown"


def test_semantically_equivalent_p_integral_answer_and_wrong_answer():
    question = q("关于含参数 p 的反常积分 I(p)=∫_e^{+∞} dx/[x(ln x)^p]，下列结论正确的是（ ）。", "A",
        kind="single_choice", options={"A":"p>1时收敛，p≤1时发散", "B":"所有p均收敛", "C":"p≥1时收敛", "D":"所有p均发散"})
    independent = verify_problem(question)
    assert final_value_matches(question, "p>1", independent) == "right"
    assert final_value_matches(question, "p≥1", independent) == "wrong"


def test_range_fill_blank_accepts_closure_instruction_and_rejects_wrong_bound():
    question = q("设机器字长为8位，采用补码表示定点整数，则可表示的十进制整数范围是________（用闭区间表示）。", "[-128, 127]")
    assert verify_problem(question)["status"] == "PASS"
    assert verify_problem(q(question.stem, "[-127, 127]"))["status"] == "FAIL"


@pytest.mark.parametrize(("left", "right", "expected"), [
    ("255", "0xFF", "right"),
    ("255", "FFH", "right"),
    ("10", "1010B", "right"),
    ("10", "0b1010", "right"),
    ("255", "0xFE", "wrong"),
    ("1/2", "0.5", "right"),
    ("(2+2)", "4", "right"),
    ("not-a-number", "4", "unknown"),
])
def test_exact_answer_normalization_is_bounded(left, right, expected):
    assert compare_exact_answer_values(left, right) == expected


def test_final_value_can_use_correct_option_label_but_not_another_label():
    question = q("一棵完全二叉树共有1000个结点，则其叶子结点数为（ ）。", "B", kind="single_choice",
        options={"A":"499", "B":"500", "C":"501", "D":"512"})
    independent = verify_problem(question)
    assert final_value_matches(question, "B", independent) == "right"
    assert final_value_matches(question, "C", independent) == "wrong"


def test_symbolic_complete_tree_provider_response_is_independently_verified_end_to_end():
    """Regression for the real DeepSeek output captured in R50 tree-r2."""
    from backend.models.learning import KnowledgePoint
    from backend.services.personal_question_families import resolve_family
    from backend.services.question_generation import Output, PERSONAL_C7_PROMPT_VERSION, assess_output
    from uuid import uuid4

    node = KnowledgePoint(id=uuid4(), code="cs408.ds.topic.1efaf3d00b50",
        name="二叉树", subject="408", is_active=True, is_assessable=True,
        is_reference_only=True)
    output = Output(
        stem="一棵完全二叉树共有n个结点，则其叶子结点数为（ ）。",
        question_type="single_choice",
        options={"A": "⌊n/2⌋", "B": "n−⌊n/2⌋", "C": "⌈n/2⌉−1", "D": "n−⌈n/2⌉"},
        correct_answer="B",
        explanation="完全二叉树按层序从1编号，编号大于⌊n/2⌋的结点都是叶子。"
                    "因此叶子结点数为 n−⌊n/2⌋，也等于⌈n/2⌉。其余选项与这一计数不符。",
        final_value="n−⌊n/2⌋",
        steps=[{"expression": "n−floor(n/2)", "value": "n−⌊n/2⌋"}],
    )
    result = assess_output(output, node, request_id="R50:real-provider-tree-response-regression",
        mode="original", family="complete_tree",
        family_spec=resolve_family(node.code, output.question_type),
        trace={"mode": "real_model", "model": "deepseek-flash", "model_calls": 1,
               "prompt_version": PERSONAL_C7_PROMPT_VERSION})

    assert result["status"] == "AUTO_PASS", result
    assert result["record"]["independent_verification"]["status"] == "PASS"
    assert result["record"]["independent_verification"]["adapter"] == "phase45i_complete_tree_symbolic_leaf_count_v1"
    assert result["record"]["narrative_verification"]["status"] == "PASS"
    assert result["record"]["review_status"] == "AUTO_PASS"


def test_symbolic_complete_tree_final_value_accepts_answer_key_and_rejects_wrong_key():
    question = q("一棵完全二叉树共有n个结点，则其叶子结点数为（ ）。", "B", kind="single_choice",
        options={"A": "⌊n/2⌋", "B": "n−⌊n/2⌋", "C": "⌈n/2⌉−1", "D": "n−⌈n/2⌉"})
    independent = verify_problem(question)
    assert independent["status"] == "PASS"
    assert final_value_matches(question, "B", independent) == "right"
    assert final_value_matches(question, "C", independent) == "wrong"
    assert final_value_matches(question, "n-floor(n/2)", independent) == "right"
    assert final_value_matches(question, "floor(n/2)", independent) == "wrong"


def test_symbolic_complete_tree_rejects_ambiguous_options_and_does_not_guess_unknown_forms():
    ambiguous = q("一棵完全二叉树共有n个结点，则其叶子结点数为（ ）。", "B", kind="single_choice",
        options={"A": "⌊(n+1)/2⌋", "B": "n−⌊n/2⌋", "C": "⌈n/2⌉−1", "D": "n−⌈n/2⌉"})
    unsupported = q("一棵完全二叉树共有n个结点，则其叶子结点数为（ ）。", "B", kind="single_choice",
        options={"A": "floor(n/2)+1", "B": "n−⌊n/2⌋", "C": "ceil(n/2)-1", "D": "n-ceil(n/2)"})
    assert verify_problem(ambiguous)["status"] == "FAIL"
    assert verify_problem(ambiguous)["reason"] == "non_unique_correct_option"
    # Every option must parse under the bounded allowlist before the item can
    # pass; an unsupported expression cannot be assumed to be a distractor.
    assert verify_problem(unsupported)["status"] == "UNKNOWN"
    assert verify_problem(unsupported)["reason"] == "option_outside_exact_scope"


def test_real_provider_numeric_complete_tree_wording_and_explanation_are_bounded_and_exact():
    from backend.services.phase45i_quality_verifiers import verify_narrative_claims

    question = q("一棵完全二叉树共有n=1000个结点，则其叶子结点数为（ ）。", "B",
        kind="single_choice", options={"A": "499", "B": "500", "C": "501", "D": "512"})
    independent = verify_problem(question)
    assert independent and independent["status"] == "PASS", independent
    assert independent["adapter"] == "phase45i_complete_tree_leaf_count_v1"
    assert final_value_matches(question, "500", independent) == "right"
    assert final_value_matches(question, "501", independent) == "wrong"
    assert verify_explanation_step("1000-floor(1000/2)", "500") == "right"
    assert verify_explanation_step("ceil(1000/2)", "500") == "right"
    assert verify_explanation_step("⌈1000/2⌉", "500") == "right"
    assert verify_explanation_step("⌈1000/2⌉", "501") == "wrong"

    question.explanation = (
        "完全二叉树按层序从1开始编号，编号大于⌊n/2⌋的结点为叶结点。"
        "取n=1000，⌊1000/2⌋=500，因此叶子结点数为1000−500=500，也等于⌈1000/2⌉。"
    )
    narrative = verify_narrative_claims(question, independent)
    assert narrative["status"] == "PASS", narrative
    assert narrative["checked_claim_count"] == 4

    question.explanation = question.explanation.replace("1000−500=500", "1000−500=501")
    assert verify_narrative_claims(question, independent)["status"] == "FAIL"


def test_real_provider_numeric_complete_tree_response_can_pass_generation_quality_gate():
    from uuid import uuid4
    from backend.models.learning import KnowledgePoint
    from backend.services.personal_question_families import resolve_family
    from backend.services.question_generation import Output, PERSONAL_C7_PROMPT_VERSION, assess_output

    node = KnowledgePoint(id=uuid4(), code="cs408.ds.topic.1efaf3d00b50",
        name="二叉树", subject="408", is_active=True, is_assessable=True,
        is_reference_only=True)
    output = Output(
        stem="一棵完全二叉树共有n=1000个结点，则其叶子结点数为（ ）。",
        question_type="single_choice", options={"A": "499", "B": "500", "C": "501", "D": "512"},
        correct_answer="B",
        explanation=("完全二叉树按层序从1编号，编号大于⌊n/2⌋的结点均为叶子结点。"
            "n=1000时⌊n/2⌋=500，故叶子结点数为1000−500=500。也可由公式⌈n/2⌉得到500。"),
        final_value="500", steps=[{"expression": "floor(1000/2)", "value": "500"},
            {"expression": "1000-500", "value": "500"}],
    )
    result = assess_output(output, node, request_id="R50:real-provider-tree-numeric-regression",
        mode="original", family="complete_tree", family_spec=resolve_family(node.code, output.question_type),
        trace={"mode": "real_model", "model": "deepseek-flash", "model_calls": 1,
               "prompt_version": PERSONAL_C7_PROMPT_VERSION})
    assert result["status"] == "AUTO_PASS", result
    assert result["record"]["independent_verification"]["status"] == "PASS"
    assert result["record"]["narrative_verification"]["status"] == "PASS"
    assert result["record"]["narrative_verification"]["checked_claim_count"] == 4


def test_real_provider_ascii_floor_complete_tree_wording_has_checked_narrative_claims():
    from backend.services.phase45i_quality_verifiers import verify_narrative_claims

    question = q("一棵完全二叉树共有999个结点，则其叶子结点数为（ ）。", "C",
        kind="single_choice", options={"A": "498", "B": "499", "C": "500", "D": "501"})
    independent = verify_problem(question)
    assert independent and independent["status"] == "PASS", independent
    assert independent["adapter"] == "phase45i_complete_tree_leaf_count_v1"
    question.explanation = (
        "完全二叉树中编号大于floor(n/2)的结点均为叶子结点，因此叶子数为n−floor(n/2)。"
        "当n=999时，floor(999/2)=499，所以叶子数为999−499=500。"
    )
    narrative = verify_narrative_claims(question, independent)
    assert narrative["status"] == "PASS", narrative
    assert narrative["checked_claim_count"] == 4
    question.explanation = question.explanation.replace("floor(999/2)=499", "floor(999/2)=500")
    assert verify_narrative_claims(question, independent)["status"] == "FAIL"


def test_real_provider_ascii_floor_complete_tree_output_passes_assessment():
    from uuid import uuid4
    from backend.models.learning import KnowledgePoint
    from backend.services.personal_question_families import resolve_family
    from backend.services.question_generation import Output, PERSONAL_C7_PROMPT_VERSION, assess_output

    node = KnowledgePoint(id=uuid4(), code="cs408.ds.topic.1efaf3d00b50",
        name="二叉树", subject="408", is_active=True, is_assessable=True,
        is_reference_only=True)
    output = Output(
        stem="一棵完全二叉树共有999个结点，则其叶子结点数为（ ）。",
        question_type="single_choice", options={"A": "498", "B": "499", "C": "500", "D": "501"},
        correct_answer="C",
        explanation=("完全二叉树中编号大于floor(n/2)的结点均为叶子结点，因此叶子数为n−floor(n/2)。"
            "当n=999时，floor(999/2)=499，所以叶子数为999−499=500。"),
        final_value="500", steps=[{"expression": "floor(999/2)", "value": "499"},
            {"expression": "999-499", "value": "500"}],
    )
    result = assess_output(output, node, request_id="R50:real-provider-tree-ascii-floor-regression",
        mode="original", family="complete_tree", family_spec=resolve_family(node.code, output.question_type),
        trace={"mode": "real_model", "model": "deepseek-flash", "model_calls": 1,
               "prompt_version": PERSONAL_C7_PROMPT_VERSION})
    assert result["status"] == "AUTO_PASS", result
    assert result["record"]["independent_verification"]["status"] == "PASS"
    assert result["record"]["narrative_verification"]["checked_claim_count"] == 4


def test_generation_audit_has_explicit_wrong_unsupported_and_insufficient_states():
    from uuid import uuid4
    from backend.models.learning import KnowledgePoint
    from backend.services.question_generation import Output, assess_output

    node = KnowledgePoint(id=uuid4(), code="TEST_FIXTURE.derivative", name="导数与微分的计算",
        subject="考研数学", is_active=True, is_assessable=True, is_reference_only=True)
    stem = "设函数 f(x)=2x^6-5x^3+x，求 f'(x)。"
    options = {"A":"12x^5-15x^2+1", "B":"12x^5-15x^2", "C":"12x^6-15x^3+1", "D":"2x^5-5x^2+1"}

    def review(question_stem, answer, final, choices):
        output = Output(stem=question_stem, question_type="single_choice", options=choices,
            correct_answer=answer, explanation="逐项求导得到对应表达式。", final_value=final,
            steps=[{"expression":"2×6", "value":"12"}])
        return assess_output(output, node, request_id="TEST_FIXTURE:phase45i-state:"+answer+final,
            mode="original", family="power_derivative")

    wrong = review(stem, "B", options["B"], options)
    assert wrong["review_status"] == "CONFIRMED_WRONG"
    assert wrong["status"] == "REJECTED"

    unsupported = review("求一个未给定函数的导数。", "A", "x", options)
    assert unsupported["review_status"] == "UNSUPPORTED"
    assert unsupported["status"] != "AUTO_PASS"

    ambiguous_options = dict(options, D=options["A"])
    ambiguous = review(stem, "A", options["A"], ambiguous_options)
    assert ambiguous["review_status"] == "CONFIRMED_WRONG"
    assert ambiguous["record"]["independent_verification"]["reason"] == "non_unique_correct_option"


def test_ai_personal_interval_answer_is_practice_gradable_but_never_verified_grader():
    from backend.services.answer_grading import (available_grading_method, available_practice_grading_method,
        grade_practice_final_answer)
    config = {"verified":False,"method":None,"generated_practice_method":"range_final",
        "generation":{"version":"bounded-question-generation-v5"}}
    common = dict(question_type="fill_blank", config=config, expected="[-128,127]", options=None,
        answer_provenance="ai_generated", content_trust="unreviewed", answer_reliability="model_generated")
    assert available_practice_grading_method(**common) == "ai_generated_range_final"
    assert available_grading_method(question_type="fill_blank",config={"verified":True,"method":"range_final"},
        expected="[-128,127]",options=None) is None
    grade = lambda answer: grade_practice_final_answer(**common,answer=answer,selected_option=None)
    assert grade("[-128.0, 127]").result == "right"
    assert grade("[-127,127]").result == "wrong"
    assert grade("").result == "unknown"


@pytest.mark.parametrize("answer", [
    "[-2^(n-1), 2^(n-1)-1]",
    r"\left[-2^{n-1},\ 2^{n-1}-1\right]",
    r"$[-2^{n-1},2^{n-1}-1]$",
])
def test_generic_twos_complement_range_is_independently_verified_only_in_registered_stem(answer):
    question = q("设机器字长为n位，采用补码表示定点整数，则可表示的十进制整数范围是____（用闭区间表示）。", answer)
    result = verify_problem(question)
    assert VERSION == "bounded-problem-verifiers-v19"
    assert result and result["status"] == "PASS", result
    assert result["adapter"] == "phase45i_twos_complement_symbolic_range_v1"
    assert final_value_matches(question, r"\left[-2^{n-1}, 2^{n-1}-1\right]", result) == "right"
    assert final_value_matches(question, "[-2^(n-1),2^(n-1)]", result) == "unknown"


@pytest.mark.parametrize("answer", [
    "[-2^(n-1),2^(n-1)]",
    "[-2^n-1,2^(n-1)-1]",
    "[-2^(n-1),2^n-1]",
])
def test_wrong_or_ambiguous_symbolic_twos_complement_range_is_not_accepted(answer):
    result = verify_problem(q("设机器字长为n位，采用补码表示定点整数，则可表示的十进制整数范围是____（用闭区间表示）。", answer))
    assert result and result["status"] == "FAIL", result


def test_symbolic_range_verification_requires_the_exact_registered_problem_statement():
    result = verify_problem(q("设机器字长为n位，采用原码表示定点整数，则可表示的十进制整数范围是____（用闭区间表示）。",
        "[-2^(n-1),2^(n-1)-1]"))
    assert result is None or result["status"] != "PASS"


def test_ai_personal_symbolic_range_answer_is_exactly_practice_gradable():
    from backend.services.answer_grading import available_practice_grading_method, grade_practice_final_answer
    config = {"verified": False, "method": None, "generated_practice_method": "range_final",
        "generation": {"version": "bounded-question-generation-v10"}}
    common = dict(question_type="fill_blank", config=config,
        expected="[-2^(n-1),2^(n-1)-1]", options=None, answer_provenance="ai_generated",
        content_trust="unreviewed", answer_reliability="model_generated")
    assert available_practice_grading_method(**common) == "ai_generated_range_final"
    grade = lambda answer: grade_practice_final_answer(**common, answer=answer, selected_option=None)
    assert grade(r"\left[-2^{n-1},2^{n-1}-1\right]").result == "right"
    assert grade("[-2^(n-1),2^(n-1)]").result == "unknown"
    assert grade("").result == "unknown"


def test_legacy_teaching_verifier_must_match_requested_family():
    from backend.services.question_generation import family_matches

    assert family_matches("power_derivative", {
        "status": "PASS", "adapter": "teaching_family_v1",
        "proof": {"family": "power_derivative"},
    })
    assert not family_matches("power_integral", {
        "status": "PASS", "adapter": "teaching_family_v1",
        "proof": {"family": "power_derivative"},
    })
    assert not family_matches("power_derivative", {
        "status": "PASS", "adapter": "teaching_family_v1", "proof": {},
    })


def test_legacy_binary_float_family_accepts_only_exact_ieee_adapters():
    from backend.services.question_generation import family_matches

    assert family_matches("binary_float", {"status": "PASS", "adapter": "hs_ieee_decode"})
    assert family_matches("binary_float", {"status": "PASS", "adapter": "hs_ieee_encode"})
    assert family_matches("binary_float", {"status": "PASS", "adapter": "binary_rational_v1"})
    assert not family_matches("binary_float", {"status": "PASS", "adapter": "phase45d_page_replacement_v1"})
    assert not family_matches("binary_float", {"status": "UNKNOWN", "adapter": "hs_ieee_decode"})


def test_ieee754_binary32_hex_is_decoded_exactly_and_rejects_special_values():
    good=q("某 IEEE 754 单精度浮点数的 32 位十六进制表示为 C1A80000，求其表示的十进制真值。", "-21")
    assert verify_problem(good)["status"]=="PASS"
    assert verify_problem(q(good.stem,"-20"))["status"]=="FAIL"
    subnormal=q("某 IEEE 754 单精度浮点数的 32 位十六进制表示为 00000001，求其表示的十进制真值。",
        "1/713623846352979940529142984724747568191373312")
    assert verify_problem(subnormal)["status"]=="UNKNOWN"
    assert verify_problem(q("某 IEEE 754 单精度浮点数的 32 位十六进制表示为 00000000，求其表示的十进制真值。","0"))["status"]=="PASS"
    special=verify_problem(q("某 IEEE 754 单精度浮点数的 32 位十六进制表示为 7F800000，求其表示的十进制真值。","inf"))
    assert special["status"]=="NOT_APPLICABLE"


def test_numeric_determinant_template_uses_unseen_values_and_checks_choice_uniqueness():
    stem="计算二阶行列式，其中第一行是7、-4，第二行是3、9。"
    opts={"A":"75","B":"63","C":"-75","D":"39"}
    assert verify_problem(q(stem,"A",kind="single_choice",options=opts))["status"]=="PASS"
    assert verify_problem(q(stem,"B",kind="single_choice",options=opts))["status"]=="FAIL"
    duplicate=dict(opts,B="75")
    assert verify_problem(q(stem,"A",kind="single_choice",options=duplicate))["reason"]=="non_unique_correct_option"


def test_numeric_determinant_accepts_matching_explicit_latex_matrix_and_row_text():
    stem = r"计算二阶行列式 \begin{vmatrix} 3 & -2 \\ 5 & 4 \end{vmatrix}，其中第一行是 3、-2，第二行是 5、4。"
    result = verify_problem(q(stem, "B", kind="single_choice", options={
        "A": "2", "B": "22", "C": "-22", "D": "-2",
    }))
    assert result["status"] == "PASS", result
    assert result["adapter"] == "phase45i_determinant_2x2_numeric_v1"
    assert result["proof"]["matrix"] == [[3, -2], [5, 4]]


def test_numeric_determinant_rejects_conflicting_latex_matrix_and_row_text():
    stem = r"计算二阶行列式 \begin{vmatrix} 3 & -2 \\ 5 & 4 \end{vmatrix}，其中第一行是 3、-2，第二行是 5、3。"
    result = verify_problem(q(stem, "B", kind="single_choice", options={
        "A": "2", "B": "22", "C": "-22", "D": "-2",
    }))
    assert result["status"] == "UNKNOWN", result
    assert result["reason"] == "determinant_rendering_conflicts_with_row_statement"


def test_derivative_at_point_family_has_parameterized_exact_solution():
    stem="已知函数f(x)=x^3+7x+1，求f'(2)的值。"
    assert verify_problem(q(stem,"19"))["status"]=="PASS"
    assert verify_problem(q(stem,"18"))["status"]=="FAIL"
    unsupported=verify_problem(q("已知函数f(x)=sqrt(x)，求f'(2)的值。","1"))
    assert unsupported["status"]=="UNKNOWN"


@pytest.mark.parametrize(("question", "expected_adapter"), [
    (q("已知函数f(x)=x^4-3x^2+2x，求f'(2)的值。", "22"),
     "phase45i_polynomial_derivative_value_v1"),
    (q("计算定积分：∫_-1^2 x^3+2x dx = ______。", "27/4"),
     "phase45i_polynomial_definite_integral_v1"),
    (q("关于含参数 p 的反常积分 I(p)=∫_e^{+∞} dx/[x(ln x)^p]，下列结论正确的是（ ）。", "A",
        kind="single_choice", options={"A":"p>1当且仅当收敛", "B":"p≥1时收敛", "C":"所有p均收敛", "D":"所有p均发散"}),
     "phase45i_log_improper_integral_p_test_v1"),
    (q(r"计算极限：\lim_{x\to 0}\frac{e^{5x}-1-5x}{x^2}=______。", "25/2"),
     "phase45i_exp_second_order_limit_v1"),
    (q("计算二阶行列式，其中第一行是7、-4，第二行是3、9。", "75"),
     "phase45i_determinant_2x2_numeric_v1"),
    (q("一棵完全二叉树共有12345个结点，则其叶子结点数为（ ）。", "B", kind="single_choice",
        options={"A":"6172", "B":"6173", "C":"6174", "D":"12345"}),
     "phase45i_complete_tree_leaf_count_v1"),
    (q("设机器字长为16位，采用补码表示定点整数，则可表示的十进制整数范围是________（用闭区间表示）。",
        "[-32768,32767]"), "phase45i_twos_complement_range_v1"),
    (q("某 IEEE 754 单精度浮点数的 32 位十六进制表示为 3F000000，求其表示的十进制真值。", "1/2"),
     "phase45i_ieee754_binary32_hex_v1"),
    (q("对长度为257的升序有序表进行折半查找，若所有查找均成功，则查找成功时最多需要比较的关键字个数是（ ）。", "B",
        kind="single_choice", options={"A":"8", "B":"9", "C":"10", "D":"257"}),
     "phase45i_binary_search_max_success_v1"),
    (q("采用LRU页面置换算法，内存有3个页框且初始为空，访问序列为1,2,1,3,1,4，求缺页次数？", "4"),
     "phase45d_page_replacement_v1"),
])
def test_c4_registered_families_verify_unseen_parameterized_examples(question, expected_adapter):
    result = verify_problem(question)
    assert result and result["status"] == "PASS", result
    assert result["adapter"] == expected_adapter


@pytest.mark.parametrize("question", [
    q("已知函数f(x)=x^4-3x^2+2x，求f'(2)的值。", "21"),
    q("计算定积分：∫_-1^2 x^3+2x dx = ______。", "7"),
    q("计算二阶行列式，其中第一行是7、-4，第二行是3、9。", "63"),
    q("某 IEEE 754 单精度浮点数的 32 位十六进制表示为 3F000000，求其表示的十进制真值。", "1"),
])
def test_c4_registered_families_reject_wrong_answers_on_unseen_values(question):
    result = verify_problem(question)
    assert result and result["status"] == "FAIL", result


def test_c4_registered_family_refuses_ambiguous_options_and_missing_conditions():
    ambiguous = q("计算二阶行列式，其中第一行是7、-4，第二行是3、9。", "A", kind="single_choice",
        options={"A":"75", "B":"75", "C":"63", "D":"-75"})
    incomplete = q("对一个序列运行LRU，求缺页次数。", "3")
    assert verify_problem(ambiguous)["reason"] == "non_unique_correct_option"
    result = verify_problem(incomplete)
    assert result is None or result["status"] != "PASS"


def test_generation_failure_status_keeps_truncation_and_format_distinct():
    from json import JSONDecodeError
    from pydantic import ValidationError
    from backend.errors import AppError
    from backend.services.personal_question_service import _generation_failure_status

    assert _generation_failure_status(AppError("answer_truncated")) == "OUTPUT_TRUNCATED"
    assert _generation_failure_status(JSONDecodeError("bad json", "{", 1)) == "FORMAT_ERROR"
    # 超时已从笼统的 BLOCKED 细分为可审计的 PROVIDER_TIMEOUT；两者不可混同。
    assert _generation_failure_status(TimeoutError()) == "PROVIDER_TIMEOUT"

    # A missing-field schema failure is a response-format problem, not a
    # content-correctness verdict. Pydantic's error object is constructed
    # using the same public validation API as the production parser.
    from backend.services.question_generation import Output
    with pytest.raises(ValidationError) as exc:
        Output.model_validate({"stem":"x"})
    assert _generation_failure_status(exc.value) == "FORMAT_ERROR"
