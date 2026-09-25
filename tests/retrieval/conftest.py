"""检索层测试的共享夹具。

这些测试打真实 PostgreSQL（kaoyan_test）：检索的正确性一半取决于
「哪些 chunk 允许被召回」，那部分是数据库状态决定的，用 mock 会测不到真问题。
向量库与 embedding 则使用可控替身 —— 检索链路的接线必须能在没有模型的环境里验证。
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.ingestion.text_normalize import material_content_hash, normalize_text
from backend.models.rag import ChunkKnowledgePoint, DocumentChunk, Material
from backend.retrieval.embedding import FakeEmbedder
from backend.retrieval.vector_store import InMemoryVectorStore

from tests.conftest import TEST_DATABASE_URL

# 这些表由本目录的测试独占；清空顺序遵循外键依赖。
RAG_TABLES = ("chunk_knowledge_points", "document_chunks", "materials")

# 本目录的用例会**自建知识点**（`test.retrieval.kp.<随机后缀>`），
# 用来验证 kp 过滤，且刻意不依赖种子数据。
#
# 为什么必须在这里清掉它们：原先只 TRUNCATE RAG_TABLES（不含 knowledge_points），
# 于是每跑一次 pytest，测试库就多留一个可考核叶子。跑一次没事，
# 但 e2e 打的是**同一个测试库**，它的知识树用例断言「叶子恰好 5 个」——
# 被这种残留顶到 6 个就会失败，而且看起来像前端 bug、极难归因。
#
# 用 `test.` 前缀而不是 `test.retrieval.`：这个约定是「所有测试自建数据都以 test. 开头」，
# 一并清掉同类的残留更彻底，且绝不会碰到种子知识点（math.* / 手工建的）。
TEST_KP_CODE_PREFIX = "test."


@pytest.fixture
def session_factory():
    from backend.db import create_db_engine, create_session_factory

    engine = create_db_engine(TEST_DATABASE_URL)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_rag_tables(session_factory) -> Iterator[None]:
    """清空资料相关表：每个用例从空知识库开始，避免上一个用例的资料被召回。

    同时清掉**本目录自建的知识点**（`test.` 前缀）：
    它们不属于种子数据，留着会污染同一个测试库上的 e2e（见上面常量的说明）。
    """
    with session_factory() as db:
        db.execute(
            text("TRUNCATE TABLE " + ", ".join(RAG_TABLES) + " RESTART IDENTITY CASCADE")
        )
        db.execute(
            text("DELETE FROM knowledge_points WHERE code LIKE :prefix"),
            {"prefix": f"{TEST_KP_CODE_PREFIX}%"},
        )
        db.commit()
    yield
    # 用例结束后再清一次：本条用例自建的 kp 不该留给下一个用例，
    # 更不该留给 pytest 之后才跑的 e2e。
    with session_factory() as db:
        db.execute(
            text("DELETE FROM knowledge_points WHERE code LIKE :prefix"),
            {"prefix": f"{TEST_KP_CODE_PREFIX}%"},
        )
        db.commit()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder(dimension=64)


@pytest.fixture
def vector_store(embedder: FakeEmbedder) -> InMemoryVectorStore:
    return InMemoryVectorStore(embedding_model=embedder.model_name)


# ------------------------------------------------------------------ 造数据助手


def create_material(
    session,
    *,
    title: str,
    body: str,
    source_type: str = "builtin",
    status: str = "ready",
    index_version: str | None = "v1-test",
) -> Material:
    """建一份资料并写入规范化正文；index_version=None 表示还没建立索引。"""
    normalized = normalize_text(body)
    material = Material(
        id=uuid4(),
        title=title,
        source_type=source_type,
        original_filename=None,
        stored_path=f"{uuid4()}/source.md",
        normalized_text=normalized,
        content_hash=material_content_hash(normalized),
        raw_hash=material_content_hash(normalized),
        file_size=len(normalized.encode("utf-8")),
        status=status,
        active_index_version=index_version if status == "ready" else None,
    )
    session.add(material)
    session.flush()
    return material


def create_chunk(
    session,
    material: Material,
    *,
    content: str,
    ordinal: int,
    heading_path: tuple[str, ...] = (),
    index_version: str | None = None,
    kp_ids: tuple = (),
) -> DocumentChunk:
    """建一个 chunk；content 必须能在 normalized_text 里原样找到，保持 offset 自洽。"""
    version = index_version or material.active_index_version or "v1-test"
    text_body = material.normalized_text or ""
    start = text_body.find(content)
    if start < 0:
        raise AssertionError(f"chunk 正文不在资料规范化文本里：{content!r}")
    chunk = DocumentChunk(
        id=uuid4(),
        material_id=material.id,
        index_version=version,
        ordinal=ordinal,
        content=content,
        start_offset=start,
        end_offset=start + len(content),
        heading_path=list(heading_path),
        content_hash="0" * 64,
        kp_hint_code=None,
    )
    session.add(chunk)
    session.flush()
    for kp_id in kp_ids:
        session.add(ChunkKnowledgePoint(chunk_id=chunk.id, kp_id=kp_id, confidence=1.0))
    session.flush()
    return chunk