from scripts.prepare_transcribed_question_pack import extract, prepare
import pytest


def candidate():
    return {"raw_transcription": "8. 原卷隔离合成题干\n(A) 甲\n(B) 乙\n(C) 丙\n(D) 丁\n【答案】(B)\n页脚广告", "issues": []}


def selection():
    return {"question_type": "single_choice", "printed_answer": "B", "visual_comparison_complete": True}


def test_extract_does_not_leak_answer_or_footer_into_stem():
    stem, options, answer = extract(candidate(), selection())
    assert stem == "原卷隔离合成题干"
    assert options == {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    assert answer == "B"


@pytest.mark.parametrize("problem", ["missing_options", "cross_page", "no_answer", "different_answer", "no_comparison"])
def test_no_fabrication_or_silent_repair(problem):
    q, choice = candidate(), selection()
    if problem == "missing_options": q["issues"].append("missing_choice_options")
    if problem == "cross_page": q["issues"].append("last_page_boundary_requires_next_page")
    if problem == "no_answer": q["raw_transcription"] = "题干，没有答案"
    if problem == "different_answer": choice["printed_answer"] = "D"
    if problem == "no_comparison": choice["visual_comparison_complete"] = False
    with pytest.raises(ValueError):
        extract(q, choice)


def test_previous_source_contradiction_cannot_be_silently_selected():
    identity = {"subject": "math2", "year": 2026, "question_number": 6}
    with pytest.raises(ValueError, match="Known source"):
        prepare({"questions": [identity]}, {"questions": [identity]},
                {"observations": [{**identity, "kind": "source_internal_inconsistency"}]})


def test_primary_mapping_and_source_question_type_need_explicit_rationale():
    identity = {"subject": "cs408", "year": 2026, "question_number": 1}
    with pytest.raises(ValueError, match="mapping rationale"):
        prepare({"questions": [identity]}, {"questions": [identity]}, {"observations": []})
