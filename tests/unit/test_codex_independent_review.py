from types import SimpleNamespace

import pytest

from backend.services.auto_question_review import (
    attach_codex_independent_review,
    current_codex_independent_review,
)


def _objects():
    node = SimpleNamespace(
        id="kp-1", code="math.example.limit", is_active=True,
        is_assessable=True, children=[],
    )
    question = SimpleNamespace(
        id="q-1", kp_id=node.id, question_type="single_choice",
        stem="求 lim_{x→0} sin(x)/x 的值。", options={
            "A": "0", "B": "1", "C": "2", "D": "不存在",
        }, correct_answer="B", explanation="由基本极限 sin(x)/x→1，因此答案为B。",
        grading_config={"method": "single_choice"},
    )
    return question, node


def _review():
    return {
        "derived_answer": "B",
        "method_evidence": [
            {"method": "limit_definition", "result": "令 u=x，则 sin(u)/u 的标准基本极限为1。"},
            {"method": "series_cross_check", "result": "sin(x)=x-x^3/6+...，故商趋于1。"},
        ],
        "explanation_key_steps": [
            "将变量替换为基本极限中的同一变量。",
            "由 sin(x)/x 在0处的基本极限得1。",
        ],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
    }


def test_independent_review_is_bound_to_current_question_and_node():
    question, node = _objects()
    receipt = attach_codex_independent_review(question, node, **_review())
    assert receipt["human_verified"] is False
    assert current_codex_independent_review(question, node) == receipt
    question.explanation += " 修改"
    assert current_codex_independent_review(question, node) is None


def test_review_rejects_answer_conflict_and_insufficient_independence():
    question, node = _objects()
    review = _review()
    review["derived_answer"] = "A"
    with pytest.raises(ValueError, match="conflicts"):
        attach_codex_independent_review(question, node, **review)

    review = _review()
    review["method_evidence"][1]["method"] = review["method_evidence"][0]["method"]
    with pytest.raises(ValueError, match="two_distinct"):
        attach_codex_independent_review(question, node, **review)


def test_review_rejects_multiple_correct_options():
    question, node = _objects()
    review = _review()
    review["option_truth_table"]["C"] = True
    with pytest.raises(ValueError, match="exactly_one"):
        attach_codex_independent_review(question, node, **review)


@pytest.mark.parametrize("duplicate", ["1", "  $1$ ", "0.5+0.5"])
def test_declared_truth_table_cannot_override_equal_choice_contents(duplicate):
    question, node = _objects()
    question.options["C"] = duplicate
    with pytest.raises(ValueError, match="distinct_option_content"):
        attach_codex_independent_review(question, node, **_review())


def test_forged_refreshed_hashes_do_not_make_duplicate_choice_review_current():
    from backend.services.question_attestation import question_content_sha256
    from backend.services.answer_verification import answer_version_sha256
    question, node = _objects()
    receipt = attach_codex_independent_review(question, node, **_review())
    question.options["C"] = "1"
    receipt["question_content_sha256"] = question_content_sha256(question)
    receipt["answer_sha256"] = answer_version_sha256(question)
    assert current_codex_independent_review(question, node) is None


def test_review_rejects_parent_node_mapping():
    question, node = _objects()
    node.children = ["leaf"]
    with pytest.raises(ValueError, match="leaf_mapping"):
        attach_codex_independent_review(question, node, **_review())
