"""删除被问答引用过的资料：能否成功，以及历史引用怎么处理。

为什么单独写这个文件（这是一次真实的用户可见缺陷）：
`material_service.delete_material` 里有三个约束凑在一起，让「被引用过的资料」
**永远删不掉**：

  1. `message_citations.chunk_id → document_chunks.id` 是 **NO ACTION**（无 ON DELETE）
  2. `document_chunks.material_id → materials.id` 是 **ON DELETE CASCADE**
  3. `message_citations.chunk_id` 是 **NOT NULL**

于是 `DELETE FROM materials` 会 CASCADE 去删 `document_chunks`，而分块仍被
`message_citations` 引用着 → `ForeignKeyViolation` → 接口 500。

**为什么原有 72 条 e2e 一条都没抓到**：
`frontend/e2e/materials.spec.ts` 的删除用例删的是**刚上传、从未被问答引用过**的资料，
根本不经过那条外键。「删除被引用过的资料」这条路径此前**没有任何测试覆盖**。
这正是下面每条用例都**显式造出 message_citations** 的原因 ——
不造引用，用例就还是在测同一条走不通的路径。

与重建索引那条路径是**同一个外键**：D-46 只修了「版本相同时复用块」，
删除路径当时漏了。
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import text

from backend.models import import_models

import_models()

from backend.models.chat import ChatMessage, ChatSession, MessageCitation  # noqa: E402

from tests.conftest import TEST_DATABASE_URL  # noqa: E402
from tests.materials.conftest import RAG_TABLES  # noqa: E402
from tests.retrieval.conftest import create_chunk, create_material  # noqa: E402

CHAT_TABLES = ("message_citations", "chat_messages", "chat_sessions")
ALL_TABLES = CHAT_TABLES + tuple(t for t in RAG_TABLES if t not in CHAT_TABLES)

# 正文与分块内容：`create_chunk` 要求 content 能在 normalized_text 里原样找到。
BODY = "# 洛必达法则讲义\n\n洛必达法则用于求未定式极限，使用前要确认可导条件。\n"
HIT_TEXT = "洛必达法则用于求未定式极限，使用前要确认可导条件。"


@pytest.fixture
def session_factory():
    from backend.db import create_db_engine, create_session_factory

    engine = create_db_engine(TEST_DATABASE_URL)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(session_factory) -> Iterator[None]:
    with session_factory() as db:
        db.execute(text("TRUNCATE TABLE " + ", ".join(ALL_TABLES) + " RESTART IDENTITY CASCADE"))
        db.commit()
    yield


def make_material_with_chunk(session_factory, *, title: str) -> tuple[UUID, UUID]:
    """建一份资料 + 一个分块，返回 (material_id, chunk_id)。"""
    with session_factory() as db:
        material = create_material(db, title=title, body=BODY)
        db.flush()
        chunk = create_chunk(db, material, content=HIT_TEXT, ordinal=0)
        db.flush()
        material_id, chunk_id = material.id, chunk.id
        db.commit()
    return material_id, chunk_id


def make_citation(session_factory, *, chunk_id: UUID, label: str = "[C1]") -> UUID:
    """造一条指向该分块的真实引用记录（会话 → 回答 → 引用）。

    必须真的插入 `message_citations`：这条路径的缺陷正是由它触发的，
    不造引用就等于没测。
    """
    with session_factory.begin() as db:
        session_row = ChatSession(title=f"引用过这份资料的会话{label}", mode="user")
        db.add(session_row)
        db.flush()
        message = ChatMessage(
            session_id=session_row.id,
            role="assistant",
            content=f"这个问题的依据是 {label}。",
            status="completed",
        )
        db.add(message)
        db.flush()
        citation = MessageCitation(
            message_id=message.id,
            chunk_id=chunk_id,
            label=label,
            ordinal=0,
        )
        db.add(citation)
        db.flush()
        citation_id = citation.id
    return citation_id


def count_rows(session_factory, table: str, where: str, params: dict) -> int:
    with session_factory() as db:
        return int(db.scalar(text(f"select count(*) from {table} where {where}"), params) or 0)


def test_delete_cited_material_succeeds(client, session_factory) -> None:
    """**核心回归**：被问答引用过的资料必须能删掉（此前返回 500）。"""
    material_id, chunk_id = make_material_with_chunk(session_factory, title="被引用过的资料")
    citation_id = make_citation(session_factory, chunk_id=chunk_id)

    # 前置断言：引用确实存在 —— 否则这条用例会「测不到那条路径」
    assert count_rows(session_factory, "message_citations", "id = :i", {"i": str(citation_id)}) == 1

    response = client.delete(f"/api/materials/{material_id}")

    assert response.status_code == 204, (
        "删除被引用过的资料失败；如果是 500，说明又回到外键约束那条老路："
        f"{response.text[:300]}"
    )
    assert count_rows(session_factory, "materials", "id = :i", {"i": str(material_id)}) == 0
    assert (
        count_rows(session_factory, "document_chunks", "material_id = :i", {"i": str(material_id)})
        == 0
    )


def test_delete_cited_material_clears_its_citations(client, session_factory) -> None:
    """方案 A 的语义：引用指向的来源被删了，引用本身一并清掉。

    留一条指向「已不存在来源」的引用，与产品「引用必须可核验」直接冲突。
    """
    material_id, chunk_id = make_material_with_chunk(session_factory, title="待删除的被引用资料")
    citation_id = make_citation(session_factory, chunk_id=chunk_id)

    assert client.delete(f"/api/materials/{material_id}").status_code == 204

    assert count_rows(session_factory, "message_citations", "id = :i", {"i": str(citation_id)}) == 0
    # 会话与消息本身**保留**：用户的历史回答不该因为删了一份资料而消失。
    assert count_rows(session_factory, "chat_sessions", "1 = 1", {}) == 1
    assert count_rows(session_factory, "chat_messages", "1 = 1", {}) == 1


def test_delete_uncited_material_still_works(client, session_factory) -> None:
    """没被引用过的资料照旧能删 —— 修复不能把常见路径弄坏。"""
    material_id, _ = make_material_with_chunk(session_factory, title="没人引用过的资料")

    assert client.delete(f"/api/materials/{material_id}").status_code == 204
    assert count_rows(session_factory, "materials", "id = :i", {"i": str(material_id)}) == 0


def test_deleting_one_material_keeps_citations_of_another(client, session_factory) -> None:
    """清理只针对被删资料的分块，**不能误伤别的资料**的引用。

    这是最容易写错的地方：`DELETE FROM message_citations` 如果漏了 where 条件，
    就会把整个引用表清空 —— 表面上「删除成功了」，实际毁掉了所有历史引用。
    """
    keep_material, keep_chunk = make_material_with_chunk(session_factory, title="保留的资料")
    keep_citation = make_citation(session_factory, chunk_id=keep_chunk, label="[C1]")

    doomed_material, doomed_chunk = make_material_with_chunk(session_factory, title="要删的资料")
    doomed_citation = make_citation(session_factory, chunk_id=doomed_chunk, label="[C1]")

    assert client.delete(f"/api/materials/{doomed_material}").status_code == 204

    assert (
        count_rows(session_factory, "message_citations", "id = :i", {"i": str(keep_citation)}) == 1
    ), "误删了别的资料的引用"
    assert (
        count_rows(session_factory, "message_citations", "id = :i", {"i": str(doomed_citation)})
        == 0
    )
    assert count_rows(session_factory, "document_chunks", "id = :i", {"i": str(keep_chunk)}) == 1
    assert count_rows(session_factory, "materials", "id = :i", {"i": str(keep_material)}) == 1


# ---------------------------------------------------------------------------
# 真实路径：上传 → 提问并拿到引用 → 再删除
#
# 上面几条是**直接造** message_citations 来覆盖删除逻辑；这一条走真实问答链路
# （真实检索栈 + 假 provider），让引用由问答流程自己落库 —— 缺陷报告特别要求如此，
# 因为「不造引用就等于没测到那条路径」，而那正是原有用例的失误。
# ---------------------------------------------------------------------------


class _FakeEmbedder:
    """确定性假 embedder：相同文本 → 相同向量。"""

    def __init__(self) -> None:
        self._cache: dict[str, list[float]] = {}

    @property
    def model_name(self) -> str:
        return "fake-embedder-for-delete-test"

    @property
    def dimension(self) -> int:
        return 8

    def encode(self, texts):  # type: ignore[no-untyped-def]
        out = []
        for text in texts:
            if text not in self._cache:
                vector = [0.0] * 8
                for index, char in enumerate(text[:8]):
                    vector[index] = float(ord(char) % 97) + 1.0
                norm = sum(v * v for v in vector) ** 0.5 or 1.0
                self._cache[text] = [v / norm for v in vector]
            out.append(list(self._cache[text]))
        return out


@pytest.fixture
def stack():
    """真实检索栈：假 embedder + 内存向量库 + 真实关键词索引。

    关键词索引是真的 —— 引用能否产生取决于检索是否命中，这一层不替身。
    """
    from backend.retrieval.keyword import KeywordIndex
    from backend.retrieval.vector_store import InMemoryVectorStore

    class _Stack:
        def __init__(self) -> None:
            self.embedder = _FakeEmbedder()
            self.vector_store = InMemoryVectorStore(embedding_model=self.embedder.model_name)
            self.keyword_index = KeywordIndex()
            self.reranker = None

    return _Stack()


class _FixedProvider:
    """输出固定文本的 provider 替身（不消耗真实模型额度、输出可复现）。

    只实现 `answer()` 需要的那部分协议；`Provider` 基类不调用，因为那需要真实凭据。
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self._text, {"prompt_tokens": 1, "completion_tokens": 1}


