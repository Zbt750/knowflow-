"""分块与标题树的纯函数测试：不依赖数据库、模型或网络。"""

from __future__ import annotations

import pytest

from backend.ingestion.chunker import (
    DEFAULT_MAX_CHARS,
    build_chunk_drafts,
    split_block,
    validate_chunk_drafts,
)
from backend.ingestion.text_normalize import content_hash, normalize_text
from backend.ingestion.title_tree import (
    build_title_tree,
    scan_headings,
    scan_kp_hints,
    source_blocks_from_title_tree,
)

SAMPLE = """# 高等数学

导语段落。

## 函数与极限

极限是高等数学的起点。

<!-- kp:math.calculus.limit.lhopital -->

### 洛必达法则

0/0 型未定式可以用导数化简。

$$
f'(x)
$$

## 无穷级数

等比级数在公比绝对值小于 1 时收敛。
"""


def test_normalize_text_unifies_newlines_and_trims_trailing_space() -> None:
    raw = "\ufeffa  \r\nb\r\n\r\n\r\n\r\nc   "
    # 收尾统一为恰好一个换行，这是全文 offset 的唯一基准。
    assert normalize_text(raw) == "a\nb\n\n\nc\n"
    # 幂等：再规范化一次结果不变。
    assert normalize_text(normalize_text(raw)) == normalize_text(raw)


def test_normalize_text_keeps_at_most_two_blank_lines() -> None:
    assert normalize_text("a\n\n\n\n\nb") == "a\n\n\nb\n"


def test_scan_headings_ignores_fenced_code_blocks() -> None:
    text = "# 标题\n\n```\n# 这不是标题\n```\n\n## 真标题\n"
    hits = scan_headings(text)
    assert [hit.text for hit in hits] == ["标题", "真标题"]
    assert [hit.level for hit in hits] == [1, 2]


def test_scan_kp_hints_collects_comments_outside_fences() -> None:
    text = "<!-- kp:math.a -->\n正文\n```\n<!-- kp:math.b -->\n```\n"
    hints = scan_kp_hints(text)
    assert list(hints.values()) == ["math.a"]


def test_build_title_tree_builds_nested_paths() -> None:
    text = normalize_text(SAMPLE)
    roots = build_title_tree(scan_headings(text), document_length=len(text))
    assert len(roots) == 1
    calculus = roots[0]
    assert calculus.heading == "高等数学"
    assert [child.heading for child in calculus.children] == ["函数与极限", "无穷级数"]
    limit = calculus.children[0]
    assert [child.heading for child in limit.children] == ["洛必达法则"]


def test_direct_ranges_exclude_child_headings() -> None:
    text = normalize_text(SAMPLE)
    roots = build_title_tree(scan_headings(text), document_length=len(text))
    calculus = roots[0]
    # 父节点的直接正文只有导语，不含子标题内容。
    joined = "".join(text[start:end] for start, end in calculus.direct_ranges)
    assert "导语段落" in joined
    assert "极限是高等数学的起点" not in joined


def test_no_heading_document_still_yields_one_block() -> None:
    text = normalize_text("只有正文，没有任何标题。")
    blocks = source_blocks_from_title_tree(text, fallback_title="我的讲义")
    assert len(blocks) == 1
    assert blocks[0].heading_path == ("我的讲义",)
    assert text[blocks[0].start_offset : blocks[0].end_offset] == "只有正文，没有任何标题。"


def test_source_blocks_carry_kp_hint_and_exclude_comment_from_content() -> None:
    text = normalize_text(SAMPLE)
    blocks = source_blocks_from_title_tree(text)
    lhopital = next(block for block in blocks if block.heading_path[-1] == "洛必达法则")
    assert lhopital.kp_hint_code == "math.calculus.limit.lhopital"
    content = text[lhopital.start_offset : lhopital.end_offset]
    # kp: 注释是结构元数据，不能进入正文。
    assert "kp:" not in content
    assert "0/0 型未定式" in content


def test_split_block_rejects_too_small_window() -> None:
    text = "abc"
    block = source_blocks_from_title_tree(text)[0]
    with pytest.raises(ValueError, match="至少为"):
        split_block(text, block, max_chars=10)


def test_split_block_advances_and_never_exceeds_window() -> None:
    text = normalize_text("句子一。" * 200)
    block = source_blocks_from_title_tree(text)[0]
    ranges = split_block(text, block, max_chars=100)
    assert ranges
    for start, end in ranges:
        assert end - start <= 100
    # 区间连续且覆盖整段正文。
    assert ranges[0][0] == block.start_offset
    assert ranges[-1][1] == block.end_offset


def test_build_chunk_drafts_ordinals_are_contiguous_from_zero() -> None:
    text = normalize_text(SAMPLE)
    drafts = build_chunk_drafts(text, source_blocks_from_title_tree(text))
    assert drafts
    assert [draft.ordinal for draft in drafts] == list(range(len(drafts)))
    validate_chunk_drafts(text, drafts)


def test_every_chunk_content_equals_offset_slice() -> None:
    text = normalize_text(SAMPLE)
    drafts = build_chunk_drafts(text, source_blocks_from_title_tree(text))
    for draft in drafts:
        assert text[draft.start_offset : draft.end_offset] == draft.content


def test_chunk_content_hash_is_stable_and_path_sensitive() -> None:
    # 同一正文在不同章节不能算出同一个 hash。
    assert content_hash(("a",), "正文") != content_hash(("b",), "正文")
    assert content_hash(("a",), "正文") == content_hash(("a",), "正文")


def test_same_input_produces_identical_drafts() -> None:
    text = normalize_text(SAMPLE)
    first = build_chunk_drafts(text, source_blocks_from_title_tree(text))
    second = build_chunk_drafts(text, source_blocks_from_title_tree(text))
    assert first == second


def test_validate_rejects_drifted_content() -> None:
    text = normalize_text(SAMPLE)
    drafts = build_chunk_drafts(text, source_blocks_from_title_tree(text))
    broken = list(drafts)
    broken[0] = broken[0].__class__(
        ordinal=broken[0].ordinal,
        content=broken[0].content + "漂移",
        start_offset=broken[0].start_offset,
        end_offset=broken[0].end_offset,
        heading_path=broken[0].heading_path,
        content_hash=broken[0].content_hash,
        kp_hint_code=broken[0].kp_hint_code,
    )
    with pytest.raises(ValueError, match="不一致"):
        validate_chunk_drafts(text, broken)


def test_default_window_is_seven_hundred() -> None:
    assert DEFAULT_MAX_CHARS == 700