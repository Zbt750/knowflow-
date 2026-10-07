import pytest

from scripts.audit_real_learning_slices import SLICE_SCOPES
from scripts.stage_real_slice_candidates import stage_cs, stage_math


def refs(subject="408", year=2026, number=3):
    scope = SLICE_SCOPES["binary_tree" if subject == "408" else "integral"]
    return [{"year": year, "question_number": number, "knowledge_point_code": scope["primary"]}]


def row(**kwargs):
    return {"year": 2026, "num": 3, "subject": "数据结构", "stem_text": "Synthetic tree question",
        "stem_html": "<p>Synthetic tree question</p>", "options": [{"label": c, "text": c} for c in "ABCD"],
        "answer": "A", **kwargs}


def test_printed_answer_never_promotes_candidate_to_verified():
    result = stage_cs([row()], refs(), {}, "synthetic-hash")[0]
    assert result["printed_reference_answer"] == "A"
    assert not result["can_import"] and not result["verified"]
    assert result["primary_kp_code"] is None
    assert result["rights_status"] == "UNCONFIRMED"
    assert result["grading_status"] == "UNSUPPORTED"


def test_known_problem_and_diagram_cannot_disappear_in_new_source():
    result = stage_cs([row(stem_html='<img src="synthetic.png">')], refs(),
        {"observations": [{"subject": "cs408", "question_number": 3}]}, "synthetic-hash")[0]
    assert "known_source_problem_requires_independent_resolution" in result["issues"]
    assert "diagram_requires_original_comparison" in result["issues"]


def test_duplicate_identity_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        stage_cs([row(), row()], refs(), {}, "synthetic-hash")


def test_wrong_subject_incomplete_options_and_missing_answer_preserved():
    result = stage_cs([row(subject="操作系统", options=[], answer="")], refs(), {}, "synthetic-hash")[0]
    assert {"source_subject_conflict", "choice_options_incomplete", "reference_answer_invalid_or_missing"} <= set(result["issues"])


def test_unrelated_question_not_added_and_node_bindings_deduplicated():
    assert stage_cs([row(num=4)], refs(), {}, "synthetic-hash") == []
    result = stage_cs([row()], refs() * 2, {}, "synthetic-hash")[0]
    assert len(result["candidate_node_codes"]) == 1


def test_math_subquestions_not_treated_as_new_source_questions():
    text = "3. Synthetic integral problem\n(1) prove a fact\n(2) compute a value\n4. Next question"
    result = stage_math(text, refs("math2", 2024, 3), "synthetic-hash")[0]
    assert "(2) compute a value" in result["raw_text"]
    assert "Next question" not in result["raw_text"]
    assert result["question_type"] is None and result["printed_reference_answer"] is None


def test_duplicate_math_markers_do_not_silently_overwrite():
    with pytest.raises(ValueError, match="Duplicate"):
        stage_math("3. Synthetic one\n3. Synthetic two", refs("math2", 2024, 3), "synthetic-hash")


def test_chinese_score_marker_without_space_starts_new_question():
    text = "18.（本题满分12分）\nSynthetic preceding problem\n19.（本题满分12分）\nSynthetic target problem\n20. Next problem"
    result = stage_math(text, refs("math2", 2024, 19), "synthetic-hash")[0]
    assert "Synthetic target problem" in result["raw_text"]
    assert "preceding" not in result["raw_text"] and "Next problem" not in result["raw_text"]


def test_scope_tag_mismatch_is_warning_not_silent_node_remapping():
    result = stage_cs([row(tags="入栈出栈序列")], refs(), {}, "synthetic-hash")[0]
    assert "source_tag_scope_needs_manual_review" in result["issues"]
    assert result["primary_kp_code"] is None


def test_superscript_loss_and_duplicate_plaintext_options_are_not_silently_accepted():
    options = [{"label": c, "text": "2k-1", "html": "2<sup>k</sup>-1"} for c in "ABCD"]
    result = stage_cs([row(options=options)], refs(), {}, "synthetic-hash")[0]
    assert "option_text_collision_requires_formula_preservation" in result["issues"]
    assert "formula_markup_requires_preservation" in result["issues"]
    assert result["options"][0]["html"] == "2<sup>k</sup>-1"
    assert not result["can_import"]