def test_citation_from_real_qa_is_deletable(client, session_factory, stack) -> None:
    """**真实路径**：问答产生引用 → 删除该资料必须成功（此前 500）。

    走真实 `answer()`，引用由问答流程自己写进 `message_citations`，
    而不是测试直接插一条 —— 这样测到的才是用户真实走的那条路。
    """
    from backend.chat.service import answer as chat_answer
    from backend.retrieval.protocols import VectorRecord

    with session_factory() as db:
        material = create_material(db, title="被问答引用过的资料", body=BODY, index_version="v1-test")
        chunk = create_chunk(db, material, content=HIT_TEXT, ordinal=0, index_version="v1-test")
        db.commit()
        material_id, chunk_id = material.id, chunk.id

    # 让检索层能找到它：向量库与关键词索引都要有。
    record = VectorRecord(
        chunk_id=chunk_id,
        material_id=material_id,
        index_version="v1-test",
        ordinal=0,
        content=HIT_TEXT,
        heading_path=(),
        source_type="builtin",
    )
    stack.vector_store.upsert([record], stack.embedder.encode([HIT_TEXT]))
    stack.keyword_index.rebuild([record])

    with session_factory.begin() as db:
        session_row = ChatSession(title="真实提问的会话", mode="builtin")
        db.add(session_row)
        db.flush()
        session_id = session_row.id

    provider = _FixedProvider("依据资料 [C1]，需要先判断未定式类型。")
    message, citations, _ = chat_answer(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
    )

    # 前置断言：问答确实产生了落库的引用 —— 否则这条用例又"测不到那条路径"
    assert provider.calls == 1, "provider 没被调用，问答路径没走通"
    assert citations, "问答没有产生引用，用例无法覆盖目标路径"
    assert (
        count_rows(session_factory, "message_citations", "message_id = :m", {"m": str(message.id)})
        >= 1
    ), "引用没有落库"

    # 核心断言：这份**真实被引用过**的资料必须能删掉。
    response = client.delete(f"/api/materials/{material_id}")
    assert response.status_code == 204, (
        "删除被问答引用过的资料失败；若为 500，说明又回到外键约束那条老路："
        f"{response.text[:300]}"
    )
    assert count_rows(session_factory, "materials", "id = :i", {"i": str(material_id)}) == 0
    assert (
        count_rows(session_factory, "message_citations", "message_id = :m", {"m": str(message.id)})
        == 0
    )
    # 历史回答保留：删资料不该让用户的回答消失。
    assert count_rows(session_factory, "chat_messages", "id = :i", {"i": str(message.id)}) == 1

