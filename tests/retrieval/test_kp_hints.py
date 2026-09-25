"""知识点注释归属测试。

`<!-- kp:code -->` 是「chunk 与知识点显式关联」的唯一来源，也是 matched_kp 的
可信依据。归属错一位不会报错，只会让所有引用标错知识点 —— 因此逐条钉住。
"""

from __future__ import annotations

from backend.ingestion.text_normalize import normalize_text
from backend.ingestion.title_tree import source_blocks_from_title_tree

LECTURE = "第一章 洛必达法则"


def hint_of(blocks, heading: str) -> str | None:
    """按标题路径最后一段找块的 kp code。"""
    for block in blocks:
        if block.heading_path and block.heading_path[-1] == heading:
            return block.kp_hint_code
    raise AssertionError(f"没有找到标题：{heading}")


def hints_by_heading(text: str) -> dict[str, str | None]:
    blocks = source_blocks_from_title_tree(normalize_text(text))
    result: dict[str, str | None] = {}
    for block in blocks:
        if block.heading_path:
            result[block.heading_path[-1]] = block.kp_hint_code
    return result


def test_hint_belongs_to_title_below_it() -> None:
    """注释在标题上方时，归属于它下面那个标题，而不是上面的标题。"""
    text = "# 讲义\n\n<!-- kp:a.b -->\n\n## 第一章\n\n正文一。\n"
    assert hints_by_heading(text)["第一章"] == "a.b"


def test_hint_does_not_leak_to_previous_title() -> None:
    """关键回归：第二个注释不能被「上一个标题」抢走。

    这是曾经真实存在的缺陷：范围起点用了父节点正文起点（在父标题行之后），
    结果注释落到父节点之外，整份文档的注释全部错位一格。
    """
    text = (
        "# 讲义\n\n"
        "<!-- kp:first -->\n\n## 第一章\n\n正文一。\n\n"
        "<!-- kp:second -->\n\n## 第二章\n\n正文二。\n"
    )
    hints = hints_by_heading(text)
    assert hints["第一章"] == "first"
    assert hints["第二章"] == "second"


def test_three_sequential_hints_are_attributed_in_order() -> None:
    """连续多个注释必须一一对应，不能整体错位。"""
    text = (
        "# 讲义\n\n"
        "<!-- kp:c1 -->\n\n## 一\n\n正文。\n\n"
        "<!-- kp:c2 -->\n\n## 二\n\n正文。\n\n"
        "<!-- kp:c3 -->\n\n## 三\n\n正文。\n"
    )
    hints = hints_by_heading(text)
    assert hints["一"] == "c1"
    assert hints["二"] == "c2"
    assert hints["三"] == "c3"


def test_hint_is_inherited_by_children() -> None:
    """整章共用一个标记：子标题下的正文都继承同一个 code。

    注意「第一章」自己没有直接正文（只有子标题）时不会产生块，
    因此这里断言的是子标题下的块继承了整章的标记。
    """
    text = "# 讲义\n\n<!-- kp:chapter -->\n\n## 第一章\n\n### 小节一\n\n正文。\n"
    hints = hints_by_heading(text)
    assert hints["小节一"] == "chapter"


def test_no_hint_means_none() -> None:
    text = "# 讲义\n\n## 第一章\n\n正文。\n"
    assert hints_by_heading(text)["第一章"] is None


def test_hint_far_above_title_is_not_applied() -> None:
    """注释与标题之间隔着正文时不算「紧邻」，避免一个注释影响很远的标题。"""
    text = (
        "# 讲义\n\n<!-- kp:stale -->\n\n## 第一章\n\n正文一。\n\n"
        "## 第二章\n\n正文二。\n"
    )
    hints = hints_by_heading(text)
    assert hints["第一章"] == "stale"
    # 第二章前面隔了「正文一」，不是紧邻，不能继续继承到兄弟节点。
    assert hints["第二章"] is None


def test_hint_inside_code_fence_is_ignored() -> None:
    """围栏里的注释是示例代码，不是结构标记。"""
    text = "# 讲义\n\n```\n<!-- kp:fake -->\n```\n\n## 第一章\n\n正文。\n"
    assert hints_by_heading(text)["第一章"] is None


def test_blank_lines_between_hint_and_title_are_allowed() -> None:
    """注释与标题之间允许空行（Markdown 常见写法）。"""
    text = "# 讲义\n\n<!-- kp:ok -->\n\n\n\n## 第一章\n\n正文。\n"
    assert hints_by_heading(text)["第一章"] == "ok"


def test_hint_is_inherited_by_nested_sections() -> None:
    """同一章下多个子标题的正文都继承同一个标记。"""
    text = (
        "# 讲义\n\n<!-- kp:chapter -->\n\n## 第一章\n\n"
        "### 小节一\n\n正文一。\n\n### 小节二\n\n正文二。\n"
    )
    hints = hints_by_heading(text)
    assert hints["小节一"] == "chapter"
    assert hints["小节二"] == "chapter"


def test_bundled_lecture_attributes_every_leaf() -> None:
    """内置讲义必须让每个可考核叶子都有对应的引用来源。

    这不是「文档好看」的问题：检索结果的 matched_kp 完全依赖这些标记，
    少了任何一个，对应知识点就永远检索不到出处。
    """
    from pathlib import Path

    from scripts.seed import load_json

    root = Path(__file__).resolve().parents[2]
    text = normalize_text(
        (root / "seed" / "materials" / "gaoshu-lecture-01.md").read_text(encoding="utf-8")
    )
    blocks = source_blocks_from_title_tree(text)
    used = {block.kp_hint_code for block in blocks if block.kp_hint_code}

    syllabus = load_json("syllabus.json")
    leaves: set[str] = set()

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            if node.get("is_assessable"):
                leaves.add(node["code"])
            walk(node.get("children", []))

    walk(syllabus["nodes"])
    assert used == leaves, f"讲义未覆盖的知识点：{leaves - used}；多余的标记：{used - leaves}"


def test_bundled_lecture_chunks_are_offset_safe() -> None:
    """讲义分块后每块正文都必须等于规范化全文的原始切片。"""
    from pathlib import Path

    from backend.ingestion.chunker import build_chunk_drafts

    root = Path(__file__).resolve().parents[2]
    text = normalize_text(
        (root / "seed" / "materials" / "gaoshu-lecture-01.md").read_text(encoding="utf-8")
    )
    blocks = source_blocks_from_title_tree(text)
    drafts = build_chunk_drafts(text, blocks)

    assert drafts, "讲义必须能切出块"
    for draft in drafts:
        assert text[draft.start_offset : draft.end_offset] == draft.content
        assert len(draft.content) <= 700
