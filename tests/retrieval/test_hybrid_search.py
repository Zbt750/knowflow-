"""混合检索集成测试：真实 PostgreSQL + 可控向量库/embedding。

这一层测的是「**哪些 chunk 允许被召回**」以及「三路召回怎么合并」。
这类错误不会抛异常，只会安静地返回不该返回的内容，所以每条规则都要有对应用例。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.ingestion.text_normalize import normalize_text
from backend.models.rag import DocumentChunk, Material
from backend.retrieval.embedding import FakeEmbedder
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.protocols import (
    EmbeddingUnavailableError,
    RetrievalHit,
    RetrievalRequest,
    SearchFilters,
    VectorRecord,
)
from backend.retrieval.rerank import CrossEncoderReranker, IdentityReranker
from backend.retrieval.vector_store import InMemoryVectorStore
from backend.services.retrieval_service import (
    MAX_CANDIDATE_K,
    build_index_filter,
    clamp_candidate_k,
    mmr_select_hits,
    search_chunks,
)

from tests.retrieval.conftest import create_chunk, create_material

# 手写单位向量：维度 8 便于精确控制相似度，不必依赖真实模型。
# 三个向量都归一化，与向量库的 cosine 契约一致。
V_QUERY = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 与查询完全一致：向量路必然排第一。
V_CLOSE = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 与查询有夹角但仍算接近：用于「两路都命中」的文档，避免与 V_CLOSE 同分。
V_MEDIUM = [0.8, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 与查询正交：向量路不会召回它。
V_FAR = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

QUERY = "洛必达法则"

# 故意不含查询词「洛必达法则」的任何字面片段：
# 这样它只能靠向量路被召回，才能证明「向量路确实独立工作了」。
DOC_VECTOR_ONLY = "用两个函数的导数之比来求未定式的极限值。"
DOC_KEYWORD_ONLY = "洛必达法则是高等数学的重要方法。"
DOC_BOTH = "洛必达法则的适用条件与注意事项。"

FILLER_DOCS = [
    "函数在一点连续需要左极限等于右极限。",
    "夹逼定理用两个函数夹住待求函数。",
    "导数定义是差商的极限。",
    "定积分表示曲边梯形的面积。",
    "中值定理说明存在一点使导数等于平均变化率。",
]


def make_embedder() -> FakeEmbedder:
    """构造一个受控 embedder：查询和三个目标文档的向量都写死。"""
    return FakeEmbedder(
        dimension=8,
        overrides={
            QUERY: V_QUERY,
            DOC_VECTOR_ONLY: V_CLOSE,
            DOC_KEYWORD_ONLY: V_FAR,
            # 两路都命中的文档也要与查询接近，否则它只会从关键词路回来。
            DOC_BOTH: V_MEDIUM,
        },
    )


def build_corpus(session) -> dict[str, object]:
    """建一份 ready 的资料，含三类 chunk 与若干干扰文档。"""
    body = "\n\n".join([QUERY, DOC_VECTOR_ONLY, DOC_KEYWORD_ONLY, DOC_BOTH, *FILLER_DOCS]) + "\n"
    material = create_material(session, title="高等数学讲义", body=body)
    chunks: dict[str, DocumentChunk] = {}
    for ordinal, text in enumerate([DOC_VECTOR_ONLY, DOC_KEYWORD_ONLY, DOC_BOTH, *FILLER_DOCS]):
        chunks[text] = create_chunk(
            session, material, content=text, ordinal=ordinal, heading_path=("高等数学", "极限")
        )
    session.commit()
    return {"material": material, "chunks": chunks, "body": normalize_text(body)}


def build_indexes(embedder: FakeEmbedder, session, material: Material) -> tuple[InMemoryVectorStore, KeywordIndex]:
    """按数据库里的 chunk 建向量库与关键词索引。"""
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    records = [
        VectorRecord(
            chunk_id=chunk.id,
            material_id=chunk.material_id,
            index_version=chunk.index_version,
            ordinal=chunk.ordinal,
            content=chunk.content,
            heading_path=tuple(chunk.heading_path or ()),
            source_type=material.source_type,
            material_title=material.title,
        )
        for chunk in session.query(DocumentChunk).all()
    ]
    store.upsert(records, embedder.encode([record.content for record in records]))
    keyword = KeywordIndex()
    keyword.rebuild(records)
    return store, keyword


# ---------------------------------------------------------------------------
# 结果正确性
# ---------------------------------------------------------------------------


def test_two_routes_are_merged_and_annotated(session_factory) -> None:
    """向量路与关键词路各自命中的 chunk 都必须出现在结果里，并标出来源名次。"""
    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        store, keyword = build_indexes(embedder, db, corpus["material"])

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    assert outcome.hits, "两路都应有召回"
    by_chunk = {hit.chunk_id: hit for hit in outcome.hits}
    vector_chunk = corpus["chunks"][DOC_VECTOR_ONLY]
    keyword_chunk = corpus["chunks"][DOC_KEYWORD_ONLY]

    assert vector_chunk.id in by_chunk, "向量路高相似度的 chunk 必须被召回"
    assert keyword_chunk.id in by_chunk, "关键词路命中的 chunk 必须被召回"
    # V_CLOSE 与查询向量完全一致，必须有向量名次；而它字面上不含查询词，
    # 所以关键词路不该召回它 —— 这一条正是「两路互补」的证据。
    assert by_chunk[vector_chunk.id].vector_rank == 1
    assert by_chunk[vector_chunk.id].keyword_rank is None
    # 另一篇只靠关键词被召回：它必须有关键词名次，且不在向量路的前列
    # （它的向量与查询正交，排在最末）。
    # 这里只断言「按词频同分的文档会共享靠前的名次」，不断言恰好第 1：
    # 语料里有多个文档含同一个查询词，同分时名次由内部排序决定，
    # 要求恰好第一会变成一个随机失败的脆弱断言。
    assert by_chunk[keyword_chunk.id].keyword_rank is not None
    assert by_chunk[keyword_chunk.id].keyword_rank <= 2
    assert by_chunk[keyword_chunk.id].vector_rank != 1
    assert outcome.vector_candidates >= 1
    assert outcome.keyword_candidates >= 1


def test_title_tree_route_expands_a_matched_heading_to_its_subtree(session_factory) -> None:
    """标题召回命中章节节点后，扩展该章节的块而不混入相邻章节。"""
    embedder = make_embedder()
    body = "章节甲的正文内容。\n\n章节乙的正文内容。\n"
    with session_factory() as db:
        material = create_material(db, title="标题树测试资料", body=body)
        first = create_chunk(
            db, material, content="章节甲的正文内容。", ordinal=0, heading_path=("章节甲",)
        )
        second = create_chunk(
            db, material, content="章节乙的正文内容。", ordinal=1, heading_path=("章节乙",)
        )
        db.commit()
        records = [
            VectorRecord(
                chunk_id=chunk.id,
                material_id=material.id,
                index_version=chunk.index_version,
                ordinal=chunk.ordinal,
                content=chunk.content,
                heading_path=tuple(chunk.heading_path or ()),
                source_type=material.source_type,
                material_title=material.title,
            )
            for chunk in (first, second)
        ]
        store = InMemoryVectorStore(embedding_model=embedder.model_name)
        store.upsert(records, embedder.encode([record.content for record in records]))
        keyword = KeywordIndex()
        keyword.rebuild(records)

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query="章节甲", top_k=2, candidate_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    by_id = {hit.chunk_id: hit for hit in outcome.hits}
    assert first.id in by_id and second.id in by_id  # 正文词路可独立命中两块
    assert by_id[first.id].title_rank is not None
    assert by_id[second.id].title_rank is None
    assert outcome.title_candidates == 1


def test_title_tree_root_expands_the_named_material(session_factory) -> None:
    """查询资料名命中标题树根节点后，应扩展整份资料的块。"""
    embedder = make_embedder()
    body = "第一章的内容。\n\n第二章的内容。\n"
    with session_factory() as db:
        material = create_material(db, title="超导计算方法资料", body=body)
        chunks = [
            create_chunk(
                db, material, content="第一章的内容。", ordinal=0, heading_path=("第一章",)
            ),
            create_chunk(
                db, material, content="第二章的内容。", ordinal=1, heading_path=("第二章",)
            ),
        ]
        db.commit()
        records = [
            VectorRecord(
                chunk_id=chunk.id,
                material_id=material.id,
                index_version=chunk.index_version,
                ordinal=chunk.ordinal,
                content=chunk.content,
                heading_path=tuple(chunk.heading_path or ()),
                source_type=material.source_type,
                material_title=material.title,
            )
            for chunk in chunks
        ]
        store = InMemoryVectorStore(embedding_model=embedder.model_name)
        store.upsert(records, embedder.encode([record.content for record in records]))
        keyword = KeywordIndex()
        keyword.rebuild(records)

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query="超导计算方法资料", top_k=2, candidate_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    by_id = {hit.chunk_id: hit for hit in outcome.hits}
    assert set(by_id) == {chunk.id for chunk in chunks}
    assert all(hit.title_rank is not None for hit in by_id.values())
    assert outcome.title_candidates == 2


def test_content_comes_from_database_not_vector_store(session_factory) -> None:
    """正文必须以 PostgreSQL 为准，否则引用回跳会对不上 offset 坐标系。

    做法：让向量库里同一个 chunk_id 存一份**不同的** document（模拟索引里的正文
    已经过期），检索结果仍必须返回数据库里的正文。
    """
    embedder = make_embedder()
    tampered = "这是向量库里过期的正文"
    with session_factory() as db:
        corpus = build_corpus(db)
        store, keyword = build_indexes(embedder, db, corpus["material"])
        target = corpus["chunks"][DOC_VECTOR_ONLY]
        # 用公开接口覆盖同一条记录：向量保持接近查询，但 document 被换掉。
        store.upsert(
            [
                VectorRecord(
                    chunk_id=target.id,
                    material_id=corpus["material"].id,
                    index_version=corpus["material"].active_index_version or "v1-test",
                    ordinal=target.ordinal,
                    content=tampered,
                    heading_path=("高等数学", "极限"),
                    source_type="builtin",
                )
            ],
            [V_CLOSE],
        )

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    hit = next(h for h in outcome.hits if h.chunk_id == target.id)
    assert hit.content == DOC_VECTOR_ONLY
    assert tampered not in hit.content
    assert hit.material_title == "高等数学讲义"
    assert hit.heading_path == ("高等数学", "极限")


def test_chunk_missing_in_database_is_dropped(session_factory) -> None:
    """向量库里有、数据库里没有的 chunk 必须丢弃：索引陈旧时宁可少返回。"""
    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        store, keyword = build_indexes(embedder, db, corpus["material"])
        # 用一个数据库里根本不存在的 chunk 建索引：它不能出现在结果里。
        store.upsert(
            [
                VectorRecord(
                    chunk_id=uuid4(),
                    material_id=corpus["material"].id,
                    index_version=corpus["material"].active_index_version or "v1-test",
                    ordinal=999,
                    content=QUERY,
                    heading_path=(),
                    source_type="builtin",
                )
            ],
            [V_CLOSE],
        )

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=10),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    assert outcome.hits, "真实 chunk 仍应被召回"
    for hit in outcome.hits:
        assert hit.chunk_id in {chunk.id for chunk in corpus["chunks"].values()}


def test_hit_offsets_are_consistent_with_material_text(session_factory) -> None:
    """chunk 的 offset 必须能在资料规范化正文里原样取回正文。"""
    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        body = corpus["body"]
        chunk = corpus["chunks"][DOC_BOTH]
        assert body[chunk.start_offset : chunk.end_offset] == chunk.content


def test_headings_and_source_type_are_returned(session_factory) -> None:
    """结果必须带出处信息，否则前端无法做引用回跳与来源标注。"""
    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        store, keyword = build_indexes(embedder, db, corpus["material"])
        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    for hit in outcome.hits:
        assert hit.material_id == corpus["material"].id
        assert hit.source_type == "builtin"
        assert hit.index_version == "v1-test"
        assert hit.ordinal >= 0
        assert hit.score > 0


# ---------------------------------------------------------------------------
# 可检索范围：只有 ready + 当前激活版本才允许出现在结果里
# ---------------------------------------------------------------------------


def test_wrong_index_version_is_not_retrievable(session_factory) -> None:
    """索引里存在旧版本向量时，即使内容一样也不能被召回。"""
    embedder = make_embedder()
    with session_factory() as db:
        material = create_material(db, title="版本外资料", body=f"{DOC_VECTOR_ONLY}\n")
        material.active_index_version = "v2-active"
        stale = create_chunk(
            db, material, content=DOC_VECTOR_ONLY, ordinal=0, index_version="v1-stale"
        )
        db.commit()

        store = InMemoryVectorStore(embedding_model=embedder.model_name)
        record = VectorRecord(
            chunk_id=stale.id,
            material_id=material.id,
            index_version="v1-stale",
            ordinal=0,
            content=stale.content,
            heading_path=(),
            source_type=material.source_type,
        )
        store.upsert([record], embedder.encode([record.content]))
        keyword = KeywordIndex()
        keyword.rebuild([record])

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    assert outcome.hits == []


def test_not_ready_material_is_not_retrievable(session_factory) -> None:
    """status 不是 ready 的资料一律不参与检索，避免半成品资料被引用。"""
    embedder = make_embedder()
    with session_factory() as db:
        material = create_material(
            db, title="索引中资料", body=f"{DOC_VECTOR_ONLY}\n", status="indexing"
        )
        chunk = create_chunk(
            db, material, content=DOC_VECTOR_ONLY, ordinal=0, index_version="v1"
        )
        db.commit()

        store = InMemoryVectorStore(embedding_model=embedder.model_name)
        record = VectorRecord(
            chunk_id=chunk.id,
            material_id=material.id,
            index_version="v1",
            ordinal=0,
            content=chunk.content,
            heading_path=(),
            source_type=material.source_type,
        )
        store.upsert([record], embedder.encode([record.content]))
        keyword = KeywordIndex()
        keyword.rebuild([record])

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    assert outcome.hits == []


def test_stale_index_entry_is_dropped_when_database_says_otherwise(session_factory) -> None:
    """向量库陈旧时必须丢弃：宁可不返回，也不能引用一个已经不该检索的版本。"""
    embedder = make_embedder()
    with session_factory() as db:
        material = create_material(db, title="资料", body=f"{DOC_VECTOR_ONLY}\n")
        chunk = create_chunk(db, material, content=DOC_VECTOR_ONLY, ordinal=0)
        db.commit()

        # 模拟「向量库还留着这个 chunk，但数据库已把它指向别的版本」。
        store = InMemoryVectorStore(embedding_model=embedder.model_name)
        record = VectorRecord(
            chunk_id=chunk.id,
            material_id=material.id,
            index_version="v1-test",
            ordinal=0,
            content=chunk.content,
            heading_path=(),
            source_type=material.source_type,
        )
        store.upsert([record], embedder.encode([record.content]))
        keyword = KeywordIndex()
        keyword.rebuild([record])

        # 换版本但不重建索引：旧 chunk 的 index_version 与 active 不一致。
        material.active_index_version = "v2-new"
        db.commit()

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    assert outcome.hits == []


def test_filters_restrict_materials_and_source_types(session_factory) -> None:
    """显式过滤必须真正生效：指定别的资料时不能返回本资料的 chunk。"""
    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        store, keyword = build_indexes(embedder, db, corpus["material"])

        other = search_chunks(
            db,
            request=RetrievalRequest(
                query=QUERY, top_k=6, filters=SearchFilters(material_ids=(uuid4(),))
            ),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )
        assert other.hits == []

        by_user = search_chunks(
            db,
            request=RetrievalRequest(
                query=QUERY, top_k=6, filters=SearchFilters(source_types=("user",))
            ),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )
        assert by_user.hits == []

        by_builtin = search_chunks(
            db,
            request=RetrievalRequest(
                query=QUERY, top_k=6, filters=SearchFilters(source_types=("builtin",))
            ),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )
        assert by_builtin.hits


def test_no_ready_material_returns_empty(session_factory) -> None:
    """知识库为空时返回空结果，而不是抛错或返回全库内容。"""
    embedder = make_embedder()
    with session_factory() as db:
        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=InMemoryVectorStore(embedding_model=embedder.model_name),
            keyword_index=KeywordIndex(),
        )
    assert outcome.hits == []
    assert outcome.degraded is False


# ---------------------------------------------------------------------------
# 知识点过滤
# ---------------------------------------------------------------------------


def test_kp_filter_keeps_only_explicitly_linked_chunks(session_factory) -> None:
    """知识点过滤只认显式关联：没有关联的 chunk 即使内容相关也不能返回。"""
    from backend.models.learning import KnowledgePoint
    from backend.models.rag import ChunkKnowledgePoint

    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        linked = corpus["chunks"][DOC_VECTOR_ONLY]
        # 用本用例自建的知识点（code 带随机后缀）：不依赖种子数据，
        # 也不会因为别的测试改过种子而受影响。
        kp = KnowledgePoint(
            code=f"test.retrieval.kp.{uuid4().hex[:8]}",
            name="洛必达法则",
            subject="math",
            ordinal=0,
            is_assessable=True,
        )
        db.add(kp)
        db.flush()
        db.add(ChunkKnowledgePoint(chunk_id=linked.id, kp_id=kp.id, confidence=1.0))
        db.commit()

        store, keyword = build_indexes(embedder, db, corpus["material"])
        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6, kp_ids=(kp.id,)),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )

    assert [hit.chunk_id for hit in outcome.hits] == [linked.id]
    assert outcome.hits[0].kp_ids == (kp.id,)


# ---------------------------------------------------------------------------
# 降级与边界
# ---------------------------------------------------------------------------


class BrokenEmbedder:
    """模拟模型不可用：encode 直接抛 EmbeddingUnavailableError。"""

    @property
    def model_name(self) -> str:
        return "broken"

    @property
    def dimension(self) -> int:
        return 4

    def encode(self, texts):
        raise EmbeddingUnavailableError("模型不可用")


def test_embedding_failure_degrades_to_keyword_search(session_factory) -> None:
    """向量路不可用时必须降级为关键词检索，并如实报告降级原因。"""
    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        _, keyword = build_indexes(embedder, db, corpus["material"])
        store = InMemoryVectorStore(embedding_model=embedder.model_name)

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=BrokenEmbedder(),
            vector_store=store,
            keyword_index=keyword,
        )

    assert outcome.hits, "降级后仍应由关键词路返回结果"
    assert outcome.degraded is True
    assert any("embedding_unavailable" in reason for reason in outcome.degraded_reasons)
    assert outcome.vector_candidates == 0


def test_empty_keyword_index_still_uses_vector_route(session_factory) -> None:
    """关键词索引为空（例如启动后还没重建）时，向量路仍要能工作。"""
    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        store, _ = build_indexes(embedder, db, corpus["material"])

        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=KeywordIndex(),
        )

    assert outcome.hits
    assert outcome.keyword_candidates == 0


def test_blank_query_is_rejected(session_factory) -> None:
    embedder = make_embedder()
    with session_factory() as db:
        with pytest.raises(ValueError, match="empty_query"):
            search_chunks(
                db,
                request=RetrievalRequest(query="   ", top_k=6),
                embedder=embedder,
                vector_store=InMemoryVectorStore(embedding_model=embedder.model_name),
                keyword_index=KeywordIndex(),
            )


def test_candidate_k_is_clamped_to_contract_range() -> None:
    """文档契约：top_k <= candidate_k <= 50。"""
    assert MAX_CANDIDATE_K == 50
    assert clamp_candidate_k(6, 20) == 20
    assert clamp_candidate_k(6, 2) == 6
    assert clamp_candidate_k(6, 999) == 50
    with pytest.raises(ValueError, match="top_k 必须为正"):
        clamp_candidate_k(0, 20)


def test_top_k_limits_returned_hits(session_factory) -> None:
    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        store, keyword = build_indexes(embedder, db, corpus["material"])
        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=1),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
        )
    assert len(outcome.hits) == 1


def test_identity_reranker_is_default_and_does_not_degrade(session_factory) -> None:
    """默认不重排是正常配置，不是降级。"""
    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        store, keyword = build_indexes(embedder, db, corpus["material"])
        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
            reranker=IdentityReranker(),
        )
    assert outcome.degraded is False
    assert outcome.reranked is False
    assert all(hit.rerank_score is None for hit in outcome.hits)


def test_cross_encoder_uses_heading_context_and_preserves_title_rank() -> None:
    """启用重排时仍把资料名/章节路径交给模型，并保留标题路诊断名次。"""
    class StubCrossEncoder:
        pairs = None

        def predict(self, pairs):
            self.pairs = pairs
            return [0.9]

    model = StubCrossEncoder()
    reranker = CrossEncoderReranker("stub")
    reranker._model = model
    hit = RetrievalHit(
        chunk_id=uuid4(),
        material_id=uuid4(),
        material_title="阶段验收资料",
        source_type="user",
        index_version="v1",
        ordinal=0,
        content="引用帧的验收要求。",
        heading_path=("阶段 D", "引用"),
        kp_ids=(),
        score=0.03,
        fused_score=0.03,
        title_rank=2,
    )

    outcome = reranker.rerank("引用帧", [hit], top_k=1)

    assert model.pairs == [("引用帧", "阶段验收资料\n阶段 D › 引用\n引用帧的验收要求。")]
    assert outcome.hits[0].title_rank == 2
    assert outcome.hits[0].rerank_score == 0.9


def test_reranker_failure_degrades_but_still_returns_hits(session_factory) -> None:
    """重排模型不可用时，结果顺序退回融合顺序，检索本身绝不失败。"""
    from backend.retrieval.rerank import CrossEncoderReranker

    embedder = make_embedder()
    with session_factory() as db:
        corpus = build_corpus(db)
        store, keyword = build_indexes(embedder, db, corpus["material"])
        outcome = search_chunks(
            db,
            request=RetrievalRequest(query=QUERY, top_k=6),
            embedder=embedder,
            vector_store=store,
            keyword_index=keyword,
            reranker=CrossEncoderReranker("definitely-missing-reranker-model"),
        )

    assert outcome.hits, "重排失败不能导致没有结果"
    assert outcome.degraded is True
    assert any("reranker_unavailable" in reason for reason in outcome.degraded_reasons)
    assert outcome.reranked is False


def test_build_index_filter_returns_empty_tuple_when_nothing_ready(session_factory) -> None:
    """没有任何 ready 资料时，过滤条件必须是空元组（= 检索不到东西），不能是 None。"""
    with session_factory() as db:
        index_filter = build_index_filter(db)
    assert index_filter.material_ids == ()
    assert index_filter.is_empty() is True


def test_mmr_keeps_relevance_but_skips_a_near_duplicate() -> None:
    """综合问题精排后，MMR 应保留首选证据并优先补充不同内容。"""
    first = RetrievalHit(
        chunk_id=uuid4(), material_id=uuid4(), material_title="资料", source_type="user",
        index_version="v1", ordinal=0, content="首选片段", heading_path=(), kp_ids=(), score=0.9,
    )
    duplicate = RetrievalHit(
        chunk_id=uuid4(), material_id=first.material_id, material_title="资料", source_type="user",
        index_version="v1", ordinal=1, content="重复片段", heading_path=(), kp_ids=(), score=0.8,
    )
    diverse = RetrievalHit(
        chunk_id=uuid4(), material_id=first.material_id, material_title="资料", source_type="user",
        index_version="v1", ordinal=2, content="不同主题", heading_path=(), kp_ids=(), score=0.7,
    )
    embedder = FakeEmbedder(
        dimension=2,
        overrides={
            "首选片段": [1.0, 0.0],
            "重复片段": [1.0, 0.0],
            "不同主题": [0.0, 1.0],
        },
    )

    selected = mmr_select_hits([first, duplicate, diverse], top_k=2, embedder=embedder)

    assert [hit.chunk_id for hit in selected] == [first.chunk_id, diverse.chunk_id]
