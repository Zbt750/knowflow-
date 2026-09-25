"""追问引导与多轮上下文预算。

对应两处改动：

**改动一（追问引导）**：`_prompt()` 的 system 指令里加了教学约束
（含糊先澄清、长解答只给一步、说「不懂」就换讲法）。
因为是 SSE 与非流式**共用同一个 `_prompt()`**，改一处两处生效。

这里要钉死的核心是：**追问引导不能把引用要求挤掉**。
引用校验依赖正文里的 `[C#]`；如果模型因为「只是反问一句」而省掉引用，
那次回答就会变成没有任何来源的结论 —— 而这正是本项目最不能接受的事。
因此下面既测提示词契约，也测「无引用的追问式回答」在链路里的真实行为。

**改动三（多轮预算）**：规格篇 16 把「多轮对话与上下文预算」列为 P1。
此前写死「最近 10 条」，现在改按 token 预算裁剪。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from backend.chat.service import (
    SYSTEM_PROMPT,
    USER_MATERIALS_SYSTEM_PROMPT,
    _prompt,
    estimate_tokens,
    message_tokens,
    select_history_within_budget,
)


# ---------------------------------------------------------------------------
# 改动一：提示词契约
# ---------------------------------------------------------------------------


@dataclass
class FakeHit:
    chunk_id: UUID
    content: str
    score: float = 0.03
    vector_score: float | None = 0.8
    kp_ids: tuple[UUID, ...] = ()
    material_title: str = "测试资料"
    heading_path: tuple[str, ...] = ("测试章节",)


@dataclass
class FakeMessage:
    role: str
    content: str
    status: str = "completed"


def hit(text: str = "洛必达法则用于处理 0/0 型未定式。") -> FakeHit:
    return FakeHit(chunk_id=uuid4(), content=text)


def system_text(messages: list[dict[str, str]]) -> str:
    return next(item["content"] for item in messages if item["role"] == "system")


def test_system_prompt_keeps_the_citation_requirement() -> None:
    """引用要求必须留在 system 里，而且是**不可违反**的一类。"""
    assert "[C1]" in SYSTEM_PROMPT, "必须给出引用格式示例"
    assert "[C#]" in SYSTEM_PROMPT, "必须说明引用编号的形式"
    assert "不可违反" in SYSTEM_PROMPT


def test_system_prompt_explicitly_forbids_dropping_citation_when_following_up() -> None:
    """最容易出问题的一条：模型会以为「只是反问一句」就不用带引用了。

    因此提示词里必须**显式**说出「澄清/只讲一步/换讲法时也要带引用」，
    而不是只笼统写一句「关键结论要引用」——后者在短回答里会被忽略。
    """
    assert "澄清" in SYSTEM_PROMPT
    assert "只讲一步" in SYSTEM_PROMPT
    assert "换一种讲法" in SYSTEM_PROMPT
    # 这三件事都必须点名要带引用
    assert "也必须带上 [C#] 引用" in SYSTEM_PROMPT


def test_system_prompt_carries_the_three_teaching_rules() -> None:
    """三条教学约束都要在：含糊先澄清、一次一步、不懂就换讲法。"""
    assert "问清最关键的那一点" in SYSTEM_PROMPT
    assert "一次只讲一步" in SYSTEM_PROMPT
    assert "不要原样重讲一遍" in SYSTEM_PROMPT


def test_system_prompt_keeps_refusal_rule() -> None:
    """教学约束不能挤掉「资料不足要说明、不能编造来源」这条底线。"""
    assert "资料不足时明确说明" in SYSTEM_PROMPT
    assert "不能编造来源" in SYSTEM_PROMPT


def test_user_materials_prompt_answers_fully_without_proactive_followups() -> None:
    """「我的资料」应直接解释完整，不套用内置模式的分步追问教学策略。"""
    messages, _ = _prompt("请解释这份资料的主要结论", [hit()], [], mode="user")
    prompt = system_text(messages)
    assert prompt == USER_MATERIALS_SYSTEM_PROMPT
    assert "不要为了简短省略关键内容" in prompt
    assert "不要在结尾询问是否继续" in prompt
    assert "一次只讲一步" not in prompt
    assert "[C1]" in prompt


def test_builtin_mode_keeps_its_interactive_teaching_prompt() -> None:
    messages, _ = _prompt("请解释", [hit()], [])
    assert system_text(messages) == SYSTEM_PROMPT
    assert "一次只讲一步" in system_text(messages)


def test_prompt_puts_system_first_and_evidence_second() -> None:
    """消息顺序：system → 资料证据 → 历史 → 当前问题。"""
    messages, mapping = _prompt("洛必达法则的适用条件是什么？", [hit()], [])
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "【资料证据】" in messages[1]["content"]
    assert messages[-1]["content"] == "洛必达法则的适用条件是什么？"
    assert list(mapping) == ["C1"]


def test_prompt_labels_evidence_so_citations_are_checkable() -> None:
    """证据必须带 [C1]/[C2] 编号，否则模型无法引用、校验也无从下手。"""
    messages, mapping = _prompt("问题", [hit("第一段"), hit("第二段"), hit("第三段")], [])
    evidence = messages[1]["content"]
    assert "[C1] 【资料：测试资料｜章节：测试章节】" in evidence and "第一段" in evidence
    assert "[C2] 【资料：测试资料｜章节：测试章节】" in evidence and "第二段" in evidence
    assert "[C3] 【资料：测试资料｜章节：测试章节】" in evidence and "第三段" in evidence
    assert list(mapping) == ["C1", "C2", "C3"]


def test_prompt_does_not_duplicate_the_current_question() -> None:
    """当前问题已经在历史里时（`_create_pending` 先落了 user 行）不再重复追加。"""
    history = [FakeMessage("user", "洛必达法则的适用条件是什么？")]
    messages, _ = _prompt("洛必达法则的适用条件是什么？", [hit()], history)  # type: ignore[arg-type]
    occurrences = [item for item in messages if item["content"] == "洛必达法则的适用条件是什么？"]
    assert len(occurrences) == 1


def test_prompt_appends_question_when_history_ends_with_assistant() -> None:
    history = [FakeMessage("user", "上一问"), FakeMessage("assistant", "上一答 [C1]")]
    messages, _ = _prompt("新问题", [hit()], history)  # type: ignore[arg-type]
    assert messages[-1]["content"] == "新问题"


def test_prompt_shared_by_stream_and_non_stream_paths() -> None:
    """SSE 与非流式必须共用这一个 `_prompt`。

    这条防的是「有人为了某个模式单独写一份 system」——
    那样两份提示词会慢慢漂移，用户会遇到「流式会引导追问、非流式不会」这类怪事。
    """
    import inspect

    from backend.chat import service

    source = inspect.getsource(service)
    prompt_source = inspect.getsource(service._prompt)
    # 回答 system 消息只在 `_prompt` 中构造一次；意图分类可以有自己的短 system 指令。
    assert prompt_source.count('"role": "system"') == 1
    assert source.count("SYSTEM_PROMPT") >= 2, "常量应被定义并引用"


# ---------------------------------------------------------------------------
# 改动三：多轮上下文预算
# ---------------------------------------------------------------------------


def test_estimate_tokens_counts_cjk_as_one_each() -> None:
    assert estimate_tokens("洛必达法则") == 5


def test_estimate_tokens_counts_ascii_roughly_four_per_token() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2, "向上取整，宁可多算"


def test_estimate_tokens_mixed_text() -> None:
    # 4 个汉字 + "abcd"（4 字符 → 1 token）
    assert estimate_tokens("洛必达法abcd") == 5


def test_message_tokens_includes_role_overhead() -> None:
    assert message_tokens(FakeMessage("user", "洛必达法则")) == estimate_tokens("洛必达法则") + 4  # type: ignore[arg-type]


def test_history_keeps_everything_within_budget() -> None:
    messages = [FakeMessage("user", "短问题") for _ in range(5)]
    picked = select_history_within_budget(messages, max_tokens=1000)  # type: ignore[arg-type]
    assert len(picked) == 5


def test_history_drops_oldest_first() -> None:
    """超预算时从**最旧**的开始丢，最近的一定留下。"""
    messages = [FakeMessage("user", "这是第 %d 轮的问题内容" % index) for index in range(20)]
    picked = select_history_within_budget(messages, max_tokens=60)  # type: ignore[arg-type]
    assert 0 < len(picked) < 20
    assert picked[-1].content == "这是第 19 轮的问题内容", "最近一条必须保留"
    # 保留下来的必须是**连续的尾部**，不能东挑一条西挑一条
    assert [m.content for m in picked] == [
        m.content for m in messages[len(messages) - len(picked):]
    ]


def test_history_order_is_chronological() -> None:
    """返回顺序必须是时间正序 —— 倒序会让模型把问答顺序读反。"""
    messages = [FakeMessage("user", f"第{index}问") for index in range(6)]
    picked = select_history_within_budget(messages, max_tokens=40)  # type: ignore[arg-type]
    assert [m.content for m in picked] == sorted(
        [m.content for m in picked], key=lambda text: int(text[1])
    )


def test_oversized_message_is_skipped_not_truncated() -> None:
    """单条就超预算：跳过它，但**不要**把它截一半，也不要因此丢掉更早的短消息。"""
    huge = FakeMessage("assistant", "很长的回答" * 100)
    small = FakeMessage("user", "短问题")
    picked = select_history_within_budget([small, huge], max_tokens=50)  # type: ignore[arg-type]
    assert [m.content for m in picked] == ["短问题"], "长回答整条不进，短问题要留下"
    assert all(m.content != huge.content for m in picked)


def test_zero_budget_disables_history() -> None:
    messages = [FakeMessage("user", "短问题")]
    assert select_history_within_budget(messages, max_tokens=0) == []  # type: ignore[arg-type]
    assert select_history_within_budget(messages, max_tokens=-5) == []  # type: ignore[arg-type]


def test_empty_history_stays_empty() -> None:
    assert select_history_within_budget([], max_tokens=1000) == []


def test_budget_is_bounded_even_for_many_tiny_messages() -> None:
    """消息再多，累计估算也不能超过预算。"""
    messages = [FakeMessage("user", "问") for _ in range(500)]
    picked = select_history_within_budget(messages, max_tokens=100)  # type: ignore[arg-type]
    total = sum(message_tokens(m) for m in picked)  # type: ignore[arg-type]
    assert total <= 100
    assert len(picked) < 500


def test_configured_budget_is_positive_and_reasonable() -> None:
    """配置默认值必须是正数，否则多轮上下文会被静默关掉。"""
    from backend.config import Settings

    default = Settings.model_fields["llm_history_token_budget"].default
    assert isinstance(default, int) and default > 0
