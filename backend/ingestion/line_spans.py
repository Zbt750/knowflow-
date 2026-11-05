from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class LineSpan:
    """一行文本及其在规范化文本中的确切范围 [start, end)（不含换行符）。"""

    number: int
    start: int
    end: int
    text: str


def iter_line_spans(text: str) -> Iterator[LineSpan]:
    """逐行扫描并保留 offset；标题树与分块共用同一个坐标系。"""
    # 不用 splitlines()：它会把 \r\n、\x0b 等也当换行，offset 会与 normalize_text 不一致。
    position = 0
    number = 0
    while position <= len(text):
        newline = text.find("\n", position)
        if newline == -1:
            end = len(text)
        else:
            end = newline
        yield LineSpan(number=number, start=position, end=end, text=text[position:end])
        if newline == -1:
            break
        position = newline + 1
        number += 1