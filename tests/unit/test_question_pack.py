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
        "answer_reviewed_by": "synthetic fixture", "source": {"kind": "original", "citation": "合成隔离测试",
            "rights_basis": "测试原创数据", "reviewed_by": "fixture", "reviewed_on": "2026-10-01"},
    }]}


def test_pack_fingerprint_changes_with_answer_or_source():
    original = QuestionPack.model_validate(payload()).questions[0]
    changed = original.model_copy(update={"explanation": "另一份经过核验的说明"})
    assert fingerprint(original) != fingerprint(changed)


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
