from datetime import datetime, timezone
from uuid import uuid4

from backend.models.learning import KnowledgePoint, Question
from backend.services.question_production_pipeline import (
    assess_production_question, resolve_identity, validate_question_content,
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
