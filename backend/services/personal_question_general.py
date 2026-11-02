"""全知识节点个人出题；结构检查不冒充答案正确性证明。

不具备专用求解器时仍允许保存个人练习，但只提供参考答案反馈。
这一通路永远不能授予公共正式资格或毕业证据。
"""
from typing import Literal
import re
from uuid import NAMESPACE_URL, uuid5
from pydantic import model_validator
from backend.models.learning import Question
from backend.services.question_generation import Output, generation_hash, verify_explanation_step

VERSION = "personal-general-generation-v1"
PROMPT_VERSION = "personal-general-authoring-v1"
QUESTION_TYPES = ("single_choice", "fill_blank", "calculation", "proof", "subjective")


class GeneralOutput(Output):
    question_type: Literal["single_choice", "fill_blank", "calculation", "proof", "subjective"]

    @model_validator(mode="after")
    def content_shape(self):
        from backend.services.constant_expression import compare_constant_expressions
        from backend.services.question_production_pipeline import validate_question_content
        if len(self.stem.strip()) < 5 or len(self.explanation.strip()) < 10:
            raise ValueError("question_or_explanation_incomplete")
        if not self.correct_answer.strip() or not self.final_value.strip():
            raise ValueError("answer_missing")
        if self.question_type == "single_choice":
            if not isinstance(self.options, dict) or set(self.options) != set("ABCD"):
                raise ValueError("single_choice_requires_exactly_A_to_D")
            values = [re.sub(r"\s+", "", v) for v in self.options.values()]
            if not all(values) or len(set(values)) != 4:
                raise ValueError("duplicate_or_empty_options")
            if self.correct_answer.strip() not in self.options:
                raise ValueError("single_choice_answer_must_be_option_label")
        elif self.options is not None:
            raise ValueError("non_choice_options_must_be_null")
        expected = self.options[self.correct_answer] if self.options else self.correct_answer
        if compare_constant_expressions(expected, self.final_value) == "wrong":
            raise ValueError("answer_final_value_conflict")
        from backend.services.generation_formula_consistency import (
            answer_formula_conflict, power_series_conflict, product_integral_limit_conflict,
            selected_option_conflicts_nonfinite_final)
        if self.options and selected_option_conflicts_nonfinite_final(expected, self.final_value):
            raise ValueError("selected_option_conflicts_with_nonfinite_final_value")
        if answer_formula_conflict(expected, self.final_value):
            raise ValueError("answer_final_value_conflict")
        if power_series_conflict(self.stem, expected, self.final_value, self.explanation):
            raise ValueError("statement_answer_conflict")
        if product_integral_limit_conflict(self.stem, self.final_value):
            raise ValueError("product_integral_limit_answer_conflict")
        from backend.services.generation_formula_consistency import bounded_calculus_check
        fragment = bounded_calculus_check(self.stem, expected, self.final_value, self.explanation,
            self.options, selected_option=self.correct_answer if self.options else None)
        if fragment['status'] == 'CONFLICT':
            raise ValueError('statement_answer_conflict:' + fragment['issue'])
        structure = validate_question_content(self)
        if structure.completeness != "complete":
            raise ValueError("incomplete_question_structure:" + ",".join(structure.detected_issues))
        if re.search(r"官方认证|官方标准答案|人工核验|100%正确", self.explanation):
            raise ValueError("false_authority_claim")
        for step in self.steps:
            if set(step) != {"expression", "value"}:
                raise ValueError("explanation_step_format_invalid")
            if verify_explanation_step(step["expression"], step["value"]) == "wrong":
                raise ValueError("explanation_step_conflict")
        return self


