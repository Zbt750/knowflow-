from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.models.learning import KnowledgePoint, Question
from backend.services.question_eligibility import question_eligibility


REVIEWED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


def reviewed_node(*, reference_only=False):
    return KnowledgePoint(id=uuid4(), code="synthetic.reviewed.leaf", subject="math2",
        name="隔离合成节点", is_active=True, is_assessable=True, is_reference_only=reference_only)


def question(node, *, provenance="real_exam", qtype="single_choice", answer_provenance="verified_reference",
             reliability="verified", trust="verified", source_status="verified", grading_config=None):
    choice = qtype == "single_choice"
    verified_answer = answer_provenance == "verified_reference"
    return Question(id=uuid4(), kp_id=node.id, question_type=qtype, is_active=True,
        stem="隔离合成测试题目，检查知识判断。", options={"A": "甲", "B": "乙"} if choice else None,
        correct_answer="A" if choice else "完整参考答案", explanation="隔离合成解析说明。",
        grading_config=grading_config or {}, question_provenance=provenance,
        content_trust=trust, source_status=source_status, answer_provenance=answer_provenance,
        answer_reliability=reliability, content_reviewed_by="fixture-reviewer" if trust == "verified" else None,
        content_reviewed_at=REVIEWED_AT if trust == "verified" else None,
        answer_reviewed_by="answer-reviewer" if verified_answer and reliability == "verified" else None,
        answer_reviewed_at=REVIEWED_AT if verified_answer and reliability == "verified" else None)


def test_verified_real_question_and_reference_answer_is_objectively_eligible():
    node = reviewed_node()
    item = question(node, grading_config={"verified": True, "method": "single_choice"})
    item.kp_id = node.id
    result = question_eligibility(item, node)
    assert result.practice_eligible
    assert result.grading_capability == "deterministic"
    assert result.evidence_capability == "verified_objective"


def test_ai_answer_is_practice_eligible_but_never_reference_verified_or_strong_evidence():
    node = reviewed_node()
    item = question(node, answer_provenance="ai_generated", reliability="model_generated",
        grading_config={"verified": False, "practice_method": "single_choice"})
    result = question_eligibility(item, node)
    assert result.practice_eligible
    assert result.answer_provenance == "ai_generated"
    assert result.answer_reliability == "model_generated"
    assert result.answer_comparison_method == "ai_generated_single_choice"
    assert result.grading_capability == "final_answer_limited"
    assert result.evidence_capability == "ai_low_reliability"
    assert result.verified_grading_method is None


def test_ai_reference_comparison_does_not_upgrade_ai_provenance():
    node = reviewed_node()
    item = question(node, provenance="trusted_practice", answer_provenance="ai_generated",
        reliability="ai_generated_consistent", grading_config={"practice_method": "single_choice"})
    result = question_eligibility(item, node)
    assert result.practice_eligible
    assert result.answer_provenance != "verified_reference"
    assert result.evidence_capability != "verified_objective"


def test_ai_answer_for_proof_is_practice_eligible_but_process_review_only():
    node = reviewed_node()
    item = question(node, qtype="proof", answer_provenance="ai_generated", reliability="unverified")
    result = question_eligibility(item, node)
    assert result.practice_eligible
    assert result.grading_capability == "process_review_only"
    assert result.answer_comparison_method is None
    assert result.evidence_capability == "process_review_not_objective_evidence"


def test_unreviewed_question_is_blocked_even_when_it_has_answer_and_old_verified_json():
    node = reviewed_node()
    item = question(node, trust="unreviewed", answer_provenance="unknown", reliability="unknown",
        provenance="legacy_unknown", source_status="unknown",
        grading_config={"verified": True, "method": "single_choice"})
    result = question_eligibility(item, node)
    assert not result.practice_eligible
    assert result.evidence_capability == "self_report_only"
    assert "content_not_verified" in result.blocking_reasons


def test_reference_only_mapping_is_not_silently_treated_as_assessable():
    node = reviewed_node(reference_only=True)
    item = question(node, grading_config={"verified": True, "method": "single_choice"})
    result = question_eligibility(item, node)
    assert not result.practice_eligible
    assert result.mapping_status == "reference_only"
    assert "reference_only_mapping" in result.blocking_reasons


def test_ai_disagreement_disables_choice_comparison_but_keeps_proof_process_practice():
    from backend.services.answer_grading import grade_practice_final_answer

    node = reviewed_node()
    choice = question(node, answer_provenance="ai_generated", reliability="ai_disagreement",
        grading_config={"verified": False, "practice_method": "single_choice"})
    choice_result = question_eligibility(choice, node)
    assert not choice_result.practice_eligible
    verdict = grade_practice_final_answer(question_type="single_choice", config=choice.grading_config,
        answer=None, selected_option="A", expected="A", options=choice.options,
        answer_provenance="ai_generated", content_trust="verified", answer_reliability="ai_disagreement")
    assert verdict.result == "unknown"
    assert verdict.reason == "ai_answer_disagreement"

    proof = question(node, qtype="proof", answer_provenance="ai_generated", reliability="ai_disagreement")
    proof_result = question_eligibility(proof, node)
    assert proof_result.practice_eligible
    assert proof_result.grading_capability == "process_review_only"
    assert proof_result.evidence_capability == "process_review_not_objective_evidence"


@pytest.mark.parametrize("answer_provenance,reliability", [("legacy_transcription", "unverified"), ("unknown", "unknown")])
def test_legacy_or_unknown_answer_never_becomes_eligible_from_legacy_config(answer_provenance, reliability):
    node = reviewed_node()
    item = question(node, trust="unreviewed", provenance="legacy_unknown",
        answer_provenance=answer_provenance, reliability=reliability,
        source_status="unknown", grading_config={"verified": True, "method": "single_choice"})
    result = question_eligibility(item, node)
    assert not result.practice_eligible
    assert result.practice_eligible is False
    assert result.answer_comparison_method is None
    assert result.evidence_capability != "verified_objective"
