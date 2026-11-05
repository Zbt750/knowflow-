from datetime import datetime, timezone
from uuid import uuid4

from backend.models.learning import KnowledgePoint, Question
from backend.services.question_production_pipeline import (
    assess_production_question, resolve_identity, validate_question_content, duplicate_choice_option_pairs,
)


def reviewed_question(node):
    return Question(id=uuid4(), kp_id=node.id, question_type="single_choice", grading_mode="auto",
        grading_config={"verified": True, "method": "single_choice",
            "provenance": {"source": {"subject": "math2", "year": 2024, "question_number": 1}}},
        stem="设函数在区间上连续，判断下列选项。", options={"A": "甲", "B": "乙"},
        correct_answer="A", explanation="逐项检查条件后可排除 B。", question_role="basic",
        skill_tags=["连续性"], estimated_minutes=5, is_variant=False, is_active=True,
        question_provenance="legacy_unknown", content_trust="unreviewed", source_status="unknown",
        answer_provenance="unknown", answer_reliability="unknown")


def test_identity_resolution_separates_bibliographic_match_from_trust():
    candidate = {"subject": "数学二", "year": 2024, "question_number": 1}
    exact = resolve_identity(candidate, [("q-1", ("math2", 2024, 1))])
    possible = resolve_identity(candidate, [("q-1", ("math2", 2024, 2))])
    unmatched = resolve_identity(candidate, [("q-1", ("408", 2024, 2))])
    duplicate = resolve_identity(candidate, [("q-1", ("math2", 2024, 1)), ("q-2", ("math2", 2024, 1))])

    assert exact.status == "EXACT" and exact.matched_question_ids == ("q-1",)
    assert possible.status == "POSSIBLE"
    assert unmatched.status == "UNMATCHED"
    assert duplicate.status == "CONFLICT"
    assert exact.reason != "verified"  # identity never certifies content or answer


def test_candidate_declared_identity_conflict_fails_closed():
    result = resolve_identity({"subject": "math2", "year": 2024, "question_number": 1,
        "identity": {"subject": "408", "year": 2024, "question_number": 1}}, [])
    assert result.status == "CONFLICT"
    assert result.reason == "candidate_declares_conflicting_identity"


def test_content_validator_catches_missing_options_figure_placeholders_and_duplicates():
    q = Question(id=uuid4(), kp_id=uuid4(), question_type="single_choice",
        stem="如图所示，求该函数的值。TODO", options={"A": "", "a": "乙"},
        correct_answer="C", explanation="解析待补")
    result = validate_question_content(q, duplicate_content=True)
    assert result.status == "INCOMPLETE"
    assert {"placeholder_or_ocr_marker", "choice_options_invalid_or_duplicate",
            "choice_answer_not_in_options", "figure_or_table_asset_not_embedded",
            "duplicate_question_content"} <= set(result.detected_issues)


def test_duplicate_choice_content_is_a_hard_structure_error():
    node = KnowledgePoint(id=uuid4(), code="test.leaf", name="隔离节点", subject="math2")
    q = reviewed_question(node)
    q.options = {"A": "1/2", "B": "0.5", "C": "1", "D": "2"}
    result = validate_question_content(q)
    assert result.status == "INCOMPLETE"
    assert "choice_options_duplicate_content" in result.detected_issues
    assert duplicate_choice_option_pairs(q.options) == [("A", "B")]


def test_option_comparison_preserves_superscripts_variable_case_and_interval_bounds():
    options = {"A": "2ᵐ−1", "B": "2ᵐ⁻¹", "C": "A", "D": "a"}
    assert duplicate_choice_option_pairs(options) == []
    assert duplicate_choice_option_pairs({"A": "(0,1)", "B": "[0,1]"}) == []
    assert duplicate_choice_option_pairs({"A": " A,C ", "B": "$A,C$"}) == [("A", "B")]


def test_source_diagram_reference_requires_embedded_information():
    node = KnowledgePoint(id=uuid4(), code="test.leaf", name="隔离节点", subject="408")
    q = reviewed_question(node)
    q.stem = "如原卷网络图所示，主机H通过AP向Internet发送IP分组，判断帧地址。"
    assert "figure_or_table_asset_not_embedded" in validate_question_content(q).detected_issues
    q.stem += "\n\n```text\nH --无线帧F--> AP\nAP --连接--> R --连接--> Internet\nH MAC: 00-12-34-56-78-9a\nAP MAC: 00-12-34-56-78-9b\nR MAC: 00-12-34-56-78-9c\n```"
    assert validate_question_content(q).completeness == "complete"


def test_code_block_pointing_elsewhere_is_not_a_diagram():
    node = KnowledgePoint(id=uuid4(), code="test.leaf", name="隔离节点", subject="408")
    q = reviewed_question(node)
    q.stem = "如原卷网络图所示，判断帧地址。\n```text\n请自行打开本机PDF原卷查看\n```"
    assert "figure_or_table_asset_not_embedded" in validate_question_content(q).detected_issues


def test_production_assessment_does_not_promote_exact_unreviewed_question():
    node = KnowledgePoint(id=uuid4(), code="synthetic.node", name="隔离节点", subject="math2",
        is_active=True, is_assessable=True, is_reference_only=False)
    q = reviewed_question(node)
    identity = resolve_identity({"subject": "math2", "year": 2024, "question_number": 1},
        [(str(q.id), ("math2", 2024, 1))])
    before = (q.question_provenance, q.content_trust, q.answer_provenance, q.answer_reliability)

    report = assess_production_question(q, node, identity=identity)

    assert report["stages"]["identity_resolution"] == "EXACT"
    assert report["stages"]["eligibility"] == "BLOCKED"
    assert report["production_ready"] is False
    assert report["automatic_trust_promotion"] is False
    assert before == (q.question_provenance, q.content_trust, q.answer_provenance, q.answer_reliability)


def test_reference_only_is_not_treated_as_online_question():
    node = KnowledgePoint(id=uuid4(), code="synthetic.reference", name="索引节点", subject="math2",
        is_active=True, is_assessable=True, is_reference_only=True)
    q = reviewed_question(node)
    report = assess_production_question(q, node)
    assert "reference_only_mapping_not_online_question" in report["content_validation"]["detected_issues"]
    assert report["stages"]["knowledge_mapping_validation"] == "BLOCKED"
    assert report["production_ready"] is False
def test_embedded_table_is_not_missing_asset_and_never_satisfies_missing_figure():
    from types import SimpleNamespace
    from backend.services.question_production_pipeline import validate_question_content
    table='\n| 状态 | 序列 |\n|---|---|\n|初始|1,3,2|\n|第一趟|1,2,3|'
    q=SimpleNamespace(stem='排序结果如下表所示，选择算法。'+table,
        question_type='single_choice',options={'A':'算法甲','B':'算法乙'},correct_answer='A',explanation='逐项核对表格中的序列变化。')
    assert 'figure_or_table_asset_not_embedded' not in validate_question_content(q).detected_issues
    q.stem='依据下图和如下表分析。'+table
    assert 'figure_or_table_asset_not_embedded' in validate_question_content(q).detected_issues
    q.stem='排序结果如下表所示。\n|状态|序列|\n|---|---|'
    assert 'figure_or_table_asset_not_embedded' in validate_question_content(q).detected_issues
    q.stem='排序结果如下表所示。\n|状态|序列|\n|---|---|\n|只有一格|'
    assert 'figure_or_table_asset_not_embedded' in validate_question_content(q).detected_issues