def assess_general_output(output, node, *, request_id, trace, difficulty, parent=None):
    from backend.services.quality_verifiers import verify_problem
    from backend.services.question_pack import QuestionContent
    from backend.services.question_generation import source_input_hash
    # Revalidate at admission, even for an injected/test provider object.
    output = GeneralOutput.model_validate(output.model_dump())
    QuestionContent.model_validate(dict(source_id="personal-general", kp_code=node.code,
        **output.model_dump(exclude={"final_value", "steps"}), difficulty=difficulty,
        question_role="variant" if parent else "basic", skill_tags=[node.name],
        estimated_minutes=12 if output.question_type in {"calculation", "proof", "subjective"} else 5,
        is_variant=bool(parent)))
    q = Question(id=uuid5(NAMESPACE_URL, "personal-general:" + request_id), kp_id=node.id,
        stem=output.stem, question_type=output.question_type, options=output.options,
        correct_answer=output.correct_answer, explanation=output.explanation,
        difficulty=difficulty, question_role="variant" if parent else "basic", skill_tags=[node.name],
        estimated_minutes=12 if output.question_type in {"calculation", "proof", "subjective"} else 5,
        is_variant=bool(parent), is_active=True, is_hidden=False, bank_scope="personal",
        grading_mode="self_assessed", content_trust="unreviewed", source_status="not_applicable",
        question_provenance="ai_generated_practice", answer_provenance="ai_generated",
        answer_reliability="model_generated", grading_config={"verified": False, "method": None})
    try:
        independent = verify_problem(q)
    except Exception as exc:
        # 求解器不适用/报错不代表题目已证错，也不能伪装成PASS。
        independent = {"status": "ERROR", "error_type": type(exc).__name__,
            "reason": "optional_independent_verifier_unavailable"}
    # 解析自证题目有误/选项不匹配时，直接拒绝保存（模型已声明无法与选项一致）。
    _self_contradict = re.search(
        r'选项与计算结果不匹配|四个选项均不正确|选项均不正确|题目有误|题设有误|条件不足|题目条件矛盾|无法确定正确选项',
        output.explanation or "")
    if _self_contradict:
        return {"status": "REJECTED", "review_status": "CONFIRMED_WRONG",
            "errors": ["generated_question_inconsistent"], "question": q,
            "validation_detail": {"self_contradiction": _self_contradict.group(0),
                                  "correct_answer": output.correct_answer,
                                  "explanation": (output.explanation or "")[:500]}}
    if independent and independent.get("status") == "FAIL":
        return {"status": "REJECTED", "review_status": "CONFIRMED_WRONG",
            "errors": ["independent_answer_conflict"], "question": q,
            "validation_detail": {"independent_verification": independent,
                                  "correct_answer": output.correct_answer,
                                  "final_value": output.final_value}}
    # Even a supported arithmetic fragment cannot certify an entire free-form
    # question/explanation. Deliberately retain reference-only feedback here.
    record = {"version": VERSION, "prompt_version": PROMPT_VERSION, "node_code": node.code,
        "generation_mode": "ai_generated", "identity_label": "个人 AI 练习",
        "request_id": request_id, "model": trace.get("model", "unknown"),
        "model_calls": trace.get("model_calls", 1), "authoring_mode": trace.get("mode", "unknown"),
        "parent_question_id": str(parent.id) if parent else None,
        "parent_input_sha256": source_input_hash(parent) if parent else None,
        "independent_verification": independent,
        "mathematical_correctness_status": "not_independently_verified",
        "mathematical_correctness_note": (
            "结构、答案字段和适用的有界一致性检查通过；这不构成整题数学正确性证明。"
            "超出独立验证器范围的题目只作为个人练习参考。"
        ),
        "review_status": "STRUCTURE_CHECKED_REFERENCE_ONLY",
        "answer_independently_verified": False,
        "explanation_steps": output.steps, "final_value": output.final_value,
        "raw_response_sha256": trace.get("raw_response_sha256"),
        "normalized_response_sha256": trace.get("normalized_response_sha256")}
    from backend.services.generation_formula_consistency import bounded_calculus_check
    record['bounded_calculus_check'] = bounded_calculus_check(output.stem,
        output.options[output.correct_answer] if output.options else output.correct_answer,
        output.final_value,output.explanation,output.options,
        selected_option=output.correct_answer if output.options else None)
    q.grading_config = {**q.grading_config, "generation": record}
    record["verified_content_hash"] = generation_hash(q)
    return {"status": "REFERENCE_SAVED", "review_status": record["review_status"],
        "errors": [], "question": q}


def current_general_binding(q, node):
    record = (q.grading_config or {}).get("generation", {})
    if not isinstance(record, dict) or record.get("version") != VERSION:
        return False
    if not (node and node.is_active and node.is_assessable and q.kp_id == node.id
            and q.bank_scope == "personal" and q.generation_batch_id is not None
            and q.question_provenance == "ai_generated_practice" and q.content_trust == "unreviewed"
            and q.answer_provenance == "ai_generated" and q.answer_reliability == "model_generated"
            and q.source_status == "not_applicable" and q.grading_mode == "self_assessed"
            and (q.grading_config or {}).get("verified") is False
            and (q.grading_config or {}).get("method") is None
            and record.get("node_code") == node.code and record.get("prompt_version") == PROMPT_VERSION
            and record.get("review_status") == "STRUCTURE_CHECKED_REFERENCE_ONLY"
            and record.get("answer_independently_verified") is False
            and record.get("verified_content_hash") == generation_hash(q)):
        return False
    try:
        GeneralOutput.model_validate(dict(stem=q.stem, options=q.options, correct_answer=q.correct_answer,
            explanation=q.explanation, question_type=q.question_type,
            final_value=record.get("final_value"), steps=record.get("explanation_steps", [])))
    except (TypeError, ValueError):
        return False
    return True
