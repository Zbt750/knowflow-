from types import SimpleNamespace
from uuid import uuid4

from backend.chat.service import _prompt, _is_overview_question, classify_answer_style, _normalize_known_citation_aliases, _citations


def row(role, content):
    return SimpleNamespace(role=role, content=content, status="completed")


def hit(stage):
    return SimpleNamespace(chunk_id=uuid4(), content=f"阶段 {stage} 的真实验收正文", heading_path=(f"阶段 {stage}",), material_title="验收")


def test_full_document_does_not_inherit_wrong_assistant_scope():
    question = "帮我看我的验收文件的大概讲述内容"
    messages, mapping = _prompt(question, [hit(s) for s in "ABCDEFG"], [
        row("user", "只介绍阶段A"), row("assistant", "能细讲的只有阶段 A，其他阶段没有证据 [C1]。"), row("user", question),
    ], mode="user", full_document=True)
    assert len(mapping) == 7
    assert not any(m["role"] == "assistant" for m in messages)
    assert "能细讲的只有" not in str(messages)
    assert all(f"阶段 {s}" in messages[0]["content"] for s in "ABCDEFG")
    assert messages[-2]["content"].startswith("【资料证据】")
    assert messages[-1]["content"] == question
    assert sum(m["content"] == question for m in messages) == 1


def test_detail_history_stays_but_citations_are_not_reused():
    messages, _ = _prompt("这一条件为什么必要？", [hit("A")], [row("assistant", "上轮条件说明 [C9]")])
    assert any(m["role"] == "assistant" and "上轮条件说明" in m["content"] for m in messages)
    assert "[C9]" not in str(messages)
    assert messages[-2]["content"].startswith("【资料证据】")


def test_user_wordings_enter_full_document_path():
    for question in ["帮我看验收文件的讲述内容", "验收.md主要讲了什么", "剩下的阶段呢？", "后面的阶段也讲一下", "帮我看看验收文件都写了些什么", "这份验收资料都讲些啥？", "验收有哪些阶段？"]:
        assert _is_overview_question(question)


def test_explicit_single_chapter_does_not_force_every_chapter():
    assert not _is_overview_question("只概述验收文件的阶段 A，其余阶段不要讲")


def test_full_coverage_does_not_override_explicit_summary_style():
    assert classify_answer_style("把验收文件从头到尾的主要内容总结一下") == "brief"
    assert classify_answer_style("每个阶段都详细讲解，不要遗漏") == "detailed"


def test_provider_alias_only_maps_known_evidence_not_unknown_ids():
    chunk = uuid4()
    canonical, normalized, unknown = _normalize_known_citation_aliases("依据[citation:2]，伪编号[citation:99]。", {"C2": chunk})
    assert canonical == "依据[C2]，伪编号。"
    assert normalized == ["C2"]
    assert unknown == ["C99"]
    assert _citations(canonical, {"C2": chunk})[0] == [("C2", chunk)]
    assert _citations("原始[citation:2]", {"C2": chunk})[0] == []


def test_provider_alias_does_not_rewrite_code_examples():
    text = "`[citation:1]`\n```text\n[citation:1]\n```"
    assert _normalize_known_citation_aliases(text, {"C1": uuid4()}) == (text, [], [])
