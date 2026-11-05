from uuid import uuid4
from hashlib import sha256

from backend.models.learning import KnowledgePoint, Question
from backend.services.auto_question_review import (
    _exam_subject_matches_node, _explanation_check, prepare_exam_curated_repair,
    question_snapshot_sha256,
)
from backend.services.question_attestation import question_content_sha256
from backend.services.answer_verification import answer_version_sha256
from backend.services.quality_verifiers import verify_problem
from scripts.run_phase45hr_isolated_repair import _select_pilot


def test_curated_explanation_repair_binds_the_repaired_content_and_explanation_hashes():
    node = KnowledgePoint(id=uuid4(), code="cs408.ds.synthetic-tree", subject="408",
        name="隔离合成树题节点", is_active=True, is_assessable=True, is_reference_only=True)
    question = Question(id=uuid4(), kp_id=node.id, question_type="single_choice",
        stem="非空完全二叉树所有叶在同层，且每个非叶结点有2个孩子；若叶数为k，求总结点数。",
        options={"A": "2k-1", "B": "2k", "C": "k^2", "D": "2^k-1"},
        correct_answer="A", explanation="旧解析。", skill_tags=["二叉树性质"],
        question_provenance="legacy_unknown", source_status="unverified",
        grading_config={"provenance": {"source": {"source_type": "exam", "subject": "408",
            "year": 2018, "question_number": 4, "citation": "隔离来源线索"}}},
        bank_scope="public", is_active=True)
    solver = verify_problem(question)
    assert solver["status"] == "PASS"
    before_content = question_content_sha256(question)
    before_answer = answer_version_sha256(question)
    before_snapshot = question_snapshot_sha256(question)
    source_evidence = {"mapped_node_code": node.code,
        "question_content_sha256": before_content}

    result = prepare_exam_curated_repair(question, node, source_evidence)

    assert result["changed_fields"]
    assert result["before"]["question_content_sha256"] == before_content
    assert result["after_question_content_sha256"] == question_content_sha256(question)
    # The content fingerprint intentionally covers stem/options/type/mapping,
    # while the full snapshot separately binds the repaired explanation.
    assert result["after_question_content_sha256"] == before_content
    assert answer_version_sha256(question) == before_answer
    assert question_snapshot_sha256(question) != before_snapshot
    record = question.grading_config["generation"]["machine_explanation"]
    assert record["question_content_sha256"] == question_content_sha256(question)
    assert record["answer_sha256"] == answer_version_sha256(question)
    assert record["explanation_sha256"] == sha256(question.explanation.encode("utf-8")).hexdigest()
    assert question.question_provenance == "real_exam"
    assert question.source_status == "traceable"
    assert question.content_reviewed_by is None
    assert _explanation_check(question, solver)["status"] == "PASS"


def test_phase45hr_pilot_selector_uses_inventory_field_names_and_excludes_nonleaves():
    rows = [
        {"question_id": "b", "source_pack_traceable": True, "node_eligible_leaf": True,
         "solver_status": "NOT_APPLICABLE", "subject": "408", "question_type": "proof",
         "node_code": "cs408.ds.tree"},
        {"question_id": "a", "source_pack_traceable": True, "node_eligible_leaf": True,
         "solver_status": "PASS", "subject": "408", "question_type": "single_choice",
         "node_code": "cs408.ds.tree"},
        {"question_id": "c", "source_pack_traceable": True, "node_eligible_leaf": False,
         "solver_status": "PASS", "subject": "math2", "question_type": "fill_blank",
         "node_code": "math2.limit"},
    ]
    selected = _select_pilot(rows, 10)
    assert {row["question_id"] for row in selected} == {"a", "b"}


def test_phase45hr_exam_subject_allows_math2_to_shared_math_curriculum_mapping():
    assert _exam_subject_matches_node("数学二", "考研数学")
    assert _exam_subject_matches_node("math2", "数学二")
    assert not _exam_subject_matches_node("408", "考研数学")
    assert not _exam_subject_matches_node("数学二", "408")
