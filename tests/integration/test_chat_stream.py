"""SSE 流式问答集成测试（契约要求的 tests/integration/test_chat_stream.py）。

契约 D-02 的帧序：`meta → delta… → citations → done`；异常时以 `error` 收尾。
`delta.seq` 必须从 1 递增。

用假 provider 驱动真实数据库：这样才能稳定构造
「正常完成」「取消（客户端断开）」「模型失败」三种收尾，
而真实模型无法可靠复现这些边界。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy import select, text

from backend.chat import service as chat_service
from backend.chat.service import Provider, encode_sse, stream_answer
from backend.errors import AppError
from backend.models import import_models

import_models()

from backend.models.chat import ChatMessage, ChatSession, MessageCitation  # noqa: E402
from backend.retrieval.embedding import FakeEmbedder  # noqa: E402
from backend.retrieval.keyword import KeywordIndex  # noqa: E402
from backend.retrieval.protocols import VectorRecord  # noqa: E402
from backend.retrieval.rerank import IdentityReranker  # noqa: E402
from backend.retrieval.stack import RetrievalStack  # noqa: E402
from backend.retrieval.vector_store import InMemoryVectorStore  # noqa: E402

from tests.conftest import TEST_DATABASE_URL  # noqa: E402
from tests.materials.conftest import RAG_TABLES  # noqa: E402
from tests.retrieval.conftest import create_chunk, create_material  # noqa: E402

CHAT_TABLES = ("message_citations", "chat_messages", "chat_sessions")
BODY = (
    "# 极限\n\n"
    "## 洛必达法则\n\n"
    "洛必达法则用于处理 0/0 型与无穷比无穷型未定式，使用前必须判断未定式类型。\n"
)


@pytest.mark.parametrize("screening_mode,fail,expected", [
    ("off", False, 2), ("shadow", False, 2), ("filter", False, 1), ("filter", True, 1),
])
def test_context_screening_persists_actual_sse_evidence(session_factory, stack, monkeypatch, screening_mode, fail, expected):
    from backend.config import get_settings
    from backend.chat.evidence import validate_evidence_snapshot
    from backend.retrieval.protocols import RetrievalHit
    from backend.services.retrieval_service import RetrievalOutcome
    settings = get_settings()
    monkeypatch.setattr(settings, "chat_context_screening", screening_mode)
    monkeypatch.setattr(settings, "capture_test_evidence", True)
    with session_factory.begin() as db:
        body = "无关线程正文\n\n可导必连续，连续不一定可导。"
        material = create_material(db, title="合成筛选对照", body=body, index_version="v1-test")
        low = create_chunk(db, material, content="无关线程正文", ordinal=0)
        high = create_chunk(db, material, content="可导必连续，连续不一定可导。", ordinal=1)
        hits = [RetrievalHit(chunk_id=c.id, material_id=material.id, material_title=material.title,
                            source_type="builtin", index_version="v1-test", ordinal=c.ordinal,
                            content=c.content, heading_path=(), kp_ids=(), score=0.03, vector_score=cosine)
                for c, cosine in [(low, 0.2), (high, 0.8)]]
    monkeypatch.setattr(chat_service, "search_chunks", lambda *_, **__: RetrievalOutcome(hits=hits))
    session_id = make_session(session_factory)
    frames = collect_frames(session_factory, session_id=session_id, question="什么是连续？",
                            stack=stack, provider=ScriptedProvider(["可导必连续[C1]。"], fail=fail),
                            request=AlwaysAliveRequest())
    assistant = assistant_rows(session_factory, session_id)[0]
    assert assistant.status == ("failed" if fail else "completed")
    diagnostic = assistant.metadata_["context_screening"]
    assert diagnostic["mode"] == screening_mode
    assert diagnostic["before_count"] == 2 and diagnostic["after_count"] == expected
    snapshot = assistant.metadata_["evaluation_evidence"]
    blocks, _ = validate_evidence_snapshot(snapshot, str(assistant.id))
    assert len(blocks) == expected and snapshot["context_screening"] == diagnostic
    if screening_mode == "filter":
        assert snapshot["citations"] == {"C1": str(hits[1].chunk_id)}
        assert "无关线程正文" not in str(snapshot["contexts"])
    if not fail:
        cards = next(data for event, data in frames if event == "citations")
        assert str(hits[1 if screening_mode == "filter" else 0].chunk_id) in str(cards)
HIT_TEXT = "洛必达法则用于处理 0/0 型与无穷比无穷型未定式，使用前必须判断未定式类型。"


class AlwaysAliveRequest:
    """永不报告断线的 Request 替身。"""

    async def is_disconnected(self) -> bool:
        return False


class DisconnectAfterRequest:
    """在若干次轮询之后报告断线，用于模拟用户点「停止」。"""

    def __init__(self, after: int = 3) -> None:
        self._checks = 0
        self._after = after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._after


class DisconnectAfterFirstDeltaRequest:
    """等生成器确实交付首段正文后再模拟断连，避免依赖检索耗时的轮询次数。"""

    def __init__(self, first_delta_delivered: asyncio.Event) -> None:
        self._first_delta_delivered = first_delta_delivered

    async def is_disconnected(self) -> bool:
        return self._first_delta_delivered.is_set()


class ScriptedProvider(Provider):
    """按脚本吐字的 provider 替身。"""

    def __init__(self, pieces: list[str], *, fail: bool = False) -> None:
        self._pieces = pieces
        self._fail = fail
        self.calls = 0

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self._fail:
            raise AppError("generation_failed", detail="simulated stream failure")
        for piece in self._pieces:
            yield piece

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        return "".join(self._pieces), None


class HangingProvider(Provider):
    """永远不产出的 provider：配合断线请求测试取消路径。

    必须先 yield 一次让编排层进入循环，之后才永久挂起 ——
    否则连一个 delta 都收不到，测不到「保存已收到文本」。
    """

    def __init__(self) -> None:
        self.calls = 0
        self.first_delta_delivered = asyncio.Event()

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        yield "开头一段"
        # 异步生成器在下一次 anext 时才从 yield 后继续；此时消费者已拿到首段。
        self.first_delta_delivered.set()
        await asyncio.Event().wait()  # 永久挂起

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        raise AssertionError("不应被调用")


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
    # Cancelling an asyncio wrapper does not stop its retrieval worker. Wait for
    # that worker to leave the DB before acquiring TRUNCATE's exclusive locks.
    assert chat_service._RETRIEVAL_SLOT.acquire(timeout=10), "retrieval worker did not finish before test cleanup"
    try:
        with session_factory() as db:
            db.execute(
                text(
                    "TRUNCATE TABLE "
                    + ", ".join(CHAT_TABLES + tuple(t for t in RAG_TABLES if t not in CHAT_TABLES))
                    + " RESTART IDENTITY CASCADE"
                )
            )
            db.commit()
    finally:
        chat_service._RETRIEVAL_SLOT.release()
    yield


@pytest.fixture
def stack() -> RetrievalStack:
    embedder = FakeEmbedder(dimension=64)
    return RetrievalStack(
        embedder=embedder,
        vector_store=InMemoryVectorStore(embedding_model=embedder.model_name),
        keyword_index=KeywordIndex(),
        reranker=IdentityReranker(),
    )


def seed_material(session_factory, stack: RetrievalStack) -> None:
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


@pytest.mark.parametrize("heading", ["## 通用知识参考", "### 通用知识参考（补充背景）"])
def test_mixed_stream_preserves_evidence_but_removes_background_citations(session_factory, stack, heading):
    """真实保存链路用替身验证来源隔离，不把提示词存在当成模型遵循证明。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = ScriptedProvider([
        "资料说明须先判断未定式类型[C1]。\n",
        heading + "\n补充背景不是文件定义[C1][C99]。",
    ])
    frames = collect_frames(session_factory, session_id=session_id,
                            question="洛必达法则用于什么类型的未定式？", stack=stack,
                            provider=provider, request=AlwaysAliveRequest())
    done = next(data for event, data in frames if event == "done")
    stored = assistant_rows(session_factory, session_id)[0]
    assert done["answer"] == stored.content
    evidence, background = stored.content.split(heading, 1)
    assert "[C1]" in evidence and "[C" not in background
    assert stored.metadata_["answer_source"] == "mixed"
    with session_factory() as db:
        citations = list(db.scalars(select(MessageCitation).where(MessageCitation.message_id == stored.id)))
    assert [row.label for row in citations] == ["C1"]
    assert provider.calls == 1


