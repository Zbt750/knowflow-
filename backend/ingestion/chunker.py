"""分块：把直接正文块切成带 offset、标题路径与稳定 hash 的 ChunkDraft。

不变量（任何人改这里都必须保持）：
- `content == normalized_text[start_offset:end_offset]`，引用才能从块回跳原文。
- `ordinal` 从 0 连续递增，且按原文顺序输出。
- `content_hash` 只依赖标题路径与正文，不依赖路径、时间或随机值。
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.ingestion.text_normalize import content_hash
from backend.ingestion.title_tree import SourceBlock

# V1 的字符窗口近似；后续可替换为 embedding tokenizer，但不要改 offset 与标题路径契约。
DEFAULT_MAX_CHARS = 700
# 低于这个值就不可能优先在段落/句末断开，窗口会退化成硬切。
MIN_MAX_CHARS = 100


@dataclass(frozen=True)
class ChunkDraft:
    """尚未写库的 canonical chunk；content 必须等于 normalized_text 的原始切片。"""

    ordinal: int
    content: str
    start_offset: int
    end_offset: int
    heading_path: tuple[str, ...]
    content_hash: str
    kp_hint_code: str | None


def split_block(text: str, block: SourceBlock, *, max_chars: int) -> list[tuple[int, int]]:
    """按自然段优先、字符窗口兜底地切一个正文区间，返回绝对 offset。"""
    if max_chars < MIN_MAX_CHARS:
        raise ValueError(f"max_chars 至少为 {MIN_MAX_CHARS}")
    start = block.start_offset
    result: list[tuple[int, int]] = []

    # start 只向前移动；任何一次没有推进都会导致无限循环，因此 end 必须回落到窗口末端。
    while start < block.end_offset:
        preferred_end = min(start + max_chars, block.end_offset)
        if preferred_end == block.end_offset:
            end = block.end_offset
        else:
            # 优先在最近段落边界断开；找不到才在句末或硬窗口断开。
            window = text[start:preferred_end]
            candidates = [
                window.rfind("\n\n"),
                window.rfind("。"),
                window.rfind("！"),
                window.rfind("？"),
            ]
            relative_end = max(candidates)
            # 断点太靠前会让块过短，因此只在窗口后半段才接受它。
            end = (
                start + relative_end + 1
                if relative_end >= max_chars // 2
                else preferred_end
            )
        chunk_text = text[start:end].strip()
        if chunk_text:
            # strip 后重新定位真实边界，保证 content 永远等于全文切片。
            actual_start = text.find(chunk_text, start, end)
            result.append((actual_start, actual_start + len(chunk_text)))
        start = end
    return result


def build_chunk_drafts(
    text: str, blocks: list[SourceBlock], *, max_chars: int = DEFAULT_MAX_CHARS
) -> list[ChunkDraft]:
    """从正文块生成顺序稳定的 chunks，并验证每块内容可由 offset 精确反查。"""
    drafts: list[ChunkDraft] = []
    for block in blocks:
        # ordinal 按遍历顺序生成，重跑相同输入时顺序和 hash 都保持稳定。
        for start, end in split_block(text, block, max_chars=max_chars):
            content = text[start:end]
            drafts.append(
                ChunkDraft(
                    ordinal=len(drafts),
                    content=content,
                    start_offset=start,
                    end_offset=end,
                    heading_path=block.heading_path,
                    content_hash=content_hash(block.heading_path, content),
                    kp_hint_code=block.kp_hint_code,
                )
            )
    # 写 PostgreSQL 前先检查所有不变量；失败时不允许留下半个候选索引版本。
    validate_chunk_drafts(text, drafts)
    return drafts


def validate_chunk_drafts(text: str, drafts: list[ChunkDraft]) -> None:
    """在入库前阻止 offset 越界、内容漂移和顺序错误。"""
    previous_start = -1
    for expected_ordinal, draft in enumerate(drafts):
        if draft.ordinal != expected_ordinal:
            raise ValueError("chunk ordinal 必须从 0 连续递增")
        if not 0 <= draft.start_offset < draft.end_offset <= len(text):
            raise ValueError("chunk offset 超出规范化文本范围")
        if text[draft.start_offset : draft.end_offset] != draft.content:
            raise ValueError("chunk content 与 offset 切片不一致")
        if draft.start_offset < previous_start:
            raise ValueError("chunk 必须按原文顺序输出")
        previous_start = draft.start_offset