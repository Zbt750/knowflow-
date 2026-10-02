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


def _strip_math_wrapper(text: str) -> str:
    value = text.strip().replace("−", "-")
    return value[1:-1].strip() if value.startswith("$") and value.endswith("$") and len(value) > 1 else value


def _numeric_value(text: str | None) -> Fraction | None:
    if text is None or len(text) > 128:
        return None
    value = _strip_math_wrapper(text)
    fraction = _LATEX_FRACTION.fullmatch(value)
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
