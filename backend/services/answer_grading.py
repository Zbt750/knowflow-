"""保守的最终答案判定基础；不执行用户表达式，不据此直接判定掌握。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re


@dataclass(frozen=True)
class AnswerVerdict:
    result: str  # right / wrong / unknown
    reason: str
    method: str = "exact_numeric_v1"


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_VALUE = re.compile(rf"{_NUMBER}(?:\s*/\s*{_NUMBER})?", re.ASCII)
_LATEX_FRACTION = re.compile(
    rf"([+-]?)\\(?:frac|dfrac|tfrac)\s*\{{\s*({_NUMBER})\s*\}}\s*\{{\s*({_NUMBER})\s*\}}", re.ASCII)
# TeX permits a single token per unbraced argument. Accept exactly two digits,
# not multi-digit/nested expressions or implicit multiplication such as frac123.
_LATEX_SHORT_FRACTION = re.compile(r"([+-]?)\\(?:frac|dfrac|tfrac)\s*([0-9])\s*([0-9])", re.ASCII)


def _strip_math_wrapper(text: str) -> str:
    value = text.strip().replace("−", "-")
    return value[1:-1].strip() if value.startswith("$") and value.endswith("$") and len(value) > 1 else value


def _numeric_value(text: str | None) -> Fraction | None:
    if text is None or len(text) > 128:
        return None
    value = _strip_math_wrapper(text)
    fraction = _LATEX_FRACTION.fullmatch(value) or _LATEX_SHORT_FRACTION.fullmatch(value)
    if fraction:
        try:
            sign, numerator, denominator = fraction.groups()
            return (-1 if sign == "-" else 1) * Fraction(numerator) / Fraction(denominator)
        except (ValueError, ZeroDivisionError):
            return None
    if not _VALUE.fullmatch(value):
        return None
    try:
        parts = value.split("/")
        numerator = Fraction(parts[0].strip())
        return numerator if len(parts) == 1 else numerator / Fraction(parts[1].strip())
    except (ValueError, ZeroDivisionError):
        return None


def grade_numeric_final_answer(
    *, answer: str | None, expected: str | None, verified: bool,
) -> AnswerVerdict:
    """仅显式核验过的数值答案可判分；公式、证明、单位与近似值均不猜测。"""
    if not verified:
        return AnswerVerdict("unknown", "answer_not_verified")
    if answer is None or not answer.strip():
        return AnswerVerdict("unknown", "not_answered")
    target = _numeric_value(expected)
    if target is None:
        return AnswerVerdict("unknown", "unsupported_reference")
    submitted = _numeric_value(answer)
    if submitted is None:
        return AnswerVerdict("unknown", "unsupported_answer")
    return AnswerVerdict(
        "right" if submitted == target else "wrong", "exact_numeric_comparison",
    )


def _log_argument(text: str | None) -> Fraction | None:
    """仅自然对数的一个正有理数常量；不求值、不解析一般表达式。"""
    if text is None or len(text) > 128:
        return None
    match = re.fullmatch(r"(?:ln|\\ln)\s*(?:\(([^()]*)\)|([^()]+))", _strip_math_wrapper(text), re.ASCII)
    if not match:
        return None
    argument = _numeric_value(match.group(1) if match.group(1) is not None else match.group(2))
    return argument if argument is not None and argument > 0 else None


def grade_logarithm_final_answer(*, answer: str | None, expected: str | None, verified: bool) -> AnswerVerdict:
    method = "exact_logarithm_v1"
    if not verified:
        return AnswerVerdict("unknown", "answer_not_verified", method)
    if answer is None or not answer.strip():
        return AnswerVerdict("unknown", "not_answered", method)
    target = _log_argument(expected)
    if target is None:
        return AnswerVerdict("unknown", "unsupported_reference", method)
    submitted = _log_argument(answer)
    # ln(1)=0 是唯一直接接受的数值特例，其他近似小数不参与比较。
    if submitted is None and target == 1:
        numeric = _numeric_value(answer)
        if numeric is not None:
            return AnswerVerdict("right" if numeric == 0 else "wrong", "exact_logarithm_comparison", method)
    if submitted is None:
        return AnswerVerdict("unknown", "unsupported_answer", method)
    # ln 在正数上严格单调，参数相等才相等；不使用浮点近似或字符串猜测。
    return AnswerVerdict("right" if submitted == target else "wrong", "exact_logarithm_comparison", method)


def grade_final_answer(*, question_type: str, config: dict | None,
                       answer: str | None, selected_option: str | None,
                       expected: str | None, options: dict | None) -> AnswerVerdict:
    config = config or {}
    if not (answer and answer.strip()) and not (selected_option and selected_option.strip()):
        return AnswerVerdict("unknown", "not_answered", "unsupported_v1")
    if config.get("verified") is not True:
        return AnswerVerdict("unknown", "answer_not_verified", "unsupported_v1")
    mode = config.get("method")
    if question_type == "single_choice" and mode == "single_choice":
        chosen = (selected_option or "").strip().upper()
        target = (expected or "").strip().upper()
        if not chosen:
            return AnswerVerdict("unknown", "not_answered", "single_choice_v1")
        if not isinstance(options, dict) or target not in options or chosen not in options:
            return AnswerVerdict("unknown", "unsupported_answer", "single_choice_v1")
        return AnswerVerdict("right" if chosen == target else "wrong",
                             "exact_option_comparison", "single_choice_v1")
    if question_type in {"fill_blank", "calculation"} and mode == "numeric_final":
        return grade_numeric_final_answer(answer=answer, expected=expected, verified=True)
    if question_type in {"fill_blank", "calculation"} and mode == "logarithm_final":
        return grade_logarithm_final_answer(answer=answer, expected=expected, verified=True)
    return AnswerVerdict("unknown", "unsupported_question", "unsupported_v1")


def available_grading_method(*, question_type: str, config: dict | None,
                             expected: str | None, options: dict | None) -> str | None:
    config = config or {}
    if config.get("verified") is not True:
        return None
    if question_type == "single_choice" and config.get("method") == "single_choice":
        return "single_choice" if isinstance(options, dict) and (expected or "").strip().upper() in options else None
    if question_type in {"fill_blank", "calculation"} and config.get("method") == "numeric_final":
        return "numeric_final" if _numeric_value(expected) is not None else None
    if question_type in {"fill_blank", "calculation"} and config.get("method") == "logarithm_final":
        return "logarithm_final" if _log_argument(expected) is not None else None
    return None


def available_practice_grading_method(*, question_type: str, config: dict | None,
                                      expected: str | None, options: dict | None,
                                      answer_provenance: str | None = None,
                                      content_trust: str | None = None,
                                      answer_reliability: str | None = None) -> str | None:
    """Compare imported answer keys for practice without certifying their correctness.

    Verified grading remains a separate contract used by mastery and Agent tools.
    Only actual exam/mock transcriptions with a supported answer can use this path.
    """
    if answer_provenance == "ai_generated" and answer_reliability == "ai_disagreement":
        return None
    method = available_grading_method(question_type=question_type, config=config,
                                     expected=expected, options=options)
    if method:
        return method
    config = config or {}
    if (answer_provenance == "ai_generated"
            and content_trust in {"verified", "source_attested"}
            and (content_trust != "source_attested" or answer_reliability == "ai_generated_consistent")):
        practice_method = config.get("practice_method")
        if practice_method in {"single_choice", "numeric_final", "logarithm_final"}:
            usable = available_grading_method(question_type=question_type,
                config={"verified": True, "method": practice_method}, expected=expected, options=options)
            if usable:
                return f"ai_generated_{usable}"
    provenance = (config or {}).get("provenance", {})
    source = provenance.get("source", {})
    if (provenance.get("content_status") != "source_transcribed"
            or source.get("source_type") not in {"exam", "mock"}):
        return None
    if question_type == "single_choice" and isinstance(options, dict):
        target = (expected or "").strip().upper()
        if target in options and all(isinstance(v, str) and v.strip() for v in options.values()):
            return "reference_single_choice"
    if question_type in {"fill_blank", "calculation"}:
        if _numeric_value(expected) is not None:
            return "reference_numeric_final"
        if _log_argument(expected) is not None:
            return "reference_logarithm_final"
        from backend.services.constant_expression import constant_expression
        if constant_expression(expected) is not None:
            return "reference_constant_final"
    return None


def grade_practice_final_answer(*, question_type: str, config: dict | None,
                                answer: str | None, selected_option: str | None,
                                expected: str | None, options: dict | None,
                                answer_provenance: str | None = None,
                                content_trust: str | None = None,
                                answer_reliability: str | None = None) -> AnswerVerdict:
    if answer_provenance == "ai_generated" and answer_reliability == "ai_disagreement":
        return AnswerVerdict("unknown", "ai_answer_disagreement", "ai_answer_consistency_v1")
    method = available_practice_grading_method(question_type=question_type, config=config,
        expected=expected, options=options, answer_provenance=answer_provenance,
        content_trust=content_trust, answer_reliability=answer_reliability)
    if method and method.startswith("ai_generated_"):
        underlying = method.removeprefix("ai_generated_")
        verdict = grade_final_answer(question_type=question_type,
            config={"verified": True, "method": underlying}, answer=answer,
            selected_option=selected_option, expected=expected, options=options)
        return AnswerVerdict(verdict.result, f"ai_answer_{verdict.reason}", f"ai_answer_{verdict.method}")
    if method and method.startswith("reference_"):
        if method == "reference_constant_final":
            from backend.services.constant_expression import compare_constant_expressions
            result = compare_constant_expressions(answer, expected)
            reason = "not_answered" if not answer or not answer.strip() else "unsupported_answer" if result == "unknown" else "constant_comparison"
            return AnswerVerdict(result, f"reference_{reason}", "reference_constant_v1")
        # The temporary comparator config is never saved or passed to evidence.
        verdict = grade_final_answer(question_type=question_type,
            config={"verified": True, "method": method.removeprefix("reference_")},
            answer=answer, selected_option=selected_option, expected=expected, options=options)
        return AnswerVerdict(verdict.result, f"reference_{verdict.reason}", f"reference_{verdict.method}")
    return grade_final_answer(question_type=question_type, config=config, answer=answer,
                             selected_option=selected_option, expected=expected, options=options)
