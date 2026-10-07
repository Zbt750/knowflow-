import json
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.answer_grading import grade_final_answer
from scripts.audit_grading_coverage import classify_question
from scripts.sync_verified_grading import sync_question, TANGENT_STEM, OLD_TANGENT_EXPLANATION

QUESTIONS = json.loads((Path(__file__).resolve().parents[3] / "seed/questions.json").read_text(encoding="utf-8"))["questions"]
VERIFIED = [q for q in QUESTIONS if q.get("grading_config", {}).get("verified") is True]


@pytest.mark.parametrize("question", VERIFIED, ids=[q["stem"][:30] for q in VERIFIED])
def test_reviewed_question_accepts_answer_and_rejects_counterexample(question):
    choice = question["question_type"] == "single_choice"
    expected = question["correct_answer"]
    wrong = next(key for key in question["options"] if key != expected) if choice else str(Fraction(expected) + 1)
    arguments = dict(question_type=question["question_type"], config=question["grading_config"],
                     expected=expected, options=question["options"])
    assert grade_final_answer(**arguments, answer=None if choice else expected,
                              selected_option=expected if choice else None).result == "right"
    assert grade_final_answer(**arguments, answer=None if choice else wrong,
                              selected_option=wrong if choice else None).result == "wrong"


def test_review_count_and_no_formula_or_multi_result_auto_grading():
    assert len(VERIFIED) == 14
    assert sum(q["question_type"] == "single_choice" for q in VERIFIED) == 8
    for question in QUESTIONS:
        if question["stem"] == TANGENT_STEM or question["correct_answer"] in {
            "-1/x^2", "x + y = 6", "|AB| = -6，|2AB| = -48", "|A^2| = 16，|A^-1| + |A| = 17/4",
        }:
            assert not question.get("grading_config")


def test_tangent_erratum_mathematically_checks_slope_and_point():
    seed = next(q for q in QUESTIONS if q["stem"] == TANGENT_STEM)
    slope = Fraction(3 * 0 ** 2 - 3, 2 * 1)
    assert slope == Fraction(-3, 2)
    assert seed["correct_answer"] == "y = -3x/2 + 1"
    assert "-3/2" in seed["explanation"]


def test_sync_is_exact_and_idempotent_and_preserves_custom_edits():
    seed = VERIFIED[-1]
    question = SimpleNamespace(**{**seed, "grading_config": None})
    assert sync_question(question, seed) == "changed"
    assert sync_question(question, seed) == "unchanged"
    question.explanation = "User reviewed explanation"
    assert sync_question(question, seed) == "conflict"
    question.explanation = seed["explanation"]
    question.grading_config = {"verified": True, "method": "custom"}
    assert sync_question(question, seed) == "conflict"


def test_erratum_requires_exact_old_version_and_does_not_touch_history():
    seed = next(q for q in QUESTIONS if q["stem"] == TANGENT_STEM)
    question = SimpleNamespace(**{**seed, "correct_answer": "y = -3x + 1",
                                "explanation": OLD_TANGENT_EXPLANATION, "grading_config": None})
    assert sync_question(question, seed) == "changed"
    assert sync_question(question, seed) == "unchanged"
    assert question.correct_answer == seed["correct_answer"]
    question.correct_answer = "user custom answer"
    assert sync_question(question, seed) == "conflict"


def test_audit_does_not_call_verified_flag_sufficient():
    q = SimpleNamespace(question_type="proof", grading_config={"verified": True, "method": "numeric_final"},
                        correct_answer="1", options=None)
    assert classify_question(q) == "invalid_verified_config"
    q.grading_config = None
    assert classify_question(q) == "manual_or_unverified"
