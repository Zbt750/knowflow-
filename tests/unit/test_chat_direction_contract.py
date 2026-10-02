from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.chat import service
from backend.chat.call_trace import PROMPT_VERSION


@pytest.mark.parametrize("mode", ["builtin", "user"])
def test_grounded_direction_question_requires_original_and_converse(mode):
    question = "这个反例证明哪个方向不能反过来？"
    hit = SimpleNamespace(chunk_id=uuid4(), content="可导必连续，连续不一定可导。", heading_path=("连续",), material_title="合成讲义")
    prompt, citations = service._prompt(question, [hit], [], mode=mode)
    assert "原命题 P⇒Q 与逆命题 Q⇒P" in prompt[0]["content"]
    assert "被反例否定" in prompt[0]["content"]
    assert citations and prompt[-1]["content"] == question


def test_general_direction_uses_same_contract_and_version():
    prompt = service._general_prompt("这个结论能逆推吗？", [])
    assert "原命题 P⇒Q 与逆命题 Q⇒P" in prompt[0]["content"]
    assert PROMPT_VERSION == "chat-evidence-v8"


def test_unrelated_question_does_not_gain_direction_prompt_or_canned_answer():
    assert service._direction_instruction("BFS使用什么队列？") == ""
    assert "可导" not in service._direction_instruction("为什么不能反过来？")


@pytest.mark.parametrize("question", [
    "可导和连续的必要充分关系是什么？",
    "充分必要关系怎么判断？", "这是充要条件吗？",
])
def test_combined_condition_wording_activates_direction_contract(question):
    instruction = service._direction_instruction(question)
    assert "满足 Q 且不满足 P" in instruction
    assert "它否定的是 Q⇒P，不是否定 P⇒Q" in instruction
    assert "不要写‘Q⇒P 这个方向不能反过来成立’" in instruction
    assert "P 是 Q 的充分条件，Q 是 P 的必要条件" in instruction


@pytest.mark.parametrize("mode", ["builtin", "user"])
def test_grounded_background_is_not_automatically_a_source_claim(mode):
    question = "TLB未命中和缺页有何区别？"
    content = "TLB未命中后仍可能从页表找到有效映射。缺页表示虚拟页不在物理内存。"
    hit = SimpleNamespace(chunk_id=uuid4(), content=content, heading_path=("分页",), material_title="合成408")
    prompt, mapping = service._prompt(question, [hit], [], mode=mode)
    system = prompt[0]["content"]
    assert "引用支持的是相邻的具体事实" in system
    assert "可以忠实改述资料" in system
    assert "不能仅因主题相关" in system
    assert "## 通用知识参考" in system
    assert "不附任何 [C数字]" in system
    assert content in prompt[-2]["content"]
    assert mapping == {"C1": hit.chunk_id}


def test_general_prompt_does_not_require_grounded_source_contract():
    system = service._general_prompt("TLB是什么？", [])[0]["content"]
    assert "【引用的支持边界】" not in system
    assert "不能使用 [C数字] 引用" in system


@pytest.mark.parametrize("mode", ["builtin", "user"])
@pytest.mark.parametrize("full_document", [False, True])
def test_atomic_citation_contract_preserves_evidence_and_answer_scope(mode, full_document):
    content = "事件A后仍可能出现B。必要时执行步骤S。"
    hit = SimpleNamespace(chunk_id=uuid4(), content=content, heading_path=("机制",), material_title="测试资料")
    messages, mapping = service._prompt("事件A之后如何处理？", [hit], [],
                                      mode=mode, full_document=full_document)
    instruction = messages[0]["content"]
    assert "【资料与背景分句】" in instruction
    assert "同一列表项或同一表格单元" in instruction
    assert "不能在同一句补出‘A的定义是D’并共用引用" in instruction
    assert "不因此拒答有证据的部分" in instruction
    assert "不为几何直觉、类比、自拟例子" in instruction
    assert "不再加重复的‘核心是’总结" in instruction
    # Contract must not insert a definition into the actual evidence or rewrite it.
    assert messages[-2]["content"].endswith(content)
    assert "定义是D" not in messages[-2]["content"]
    assert mapping == {"C1": hit.chunk_id}
    assert messages[-1]["content"] == "事件A之后如何处理？"