def make_session(session_factory, *, mode: str = "builtin") -> UUID:
    with session_factory.begin() as db:
        row = ChatSession(title="新对话", mode=mode)
        db.add(row)
        db.flush()
        return row.id


def collect_frames(
    session_factory, *, session_id: UUID, question: str, stack, provider, request
) -> list[tuple[str, dict]]:
    """驱动 stream_answer 并把 SSE 帧解析成 (event, data)。"""

    async def run() -> list[tuple[str, dict]]:
        frames: list[tuple[str, dict]] = []
        async for raw in stream_answer(
            session_factory,
            request=request,
            session_id=session_id,
            question=question,
            stack=stack,
            provider=provider,
        ):
            text_frame = raw.decode("utf-8")
            event = None
            data = None
            for line in text_frame.split("\n"):
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
            if event and data is not None:
                frames.append((event, data))
        return frames

    return asyncio.run(run())


def assistant_rows(session_factory, session_id: UUID) -> list[ChatMessage]:
    with session_factory() as db:
        return list(
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant")
                .order_by(ChatMessage.seq)
            ).all()
        )


# ---------------------------------------------------------------------------
# 正常完成
# ---------------------------------------------------------------------------


def test_stream_usage_and_trace_are_persisted(session_factory, stack):
    from backend.chat.call_trace import observe_payload, PROMPT_VERSION
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    class UsageProvider(ScriptedProvider):
        async def stream(self, messages, *, attempt=1):
            async for part in super().stream(messages, attempt=attempt): yield part
            observe_payload({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
            observe_payload({"choices": [{"finish_reason": "stop"}]})
    frames = collect_frames(session_factory, session_id=session_id, question="洛必达法则用于什么未定式？",
                            stack=stack, provider=UsageProvider(["资料回答[C1]。"]), request=AlwaysAliveRequest())
    done = next(data for event, data in frames if event == "done")
    assert done["usage"]["total_tokens"] == 15
    metadata = assistant_rows(session_factory, session_id)[0].metadata_
    trace = metadata["generation_trace"]
    assert trace["request_id"] == done["message_id"]
    assert trace["prompt_version"] == PROMPT_VERSION
    assert trace["observed_usage"] == done["usage"]
    assert trace["calls"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_actual_evidence_persistence_and_api_privacy(session_factory, stack, monkeypatch, capture, fail):
    from types import SimpleNamespace
    from backend.config import get_settings
    from backend.api.routes.chat import list_messages
    from backend.chat.evidence import validate_evidence_snapshot

    settings = get_settings()
    monkeypatch.setattr(settings, "capture_test_evidence", capture)
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    class RecordingProvider(ScriptedProvider):
        async def stream(self, messages, *, attempt=1):
            self.recorded_prompt = messages
            async for part in super().stream(messages, attempt=attempt):
                yield part

    provider = RecordingProvider(["真实回答[C1]。"], fail=fail)
    collect_frames(session_factory, session_id=session_id,
                   question="洛必达法则用于处理什么类型的未定式？", stack=stack,
                   provider=provider, request=AlwaysAliveRequest())
    assistant = assistant_rows(session_factory, session_id)[0]
    assert assistant.status == ("failed" if fail else "completed")
    assert ("evaluation_evidence" in assistant.metadata_) is capture
    if capture:
        blocks, contexts = validate_evidence_snapshot(assistant.metadata_["evaluation_evidence"], str(assistant.id))
        assert blocks and "\n\n".join(contexts) == provider.recorded_prompt[-2]["content"].removeprefix("【资料证据】\n")
    for env, enabled in [("dev", True), ("test", False), ("test", True)]:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            session_factory=session_factory, settings=SimpleNamespace(app_env=env, capture_test_evidence=enabled))))
        messages = list_messages(request, session_id)
        restored = next(m for m in messages if m["message_id"] == str(assistant.id))
        assert ("evaluation_evidence" in restored) is (env == "test" and enabled)
        if env == "test" and enabled and capture:
            assert restored["evaluation_evidence"] == assistant.metadata_["evaluation_evidence"]


