"""标题树：把规范化文本切成「标题路径 + 直接正文」的块。

设计约束：
- 所有 offset 都基于 `normalize_text()` 的返回值，与分块、引用共用同一坐标系。
- 不使用全局状态；节点区间完全由递归参数决定，因此同一输入永远得到同一结果。
- 代码围栏（三个反引号）内的 `#` 行不是标题。
- `<!-- kp:code -->` 是结构元数据，不进入正文。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Iterator

from backend.ingestion.line_spans import iter_line_spans
from backend.ingestion.text_normalize import FENCE_PATTERN, HEADING_PATTERN, KP_HINT_PATTERN


@dataclass
class TitleNode:
    """标题树节点：自己的标题行、管辖区间与直接正文区间。"""

    heading: str
    level: int
    # 标题行自身范围（不含换行）。
    heading_start: int
    heading_end: int
    # 标题行之后、本节点管辖范围之前一字符起的正文起点。
    body_start: int
    # 本节点管辖范围 [start, end)：下一个同级或更高级标题之前。
    start: int
    end: int
    # 属于本节点的直接正文（已扣除子孙标题管辖的部分）。
    direct_ranges: list[tuple[int, int]] = field(default_factory=list)
    kp_hint_code: str | None = None
    children: list["TitleNode"] = field(default_factory=list)


@dataclass(frozen=True)
class HeadingHit:
    level: int
    text: str
    start: int
    end: int
    line: int


@dataclass(frozen=True)
class SourceBlock:
    """分块输入：一段归属同一标题路径的直接正文。"""

    start_offset: int
    end_offset: int
    heading_path: tuple[str, ...]
    kp_hint_code: str | None


def scan_headings(text: str) -> list[HeadingHit]:
    """识别标题；围栏内的 `#` 行被忽略。"""
    hits: list[HeadingHit] = []
    in_fence = False
    for span in iter_line_spans(text):
        # 围栏开关只支持三个反引号；复杂 Markdown 扩展不属于 V1。
        if FENCE_PATTERN.match(span.text):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_PATTERN.match(span.text)
        if match is None:
            continue
        hits.append(
            HeadingHit(
                level=len(match.group(1)),
                text=match.group(2).strip(),
                start=span.start,
                end=span.end,
                line=span.number,
            )
        )
    return hits


def scan_kp_hints(text: str) -> dict[int, str]:
    """收集 `<!-- kp:code -->`：返回「行号 → code」。注释本身不进入正文。"""
    hints: dict[int, str] = {}
    in_fence = False
    for span in iter_line_spans(text):
        if FENCE_PATTERN.match(span.text):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = KP_HINT_PATTERN.match(span.text)
        if match is not None:
            hints[span.number] = match.group(1)
    return hints


def build_title_tree(
    hits: list[HeadingHit], *, document_length: int, fallback_title: str = "正文"
) -> list[TitleNode]:
    """把标题序列变成树；没有标题时生成一个以 fallback_title 命名的根节点。"""
    roots: list[TitleNode] = []
    # 显式栈：栈内 level 严格递增，遇到同级或更高级就弹出。
    stack: list[TitleNode] = []

    for hit in hits:
        node = TitleNode(
            heading=hit.text,
            level=hit.level,
            heading_start=hit.start,
            heading_end=hit.end,
            # 标题行结束位置 + 1 跳过换行符；文档末尾没有换行时保持不变。
            body_start=hit.end + 1 if hit.end < document_length else hit.end,
            start=hit.start,
            end=document_length,
        )
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    if not roots:
        # 无标题文档也必须可摄取：整篇作为唯一节点的直接正文。
        root = TitleNode(
            heading=fallback_title,
            level=1,
            heading_start=0,
            heading_end=0,
            body_start=0,
            start=0,
            end=document_length,
        )
        root.direct_ranges.append((0, document_length))
        return [root]

    _assign_ranges(roots, document_length)
    return roots


def _assign_ranges(nodes: list[TitleNode], limit: int) -> None:
    """给一组兄弟节点分配区间。

    第 i 个兄弟的结束位置 = 第 i+1 个兄弟的开始位置；最后一个兄弟延续到 limit。
    把 limit 作为递归参数传入后，无需任何全局索引即可算出正确区间。
    """
    for index, node in enumerate(nodes):
        end = nodes[index + 1].start if index + 1 < len(nodes) else limit
        node.end = end
        _assign_ranges(node.children, end)
        # 直接正文 = 标题行之后到 node.end，再挖掉每个子节点管辖的范围。
        ranges: list[tuple[int, int]] = [(node.body_start, node.end)]
        for child in node.children:
            ranges = _subtract(ranges, (child.start, child.end))
        node.direct_ranges = [(start, stop) for start, stop in ranges if stop > start]


def _subtract(
    ranges: list[tuple[int, int]], cut: tuple[int, int]
) -> list[tuple[int, int]]:
    """从一组区间里挖掉一个区间，返回剩余部分（保持顺序）。"""
    result: list[tuple[int, int]] = []
    cut_start, cut_end = cut
    for start, end in ranges:
        if cut_end <= start or cut_start >= end:
            result.append((start, end))
            continue
        if start < cut_start:
            result.append((start, cut_start))
        if cut_end < end:
            result.append((cut_end, end))
    return result


def iter_nodes_with_path(
    nodes: list[TitleNode], prefix: tuple[str, ...] = ()
) -> Iterator[tuple[TitleNode, tuple[str, ...]]]:
    """深度优先遍历，携带从根到当前节点的标题路径。"""
    for node in nodes:
        path = prefix + (node.heading,)
        yield node, path
        yield from iter_nodes_with_path(node.children, path)


def resolve_kp_hints(roots: list[TitleNode], text: str) -> dict[int, str | None]:
    """算出每个标题节点继承了哪个 kp: code（按节点对象 id 索引）。

    语义：`<!-- kp:code -->` 是写在某个标题**之上**的结构标记，它归属于紧随其后的
    那个标题。因此每个节点「自有」的注释范围是：
        [本节点标题起点, 第一个子节点标题起点)
    也就是「从它自己这一行开始，到它的第一个子标题之前」。

    为什么起点不能用 `body_start`：父节点的 `body_start` 在父标题行之后，
    而注释通常写在父标题行之前（为了标注父标题本身），用 body_start 当起点
    会把注释漏到父节点之外，导致整份文档的注释全部错位一格。
    """
    hints = scan_kp_hints(text)
    if not hints:
        return {id(node): None for node in _iter_all(roots)}

    # 预排序 + 二分查找：避免对每个节点都线性扫一遍注释（那会退化成 O(节点数 × 行数)）。
    ordered_lines = sorted(hints)
    line_starts = _line_starts(text)
    resolved: dict[int, str | None] = {}

    def latest_hint_before(offset: int) -> tuple[int, str] | None:
        """取起始位置严格小于 offset 的最后一个注释。"""
        position = bisect.bisect_left(line_starts, offset) - 1
        if position < 0:
            return None
        line = ordered_lines[bisect.bisect_right(ordered_lines, position) - 1]
        if line > position:
            return None
        return line, hints[line]

    def own_hint(node: TitleNode) -> str | None:
        """本节点自有的注释：必须紧邻在本节点标题行之前。"""
        found = latest_hint_before(node.heading_start)
        if found is None:
            return None
        line, code = found
        # 只接受「注释行与标题行之间只有空行」的情况，否则一个注释会一路
        # 影响到很远之后的标题，那显然不是作者的本意。
        if not _only_blank_lines_between(text, line_starts, line, node.heading_start):
            return None
        return code

    def walk(node: TitleNode, inherited: str | None) -> None:
        # 自有注释优先；没有则继承父亲 —— 这样整章共用一个 kp 标记也成立。
        own = own_hint(node)
        chosen = own if own is not None else inherited
        resolved[id(node)] = chosen
        for child in node.children:
            walk(child, chosen)

    for root in roots:
        walk(root, None)
    return resolved


def _only_blank_lines_between(
    text: str, line_starts: list[int], hint_line: int, offset: int
) -> bool:
    """注释行与目标位置之间是否只有空行。"""
    if hint_line >= len(line_starts):
        return False
    between = text[line_starts[hint_line] : offset]
    # 第一行就是注释行自身，从第二行开始判断。
    return all(not line.strip() for line in between.split("\n")[1:])


def _iter_all(nodes: list[TitleNode]) -> Iterator[TitleNode]:
    for node in nodes:
        yield node
        yield from _iter_all(node.children)


def iter_direct_sections(
    roots: list[TitleNode], text: str
) -> Iterator[tuple[tuple[str, ...], str | None, int, int]]:
    """遍历所有直接正文区间：产生 (标题路径, kp hint, start, end)。

    调试脚本与摄取服务共用，保证「检查时看到的区间」就是「实际入库的区间」。
    """
    resolved = resolve_kp_hints(roots, text)
    for node, path in iter_nodes_with_path(roots):
        hint = resolved.get(id(node))
        for start, end in sorted(node.direct_ranges):
            yield path, hint, start, end


def source_blocks_from_title_tree(
    text: str, *, fallback_title: str = "正文"
) -> list[SourceBlock]:
    """标题树 → 直接正文块列表；这是正式分块入口。"""
    roots = build_title_tree(
        scan_headings(text), document_length=len(text), fallback_title=fallback_title
    )
    blocks: list[SourceBlock] = []
    for path, hint, start, end in iter_direct_sections(roots, text):
        body = text[start:end].strip()
        if not body:
            # 空正文段落不产生块；纯 kp: 注释也不产生块。
            continue
        # strip 后重新定位真实边界，保证 content 永远等于全文切片。
        actual_start = text.find(body, start, end)
        blocks.append(
            SourceBlock(
                start_offset=actual_start,
                end_offset=actual_start + len(body),
                heading_path=path,
                kp_hint_code=hint,
            )
        )
    return blocks


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts
