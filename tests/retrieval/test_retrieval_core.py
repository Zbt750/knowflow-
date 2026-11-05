"""检索层纯逻辑测试：RRF 融合、向量库、关键词索引。

这些用例不碰数据库：融合顺序、过滤语义、归一化契约都是纯函数行为，
出错时后果很严重（排序错乱、不该召回的资料被召回）却不会报错，因此逐条钉住。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from backend.retrieval.embedding import FakeEmbedder
from backend.retrieval.fusion import RRF_K, fuse_ranked_ids, rank_map, reciprocal_rank_fusion
from backend.retrieval.keyword import KeywordIndex, tokenize
from backend.retrieval.protocols import (
    IndexFilter,
    VectorRecord,
    VectorStoreError,
)
from backend.retrieval.vector_store import (
    COLLECTION_SPACE,
    InMemoryVectorStore,
    ensure_normalized,
)


def record(material_id: UUID, content: str, **overrides) -> VectorRecord:
    values = {
        "chunk_id": uuid4(),
        "material_id": material_id,
        "index_version": "v1-test",
        "ordinal": 0,
        "content": content,
        "heading_path": ("高等数学", "极限"),
        "source_type": "builtin",
        "kp_hint_code": None,
    }
    values.update(overrides)
    return VectorRecord(**values)


# ---------------------------------------------------------------------------
# RRF 融合
# ---------------------------------------------------------------------------


def test_rrf_agreement_beats_single_route_lead() -> None:
    """两路都进前列，必须强于只有一路第一。"""
    shared = uuid4()  # 两路都召回
    vector_only = uuid4()  # 只有向量路第一
    fused = reciprocal_rank_fusion({"vector": [vector_only, shared], "keyword": [shared]})

    assert list(fused)[0] == shared
    assert fused[shared] > fused[vector_only]


def test_rrf_uses_rank_not_raw_score() -> None:
    """RRF 只看名次：顺位相同就得分相同，原始分数不影响结果。"""
    first, second = uuid4(), uuid4()
    fused = reciprocal_rank_fusion({"vector": [first, second]})

    assert fused[first] == pytest.approx(1.0 / (RRF_K + 1))
    assert fused[second] == pytest.approx(1.0 / (RRF_K + 2))


def test_rrf_deduplicates_within_one_route() -> None:
    """同一路里重复出现的 id 只按最靠前名次计一次，否则会被单路刷分。"""
    duplicated, other = uuid4(), uuid4()
    fused = reciprocal_rank_fusion({"vector": [duplicated, other, duplicated]})

    assert fused[duplicated] == pytest.approx(1.0 / (RRF_K + 1))
    assert fused[other] == pytest.approx(1.0 / (RRF_K + 2))


def test_rrf_is_deterministic_on_ties() -> None:
    """同分时按 id 排序：同一输入必须永远得到同一顺序。"""
    a, b = UUID(int=1), UUID(int=2)
    first = list(reciprocal_rank_fusion({"vector": [a, b]}))
    second = list(reciprocal_rank_fusion({"vector": [a, b]}))
    assert first == second


def test_rrf_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError, match="rrf_k 必须为正"):
        reciprocal_rank_fusion({"vector": [uuid4()]}, rrf_k=0)


def test_fuse_ranked_ids_truncates_and_handles_empty() -> None:
    ids = [uuid4() for _ in range(3)]
    assert len(fuse_ranked_ids({"vector": ids}, top_k=2)) == 2
    assert fuse_ranked_ids({"vector": ids}, top_k=0) == []
    assert fuse_ranked_ids({}, top_k=5) == []


def test_rank_map_starts_at_one() -> None:
    ids = [uuid4(), uuid4()]
    mapping = rank_map(ids)
    assert mapping[ids[0]] == 1
    assert mapping[ids[1]] == 2


# ---------------------------------------------------------------------------
# 向量归一化契约
# ---------------------------------------------------------------------------


def test_ensure_normalized_accepts_unit_vector() -> None:
    ensure_normalized([1.0, 0.0, 0.0])


@pytest.mark.parametrize("vector", [[], [0.0, 0.0], [2.0, 0.0], [float("nan"), 1.0]])
def test_ensure_normalized_rejects_bad_vectors(vector) -> None:
    """非归一化向量在 cosine 空间里会被后端接受，但分数失真且不报错，必须入口拦住。"""
    with pytest.raises(VectorStoreError):
        ensure_normalized(vector)


# ---------------------------------------------------------------------------
# 向量库
# ---------------------------------------------------------------------------


def test_in_memory_store_ranks_exact_match_first() -> None:
    embedder = FakeEmbedder(dimension=64)
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    material_id = uuid4()
    # 查询文本与第一条记录完全相同 → 余弦相似度 1.0，必然排第一。
    records = [
        record(material_id, "洛必达法则是求 0/0 型极限的方法"),
        record(material_id, "函数的连续性与间断点"),
    ]
    store.upsert(records, embedder.encode([r.content for r in records]))

    hits = store.query(embedder.encode(["洛必达法则是求 0/0 型极限的方法"])[0], top_k=2)

    assert hits[0].chunk_id == records[0].chunk_id
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)
    # document 回带原文，用于与 PostgreSQL 正文核对。
    assert hits[0].document == records[0].content


def test_in_memory_store_delete_by_material_and_version() -> None:
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    material_id = uuid4()
    v1 = record(material_id, "第一版正文", index_version="v1")
    v2 = record(material_id, "第二版正文", index_version="v2")
    store.upsert([v1, v2], embedder.encode([v1.content, v2.content]))

    assert store.delete_by_material(material_id, "v1") == 1
    assert store.count() == 1
    # 另一个版本必须保留：删除旧版本不能误伤新版本。
    assert store.delete_material_all_versions(material_id) == 1
    assert store.count() == 0


def test_in_memory_store_filters_material_ids_and_versions() -> None:
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    keep, drop = uuid4(), uuid4()
    records = [
        record(keep, "洛必达法则的内容", index_version="v-keep"),
        record(drop, "洛必达法则的内容", index_version="v-drop"),
    ]
    store.upsert(records, embedder.encode([r.content for r in records]))
    query_vector = embedder.encode(["洛必达法则的内容"])[0]

    by_material = store.query(
        query_vector, top_k=5, index_filter=IndexFilter(material_ids=(keep,))
    )
    assert [hit.chunk_id for hit in by_material] == [records[0].chunk_id]

    by_version = store.query(
        query_vector, top_k=5, index_filter=IndexFilter(index_versions=("v-drop",))
    )
    assert [hit.chunk_id for hit in by_version] == [records[1].chunk_id]

    excluded = store.query(
        query_vector, top_k=5, index_filter=IndexFilter(excluded_material_ids=(keep,))
    )
    assert [hit.chunk_id for hit in excluded] == [records[1].chunk_id]

    by_source = store.query(
        query_vector, top_k=5, index_filter=IndexFilter(source_types=("user",))
    )
    assert by_source == []


def test_index_filter_empty_means_no_match() -> None:
    """空元组的语义是「检索不到任何东西」；实现必须照做，不能当作不过滤。"""
    assert IndexFilter(material_ids=()).is_empty() is True
    assert IndexFilter(source_types=()).is_empty() is True
    assert IndexFilter(index_versions=()).is_empty() is True
    assert IndexFilter().is_empty() is False


def test_in_memory_store_empty_filter_returns_nothing() -> None:
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    material_id = uuid4()
    rec = record(material_id, "洛必达法则")
    store.upsert([rec], embedder.encode([rec.content]))

    hits = store.query(
        embedder.encode(["洛必达法则"])[0],
        top_k=5,
        index_filter=IndexFilter(material_ids=()),
    )
    assert hits == []


def test_in_memory_store_rejects_mismatched_lengths() -> None:
    store = InMemoryVectorStore(embedding_model="fake")
    with pytest.raises(VectorStoreError, match="数量不一致"):
        store.upsert([record(uuid4(), "正文")], [])


def test_cosine_space_is_declared_for_collection() -> None:
    """向量是归一化的，集合必须是 cosine 空间，否则相似度不可比。"""
    assert COLLECTION_SPACE == "cosine"


# ---------------------------------------------------------------------------
# 关键词索引
# ---------------------------------------------------------------------------


def test_tokenize_drops_punctuation_only() -> None:
    tokens = tokenize("洛必达法则，求极限。（0/0 型）")
    assert "洛必达" in tokens
    assert "极限" in tokens
    # 纯标点不得进入词表，否则会稀释 BM25 的区分度。
    assert "，" not in tokens
    assert "。" not in tokens


def test_tokenize_ignores_blank_text() -> None:
    assert tokenize("   \n\t ") == []


def test_keyword_index_ranks_term_match_first() -> None:
    material_id = uuid4()
    lhopital = record(material_id, "洛必达法则用于求 0/0 型极限。")
    # BM25 的 IDF 需要足够大的语料才有区分度：文档太少时常见词 IDF 会退化，
    # 这是算法特性而不是实现缺陷，所以测试语料要接近真实规模。
    others = [
        record(material_id, "函数在一点连续需要左极限等于右极限。"),
        record(material_id, "夹逼定理用两个函数夹住待求函数。"),
        record(material_id, "导数定义是差商的极限。"),
        record(material_id, "定积分表示曲边梯形的面积。"),
        record(material_id, "中值定理说明存在一点使导数等于平均变化率。"),
    ]
    index = KeywordIndex()
    index.rebuild([lhopital, *others])

    hits = index.search("洛必达法则", top_k=3)

    assert [chunk_id for chunk_id, _ in hits] == [lhopital.chunk_id]
    assert hits[0][1] > 0


def test_keyword_index_search_matches_heading_path() -> None:
    """标题路径里的知识点名往往就是查询词，必须参与 BM25。"""
    material_id = uuid4()
    target = record(material_id, "正文只讲推导。", heading_path=("高等数学", "洛必达法则"))
    others = [
        record(material_id, "函数在一点连续需要左极限等于右极限。"),
        record(material_id, "夹逼定理用两个函数夹住待求函数。"),
        record(material_id, "导数定义是差商的极限。"),
        record(material_id, "定积分表示曲边梯形的面积。"),
    ]
    index = KeywordIndex()
    index.rebuild([target, *others])

    hits = index.search("洛必达法则", top_k=3)
    assert [chunk_id for chunk_id, _ in hits] == [target.chunk_id]


def test_keyword_index_applies_same_filters_as_vector_store() -> None:
    keep, drop = uuid4(), uuid4()
    kept = record(keep, "洛必达法则的内容")
    dropped = record(drop, "洛必达法则的内容")
    others = [
        record(keep, "函数在一点连续需要左极限等于右极限。"),
        record(keep, "夹逼定理用两个函数夹住待求函数。"),
        record(keep, "定积分表示曲边梯形的面积。"),
    ]
    index = KeywordIndex()
    index.rebuild([kept, dropped, *others])

    hits = index.search("洛必达法则", top_k=5, index_filter=IndexFilter(material_ids=(keep,)))
    assert [chunk_id for chunk_id, _ in hits] == [kept.chunk_id]

    assert index.search("洛必达法则", top_k=5, index_filter=IndexFilter(material_ids=())) == []
    assert (
        index.search("洛必达法则", top_k=5, index_filter=IndexFilter(source_types=("user",)))
        == []
    )


def test_keyword_index_handles_empty_corpus_and_blank_query() -> None:
    index = KeywordIndex()
    index.rebuild([])
    assert index.count() == 0
    assert index.search("洛必达法则", top_k=5) == []

    rec = record(uuid4(), "洛必达法则")
    index.rebuild([rec])
    assert index.search("   ", top_k=5) == []
    assert index.search("洛必达法则", top_k=0) == []


def test_keyword_index_rebuild_is_idempotent() -> None:
    """重建必须是纯函数式结果：同一批记录重复重建，分数完全一致。"""
    material_id = uuid4()
    records = [record(material_id, "洛必达法则"), record(material_id, "夹逼定理")]
    index = KeywordIndex()
    index.rebuild(records)
    first = index.search("洛必达法则", top_k=2)
    index.rebuild(records)
    assert index.search("洛必达法则", top_k=2) == first