def test_frame_order_is_meta_delta_citations_done(session_factory, stack) -> None:
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=ScriptedProvider(["依据", "资料", "[C1]", "。"], ),
        request=AlwaysAliveRequest(),
    )
    events = [event for event, _ in frames]

    assert events[0] == "meta", "首帧必须是 meta"
    assert events[-2:] == ["citations", "done"], "成功必须以 citations → done 收尾"
    assert events.count("done") == 1
    assert "error" not in events


def test_delta_seq_increases_from_one(session_factory, stack) -> None:
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=ScriptedProvider(["a", "b", "c", "d"]),
        request=AlwaysAliveRequest(),
    )
    seqs = [data["seq"] for event, data in frames if event == "delta"]
    assert seqs == [1, 2, 3, 4]


def test_meta_carries_message_id_and_retrieved_count(session_factory, stack) -> None:
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=ScriptedProvider(["x"]),
        request=AlwaysAliveRequest(),
    )
    meta = next(data for event, data in frames if event == "meta")
    assert meta["message_id"]
    assert meta["retrieved_count"] >= 1
    assert meta["retrieval_mode"] == "hybrid"


def test_citations_frame_carries_clickable_card_fields_and_done_keeps_contract(session_factory, stack) -> None:
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=ScriptedProvider(["依据 [C1] 需要判断类型。"]),
        request=AlwaysAliveRequest(),
    )
    citations = next(data for event, data in frames if event == "citations")["citations"]
    assert citations, "必须独立发送 citations 帧"
    assert set(citations[0]) >= {
        "label", "chunk_id", "material_id", "material_title", "heading_path", "ordinal", "preview"
    }
    assert citations[0]["label"] == "C1"
    done = next(data for event, data in frames if event == "done")
    assert done["citations"] == citations
    assert isinstance(done["response_duration_ms"], int)
    assert done["response_duration_ms"] >= 0


