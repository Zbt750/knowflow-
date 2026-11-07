from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.models.learning import KnowledgePoint, Question, QuestionAnswerVerificationEvent
from backend.services.question_eligibility import question_eligibility
from backend.services.answer_verification import answer_version_sha256


REVIEWED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


def reviewed_node(*, reference_only=False):
    return KnowledgePoint(id=uuid4(), code="synthetic.reviewed.leaf", subject="math2",
        name="隔离合成节点", is_active=True, is_assessable=True, is_reference_only=reference_only)


def question(node, *, provenance="real_exam", qtype="single_choice", answer_provenance="verified_reference",
             reliability="verified", trust="verified", source_status="verified", grading_config=None):
    choice = qtype == "single_choice"
    verified_answer = answer_provenance == "verified_reference"
    item = Question(id=uuid4(), kp_id=node.id, question_type=qtype, is_active=True,
        stem="隔离合成测试题目，检查知识判断。", options={"A": "甲", "B": "乙"} if choice else None,
        correct_answer="A" if choice else "完整参考答案", explanation="隔离合成解析说明。",
        grading_config=grading_config or {}, question_provenance=provenance,
        content_trust=trust, source_status=source_status, answer_provenance=answer_provenance,
        answer_reliability=reliability, content_reviewed_by="fixture-reviewer" if trust == "verified" else None,
        content_reviewed_at=REVIEWED_AT if trust == "verified" else None,
        answer_reviewed_by="answer-reviewer" if verified_answer and reliability == "verified" else None,
        answer_reviewed_at=REVIEWED_AT if verified_answer and reliability == "verified" else None)
    if verified_answer and reliability == "verified":
        event = QuestionAnswerVerificationEvent(id=uuid4(), question_id=item.id, event_type="verified",
            verification_type="verified_reference", answer_sha256=answer_version_sha256(item),
            verification_method="isolated unit fixture", verifier="answer-reviewer",
            source_metadata={"kind": "official_answer_key", "identifier": "TEST_ONLY",
                "title": "Synthetic test fixture", "locator": "tests/unit"},
            note="Synthetic fixture only; never production verification.",
            idempotency_key="test:" + str(uuid4()), created_at=REVIEWED_AT)
        item.current_answer_verification = event
        item.answer_verification_event_id = event.id
    return item


def test_verified_real_question_and_reference_answer_is_objectively_eligible():
    node = reviewed_node()
    item = question(node, grading_config={"verified": True, "method": "single_choice"})
    item.kp_id = node.id
    result = question_eligibility(item, node)
    assert result.practice_eligible
    assert result.grading_capability == "deterministic"
    assert result.evidence_capability == "verified_objective"


def test_unqualified_ai_public_answer_is_archived_without_a_second_practice_tier():
    node = reviewed_node()
    item = question(node, answer_provenance="ai_generated", reliability="model_generated",
        grading_config={"verified": False, "practice_method": "single_choice"})
    result = question_eligibility(item, node)
    assert not result.practice_eligible
    assert result.answer_provenance == "ai_generated"
    assert result.answer_reliability == "model_generated"
    assert result.answer_comparison_method is None
    assert result.grading_capability == "unsupported"
    assert result.evidence_capability == "archive_only"
    assert result.verified_grading_method is None


def test_ai_reference_comparison_does_not_upgrade_ai_provenance():
    node = reviewed_node()
    item = question(node, provenance="trusted_practice", answer_provenance="ai_generated",
        reliability="ai_generated_consistent", grading_config={"practice_method": "single_choice"})
    result = question_eligibility(item, node)
    assert not result.practice_eligible
    assert result.answer_provenance != "verified_reference"
    assert result.evidence_capability != "verified_objective"


def test_unqualified_public_proof_is_retained_without_formal_practice_admission():
    node = reviewed_node()
    item = question(node, qtype="proof", answer_provenance="ai_generated", reliability="unverified")
    result = question_eligibility(item, node)
    assert not result.practice_eligible
    assert result.grading_capability == "unsupported"
    assert result.answer_comparison_method is None
    assert result.evidence_capability == "archive_only"


