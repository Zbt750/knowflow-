"""RRF（Reciprocal Rank Fusion）融合多路召回。

为什么用 RRF 而不是加权分数：
向量相似度与 BM25 分数**量纲完全不同**，直接加权需要每换一个 embedding 模型
就重新标定权重。RRF 只看名次，天然规避量纲问题，且对单路异常分数不敏感。

公式：score(d) = Σ 1 / (rrf_k + rank(d))，rank 从 1 开始。
"""

from __future__ import annotations

from uuid import UUID

# RRF 平滑常数。60 是文献常用取值：让前几名之间的差距不过分悬殊，
# 同时保证「两路都进前 10」明显优于「只有一路第一」。
RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: dict[str, list[UUID]],
    *,
    rrf_k: int = RRF_K,
) -> dict[UUID, float]:
    """把多路名次列表融合成分数字典。

    `ranked_lists` 的 value 必须已按相关性降序排列；顺序即全部信息，
    原始分数会被忽略（这正是 RRF 能跨量纲工作的原因）。
    """
    if rrf_k <= 0:
        raise ValueError("rrf_k 必须为正")
    scores: dict[UUID, float] = {}
    for ids in ranked_lists.values():
        # 去重范围是**单路内部**：同一路里重复的 id 只按最靠前的名次计一次，
        # 但每一路都必须独立累加，否则「两路都召回」的文档拿不到应有的加权。
        seen: set[UUID] = set()
        for position, chunk_id in enumerate(ids):
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + position + 1)
    # 分数降序；同分按 id 排序，保证同一输入永远得到同一输出顺序。
    return dict(sorted(scores.items(), key=lambda item: (-item[1], str(item[0]))))


def fuse_ranked_ids(
    ranked_lists: dict[str, list[UUID]],
    *,
    top_k: int,
    rrf_k: int = RRF_K,
) -> list[tuple[UUID, float]]:
    """融合并截断到 top_k。"""
    if top_k <= 0:
        return []
    fused = reciprocal_rank_fusion(ranked_lists, rrf_k=rrf_k)
    return list(fused.items())[:top_k]


def rank_map(ids: list[UUID]) -> dict[UUID, int]:
    """把名次列表转成「id → 名次（从 1 开始）」，便于在结果里回溯来源。"""
    return {chunk_id: position + 1 for position, chunk_id in enumerate(ids)}
