"""混合检索：正文向量 + 标题树 BM25 + 正文 BM25 → RRF → 可选重排 → 数据库补全出处。

三条不变量：
1. 只有 `status='ready'` 的资料、且命中的是它**当前激活的索引版本**才会返回；
   这样「重新索引中的版本」不会污染检索结果，旧版本也不会与新版本同时出现。
2. 返回的正文以 PostgreSQL 为准（向量库里的 document 只用于一致性核对），
   因为引用回跳必须落在 normalized_text 的 offset 坐标系里。
3. 任何一路不可用都不整体失败：向量不可用时两条 BM25 路仍可用；
   标题树为空时正文向量与正文 BM25 仍可用；没有任何一路结果时明确返回空证据。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.rag import ChunkKnowledgePoint, DocumentChunk, Material
from backend.retrieval.fusion import RRF_K, fuse_ranked_ids, rank_map
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.protocols import (
    Embedder,
    EmbeddingUnavailableError,
    IndexFilter,
    RetrievalHit,
    RetrievalRequest,
    SearchFilters,
    VectorStore,
)
from backend.retrieval.rerank import IdentityReranker, Reranker

# 单次检索最多参与融合的候选数。文档契约要求 top_k <= candidate_k <= 50。
MAX_CANDIDATE_K = 50


@dataclass(frozen=True)
class RetrievalOutcome:
    """检索结果与诊断信息。"""

    hits: list[RetrievalHit]
    degraded: bool = False
    degraded_reasons: tuple[str, ...] = field(default_factory=tuple)
    # 融合前各路候选数，便于排查「为什么没召回到」。
    vector_candidates: int = 0
    title_candidates: int = 0
    keyword_candidates: int = 0
    reranked: bool = False


def clamp_candidate_k(top_k: int, candidate_k: int) -> int:
    """把 candidate_k 夹到 [top_k, 50]：太小会浪费召回，太大会拖慢检索。"""
    if top_k <= 0:
        raise ValueError("top_k 必须为正")
    return max(top_k, min(candidate_k, MAX_CANDIDATE_K))


def mmr_select_hits(
    hits: list[RetrievalHit],
    *,
    top_k: int,
    embedder: Embedder,
    lambda_mult: float = 0.65,
) -> list[RetrievalHit]:
    """从已按相关性排序的候选中选出更少重复的结果，顺序稳定且保留首位最相关项。"""
    if top_k <= 0:
        return []
    if len(hits) <= top_k:
        return list(hits)
    if not 0.0 <= lambda_mult <= 1.0:
        raise ValueError("lambda_mult 必须位于 [0, 1]")

    vectors = embedder.encode([hit.content for hit in hits])
    if len(vectors) != len(hits):
        raise ValueError("embedding 数量与候选数量不一致")

    normalized_vectors: list[list[float]] = []
    dimension: int | None = None
    for vector in vectors:
        values = [float(value) for value in vector]
        if dimension is None:
            dimension = len(values)
        if len(values) != dimension:
            raise ValueError("候选 embedding 维度不一致")
        norm = math.sqrt(sum(value * value for value in values))
        normalized_vectors.append(
            [value / norm for value in values]
            if norm > 0 and math.isfinite(norm)
            else [0.0] * len(values)
        )

    # 重排结果已经按相关性降序；用稳定的名次分替代不同模型间不可比的原始分值。
    relevance = [1.0 - position / len(hits) for position in range(len(hits))]
    selected = [0]
    while len(selected) < min(top_k, len(hits)):
        best_index: int | None = None
        best_score = float("-inf")
        for index, vector in enumerate(normalized_vectors):
            if index in selected:
                continue
            redundancy = max(
                0.0,
                *(
                    sum(left * right for left, right in zip(vector, normalized_vectors[picked]))
                    for picked in selected
                ),
            )
            score = lambda_mult * relevance[index] - (1.0 - lambda_mult) * redundancy
            if score > best_score:
                best_index, best_score = index, score
        if best_index is None:
            break
        selected.append(best_index)
    return [hits[index] for index in selected]


def build_index_filter(
    session: Session,
    *,
    filters: SearchFilters | None = None,
    kp_ids: tuple[UUID, ...] | None = None,
) -> IndexFilter:
    """构造「只含可检索版本」的过滤条件。

    可检索 = 资料 `status='ready'` 且有 `active_index_version`。
    用户显式指定的 material_ids / source_types 与之取交集；指定的版本必须
    真实存在于可检索集合中，否则该次检索无结果（宁可空，也不返回错版本）。
    """
    allowed: dict[UUID, str] = {}
    kp_material_ids: set[UUID] | None = None

    if kp_ids:
        # 知识点过滤：先由显式关联反查出资料集合，避免把整库都拉进内存。
        kp_rows = session.execute(
            select(DocumentChunk.material_id, DocumentChunk.index_version)
            .join(ChunkKnowledgePoint, ChunkKnowledgePoint.chunk_id == DocumentChunk.id)
            .where(ChunkKnowledgePoint.kp_id.in_(kp_ids))
        ).all()
        kp_material_ids = {row[0] for row in kp_rows}

    rows = session.execute(
        select(Material.id, Material.active_index_version, Material.source_type).where(
            Material.status == "ready",
            Material.active_index_version.is_not(None),
        )
    ).all()
    for material_id, index_version, source_type in rows:
        if filters is not None:
            if filters.material_ids is not None and material_id not in set(filters.material_ids):
                continue
            if filters.source_types is not None and source_type not in set(filters.source_types):
                continue
            if (
                filters.index_versions is not None
                and index_version not in set(filters.index_versions)
            ):
                continue
            if material_id in set(filters.excluded_material_ids):
                continue
        if kp_material_ids is not None and material_id not in kp_material_ids:
            continue
        allowed[material_id] = index_version

    return IndexFilter(
        # 语义关键：allowed 为空时必须给空元组（= 检索不到任何东西），
        # 绝不能给 None —— None 的含义是「不过滤」，那会把不该检索的资料放进来。
        material_ids=tuple(allowed),
        excluded_material_ids=(filters.excluded_material_ids if filters else ()),
        source_types=(filters.source_types if filters else None),
        # allowed 为空时给空元组，同样表达「没有任何版本可检索」。
        index_versions=tuple(sorted(set(allowed.values()))),
    )


def _load_hit_details(
    session: Session,
    chunk_ids: list[UUID],
    *,
    index_filter: IndexFilter,
    kp_ids: tuple[UUID, ...] | None,
) -> tuple[dict[UUID, tuple[DocumentChunk, Material]], dict[UUID, tuple[UUID, ...]]]:
    """批量加载命中块的正文与资料信息，并校验它仍在可检索版本内。"""
    if not chunk_ids:
        return {}, {}
    rows = session.execute(
        select(DocumentChunk, Material)
        .join(Material, Material.id == DocumentChunk.material_id)
        .where(DocumentChunk.id.in_(chunk_ids))
    ).all()

    details: dict[UUID, tuple[DocumentChunk, Material]] = {}
    for chunk, material in rows:
        # 二次校验：索引可能比数据库旧，命中一个已经不该被检索的版本必须丢弃。
        if material.status != "ready":
            continue
        if material.active_index_version != chunk.index_version:
            continue
        if index_filter.index_versions is not None:
            if chunk.index_version not in set(index_filter.index_versions):
                continue
        details[chunk.id] = (chunk, material)

    kp_map: dict[UUID, tuple[UUID, ...]] = {}
    if details:
        kp_rows = session.execute(
            select(ChunkKnowledgePoint.chunk_id, ChunkKnowledgePoint.kp_id).where(
                ChunkKnowledgePoint.chunk_id.in_(list(details))
            )
        ).all()
        collected: dict[UUID, list[UUID]] = {}
        for chunk_id, kp_id in kp_rows:
            collected.setdefault(chunk_id, []).append(kp_id)
        kp_map = {chunk_id: tuple(values) for chunk_id, values in collected.items()}

    if kp_ids:
        # 知识点过滤在应用层再收一次口：即使某块挂在别的知识点上，也不能漏过来。
        wanted = set(kp_ids)
        kept = {
            chunk_id: value
            for chunk_id, value in details.items()
            if wanted & set(kp_map.get(chunk_id, ()))
        }
        return kept, kp_map
    return details, kp_map


def search_chunks(
    session: Session,
    *,
    request: RetrievalRequest,
    embedder: Embedder,
    vector_store: VectorStore,
    keyword_index: KeywordIndex,
    reranker: Reranker | None = None,
) -> RetrievalOutcome:
    """执行一次混合检索。"""
    query = request.query.strip()
    if not query:
        raise ValueError("empty_query")

    top_k = request.top_k
    candidate_k = clamp_candidate_k(top_k, request.candidate_k)
    index_filter = build_index_filter(
        session, filters=request.filters, kp_ids=request.kp_ids
    )
    # 过滤条件自相矛盾（例如指定了不存在的资料）时直接返回空结果。
    if index_filter.is_empty() or not index_filter.material_ids:
        return RetrievalOutcome(hits=[], vector_candidates=0, keyword_candidates=0)

    reasons: list[str] = []
    vector_ranked: list[UUID] = []
    title_ranked: list[UUID] = []
    keyword_ranked: list[UUID] = []
    # 原始余弦相似度必须单独留住：RRF 融合分只反映名次，
    # 用它做「相关性够不够」的判断等于没判断（见 RetrievalHit.vector_score 的说明）。
    vector_scores: dict[UUID, float] = {}

    try:
        embedding = embedder.encode([query])[0]
    except EmbeddingUnavailableError as error:
        # 向量路不可用时降级为纯关键词检索；这是可用性问题，不是业务失败。
        embedding = None
        reasons.append(f"embedding_unavailable:{error}")
    if embedding is not None:
        vector_hits = vector_store.query(
            embedding, top_k=candidate_k, index_filter=index_filter
        )
        vector_ranked = [hit.chunk_id for hit in vector_hits]
        vector_scores = {hit.chunk_id: hit.score for hit in vector_hits}

    keyword_hits = keyword_index.search(
        query, top_k=candidate_k, index_filter=index_filter
    )
    keyword_ranked = [chunk_id for chunk_id, _ in keyword_hits]
    title_hits = keyword_index.search_title_tree(
        query, top_k=candidate_k, index_filter=index_filter
    )
    title_ranked = [chunk_id for chunk_id, _ in title_hits]

    if not vector_ranked and not title_ranked and not keyword_ranked:
        # 三路都没召回：可能是资料为空、也可能向量路不可用，原因一并带出去。
        if not reasons and keyword_index.count() == 0:
            reasons.append("keyword_index_empty")
        return RetrievalOutcome(
            hits=[],
            degraded=bool(reasons),
            degraded_reasons=tuple(reasons),
            vector_candidates=0,
            title_candidates=0,
            keyword_candidates=0,
        )

    fused = fuse_ranked_ids(
        {"vector": vector_ranked, "title": title_ranked, "keyword": keyword_ranked},
        top_k=candidate_k,
        rrf_k=RRF_K,
    )
    order = [chunk_id for chunk_id, _ in fused]
    scores = {chunk_id: score for chunk_id, score in fused}

    details, kp_map = _load_hit_details(
        session, order, index_filter=index_filter, kp_ids=request.kp_ids
    )
    if not details:
        reasons.append("no_retrievable_chunk")
        return RetrievalOutcome(
            hits=[],
            degraded=True,
            degraded_reasons=tuple(reasons),
            vector_candidates=len(vector_ranked),
            title_candidates=len(title_ranked),
            keyword_candidates=len(keyword_ranked),
        )

    vector_positions = rank_map(vector_ranked)
    title_positions = rank_map(title_ranked)
    keyword_positions = rank_map(keyword_ranked)
    hits: list[RetrievalHit] = []
    for chunk_id in order:
        found = details.get(chunk_id)
        if found is None:
            # 索引里有、数据库里不该检索 → 丢弃。这种情况说明索引陈旧，需要重建。
            continue
        chunk, material = found
        hits.append(
            RetrievalHit(
                chunk_id=chunk.id,
                material_id=material.id,
                material_title=material.title,
                source_type=material.source_type,
                index_version=chunk.index_version,
                ordinal=chunk.ordinal,
                # 正文以 PostgreSQL 为准：它是 offset 坐标系的权威副本。
                content=chunk.content,
                heading_path=tuple(chunk.heading_path or ()),
                kp_ids=kp_map.get(chunk.id, ()),
                score=scores[chunk_id],
                fused_score=scores[chunk_id],
                vector_score=vector_scores.get(chunk_id),
                vector_rank=vector_positions.get(chunk_id),
                title_rank=title_positions.get(chunk_id),
                keyword_rank=keyword_positions.get(chunk_id),
            )
        )
        if len(hits) >= candidate_k:
            break

    active_reranker = reranker or IdentityReranker()
    # 综合问题先精排整个候选池，再由 MMR 选出最终数量；其他问题只精排所需数量。
    rerank_top_k = candidate_k if request.diversify else top_k
    outcome = active_reranker.rerank(query, hits, top_k=rerank_top_k)
    if outcome.degraded and outcome.degraded_reason:
        reasons.append(outcome.degraded_reason)
    selected_hits = outcome.hits
    if request.diversify:
        try:
            selected_hits = mmr_select_hits(
                outcome.hits,
                top_k=top_k,
                embedder=embedder,
            )
        except Exception as error:  # noqa: BLE001 - diversity is optional; ranking remains usable
            reasons.append(f"mmr_unavailable:{type(error).__name__}")
            selected_hits = outcome.hits[:top_k]

    return RetrievalOutcome(
        hits=selected_hits,
        degraded=bool(reasons),
        degraded_reasons=tuple(reasons),
        vector_candidates=len(vector_ranked),
        title_candidates=len(title_ranked),
        keyword_candidates=len(keyword_ranked),
        reranked=outcome.model_name is not None and not outcome.degraded,
    )
