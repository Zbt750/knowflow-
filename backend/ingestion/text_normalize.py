from __future__ import annotations

import hashlib
import re

# 标题：一到六级 #，标题文本两侧允许空格与结尾 #。
HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*#*\s*$")
# 知识点提示注释：<!-- kp:math.calculus.limit.lhopital -->
KP_HINT_PATTERN = re.compile(r"^\s*<!--\s*kp:([a-z0-9][a-z0-9._-]*)\s*-->\s*$")
# 只支持三个反引号的代码围栏。
FENCE_PATTERN = re.compile(r"^```")


def normalize_text(raw: str) -> str:
    """把同一文件的换行和尾部空白统一，得到唯一 offset 坐标系。

    这是全文与所有 offset 的唯一基准：解析器、标题树、分块都必须基于它的返回值。
    """
    # BOM、CRLF 与 CR 都会使同一内容在 Windows/macOS 得到不同 hash 和 offset。
    text = raw.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    # 每行右侧空格只干扰 hash 与 chunk 长度，不影响语义，统一移除。
    lines = [line.rstrip() for line in text.split("\n")]

    # 连续空行最多留两行：保留段落感，但避免空白把 chunk 撑得过大。
    compacted: list[str] = []
    empty_count = 0
    for line in lines:
        if line:
            empty_count = 0
            compacted.append(line)
            continue
        empty_count += 1
        if empty_count <= 2:
            compacted.append("")
    # 统一收尾：去掉首尾空行并保证恰好一个结尾换行。
    # 这样同一内容在任何输入换行风格下都得到同一个 normalized_text 与同一套 offset。
    return "\n".join(compacted).strip("\n") + "\n"


def content_hash(heading_path: tuple[str, ...], content: str) -> str:
    """为标题路径与正文生成稳定 SHA-256；相同正文在不同章节不能误判成同一块。"""
    # 使用极少出现在标题中的分隔符，避免 ["ab","c"] 与 ["a","bc"] 拼接碰撞。
    stable_path = "\u001f".join(heading_path)
    return hashlib.sha256(f"{stable_path}\n{content}".encode("utf-8")).hexdigest()


def material_content_hash(normalized_text: str) -> str:
    """资料级 hash：只依赖规范化全文，绝不混入路径、时间或随机值。"""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()