def test_completed_message_is_persisted_with_citations(session_factory, stack) -> None:
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=ScriptedProvider(["依据 [C1] 需要判断类型。"]),
        request=AlwaysAliveRequest(),
    )

    rows = assistant_rows(session_factory, session_id)
    assert rows and rows[-1].status == "completed"
    assert "[C1]" in rows[-1].content
    done = next(data for event, data in frames if event == "done")
    assert rows[-1].metadata_["response_duration_ms"] == done["response_duration_ms"]
    with session_factory() as db:
        assert len(db.scalars(select(MessageCitation)).all()) == 1


def test_no_hit_streams_labeled_general_reference(session_factory, stack) -> None:
    """无命中时流式生成常识参考，完成帧保留来源类型。"""
    session_id = make_session(session_factory)
    provider = ScriptedProvider(["Python 可使用 csv 模块读取文件。[C1]"])

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="完全无关的问题：如何用 Python 读取 CSV？",
        stack=stack,
        provider=provider,
        request=AlwaysAliveRequest(),
    )
    events = [event for event, _ in frames]
    assert events[0] == "meta" and events[-2:] == ["citations", "done"]
    assert provider.calls == 1
    citations = next(data for event, data in frames if event == "citations")
    assert citations["citations"] == []
    done = next(data for event, data in frames if event == "done")
    assert done["matched_kp_id"] is None
    assert done["answer_source"] == "general"
    assert "## 通用知识参考" in done["answer"]
    assert "[C1]" not in done["answer"]


