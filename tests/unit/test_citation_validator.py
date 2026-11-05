"""引用校验单元测试（契约要求的 tests/unit/test_citation_validator.py）。

契约：模型只允许引用本次检索命中的 `[C#]`。处理顺序是
严格正则提取 → 首次出现去重 → 与本次 citation_map 求交；
`[C99]` 这类不在映射里的编号**不插入任何 citation 行**，
正文可以保留，并在 metadata 写 unknown_citation_labels。

这些用例全部是纯函数测试，不碰数据库、不调用模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest

from backend.chat.service import _citations, encode_sse

CHUNK_A = UUID("00000000-0000-0000-0000-00000000000a")
CHUNK_B = UUID("00000000-0000-0000-0000-00000000000b")


# ---------------------------------------------------------------------------
# 提取与去重
# ---------------------------------------------------------------------------


def test_extracts_labels_in_first_appearance_order() -> None:
    valid, unknown = _citations("先 [C2] 再 [C1]。", {"C1": CHUNK_A, "C2": CHUNK_B})
    assert valid == [("C2", CHUNK_B), ("C1", CHUNK_A)]
    assert unknown == []


def test_duplicate_labels_are_deduplicated_by_first_appearance() -> None:
    valid, unknown = _citations("依据[C1]，再次[C1]，最后[C1]。", {"C1": CHUNK_A})
    assert valid == [("C1", CHUNK_A)]
    assert unknown == []


def test_unknown_label_is_not_a_source_but_is_reported() -> None:
    """`[C99]` 不在本次映射中：不产生来源，但要被记录。"""
    valid, unknown = _citations("依据[C1]。另见[C99]。", {"C1": CHUNK_A})
    assert valid == [("C1", CHUNK_A)]
    assert unknown == ["C99"]


def test_all_unknown_labels_means_no_sources() -> None:
    valid, unknown = _citations("依据[C7]与[C8]。", {"C1": CHUNK_A})
    assert valid == []
    assert unknown == ["C7", "C8"]


def test_text_without_any_label_yields_nothing() -> None:
    assert _citations("没有任何引用的一段话。", {"C1": CHUNK_A}) == ([], [])


def test_empty_text_and_empty_mapping() -> None:
    assert _citations("", {}) == ([], [])
    assert _citations("依据[C1]。", {}) == ([], ["C1"])


# ---------------------------------------------------------------------------
# 严格性：不合法的引用形式一律不认
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "[c1]",  # 小写
        "[C0]",  # 编号从 1 开始
        "[C01]",  # 前导零
        "[C 1]",  # 带空格
        "(C1)",  # 不是方括号
        "[C1",  # 不闭合
        "C1]",  # 缺少左括号
        "[D1]",  # 其它前缀
    ],
)
def test_non_contractual_forms_are_ignored(text: str) -> None:
    """只有 `[C<正整数>]` 才算引用；其它形式既不入来源也不入 unknown。"""
    assert _citations(text, {"C1": CHUNK_A, "C01": CHUNK_B}) == ([], [])


def test_large_label_number_is_handled() -> None:
    valid, unknown = _citations("依据[C120]。", {"C120": CHUNK_A})
    assert valid == [("C120", CHUNK_A)]


def test_label_present_but_chunk_not_in_mapping_is_unknown() -> None:
    """映射里只有 C1，模型写 C2 时 C2 不算来源。"""
    valid, unknown = _citations("依据[C1]和[C2]。", {"C1": CHUNK_A})
    assert valid == [("C1", CHUNK_A)]
    assert unknown == ["C2"]


# ---------------------------------------------------------------------------
# SSE 编码
# ---------------------------------------------------------------------------


def test_encode_sse_uses_event_and_data_lines() -> None:
    frame = encode_sse("delta", {"seq": 1, "text": "你好"})
    assert frame.endswith(b"\n\n")
    text = frame.decode("utf-8")
    assert text.startswith("event: delta\n")
    assert "data: " in text
    # 中文必须保持可读（ensure_ascii=False），否则前端会看到转义序列。
    assert "你好" in text


def test_encode_sse_data_is_single_line_even_with_newlines() -> None:
    """data 必须是单行：JSON 会把换行转义，否则 SSE 帧会被拆断。"""
    frame = encode_sse("delta", {"text": "第一行\n第二行"})
    body = frame.decode("utf-8")
    data_lines = [line for line in body.split("\n") if line.startswith("data: ")]
    assert len(data_lines) == 1


@dataclass
class _FakeHit:
    """仅用于验证 compute_matched_kp 的输入形状。"""

    kp_ids: tuple[UUID, ...]
    score: float
