from types import SimpleNamespace as Item

import pytest

from scripts.audit_knowledge_assets import question_supply


def node(code, count=0, refs=100, assessable=True):
    return {"code": code, "subject": "408", "assessable": assessable,
            "answerable_questions": count, "exam_reference_bindings": refs}


def test_many_references_and_candidates_do_not_fill_online_gap():
    candidate = Item(questions=[Item(content=Item(kp_code="tree", stem="某题"))])
    report = question_supply({"nodes": [node("tree"), node("parent", assessable=False)]},
                             minimum=5, candidate_assets=[candidate, candidate])
    assert report["online_quantity_gap"] == 5
    assert len(report["nodes"]) == 1
    assert report["nodes"][0]["draft_candidates"] == 1
    assert report["nodes"][0]["exam_references_not_counted"] == 100
    assert not report["coverage_or_quality_certified"]


def test_other_node_cannot_borrow_excess_questions():
    report = question_supply({"nodes": [node("a", count=10), node("b", count=1)]}, minimum=5)
    assert report["online_quantity_gap"] == 4
    assert report["subjects"]["408"]["nodes_below_quantity_floor"] == 1


def test_invalid_draft_mapping_stays_visible():
    candidate = Item(questions=[Item(content=Item(kp_code="inactive", stem="某题"))])
    report = question_supply({"nodes": [node("tree")]}, minimum=5, candidate_assets=[candidate])
    assert report["candidate_codes_outside_active_assessable_scope"] == ["inactive"]


@pytest.mark.parametrize("minimum", [0, -1, 101])
def test_invalid_quantity_floor_is_rejected(minimum):
    with pytest.raises(ValueError):
        question_supply({"nodes": []}, minimum=minimum)