def test_builtin_mode_personal_file_reference_finishes_without_retrieval(
    session_factory, stack
) -> None:
    """误在内置模式询问个人文件时，SSE 快速提示切换，不触发向量检索。"""
    session_id = make_session(session_factory, mode="builtin")
    body = "这是用户上传的验收文件。"
    with session_factory() as db:
        material = create_material(
            db, title="阶段验收资料", body=body, source_type="user", index_version="v1-user"
        )
        material.original_filename = "验收.md"
        create_chunk(db, material, content=body, ordinal=0, index_version="v1-user")
        db.commit()

    provider = ScriptedProvider(["不应调用"])
    encode_calls = list(stack.embedder.encode_calls)
    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="那份文件说的内容大概是什么？",
        stack=stack,
        provider=provider,
        request=AlwaysAliveRequest(),
    )

    assert [event for event, _ in frames] == ["meta", "delta", "citations", "done"]
    assert "内置资料" in frames[1][1]["text"]
    assert "我的资料" in frames[1][1]["text"]
    assert provider.calls == 0
    assert stack.embedder.encode_calls == encode_calls


def test_retrieval_timeout_emits_error_and_marks_assistant_failed(
    session_factory, stack, monkeypatch
) -> None:
    """检索线程卡住时，SSE 必须在总时限后以错误帧结束。"""
    session_id = make_session(session_factory)
    monkeypatch.setattr(chat_service, "RETRIEVAL_TIMEOUT_SECONDS", 0.01)
    worker_started = Event()
    worker_finished = Event()

    def slow_prepare(_factory, **_kwargs) -> None:
        try:
            worker_started.set()
            time.sleep(0.08)
        finally:
            worker_finished.set()

    monkeypatch.setattr(chat_service, "_prepare_from_factory", slow_prepare)
    original_submit = chat_service._submit_preparation

    def submit_started_worker(*args, **kwargs):
        future = original_submit(*args, **kwargs)
        # 此用例验证“正在执行的线程不可被取消”，不是“队列中的任务被取消”。
        # 10ms 内线程可能尚未调度；必须先建立 running 前置条件再开始超时计时。
        assert worker_started.wait(timeout=2), "test retrieval worker did not start"
        return future

    monkeypatch.setattr(chat_service, "_submit_preparation", submit_started_worker)
    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="请概述那份文件",
        stack=stack,
        provider=ScriptedProvider(["不应调用"]),
        request=AlwaysAliveRequest(),
    )

    error = next(data for event, data in frames if event == "error")
    assert error["code"] == "retrieval_timeout"
    assert error["retryable"] is True
    rows = assistant_rows(session_factory, session_id)
    assert rows and rows[-1].status == "failed"
    # asyncio 包装任务超时后不能杀掉线程；等真实 worker 和 done callback 释放槽位，
    # 否则下一条测试/请求正确地得到 retrieval_busy，造成与用例目的无关的串扰。
    assert worker_finished.wait(timeout=1)
    deadline = time.monotonic() + 1
    while not chat_service._RETRIEVAL_SLOT.acquire(blocking=False):
        if time.monotonic() >= deadline:
            pytest.fail("retrieval worker slot was not released after worker exit")
        time.sleep(0.001)
    chat_service._RETRIEVAL_SLOT.release()


# ---------------------------------------------------------------------------
# 取消（用户点停止）
# ---------------------------------------------------------------------------


def test_disconnect_marks_message_cancelled_and_keeps_partial_text(
    session_factory, stack
) -> None:
    """取消：状态必须是 cancelled，并**保留已收到的文本**（契约 §3）。

    保留文本的理由：它比空白更有用 —— 用户能看到中断前的进度；
    而状态绝不能停在 generating，否则刷新页面会永远显示生成中。
    """
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    provider = HangingProvider()
    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
        request=DisconnectAfterFirstDeltaRequest(provider.first_delta_delivered),
    )
    events = [event for event, _ in frames]
    # 取消时不发 done，也不应该是 error（用户自己停的不是错误）
    assert "done" not in events
    assert "error" not in events, frames
    assert "delta" in events, "取消前应已发出部分内容"

    rows = assistant_rows(session_factory, session_id)
    assert rows and rows[-1].status == "cancelled"
    assert rows[-1].content, "已收到的文本必须保存下来"
    assert rows[-1].content in "".join(
        data["text"] for event, data in frames if event == "delta"
    )


