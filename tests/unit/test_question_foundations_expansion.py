"""Independent arithmetic checks for authored candidates, NOT human verification."""
from fractions import Fraction as F
from pathlib import Path

import pytest

from backend.services.golden_learning_slice import GoldenSlice, reviewed_pack
from scripts.audit_golden_learning_slice import audit_files, render_review_sheet
from tests.unit.test_golden_learning_slice import bind_current_lessons_for_test

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "eval/golden/math2_408_foundations_expansion_v1.json"


def asset():
    return GoldenSlice.model_validate_json(PATH.read_text(encoding="utf-8"))


def matrix_rank(rows):
    matrix = [[F(value) for value in row] for row in rows]
    pivot = 0
    for col in range(len(matrix[0])):
        selected = next((i for i in range(pivot, len(matrix)) if matrix[i][col]), None)
        if selected is None:
            continue
        matrix[pivot], matrix[selected] = matrix[selected], matrix[pivot]
        scale = matrix[pivot][col]
        matrix[pivot] = [x / scale for x in matrix[pivot]]
        for i in range(len(matrix)):
            if i != pivot:
                scale = matrix[i][col]
                matrix[i] = [x - scale * y for x, y in zip(matrix[i], matrix[pivot])]
        pivot += 1
        if pivot == len(matrix):
            break
    return pivot


def rr_completion():
    queue, remaining, clock, completion = ["A", "B"], {"A": 5, "B": 3}, 0, {}
    while queue:
        item = queue.pop(0)
        duration = min(2, remaining[item])
        clock += duration
        remaining[item] -= duration
        if remaining[item]:
            queue.append(item)
        else:
            completion[item] = clock
    return completion


def integral(coefficients, upper):
    return sum((F(c, power + 1) * F(upper) ** (power + 1)
                for power, c in enumerate(coefficients)), F(0))


ORACLES = {
    "I09": integral([0, 2, 3], 2),
    "I10": integral([0, 1, -2, 1], 1),
    "I12": (1 + 1 ** 2) * 2 * 1,
    "R01": matrix_rank([[1, 2, 3], [2, 4, 6], [0, 1, 1]]),
    "R03": sum(matrix_rank([[1, 1, 0], [0, a, 1], [0, 0, a - 2]]) == 2 for a in [0, 2]),
    "L01": F(5 + 1, 1 + 2),
    "L03": 2 * 1 - 1,
    "C01": 2 + 2,
    "C03": (2 * 1 + 1) + 2,
    "D01": 3 * 2 ** 2 - 4 * 2,
    "D02": F(2 * 1, 1 + 1 ** 2),
    "D04": F(-3, 4),
    "T09": 12 + 1,
    "T10": 26 - 26 // 2,
    "S02": len(range(1, 10)),
    "S03": sum(range(1, 5)),
    "H01": (32).bit_length() - 1,
    "H02": 32 - ((4096 // 32).bit_length() - 1) - ((32).bit_length() - 1),
    "H03": (8192 // 32 // 4).bit_length() - 1,
    "P01": F(0 + 4 + (4 + 2), 3),
    "P02": F(1 + (1 + 2) + (1 + 2 + 4), 3),
    "P03": rr_completion()["B"],
    "N01": 1000 + 300,
    "N02": 5000,
}


@pytest.mark.parametrize("source_id", sorted(ORACLES))
def test_numeric_candidates_match_independent_calculations(source_id):
    question = next(q for q in asset().questions if q.content.source_id == source_id)
    assert F(question.content.correct_answer) == ORACLES[source_id]
    assert question.content.grading_method == "numeric_final"
    assert not question.verified


def test_all_candidates_are_mapped_deduplicated_and_blocked_from_release():
    frozen = asset()
    before = frozen.model_dump(mode="json")
    candidate = bind_current_lessons_for_test(frozen)
    report = audit_files(candidate)
    assert len(candidate.topics) == 10 and len(candidate.questions) == 40
    assert len({q.content.stem for q in candidate.questions}) == 40
    assert sum(t.subject == "408" for t in candidate.topics) == 5
    assert report["structural_checks_passed"]
    assert report["verified_questions"] == 0 and not report["release_ready"]
    assert all(q.source.origin == "AI_GENERATED" for q in candidate.questions)
    assert all(r.status == "GENERATED" for q in candidate.questions for r in q.reviews.values())
    assert {q.content.source_id for q in candidate.questions if q.content.grading_method == "numeric_final"} == set(ORACLES)
    with pytest.raises(ValueError, match="human review incomplete"):
        reviewed_pack(candidate)
    assert frozen.model_dump(mode="json") == before


def test_choices_have_unique_options_and_manual_types_never_auto_grade():
    for q in asset().questions:
        c = q.content
        if c.options:
            assert len(c.options) == len(set(c.options.values())) == 4
            assert c.correct_answer in c.options
        if c.question_type in {"proof", "subjective"}:
            assert c.grading_method is None


def test_human_sheet_includes_each_question_source_and_review_hash():
    candidate = asset()
    sheet = render_review_sheet(candidate, audit_files(candidate))
    assert "10 个专题、40 道候选题" in sheet
    for q in candidate.questions:
        assert q.content.source_id in sheet
        assert q.content.stem in sheet
        assert q.source.citation in sheet
        assert q.content_hash() in sheet
