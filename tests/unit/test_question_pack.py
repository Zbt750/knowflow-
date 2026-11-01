from copy import deepcopy
import pytest
from pydantic import ValidationError
from backend.services.question_pack import QuestionPack, fingerprint


def payload():
    return {"pack_id": "synthetic", "version": "1", "questions": [{
        "source_id": "q1", "kp_code": "cs408.synthetic", "question_type": "single_choice",
        "stem": "合成练习：二进制10等于多少？", "options": {"A": "2", "B": "3"},
        "correct_answer": "A", "explanation": "按二进制位权计算，1乘2加0等于2。",
        "estimated_minutes": 2, "skill_tags": ["进制转换"], "grading_method": "single_choice",
        "answer_reviewed_by": "synthetic fixture", "answer_reviewed_on": "2026-10-01",
        "answer_provenance": "human_verified", "answer_reliability": "verified",
        "answer_review_method": "isolated synthetic fixture review",
        "answer_review_note": "Synthetic test answer was reviewed for schema behavior.",
        "content_reviewed_by": "synthetic content fixture", "content_reviewed_on": "2026-10-01",
        "source": {"kind": "original", "citation": "合成隔离测试",
            "rights_basis": "测试原创数据", "reviewed_by": "fixture", "reviewed_on": "2026-10-01"},
    }]}


def test_pack_fingerprint_changes_with_answer_or_source():
    original = QuestionPack.model_validate(payload()).questions[0]
    changed = original.model_copy(update={"explanation": "另一份经过核验的说明"})
    assert fingerprint(original) != fingerprint(changed)


def test_reviewer_fields_alone_do_not_infer_answer_verification():
    data = payload()
    question = data["questions"][0]
    question.pop("answer_provenance")
    question.pop("answer_reliability")
    question.pop("answer_review_method")
    question.pop("answer_review_note")
    with pytest.raises(ValidationError, match="reviewed content must declare"):
        QuestionPack.model_validate(data)


def test_ai_generated_question_cannot_claim_exam_authenticity():
    data = payload()
    question = data["questions"][0]
    question["source"].update(content_origin="AI_GENERATED", source_type="exam",
        year=2025, question_number=1, paper_title="synthetic", subject="408")
    with pytest.raises(ValidationError, match="AI-generated content cannot claim"):
        QuestionPack.model_validate(data)


@pytest.mark.parametrize("change", ["missing_source", "duplicate", "unknown_option", "proof_auto", "blank_tag"])
def test_pack_refuses_unreviewed_or_unsupported_content(change):
    data = deepcopy(payload())
    q = data["questions"][0]
    if change == "missing_source": del q["source"]
    if change == "duplicate": data["questions"].append(deepcopy(q))
    if change == "unknown_option": q["correct_answer"] = "D"
    if change == "proof_auto": q.update(question_type="proof", options=None)
    if change == "blank_tag": q["skill_tags"] = [" "]
    with pytest.raises(ValidationError):
        QuestionPack.model_validate(data)