def test_disconnect_before_any_output_leaves_no_empty_message(session_factory, stack) -> None:
    """一个字都没收到就取消：不留一条空消息（否则用户看到无意义的「已取消」）。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=ScriptedProvider(["x"]),
        request=DisconnectAfterRequest(after=0),
    )
    assert [event for event, _ in frames] == []

    rows = assistant_rows(session_factory, session_id)
    assert rows == [], "没有内容的取消不应留下占位消息"


# ---------------------------------------------------------------------------
# 失败
# ---------------------------------------------------------------------------


class SilentProvider(Provider):
    """上游连接不断但始终不产出正文，验证总时限兜底。"""

    def __init__(self) -> None:
        self.timeout = 0.01
        self.calls = 0

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        await asyncio.Event().wait()
        yield "不会到达"


def test_silent_provider_finishes_with_error_frame(session_factory, stack) -> None:
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = SilentProvider()
    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
        request=AlwaysAliveRequest(),
    )
    assert provider.calls == 2
    assert [event for event, _ in frames][-1] == "error"
    assert assistant_rows(session_factory, session_id)[-1].status == "failed"


def test_provider_error_ends_with_error_frame(session_factory, stack) -> None:
    """模型失败：必须以 error 收尾，且不残留 generating。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=ScriptedProvider([], fail=True),
        request=AlwaysAliveRequest(),
    )
    events = [event for event, _ in frames]
    assert events[0] == "meta"
    assert events[-1] == "error", "失败必须以 error 收尾"
    error = next(data for event, data in frames if event == "error")
    assert error["code"] == "generation_failed"
    assert "retryable" in error

    rows = assistant_rows(session_factory, session_id)
    assert rows and rows[-1].status == "failed"


def test_error_frame_carries_no_stack_trace(session_factory, stack) -> None:
    """error 帧只能有稳定码与安全文案，绝不能泄露堆栈或内部路径。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=ScriptedProvider([], fail=True),
        request=AlwaysAliveRequest(),
    )
    error = next(data for event, data in frames if event == "error")
    blob = json.dumps(error, ensure_ascii=False)
    assert "Traceback" not in blob
    assert "simulated stream failure" not in blob, "detail 只应进日志"
    for leaked in ("D:\\", "C:\\", "postgresql://", "password"):
        assert leaked not in blob


def test_unexpected_stream_error_persists_partial_text_and_citations(session_factory, stack) -> None:
    """非业务异常也必须以 error 帧收尾，并保存已输出正文和可核验引用。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    class BrokenProvider(Provider):
        def __init__(self) -> None:
            super().__init__(
                api_key="test",
                base_url="http://localhost/v1",
                model="test",
                timeout=1.0,
                max_tokens=64,
            )

        async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
            yield "根据讲义 [C1]，"
            raise RuntimeError("private internal failure")

        def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
            raise AssertionError("流式路径不应调用 complete")

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=BrokenProvider(),
        request=AlwaysAliveRequest(),
    )

    assert frames[-1][0] == "error"
    assert frames[-1][1]["code"] == "internal_error"
    assert "private internal failure" not in json.dumps(frames[-1][1])
    rows = assistant_rows(session_factory, session_id)
    assert rows[-1].status == "failed"
    assert rows[-1].content == "根据讲义 [C1]，"
    assert rows[-1].metadata_["partial"] is True
    with session_factory() as db:
        citations = db.scalars(
            select(MessageCitation).where(MessageCitation.message_id == rows[-1].id)
        ).all()
        assert [(citation.label, citation.ordinal) for citation in citations] == [("C1", 0)]


# ---------------------------------------------------------------------------
# SSE 编码本身
# ---------------------------------------------------------------------------


