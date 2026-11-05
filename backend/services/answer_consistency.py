"""Bounded independent solves for AI-authored reference answers.

Two isolated final-answer-only model calls may establish AI consistency, never an
official answer. Unsupported proof/discussion/programming solutions are not
compared as strings and remain process-review-only.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Iterable

from backend.models.learning import QuestionAnswerConsistencyRun
from backend.services.answer_grading import _log_argument, _numeric_value, available_practice_grading_method


ANSWER_CONSISTENCY_PROMPT_VERSION = "independent-final-answer-v1"
ANSWER_NORMALIZER_VERSION = "bounded-practice-comparers-v1"
MAX_RUNS_PER_CHECK = 4
ANSWER_ATTESTATION_PROMPT_VERSION = "solve-a-b-verify-c-v1"
ANSWER_ATTESTATION_RUN_ROLES = ("solve_a", "solve_b", "verify_c")


def consistency_input_hash(question) -> str:
    """Hash only solver-relevant content and source identity, not derived reliability."""
    provenance = (question.grading_config or {}).get("provenance", {}) if isinstance(question.grading_config, dict) else {}
    source = provenance.get("source", {}) if isinstance(provenance, dict) else {}
    payload = {
        "question_type": question.question_type,
        "stem": question.stem,
        "options": question.options,
        "correct_answer": question.correct_answer,
        "source_identity": {key: source.get(key) for key in ("source_type", "subject", "year", "question_number", "paper_title")},
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode()).hexdigest()


def consistency_check_key(question, *, model: str, prompt_version: str = ANSWER_CONSISTENCY_PROMPT_VERSION) -> str:
    raw = "|".join((str(question.id), consistency_input_hash(question), model.strip(), prompt_version))
    return sha256(raw.encode("utf-8")).hexdigest()


def consistency_method(question) -> str | None:
    if question.answer_provenance != "ai_generated":
        return None
    return available_practice_grading_method(question_type=question.question_type,
        config=question.grading_config if isinstance(question.grading_config, dict) else {},
        expected=question.correct_answer, options=question.options,
        answer_provenance=question.answer_provenance, content_trust=question.content_trust,
        answer_reliability=question.answer_reliability)


def normalize_consistency_answer(*, question_type: str, method: str | None, answer: str | None,
                                options: dict | None, expected: str | None) -> str | None:
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 10000:
        return None
    value = answer.strip().replace("−", "-")
    if value.startswith("```") and value.endswith("```"):
        value = value.strip("`").strip()
    value = re.sub(r"^\s*(?:答案|最终答案)\s*[:：]\s*", "", value)
    if question_type == "single_choice" and method in {"single_choice", "ai_generated_single_choice", "reference_single_choice"}:
        match = re.fullmatch(r"(?:选项\s*)?([A-Za-z])(?:[.．、)）\s]*)", value)
        if not match:
            return None
        label = match.group(1).upper()
        valid = {str(key).strip().upper() for key in options} if isinstance(options, dict) else set()
        return f"choice:{label}" if label in valid else None

    base_method = (method or "").removeprefix("ai_generated_").removeprefix("reference_")
    if question_type not in {"fill_blank", "calculation"}:
        return None
    if base_method == "numeric_final":
        number = _numeric_value(value)
        return f"rational:{number.numerator}/{number.denominator}" if number is not None else None
    if base_method == "logarithm_final":
        argument = _log_argument(value)
        if argument is not None:
            return f"ln-argument:{argument.numerator}/{argument.denominator}"
        expected_argument = _log_argument(expected)
        numeric = _numeric_value(value)
        if expected_argument == 1 and numeric == 0:
            return "ln-argument:1/1"
        return None
    if base_method == "constant_final":
        from backend.services.constant_expression import constant_expression
        from sympy import simplify, sstr
        expression = constant_expression(value)
        return f"constant:{sstr(simplify(expression))}" if expression is not None else None
    return None


def parse_solver_output(raw: str) -> str | None:
    """Accept only a small JSON object; do not persist reasoning or free-form text."""
    if not isinstance(raw, str) or len(raw) > 12000:
        return None
    try:
        value = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or set(value) != {"answer"}:
        return None
    answer = value.get("answer")
    return answer.strip() if isinstance(answer, str) and answer.strip() and len(answer) <= 10000 else None


def build_solver_messages(question) -> list[dict[str, str]]:
    options = question.options if question.question_type == "single_choice" else None
    payload = {"question_type": question.question_type, "stem": question.stem, "options": options}
    return [
        {"role": "system", "content": (
            "独立解题，仅输出 JSON：{\"answer\":\"最终答案\"}。不要输出推理过程、解释、引用或历史上下文。"
            "选择题只输出选项字母；证明、讨论、算法设计和程序题不支持本一致性检查。"
        )},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def consistency_outcome(question, runs: Iterable[QuestionAnswerConsistencyRun]) -> dict:
    method = consistency_method(question)
    if method is None or question.question_type not in {"single_choice", "fill_blank", "calculation"}:
        return {"status": "NOT_APPLICABLE", "normalized_answer": None,
                "reason": "unsupported_question_type_or_comparer", "observed_runs": 0}
    rows = sorted(list(runs), key=lambda row: row.run_number)
    completed = [row.normalized_final_answer for row in rows
                 if row.status == "completed" and row.normalized_final_answer]
    if len(completed) < 2:
        return {"status": "INCOMPLETE", "normalized_answer": None,
                "reason": "two_successful_independent_runs_required", "observed_runs": len(completed)}
    if len(set(completed)) != 1:
        return {"status": "AI_DISAGREEMENT", "normalized_answer": None,
                "reason": "independent_solutions_disagree", "observed_runs": len(completed)}
    expected = normalize_consistency_answer(question_type=question.question_type, method=method,
        answer=question.correct_answer, options=question.options, expected=question.correct_answer)
    if expected is None:
        return {"status": "NOT_APPLICABLE", "normalized_answer": completed[0],
                "reason": "stored_reference_answer_not_supported_by_bounded_normalizer", "observed_runs": len(completed)}
    if completed[0] != expected:
        return {"status": "AI_DISAGREEMENT", "normalized_answer": completed[0],
                "reason": "independent_result_disagrees_with_stored_ai_answer", "observed_runs": len(completed)}
    return {"status": "AI_CONSISTENT", "normalized_answer": completed[0],
            "reason": "two_independent_answers_match_each_other_and_stored_ai_answer", "observed_runs": len(completed)}


def apply_consistency_reliability(question, outcome: dict) -> bool:
    """Update only AI answer reliability; never alter provenance or human review."""
    if question.answer_provenance != "ai_generated" or question.answer_reliability == "verified":
        return False
    target = {"AI_CONSISTENT": "ai_generated_consistent", "AI_DISAGREEMENT": "ai_disagreement"}.get(outcome.get("status"))
    if target is None or question.answer_reliability == target:
        return False
    question.answer_reliability = target
    return True


def build_run(*, question, check_key: str, run_number: int, model: str,
              normalized_answer: str | None, status: str, latency_ms: int | None,
              usage: dict | None, error_code: str | None = None):
    if run_number < 1 or run_number > MAX_RUNS_PER_CHECK:
        raise ValueError("consistency run bound exceeded")
    if status not in {"completed", "failed", "unsupported"}:
        raise ValueError("invalid consistency run status")
    if status == "completed" and not normalized_answer:
        raise ValueError("completed run requires a normalized answer")
    result_hash = sha256(normalized_answer.encode("utf-8")).hexdigest() if normalized_answer else None
    return QuestionAnswerConsistencyRun(
        check_key=check_key, question_id=question.id,
        question_content_sha256=consistency_input_hash(question), run_number=run_number,
        configured_model=model[:100], prompt_version=ANSWER_CONSISTENCY_PROMPT_VERSION,
        normalizer_version=ANSWER_NORMALIZER_VERSION, status=status,
        normalized_final_answer=normalized_answer, result_sha256=result_hash,
        error_code=(error_code or None), latency_ms=latency_ms,
        usage=usage if isinstance(usage, dict) else None,
    )


def answer_attestation_content_hash(question) -> str:
    """Hash the actual prompt, independent of the candidate answer being checked."""
    raw = json.dumps({"question_type": question.question_type, "stem": question.stem,
                      "options": question.options, "kp_id": str(question.kp_id)},
                     sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def answer_attestation_check_key(question, *, model: str) -> str:
    return sha256("|".join((str(question.id), answer_attestation_content_hash(question),
        model.strip(), ANSWER_ATTESTATION_PROMPT_VERSION, ANSWER_NORMALIZER_VERSION)).encode()).hexdigest()


def answer_attestation_result_hash(question) -> str:
    """Bind a successful A/B/C outcome to the current prompt and stored answer."""
    raw = json.dumps({"prompt_hash": answer_attestation_content_hash(question),
                      "answer": question.correct_answer}, sort_keys=True,
                     ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def has_current_answer_attestation(question) -> bool:
    return bool(getattr(question, "answer_attestation_key", None)
        and getattr(question, "answer_attestation_sha256", None)
        and question.answer_attestation_sha256 == answer_attestation_result_hash(question))


def answer_attestation_method(question) -> str | None:
    """Only use existing bounded comparers; never infer support from answer text."""
    return available_practice_grading_method(
        question_type=question.question_type,
        config=question.grading_config if isinstance(question.grading_config, dict) else {},
        expected=question.correct_answer, options=question.options,
        answer_provenance=question.answer_provenance,
        content_trust=question.content_trust,
        answer_reliability=question.answer_reliability,
    )


def build_attestation_solver_messages(question) -> list[dict[str, str]]:
    payload = {"question_type": question.question_type, "stem": question.stem,
               "options": question.options if question.question_type == "single_choice" else None}
    return [
        {"role": "system", "content": (
            "你在进行独立解题，只输出严格 JSON：{\"answer\":\"最终答案\"}。"
            "不得输出推理、过程、说明或其他字段。选择题只填选项字母；填空/计算只给最终答案。"
            "若题面缺失关键条件、图表或无法确定答案，返回 {\"answer\":\"\"}。"
        )},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def parse_final_answer_payload(raw: str) -> str | None:
    if not isinstance(raw, str) or len(raw) > 12000:
        return None
    try:
        payload = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or set(payload) != {"answer"}:
        return None
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip() or len(answer.strip()) > 1000:
        return None
    return answer.strip()


def build_attestation_verifier_messages(question, *, answer_a: str, answer_b: str) -> list[dict[str, str]]:
    payload = {"question_type": question.question_type, "stem": question.stem,
        "options": question.options if question.question_type == "single_choice" else None,
        "normalized_candidate_answers": [answer_a, answer_b]}
    return [
        {"role": "system", "content": (
            "你是独立答案核验员。只基于题面和给出的规范化候选最终答案逐项核验；"
            "不要接收或生成隐藏推理，不要重新给候选答案投票。仅输出严格 JSON："
            "{\"status\":\"supports|rejects|uncertain\",\"supported_answers\":[\"原样复制被支持的候选答案\"],"
            "\"note\":\"不超过120字的简短核验结论\"}。题面信息不足或无法可靠判定时必须 uncertain。"
        )},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def parse_verifier_payload(raw: str) -> dict | None:
    if not isinstance(raw, str) or len(raw) > 4000:
        return None
    try:
        value = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or set(value) != {"status", "supported_answers", "note"}:
        return None
    if value.get("status") not in {"supports", "rejects", "uncertain"}:
        return None
    supported = value.get("supported_answers")
    note = value.get("note")
    if (not isinstance(supported, list) or len(supported) > 2
            or any(not isinstance(item, str) or len(item) > 120 for item in supported)
            or not isinstance(note, str) or len(note.strip()) > 120):
        return None
    return {"status": value["status"], "supported_answers": supported,
            "note": note.strip()}


def answer_attestation_outcome(runs: Iterable[QuestionAnswerConsistencyRun]) -> dict:
    """Require A/B agreement AND C support; no majority vote or answer-key trust."""
    latest: dict[str, QuestionAnswerConsistencyRun] = {}
    for row in sorted(list(runs), key=lambda item: item.run_number):
        role = getattr(row, "run_role", None)
        if role in ANSWER_ATTESTATION_RUN_ROLES and (role not in latest or row.status == "completed"):
            latest[role] = row
    if any(role not in latest for role in ANSWER_ATTESTATION_RUN_ROLES):
        return {"status": "INCOMPLETE", "reason": "solve_a_solve_b_verify_c_required",
                "completed_roles": sorted(latest)}
    a, b, c = (latest[role] for role in ANSWER_ATTESTATION_RUN_ROLES)
    if any(row.status != "completed" for row in (a, b, c)):
        return {"status": "INCOMPLETE", "reason": "one_or_more_roles_failed_or_unsupported",
                "completed_roles": [role for role, row in latest.items() if row.status == "completed"]}
    if not a.normalized_final_answer or a.normalized_final_answer != b.normalized_final_answer:
        return {"status": "AI_DISAGREEMENT", "reason": "independent_solve_answers_differ",
                "normalized_answer": None, "verification_result": c.verification_result}
    verdict = c.verification_result if isinstance(c.verification_result, dict) else {}
    supported_answers = verdict.get("supported_answers")
    # Some compatible chat models repeat the same answer for both candidates
    # when A and B are identical. Repetition is not a vote; accept only when
    # every returned value is still exactly the shared canonical candidate.
    # Any extra/different answer remains fail-closed.
    if (verdict.get("status") != "supports"
            or not isinstance(supported_answers, list) or not supported_answers
            or any(answer != a.normalized_final_answer for answer in supported_answers)):
        status = "AI_DISAGREEMENT" if verdict.get("status") == "rejects" else "NEEDS_REVIEW"
        return {"status": status, "reason": "verify_c_did_not_support_consensus_answer",
                "normalized_answer": None, "verification_result": verdict}
    return {"status": "AI_CONSISTENT", "reason": "solve_a_solve_b_agree_and_verify_c_supports",
            "normalized_answer": a.normalized_final_answer,
            "final_answer": a.final_answer,
            "verification_result": verdict}


def build_attestation_run(*, question, check_key: str, run_number: int, run_role: str,
                          model: str, final_answer: str | None, normalized_answer: str | None,
                          status: str, latency_ms: int | None, usage: dict | None,
                          verification_result: dict | None = None,
                          candidate_answers_sha256: str | None = None,
                          source_answer_sha256: str | None = None,
                          error_code: str | None = None):
    if run_number not in range(1, 7) or run_role not in ANSWER_ATTESTATION_RUN_ROLES:
        raise ValueError("invalid three-role answer-attestation run")
    if status not in {"completed", "failed", "unsupported"}:
        raise ValueError("invalid answer-attestation run status")
    if status == "completed" and run_role in {"solve_a", "solve_b"} and not final_answer:
        raise ValueError("completed solve requires a final answer")
    if status == "completed" and run_role == "verify_c" and not isinstance(verification_result, dict):
        raise ValueError("completed verifier requires structured result")
    answer_hash = sha256(normalized_answer.encode("utf-8")).hexdigest() if normalized_answer else None
    return QuestionAnswerConsistencyRun(
        check_key=check_key, question_id=question.id,
        question_content_sha256=answer_attestation_content_hash(question),
        run_number=run_number, run_role=run_role, configured_model=model[:100],
        prompt_version=ANSWER_ATTESTATION_PROMPT_VERSION,
        normalizer_version=ANSWER_NORMALIZER_VERSION, status=status,
        normalized_final_answer=normalized_answer, final_answer=final_answer,
        verification_result=verification_result,
        verification_note=(str(verification_result.get("note") or "")[:500]
                           if isinstance(verification_result, dict) else None),
        candidate_answers_sha256=candidate_answers_sha256,
        source_answer_sha256=source_answer_sha256,
        result_sha256=answer_hash, error_code=(error_code or None),
        latency_ms=latency_ms, usage=usage if isinstance(usage, dict) else None,
    )
