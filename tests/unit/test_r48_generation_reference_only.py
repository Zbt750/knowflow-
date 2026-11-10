from uuid import uuid4

from backend.models.learning import KnowledgePoint, Question
from backend.services.personal_question_families import resolve_family
from backend.services.question_generation import Output, assess_output


def _assessment(*, step_expression="对分子和分母连续求导并取极限", step_value="2",
                final_value="2", prompt_version="question-generation-c4-v1"):
    node = KnowledgePoint(id=uuid4(), code="math.calculus.limit.lhopital", name="洛必达法则",
        subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
    family = resolve_family(node.code, "single_choice")
    parent = Question(id=uuid4(), kp_id=node.id, question_type="single_choice",
        stem="TEST_FIXTURE 原题：lim x→0 sin(x)/x", options={"A": "1", "B": "0", "C": "2", "D": "不存在"},
        correct_answer="A", explanation="TEST_FIXTURE", question_provenance="trusted_practice",
        source_status="verified", grading_config={}, difficulty="basic", skill_tags=[node.name])
    output = Output(stem=r"计算极限：\lim_{x\to 0}\frac{e^{2x}-1-2x}{x^2} 的值是（ ）。",
        question_type="single_choice", options={"A": "1", "B": "2", "C": "3", "D": "4"},
        correct_answer="B", explanation="当x趋近0时可连续使用洛必达法则，最终得到2。",
        final_value=final_value, steps=[{"expression": step_expression, "value": step_value}])
    result = assess_output(output, node, request_id="r48-reference-only-regression", mode="adapted",
        family=family.family_id, parent=parent,
        trace={"prompt_version": prompt_version, "mode": "real_model", "model_calls": 1},
        difficulty="basic", family_spec=family)
    return result


def test_c4_answer_proven_with_unverified_explanation_is_only_personal_reference():
    result = _assessment()

    assert result["status"] == "REFERENCE_SAVED"
    assert result["review_status"] == "ANSWER_VERIFIED_EXPLANATION_REFERENCE_ONLY"
    assert result["question"].bank_scope is None  # run_generation assigns the personal scope at commit.
    assert result["question"].grading_mode == "self_assessed"
    assert result["question"].question_provenance == "ai_generated_practice"
    assert result["question"].grading_config["verified"] is False
    record = result["question"].grading_config["generation"]
    assert record["answer_independently_verified"] is True
    assert record["explanation_independently_verified"] is False
    assert record["reference_only_reason"] == ["explanation_step_not_independently_verified"]


def test_c4_answer_or_proven_explanation_conflict_still_rejects():
    wrong_answer = _assessment(final_value="3")
    wrong_step = _assessment(step_expression="1+1", step_value="3")

    assert wrong_answer["status"] == "REJECTED"
    assert "explanation_final_value_conflict" in wrong_answer["errors"]
    assert wrong_step["status"] == "REJECTED"
    assert "explanation_step_conflict" in wrong_step["errors"]