class FlakyProvider(Provider):
    """第一轮抛出指定错误，第二轮正常出字。

    复现的是本机实测到的另一种真实故障：上游返回 503 / 429，
    第一次调用直接抛错（此时**一次 delta 都没有**），重试即可成功。
    """

    def __init__(self, pieces: list[str], error: AppError) -> None:
        self._pieces = pieces
        self._error = error
        self.calls = 0

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            raise self._error
        for piece in self._pieces:
            yield piece

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        raise AssertionError("流式路径不应调用 complete")


def test_retryable_provider_error_is_retried_once(session_factory, stack) -> None:
    """首轮抛可重试故障（429/5xx/超时）且尚未产出任何内容 → 重试一次并成功。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = FlakyProvider(
        ["洛必达法则 [C1]。"],
        AppError("generation_failed", detail="stream:http_503", retryable=True),
    )

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
        request=AlwaysAliveRequest(),
    )

    assert provider.calls == 2, "可重试故障应当重试一次"
    assert [event for event, _ in frames] == ["meta", "delta", "citations", "done"]
    rows = assistant_rows(session_factory, session_id)
    assert rows[0].status == "completed"
    assert rows[0].content == "洛必达法则 [C1]。"


def test_deterministic_error_is_not_retried(session_factory, stack) -> None:
    """确定性失败（鉴权、模型名错）不该重试：重试只会让用户多等一遍。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = FlakyProvider(
        ["不该被用到"],
        AppError("generation_failed", detail="stream:http_401", retryable=False),
    )

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
        request=AlwaysAliveRequest(),
    )

    assert provider.calls == 1, "确定性失败不得重试"
    assert [event for event, _ in frames][-1] == "error"


