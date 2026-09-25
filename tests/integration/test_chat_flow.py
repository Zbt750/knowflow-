"""问答流程集成测试（契约要求的 tests/integration/test_chat_flow.py）。

用**真实数据库 + 真实检索栈 + 假 provider**：
- 真实数据库与检索是必须的 —— 引用校验、matched_kp、状态落库都依赖它们；
- provider 用替身是因为真实模型慢、消耗额度、输出不可复现。
  用假 provider 才能稳定断言「无引用时怎么办」「引用不在本次命中时怎么办」。

假 provider 的替换方式：`answer()` / `stream_answer()` 的 provider 是参数，
直接从测试传入即可，不需要 monkeypatch 内部实现。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select, text

from backend.chat.service import (
    Provider,
    answer,
    prepare_answer,
    require_active_session,
    stream_answer,
)
from backend.errors import AppError
from backend.models import import_models

import_models()

from backend.models.chat import ChatMessage, ChatSession, MessageCitation  # noqa: E402
from backend.models.learning import LearningEvent  # noqa: E402
from backend.models.rag import Material  # noqa: E402

from tests.conftest import TEST_DATABASE_URL  # noqa: E402
from tests.materials.conftest import RAG_TABLES  # noqa: E402
from tests.retrieval.conftest import create_chunk, create_material  # noqa: E402

CHAT_TABLES = ("message_citations", "chat_messages", "chat_sessions")

# 一份内容可通过关键词命中的资料。
BODY = (
    "# 极限\n\n"
    "## 洛必达法则\n\n"
    "洛必达法则用于处理 0/0 型与无穷比无穷型未定式，使用前必须判断未定式类型。\n\n"
    "## 等价无穷小\n\n"
    "在加减结构中不能直接替换等价无穷小，因为会发生高阶抵消。\n"
)
HIT_TEXT = "洛必达法则用于处理 0/0 型与无穷比无穷型未定式，使用前必须判断未定式类型。"


class FakeProvider(Provider):
    """可控制输出的 provider 替身。"""

    def __init__(self, text: str = "依据资料，需要先判断未定式类型 [C1]。") -> None:
        # 不调用父类构造：这里不需要 api_key / 真实端点。
        self._text = text
        self.calls = 0

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self._text, {"prompt_tokens": 1, "completion_tokens": 1}

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        # 逐字吐出，模拟真实流式。
        for char in self._text:
            yield char


class BrokenProvider(Provider):
    """总是失败的 provider：验证失败路径。

    注意异常类型必须是 AppError 之外的真实异常，
    这样才检验得到「provider 抛错时编排层怎么收尾」。
    """

    def __init__(self) -> None:
        pass

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        raise AppError("generation_failed", detail="simulated")

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        raise AppError("generation_failed", detail="simulated")
        yield ""  # pragma: no cover - 让它是异步生成器


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
    """清空 chat 与资料相关表；chat 表有外键指向 materials。"""
    with session_factory() as db:
        db.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(CHAT_TABLES + tuple(t for t in RAG_TABLES if t not in CHAT_TABLES))
                + " RESTART IDENTITY CASCADE"
            )
        )
        db.commit()
    yield


@pytest.fixture
def stack(embedder):
    """真实检索栈（真实向量库 + 关键词索引），只有 embedding 是可控替身。"""
    from backend.retrieval.keyword import KeywordIndex
    from backend.retrieval.rerank import IdentityReranker
    from backend.retrieval.stack import RetrievalStack
    from backend.retrieval.vector_store import InMemoryVectorStore

    return RetrievalStack(
        embedder=embedder,
        vector_store=InMemoryVectorStore(embedding_model=embedder.model_name),
        keyword_index=KeywordIndex(),
        reranker=IdentityReranker(),
    )


@pytest.fixture
def embedder():
    from backend.retrieval.embedding import FakeEmbedder

    return FakeEmbedder(dimension=64)


def seed_builtin_material(session_factory, stack) -> None:
    """建一份内置资料、写入分块，并让它进向量库与关键词索引。"""
    from backend.retrieval.protocols import VectorRecord

    with session_factory() as db:
        material = create_material(
            db, title="极限讲义", body=BODY, source_type="builtin", index_version="v1-test"
        )
        chunk = create_chunk(
            db,
            material,
            content=HIT_TEXT,
            ordinal=0,
            heading_path=("极限", "洛必达法则"),
            index_version="v1-test",
        )
        db.commit()
        material_id, chunk_id = material.id, chunk.id

    # 让检索层能找到它（fake embedder 下用同一段文本即可命中关键词路）。
    record = VectorRecord(
        chunk_id=chunk_id,
        material_id=material_id,
        index_version="v1-test",
        ordinal=0,
        content=HIT_TEXT,
        heading_path=("极限", "洛必达法则"),
        source_type="builtin",
    )
    stack.vector_store.upsert([record], stack.embedder.encode([HIT_TEXT]))
    stack.keyword_index.rebuild([record])


def make_session(session_factory, *, mode: str = "builtin") -> str:
    with session_factory.begin() as db:
        row = ChatSession(title="新对话", mode=mode)
        db.add(row)
        db.flush()
        return str(row.id)


@pytest.mark.parametrize(
    ("question", "expected_top_k", "expected_candidates", "expected_diversify"),
    [
        ("什么是洛必达法则", 8, 24, False),
        ("为什么洛必达法则使用前要判断未定式", 12, 36, False),
        ("列举洛必达法则的适用场景", 16, 48, True),
    ],
)
def test_chat_retrieval_uses_intent_based_plan(
    session_factory,
    stack,
    monkeypatch,
    question: str,
    expected_top_k: int,
    expected_candidates: int,
    expected_diversify: bool,
) -> None:
    """普通聊天按问题意图切换证据量，综合问题额外请求去重。"""
    from types import SimpleNamespace
    from uuid import UUID

    import backend.chat.service as chat_service

    captured = {}

    def capture_search(_db, *, request, **_kwargs):
        captured["request"] = request
        return SimpleNamespace(hits=[])

    monkeypatch.setattr(chat_service, "search_chunks", capture_search)
    session_id = make_session(session_factory)
    with session_factory() as db:
        prepare_answer(
            db,
            session_id=UUID(session_id),
            question=question,
            stack=stack,
        )

    request = captured["request"]
    assert request.top_k == expected_top_k
    assert request.candidate_k == expected_candidates
    assert request.diversify is expected_diversify


def messages_of(session_factory, session_id: str) -> list[ChatMessage]:
    from uuid import UUID

    with session_factory() as db:
        return list(
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == UUID(session_id))
                .order_by(ChatMessage.seq)
            ).all()
        )


# ---------------------------------------------------------------------------
# 无命中：不调用模型、不产生引用、不写学习事件
# ---------------------------------------------------------------------------


def test_no_hit_refuses_without_calling_provider(session_factory, stack) -> None:
    """知识库里没有相关内容时：明确拒答，且**不调用 provider**。

    这条曾经偶发失败（只在完整套件里，单独跑必过），而且报错只有一句
    `assert 1 == 0`，完全看不出命中了什么。既然它依赖「检索必须无命中」，
    失败就一定是**测试库或索引里还有东西**，所以这里主动把命中打出来 ——
    下次偶发时能直接判断是留给上一个用例的残留，还是别的原因。
    """
    from uuid import UUID

    from backend.retrieval.protocols import RetrievalRequest, SearchFilters
    from backend.services.retrieval_service import search_chunks

    session_id = make_session(session_factory)
    provider = FakeProvider()
    question = "完全无关的问题：如何用 Python 读取 CSV？"

    # 先单独跑一次检索：命中列表为空才是这条用例成立的前提。
    # 把它当作显式前置条件来断言，失败信息里带上命中详情。
    with session_factory() as probe:
        outcome = search_chunks(
            probe,
            request=RetrievalRequest(
                query=question, top_k=8, candidate_k=24, filters=SearchFilters(source_types=("builtin",))
            ),
            embedder=stack.embedder,
            vector_store=stack.vector_store,
            keyword_index=stack.keyword_index,
            reranker=stack.reranker,
        )
    assert not outcome.hits, (
        "前提不成立：这个「无关问题」本应零命中，却召回了资料 —— "
        "说明测试库里留有上一轮的资料（或索引未清空）。"
        f"命中={[(str(hit.material_id), (hit.heading_path or ('<无标题>',))[0], round(hit.score, 4)) for hit in outcome.hits]}"
    )

    message, citations, _ = answer(
        session_factory,
        session_id=UUID(session_id),
        question=question,
        stack=stack,
        provider=provider,
    )

    assert provider.calls == 0, "无命中时不得调用模型（既省钱也避免编造）"
    assert citations == []
    assert message.status == "completed"
    assert "没有找到" in message.content or "资料" in message.content
    # 拒答也不该产生学习事件
    with session_factory() as db:
        assert db.scalars(select(LearningEvent)).all() == []


def test_no_hit_still_persists_user_and_assistant_rows(session_factory, stack) -> None:
    """拒答也要留下完整的两条消息（用户问过什么必须可追溯）。"""
    session_id = make_session(session_factory)
    answer(
        session_factory,
        session_id=__import__("uuid").UUID(session_id),
        question="完全无关的问题",
        stack=stack,
        provider=FakeProvider(),
    )
    rows = messages_of(session_factory, session_id)
    assert [row.role for row in rows] == ["user", "assistant"]
    assert all(row.status == "completed" for row in rows)


def test_named_file_overview_includes_all_chunks_and_heading_context(session_factory, stack) -> None:
    """点名一份中小型资料作概览时，证据应覆盖全文件而不是固定取 4 块。"""
    from uuid import UUID

    session_id = make_session(session_factory, mode="user")
    body = (
        "# 阶段验收\n\n阶段 A 负责项目基础结构和运行环境。\n\n"
        "## 阶段 D\n\n阶段 D 验收流式回答、引用帧和资料定位。\n"
    )
    with session_factory.begin() as db:
        material = create_material(
            db, title="阶段验收资料", body=body, source_type="user", index_version="v1-test"
        )
        material.original_filename = "验收.md"
        first = create_chunk(
            db, material, content="阶段 A 负责项目基础结构和运行环境。", ordinal=0,
            heading_path=("阶段验收",),
        )
        second = create_chunk(
            db, material, content="阶段 D 验收流式回答、引用帧和资料定位。", ordinal=1,
            heading_path=("阶段验收", "阶段 D"),
        )

    with session_factory() as db:
        prepared = prepare_answer(
            db,
            session_id=UUID(session_id),
            question="请把验收.md所有内容简要说明。",
            stack=stack,
        )

    evidence = prepared.prompt[1]["content"]
    assert set(prepared.citation_map.values()) == {first.id, second.id}
    assert "阶段验收资料" in evidence
    assert "阶段验收 › 阶段 D" in evidence
    assert "阶段 A 负责项目基础结构和运行环境。" in evidence
    assert "阶段 D 验收流式回答、引用帧和资料定位。" in evidence


def test_single_file_overview_under_generic_reference_covers_all_chunks(session_factory, stack) -> None:
    """我的资料范围只有一份文件时，「那份文件说的内容」应概述全文件。"""
    from uuid import UUID

    session_id = make_session(session_factory, mode="user")
    with session_factory.begin() as db:
        material = create_material(
            db,
            title="阶段验收资料",
            body="阶段 A 负责项目基础结构和运行环境。\n\n阶段 D 验收流式回答、引用帧和资料定位。",
            source_type="user",
            index_version="v1-test",
        )
        material.original_filename = "验收.md"
        first = create_chunk(
            db, material, content="阶段 A 负责项目基础结构和运行环境。", ordinal=0,
            heading_path=("阶段验收",),
        )
        second = create_chunk(
            db, material, content="阶段 D 验收流式回答、引用帧和资料定位。", ordinal=1,
            heading_path=("阶段验收", "阶段 D"),
        )

    with session_factory() as db:
        prepared = prepare_answer(
            db,
            session_id=UUID(session_id),
            question="那份文件说的内容大概是什么？",
            stack=stack,
        )

    assert set(prepared.citation_map.values()) == {first.id, second.id}
    evidence = prepared.prompt[1]["content"]
    assert "阶段 A 负责项目基础结构和运行环境。" in evidence
    assert "阶段 D 验收流式回答、引用帧和资料定位。" in evidence


def test_detailed_followup_uses_recently_named_file_and_includes_every_chunk(
    session_factory, stack
) -> None:
    """后续问题省略文件名时，按最近用户消息定位全文，并覆盖每个阶段。"""
    from uuid import UUID

    session_id = make_session(session_factory, mode="user")
    with session_factory.begin() as db:
        acceptance = create_material(
            db,
            title="验收资料",
            body="阶段 A 完成基础连通。\n阶段 B 完成学习记录。\n阶段 D 完成引用定位。",
            source_type="user",
            index_version="v1-acceptance",
        )
        acceptance.original_filename = "验收.md"
        acceptance_chunks = [
            create_chunk(
                db,
                acceptance,
                content=content,
                ordinal=index,
                heading_path=(f"阶段 {letter}",),
                index_version="v1-acceptance",
            )
            for index, (letter, content) in enumerate(
                [
                    ("A", "阶段 A 完成基础连通。"),
                    ("B", "阶段 B 完成学习记录。"),
                    ("D", "阶段 D 完成引用定位。"),
                ]
            )
        ]
        unrelated = create_material(
            db,
            title="数学讲义",
            body="导数的定义与几何意义。",
            source_type="user",
            index_version="v1-math",
        )
        unrelated_chunk = create_chunk(
            db,
            unrelated,
            content="导数的定义与几何意义。",
            ordinal=0,
            index_version="v1-math",
        )
        db.add(
            ChatMessage(
                session_id=UUID(session_id),
                role="user",
                content="验收.md 文件大概说了什么？",
                status="completed",
            )
        )
        db.flush()
        db.add(
            ChatMessage(
                session_id=UUID(session_id),
                role="assistant",
                content="它介绍了阶段 A、B 和 D。",
                status="completed",
            )
        )

    with session_factory() as db:
        prepared = prepare_answer(
            db,
            session_id=UUID(session_id),
            question="每一个阶段都给我细讲一下",
            stack=stack,
        )

    assert set(prepared.citation_map.values()) == {chunk.id for chunk in acceptance_chunks}
    assert unrelated_chunk.id not in prepared.citation_map.values()
    evidence = prepared.prompt[1]["content"]
    assert all(chunk.content in evidence for chunk in acceptance_chunks)
    assert "【本次回答：详细完整】" in prepared.prompt[0]["content"]
    assert "不得只回答第一项后停下" in prepared.prompt[0]["content"]


def test_builtin_mode_does_not_search_for_personal_file(session_factory, stack) -> None:
    """误在内置模式问到个人文件时立即提示切换，不调用 embedding 或 LLM。"""
    from uuid import UUID

    session_id = make_session(session_factory, mode="builtin")
    with session_factory.begin() as db:
        material = create_material(
            db,
            title="阶段验收资料",
            body="这是用户上传的验收文件。",
            source_type="user",
            index_version="v1-user",
        )
        material.original_filename = "验收.md"
        create_chunk(db, material, content="这是用户上传的验收文件。", ordinal=0)

    provider = FakeProvider()
    before = list(stack.embedder.encode_calls)
    message, citations, _ = answer(
        session_factory,
        session_id=UUID(session_id),
        question="那份文件说的内容大概是什么？",
        stack=stack,
        provider=provider,
    )

    assert "内置资料" in message.content and "我的资料" in message.content
    assert citations == []
    assert provider.calls == 0
    assert stack.embedder.encode_calls == before


def test_standalone_greeting_does_not_retrieve_random_document_evidence(session_factory, stack) -> None:
    """独立问候语不属于资料问题，不应拿随机命中片段喂给模型。"""
    from uuid import UUID

    seed_builtin_material(session_factory, stack)

    session_id = make_session(session_factory, mode="builtin")
    provider = FakeProvider()
    message, citations, _ = answer(
        session_factory,
        session_id=UUID(session_id),
        question="你好！",
        stack=stack,
        provider=provider,
    )

    assert provider.calls == 0
    assert citations == []
    assert "资料" in message.content


# ---------------------------------------------------------------------------
# 命中：引用落库、matched_kp、来源字段完整
# ---------------------------------------------------------------------------


def test_hit_persists_citations_with_label_and_chunk(session_factory, stack) -> None:
    seed_builtin_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = FakeProvider("依据资料 [C1]，需要先判断未定式类型。")

    message, citations, _ = answer(
        session_factory,
        session_id=__import__("uuid").UUID(session_id),
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
    )

    assert provider.calls == 1
    assert message.status == "completed"
    assert isinstance(message.metadata_["response_duration_ms"], int)
    assert message.metadata_["response_duration_ms"] >= 0
    assert [label for label, _ in citations] == ["C1"]

    from uuid import UUID

    with session_factory() as db:
        rows = db.scalars(
            select(MessageCitation).where(MessageCitation.message_id == message.id)
        ).all()
    assert len(rows) == 1
    assert rows[0].label == "C1"
    assert rows[0].ordinal == 1
    # chunk_id 必须是真实存在的 canonical chunk
    assert rows[0].chunk_id is not None


def test_unknown_citation_label_is_recorded_but_not_a_source(session_factory, stack) -> None:
    """模型写 [C99]：正文保留、来源不含它、metadata 记录它。"""
    seed_builtin_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = FakeProvider("依据 [C1] 与 [C99]。")

    message, citations, _ = answer(
        session_factory,
        session_id=__import__("uuid").UUID(session_id),
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
    )

    assert [label for label, _ in citations] == ["C1"]
    metadata = message.metadata_ or {}
    assert metadata.get("unknown_citation_labels") == ["C99"]


def test_answer_without_any_citation_is_not_a_failure(session_factory, stack) -> None:
    """模型没写引用时：回答仍然可用，只在 metadata 记一个待排查信号。

    这是契约要求：把「模型忘了引用」当成生成失败，会丢掉一次可用的回答，
    也会让用户看到与事实不符的错误。
    """
    seed_builtin_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = FakeProvider("根据资料，需要先判断未定式类型。")

    message, citations, _ = answer(
        session_factory,
        session_id=__import__("uuid").UUID(session_id),
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
    )

    assert message.status == "completed"
    assert citations == []
    assert (message.metadata_ or {}).get("citation_warning") == "no_valid_citation"


# ---------------------------------------------------------------------------
# 模式隔离与失败收尾
# ---------------------------------------------------------------------------


def test_user_mode_does_not_search_builtin_material(session_factory, stack) -> None:
    """模式隔离：`user` 会话只检索用户资料，内置资料不得被搜到。"""
    seed_builtin_material(session_factory, stack)
    session_id = make_session(session_factory, mode="user")
    provider = FakeProvider()

    _, citations, _ = answer(
        session_factory,
        session_id=__import__("uuid").UUID(session_id),
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
    )

    assert citations == [], "user 模式不得引用内置资料"
    assert provider.calls == 0


def test_provider_failure_marks_message_failed(session_factory, stack) -> None:
    """模型失败：消息必须是 failed，不能永久停在 generating。"""
    seed_builtin_material(session_factory, stack)
    session_id = make_session(session_factory)

    with pytest.raises(AppError):
        answer(
            session_factory,
            session_id=__import__("uuid").UUID(session_id),
            question="洛必达法则用于处理什么类型的未定式？",
            stack=stack,
            provider=BrokenProvider(),
        )

    rows = messages_of(session_factory, session_id)
    assistant = [row for row in rows if row.role == "assistant"]
    assert assistant and assistant[-1].status == "failed"


def test_ask_on_missing_session_returns_404_code(session_factory, stack) -> None:
    from uuid import uuid4

    with session_factory() as db:
        with pytest.raises(AppError) as captured:
            require_active_session(db, uuid4())
    assert captured.value.code == "chat_session_not_found"
    assert captured.value.status_code == 404


def test_ask_on_archived_session_is_rejected(session_factory, stack) -> None:
    """归档会话禁止继续写消息（契约）。"""
    from datetime import datetime, timezone
    from uuid import UUID

    session_id = make_session(session_factory)
    with session_factory.begin() as db:
        row = db.get(ChatSession, UUID(session_id))
        assert row is not None
        row.archived_at = datetime.now(timezone.utc)

    with pytest.raises(AppError) as captured:
        answer(
            session_factory,
            session_id=UUID(session_id),
            question="任何问题",
            stack=stack,
            provider=FakeProvider(),
        )
    assert captured.value.code == "chat_session_not_found"


def test_prepare_answer_creates_placeholder_before_search(session_factory, stack) -> None:
    """两段短事务的第一段：先落 user + assistant(generating) 占位。"""
    from uuid import UUID

    seed_builtin_material(session_factory, stack)
    session_id = make_session(session_factory)

    # 注意：`prepare_answer` 接收的是 Session（而不是 sessionmaker），
    # 因为它本身就是「一次短事务」的入口；`answer()` 才负责管理多次事务。
    with session_factory() as db:
        prepared = prepare_answer(
            db,
            session_id=UUID(session_id),
            question="洛必达法则用于处理什么类型的未定式？",
            stack=stack,
        )
    assert prepared.assistant_id is not None

    # 占位必须先于检索结果存在，且状态是 generating
    rows = messages_of(session_factory, session_id)
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[-1].status == "generating"
    assert rows[-1].id == prepared.assistant_id


class AttemptRecordingProvider(Provider):
    """记录每次调用收到的 attempt，用来验证重试确实换了预算。

    为什么值得单独测：`Provider` 只在 `attempt > 1` 时才使用加大的预算。
    如果调用方漏传 `attempt`（默认值 1），重试就会用**同样的**小预算，
    行为上退回「原样重试」—— 而那是实测下来救不回空回答的做法。
    这个错误不会报错、也不会让任何断言失败，只能靠显式检查 attempt 抓到。
    """

    def __init__(self, text: str = "依据资料 [C1]。") -> None:
        self._text = text
        self.attempts: list[int] = []
        self.calls = 0

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.attempts.append(attempt)
        if attempt == 1:
            # 首轮空回答：触发「以更大预算重试一次」。
            return "", {"prompt_tokens": 1}
        return self._text, {"prompt_tokens": 1, "completion_tokens": 1}

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.attempts.append(attempt)
        if attempt == 1:
            return
        for char in self._text:
            yield char


def test_retry_uses_a_larger_output_budget(session_factory, stack) -> None:
    """非流式重试必须把 attempt=2 传下去，否则重试等于原样再赌一次。"""
    from uuid import UUID

    seed_builtin_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = AttemptRecordingProvider()

    message, _, _ = answer(
        session_factory,
        session_id=UUID(session_id),
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
    )

    assert provider.attempts == [1, 2], "首次 attempt=1，重试 attempt=2"
    assert message.content == "依据资料 [C1]。"


def test_provider_budget_grows_only_on_retry() -> None:
    """`Provider` 的预算语义：首轮用基础预算，重试才切到更大预算。"""
    provider = Provider(
        api_key="k",
        base_url="http://127.0.0.1:9",
        model="m",
        timeout=1.0,
        max_tokens=4000,
        retry_max_tokens=8000,
    )
    assert provider._token_budget(1) == 4000
    assert provider._token_budget(2) == 8000


def test_retry_budget_never_shrinks() -> None:
    """写反配置（重试预算更小）时不得让重试比首次还紧张。"""
    provider = Provider(
        api_key="k",
        base_url="http://127.0.0.1:9",
        model="m",
        timeout=1.0,
        max_tokens=4000,
        retry_max_tokens=100,
    )
    assert provider._token_budget(2) == 4000, "重试预算不得小于基础预算"


class ClarifyingProvider(Provider):
    """模拟「追问引导」生效后的回复：只反问一句，**不带任何 [C#] 引用**。

    提示词里已经明确要求「即使只是澄清问题、只讲一步、换一种讲法，也必须带 [C#] 引用」，
    但提示词是**软约束** —— 模型仍可能省掉引用。
    真正要保证的是：万一它省了，链路也不能崩、更不能凭空造一个来源出来。
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self._text, {"prompt_tokens": 1}

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        for char in self._text:
            yield char


def test_clarifying_answer_without_citation_is_not_a_failure(session_factory, stack) -> None:
    """模型只回一句澄清问句、忘了引用时：回答保留、来源为空、绝不伪造。"""
    from uuid import UUID

    seed_builtin_material(session_factory, stack)
    session_id = make_session(session_factory)
    clarifying = "你问的是 0/0 型还是无穷比无穷型？两种的处理不一样。"
    provider = ClarifyingProvider(clarifying)

    message, citations, _ = answer(
        session_factory,
        session_id=UUID(session_id),
        question="洛必达法则什么时候能用？",
        stack=stack,
        provider=provider,
    )

    # 1) 追问式回答本身是有用的，不能因为它没引用就判失败
    assert message.status == "completed"
    assert message.content == clarifying
    # 2) 但**绝不能**因此凭空造出一个来源
    assert citations == [], "模型没引用时不得伪造来源"
    # 3) 要有可排查的信号：这次有命中却没落地任何引用
    assert message.metadata_.get("citation_warning") == "no_valid_citation"


def test_clarifying_answer_still_attributes_when_hits_support_it(session_factory, stack) -> None:
    """追问式回答只要引用带上了，归因与引用都必须照常工作。

    防止「引入追问引导」把引用的整条链路一起改坏。
    """
    from uuid import UUID

    seed_builtin_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = ClarifyingProvider("你问的是哪种未定式？[C1] 资料里区分了 0/0 型与无穷比无穷型。")

    message, citations, _ = answer(
        session_factory,
        session_id=UUID(session_id),
        question="洛必达法则什么时候能用？",
        stack=stack,
        provider=provider,
    )

    assert message.status == "completed"
    assert [label for label, _ in citations] == ["C1"]
    assert message.metadata_.get("citation_warning") is None
    with session_factory() as db:
        rows = db.scalars(
            select(MessageCitation).where(MessageCitation.message_id == message.id)
        ).all()
    assert len(rows) == 1, "引用必须真的落库"
