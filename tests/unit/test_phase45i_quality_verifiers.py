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
    assert VERSION == "bounded-problem-verifiers-v17"
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