def test_retryable_error_after_output_is_not_retried(session_factory, stack) -> None:
    """已经给用户吐过内容之后出错，绝不重试 —— 否则第二个回答会接在残句后面。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = FailMidStreamProvider(
        ["开头一段。", "第二段。"],
        AppError("generation_failed", detail="stream:http_503", retryable=True),
    )

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
        request=AlwaysAliveRequest(),
    )

    assert provider.calls == 1, "已产出内容后不得重试"
    assert [event for event, _ in frames][-1] == "error"


class FailMidStreamProvider(Provider):
    """先正常吐两块，然后抛错。"""

    def __init__(self, pieces: list[str], error: AppError) -> None:
        self._pieces = pieces
        self._error = error
        self.calls = 0

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        for piece in self._pieces:
            yield piece
        raise self._error

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        raise AssertionError("流式路径不应调用 complete")


@pytest.mark.parametrize("exhausted", [False, True])
def test_partial_output_limit_recovers_or_persists_failed_body(session_factory, stack, exhausted) -> None:
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)

    class LimitedProvider(Provider):
        def __init__(self):
            self.calls = 0

        async def stream(self, messages, *, attempt=1):
            self.calls += 1
            yield "首轮残句" if attempt == 1 else "洛必达法则用于 0/0 型和无穷比无穷型未定式。[C1]"
            if attempt == 1 or exhausted:
                raise AppError("answer_truncated", retryable=True)

    provider = LimitedProvider()
    frames = collect_frames(session_factory, session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？", stack=stack,
        provider=provider, request=AlwaysAliveRequest())
    assert provider.calls == 2
    deltas = [data for event, data in frames if event == "delta"]
    assert [d["seq"] for d in deltas] == list(range(1, len(deltas) + 1))
    assert sum(d.get("replace") is True for d in deltas) == 1
    row = assistant_rows(session_factory, session_id)[0]
    assert "首轮残句" not in row.content
    assert "洛必达法则" in row.content
    assert row.status == ("failed" if exhausted else "completed")
    assert frames[-1][0] == ("error" if exhausted else "done")
    if exhausted:
        assert row.metadata_["partial"] is True
        assert row.metadata_["error_code"] == "answer_truncated"
        assert not any(event == "citations" for event, _ in frames)


def test_provider_citation_alias_is_canonical_and_unknown_never_creates_card(session_factory, stack) -> None:
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    frames = collect_frames(session_factory, session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？", stack=stack,
        provider=ScriptedProvider(["洛必达法则用于 0/0 型未定式。[citation:1] [citation:99]"]),
        request=AlwaysAliveRequest())
    done = frames[-1][1]
    assert frames[-1][0] == "done"
    assert "[C1]" in done["answer"]
    assert "citation:" not in done["answer"]
    assert [card["label"] for card in done["citations"]] == ["C1"]
    row = assistant_rows(session_factory, session_id)[0]
    assert row.metadata_["normalized_citation_labels"] == ["C1"]
    assert row.metadata_["unknown_citation_labels"] == ["C99"]


def test_encode_sse_format() -> None:
    frame = encode_sse("meta", {"message_id": "m1"}).decode("utf-8")
    assert frame.startswith("event: meta\n")
    assert "data: " in frame
    assert frame.endswith("\n\n"), "每帧必须以空行结束，否则前端无法分帧"


def test_encode_sse_keeps_chinese_readable() -> None:
    """中文不能被转义成 \\uXXXX：前端要直接渲染，转义会让日志与调试都难读。"""
    frame = encode_sse("delta", {"text": "洛必达法则"}).decode("utf-8")
    assert "洛必达法则" in frame


# ---------------------------------------------------------------------------
# 空回答重试一次
# ---------------------------------------------------------------------------


class EmptyFirstProvider(Provider):
    """第一轮一个新块都不给，第二轮才正常出字。

    复现的是本机实测到的真实故障：真实模型偶发返回空回答，
    用户看到的是「回答生成失败」，而同一个请求重试就能成功。
    """

    def __init__(self, pieces: list[str]) -> None:
        self._pieces = pieces
        self.calls = 0

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return
        for piece in self._pieces:
            yield piece

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        raise AssertionError("流式路径不应调用 complete")


class AlwaysEmptyProvider(Provider):
    """两轮都是空回答：重试也救不回来，必须如实报错。"""

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        self.calls += 1
        return
        yield  # pragma: no cover - 让它是异步生成器

    def complete(self, messages, *, attempt: int = 1):  # type: ignore[no-untyped-def]
        raise AssertionError("流式路径不应调用 complete")


def test_empty_first_round_is_retried_once_and_succeeds(session_factory, stack) -> None:
    """第一轮空回答要重试一次；重试成功后用户看到的是正常回答，不是报错。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = EmptyFirstProvider(["洛必达法则", "用于处理 0/0 型 [C1]。"])

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
        request=AlwaysAliveRequest(),
    )

    assert provider.calls == 2, "空回答必须重试一次"
    assert [event for event, _ in frames] == ["meta", "delta", "delta", "citations", "done"]
    rows = assistant_rows(session_factory, session_id)
    assert len(rows) == 1, "重试不能产生第二条 assistant 消息"
    assert rows[0].status == "completed"
    assert "洛必达法则" in rows[0].content


def test_retry_start_over_does_not_mix_partial_text(session_factory, stack) -> None:
    """重试必须从头开始：第一轮一个字都没有，所以最终内容里不能有重复前缀。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = EmptyFirstProvider(["完整回答 [C1]。"])

    collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
        request=AlwaysAliveRequest(),
    )

    rows = assistant_rows(session_factory, session_id)
    assert rows[0].content == "完整回答 [C1]。", "不得把两轮内容拼接起来"


def test_two_empty_rounds_end_with_error_frame(session_factory, stack) -> None:
    """两轮都空：这才是真失败，必须以 error 收尾且不伪造回答。"""
    seed_material(session_factory, stack)
    session_id = make_session(session_factory)
    provider = AlwaysEmptyProvider()

    frames = collect_frames(
        session_factory,
        session_id=session_id,
        question="洛必达法则用于处理什么类型的未定式？",
        stack=stack,
        provider=provider,
        request=AlwaysAliveRequest(),
    )

    assert provider.calls == 2, "只重试一次，不能无限重试"
    assert [event for event, _ in frames][-1] == "error"
    assert "delta" not in [event for event, _ in frames]
    rows = assistant_rows(session_factory, session_id)
    assert rows[0].status == "failed"
    assert rows[0].content == "", "失败的回答不能留下半截正文"