def test_unreviewed_question_is_blocked_even_when_it_has_answer_and_old_verified_json():
    node = reviewed_node()
    item = question(node, trust="unreviewed", answer_provenance="unknown", reliability="unknown",
        provenance="legacy_unknown", source_status="unknown",
        grading_config={"verified": True, "method": "single_choice"})
    result = question_eligibility(item, node)
    assert not result.practice_eligible
    assert result.evidence_capability == "archive_only"
    assert "content_not_verified" in result.blocking_reasons


def test_reference_only_mapping_is_not_silently_treated_as_assessable():
    node = reviewed_node(reference_only=True)
    item = question(node, grading_config={"verified": True, "method": "single_choice"})
    result = question_eligibility(item, node)
    assert not result.practice_eligible
    assert result.mapping_status == "reference_only"
    assert "reference_only_mapping" in result.blocking_reasons


@pytest.mark.parametrize(("qualification_class", "expected_status", "provenance", "source_status"), [
    ("exam_curated", "source_attested_reference_topic", "real_exam", "verified"),
    ("exam_variant", "auto_reviewed_reference_topic", "ai_generated_practice", "traceable"),
])
def test_reference_mapping_uses_the_validated_receipt_without_reloading_its_json(
    monkeypatch, qualification_class, expected_status, provenance, source_status,
):
    from backend.services import auto_question_review as review

    node = reviewed_node(reference_only=True)
    item = question(node, provenance=provenance, answer_provenance="auto_verified",
        reliability="verified", trust="auto_verified", source_status=source_status,
        grading_config={"verified": True, "method": "single_choice"})

    class ValidatedReceipt:
        def __init__(self, value):
            self.id = uuid4()
            self.qualification_class = value
            self.review_version = "public-question-auto-review-v8"
            self.question_snapshot_sha256 = "a" * 64

        @property
        def audit_snapshot(self):
            raise AssertionError("eligibility reloaded receipt JSON after the shared bound check")

    receipt = ValidatedReceipt(qualification_class)
    monkeypatch.setattr(review, "current_auto_review", lambda *_args, **_kwargs: receipt)
    result = question_eligibility(item, node)
    assert result.mapping_status == expected_status


def test_human_review_of_exact_full_exam_preserves_source_binding_on_reference_topic():
    from backend.services.question_attestation import question_content_sha256

    node = reviewed_node(reference_only=True)
    item = question(node, grading_config={"verified": True, "method": "single_choice"})
    item.source_attestation_key = "a" * 64
    item.source_attestation_sha256 = question_content_sha256(item)
    result = question_eligibility(item, node)
    assert result.source_attestation_current
    assert result.mapping_status == "source_attested_reference_topic"
    assert result.practice_eligible and result.evidence_capability == "verified_objective"
    assert item.question_type == "single_choice"
    # Changing content invalidates both the source mapping and answer review.
    item.stem += " Edited content"
    stale = question_eligibility(item, node)
    assert not stale.source_attestation_current and not stale.practice_eligible
    assert not stale.answer_verification_current


def test_reference_topic_binding_alone_cannot_replace_source_or_answer_review():
    from backend.services.question_attestation import question_content_sha256

    node = reviewed_node(reference_only=True)
    item = question(node, source_status="traceable", grading_config={"verified": True, "method": "single_choice"})
    item.source_attestation_key = "b" * 64
    item.source_attestation_sha256 = question_content_sha256(item)
    assert not question_eligibility(item, node).practice_eligible
    item.source_status = "verified"
    item.answer_verification_event_id = None
    item.current_answer_verification = None
    result = question_eligibility(item, node)
    assert result.source_attestation_current
    assert not result.practice_eligible and result.evidence_capability != "verified_objective"


def test_ai_disagreement_keeps_unqualified_public_choice_and_proof_out_of_practice():
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
    assert not proof_result.practice_eligible
    assert proof_result.grading_capability == "unsupported"
    assert proof_result.evidence_capability == "archive_only"


def test_old_public_release_or_teaching_flags_cannot_bypass_formal_admission():
    node = reviewed_node()
    item = question(node, answer_provenance="ai_generated", reliability="model_generated",
        grading_config={"practice_method": "single_choice", "public_practice_release": {"version": "old"}})
    result = question_eligibility(item, node, teaching_enabled=True)
    assert not result.practice_eligible
    assert "public_formal_review_required" in result.blocking_reasons


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
