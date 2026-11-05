from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.chat import service


@pytest.mark.parametrize("mode", ["user", "builtin"])
def test_grounded_answers_do_not_infer_absence_from_missing_fragments(mode):
    hit = SimpleNamespace(chunk_id=uuid4(), content="部署应保留数据。",
                          heading_path=("阶段F",), material_title="合成讲义")
    question = "文件有没有其他阶段？"
    prompt, citations = service._prompt(question, [hit], [], mode=mode)
    assert service.EVIDENCE_BOUNDARY_INSTRUCTION in prompt[0]["content"]
    assert "没有检查完整文件时" in prompt[0]["content"]
    assert citations and prompt[-1]["content"] == question


def test_no_evidence_advice_cannot_claim_official_absence_or_browsing():
    question = "有没有官方平均分，没有记录就给核验建议"
    prompt = service._general_prompt(question, [])
    text = prompt[0]["content"]
    assert "未找到可核验来源" in text
    assert "不声称已查过官网" in text
    assert "不能写‘查不到就当不存在’" in text
    assert prompt[-1]["content"] == question
    # This is a model instruction, not a canned replacement for its answer.
    assert len(prompt) == 2
