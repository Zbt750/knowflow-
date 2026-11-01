"""会话列表契约：按模式过滤 + 空会话不返回。

为什么要单独写这个文件：
`GET /chat/sessions` 此前**没有任何测试覆盖**，它返回「全部未归档会话」。
后果在真实开发库里看得见：94 条未归档会话中 **46 条是空壳**
（builtin 23 条 / user 23 条）—— 它们全部来自「点了一下新建对话」或切换范围，
一条消息都没有。叠加篇 01「两种问答模式严格隔离」（两种模式的检索范围、
matched_kp、追练推荐与学习事件完全不同），用户在一个扁平列表里根本分不清。

本次改动：接口支持可选 `mode`，并且**空会话不再返回**。
这里把这两条行为与「向后兼容」一起锁住。
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend.models import import_models

import_models()

from backend.models.chat import ChatMessage, ChatSession, MessageCitation  # noqa: E402

from tests.conftest import TEST_DATABASE_URL  # noqa: E402
from tests.materials.conftest import RAG_TABLES  # noqa: E402
from tests.retrieval.conftest import create_chunk, create_material  # noqa: E402

CHAT_TABLES = ("message_citations", "chat_messages", "chat_sessions")

# 响应字段是冻结契约：改动会直接影响前端与规格，因此逐字断言。
EXPECTED_FIELDS = {"session_id", "title", "mode"}


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
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def make_session(session_factory, *, mode: str, title: str = "新对话", purpose: str = "qa") -> UUID:
    with session_factory.begin() as db:
        row = ChatSession(title=title, mode=mode, purpose=purpose,
            study_date="2026-01-01" if purpose == "study" else None)
        db.add(row)
        db.flush()
        return row.id


def add_user_message(session_factory, *, session_id: UUID, content: str = "问一句") -> None:
    with session_factory.begin() as db:
        db.add(
            ChatMessage(session_id=session_id, role="user", content=content, status="completed")
        )


def test_completed_answer_duration_is_returned_in_history(client, session_factory) -> None:
    session_id = make_session(session_factory, mode="builtin")
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=session_id, role="assistant", content="回答", status="completed", metadata_={"response_duration_ms": 1234}))

    response = client.get(f"/api/chat/sessions/{session_id}/messages")
    assert response.status_code == 200
    assert response.json()[0]["response_duration_ms"] == 1234


def archive(session_factory, *, session_id: UUID) -> None:
    from datetime import datetime, timezone

    with session_factory.begin() as db:
        row = db.get(ChatSession, session_id)
        row.archived_at = datetime.now(timezone.utc)


def listed_ids(client: TestClient, **params) -> list[str]:
    response = client.get("/api/chat/sessions", params=params or None)
    assert response.status_code == 200
    return [item["session_id"] for item in response.json()]


def test_empty_session_is_not_listed(client, session_factory) -> None:
    """没有任何消息的会话不返回：它只是「点了一下新建」的残留。"""
    empty = make_session(session_factory, mode="builtin")

    assert listed_ids(client) == []
    assert listed_ids(client, mode="builtin") == []


def test_session_with_a_single_user_message_is_listed(client, session_factory) -> None:
    """只要写了第一条 user 消息就应出现 —— 用户真正开始提问的会话不能被吞掉。"""
    started = make_session(session_factory, mode="builtin")
    add_user_message(session_factory, session_id=started)

    assert listed_ids(client) == [str(started)]


def test_mode_filter_returns_only_that_mode(client, session_factory) -> None:
    """两种模式的检索范围与后续行为完全不同，必须能各看各的。"""
    builtin = make_session(session_factory, mode="builtin", title="内置问题")
    user = make_session(session_factory, mode="user", title="我的资料问题")
    add_user_message(session_factory, session_id=builtin)
    add_user_message(session_factory, session_id=user)

    assert listed_ids(client, mode="builtin") == [str(builtin)]
    assert listed_ids(client, mode="user") == [str(user)]


def test_list_without_mode_returns_both_modes(client, session_factory) -> None:
    """不传 mode 是原来的行为（向后兼容），只是不再包含空会话。"""
    builtin = make_session(session_factory, mode="builtin")
    user = make_session(session_factory, mode="user")
    add_user_message(session_factory, session_id=builtin)
    add_user_message(session_factory, session_id=user)
    make_session(session_factory, mode="user")  # 空壳，不应出现

    assert set(listed_ids(client)) == {str(builtin), str(user)}


def test_archived_session_is_still_excluded(client, session_factory) -> None:
    """归档语义不变：归档后不再出现在列表里（无论有没有消息）。"""
    archived = make_session(session_factory, mode="builtin")
    add_user_message(session_factory, session_id=archived)
    archive(session_factory, session_id=archived)

    assert listed_ids(client) == []
    assert listed_ids(client, mode="builtin") == []


def test_invalid_mode_is_rejected(client) -> None:
    """mode 是 Literal：非法取值必须 422，而不是被当成「不过滤」。"""
    response = client.get("/api/chat/sessions", params={"mode": "builtin,user"})

    assert response.status_code == 422


def test_response_fields_are_unchanged(client, session_factory) -> None:
    """保留既有身份字段及 Phase 4 已提供的 purpose / material_scope_ids。"""
    started = make_session(session_factory, mode="user", title="我的资料问题")
    add_user_message(session_factory, session_id=started)

    response = client.get("/api/chat/sessions", params={"mode": "user"})

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert set(items[0]) == EXPECTED_FIELDS | {"purpose", "material_scope_ids"}
    assert items[0]["title"] == "我的资料问题"
    assert items[0]["mode"] == "user"


def test_purpose_filters_history_detail_and_delete_scope(client, session_factory) -> None:
    qa = make_session(session_factory, mode="builtin", title="问答历史", purpose="qa")
    study = make_session(session_factory, mode="builtin", title="今日学习首页", purpose="study")
    add_user_message(session_factory, session_id=qa, content="普通知识问题")
    add_user_message(session_factory, session_id=study, content="系统推荐与预览")

    assert listed_ids(client, mode="builtin", purpose="qa") == [str(qa)]
    assert listed_ids(client, mode="builtin", purpose="study") == [str(study)]
    assert client.get(f"/api/chat/sessions/{study}/messages", params={"purpose": "qa"}).status_code == 404
    assert client.get(f"/api/chat/sessions/{qa}/messages", params={"purpose": "study"}).status_code == 404
    study_assistant = client.post(f"/api/chat/sessions/{study}/assistant:stream", params={"purpose": "qa"},
        json={"question": "确认"})
    qa_assistant = client.post(f"/api/chat/sessions/{qa}/assistant:stream", params={"purpose": "study"},
        json={"question": "确认"})
    assert study_assistant.status_code == 404
    assert qa_assistant.status_code == 404
    study_answer = client.post(f"/api/chat/sessions/{study}/answers:stream", params={"purpose": "qa"},
        json={"question": "洛必达法则是什么？"})
    assert study_answer.status_code == 404
    assert client.patch(f"/api/chat/sessions/{study}", params={"purpose": "qa"},
                        json={"title": "不应改名"}).status_code == 404
    assert client.delete(f"/api/chat/sessions/{study}", params={"purpose": "qa"}).status_code == 404
    assert client.get(f"/api/chat/sessions/{study}/messages", params={"purpose": "study"}).status_code == 200
    with session_factory() as db:
        assert db.get(ChatSession, study) is not None
        assert db.get(ChatSession, qa) is not None
    assert client.delete(f"/api/chat/sessions/{qa}", params={"purpose": "qa"}).status_code == 204
    assert client.get(f"/api/chat/sessions/{study}/messages", params={"purpose": "study"}).status_code == 200
    assert client.get(f"/api/chat/sessions/{qa}/messages", params={"purpose": "qa"}).status_code == 404


def test_positively_tagged_legacy_home_session_is_recovered_as_study_only(client, session_factory) -> None:
    legacy = make_session(session_factory, mode="builtin", title="线性代数安排90分钟", purpose="qa")
    add_user_message(session_factory, session_id=legacy, content="线性代数安排90分钟")
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=legacy, role="assistant", status="completed",
            content="试卷预览：18道，预计90分钟。尚未创建今日卷。",
            metadata_={"home_recommendation": True}))

    qa_rows = client.get("/api/chat/sessions", params={"mode": "builtin", "purpose": "qa"})
    study_rows = client.get("/api/chat/sessions", params={"mode": "builtin", "purpose": "study"})
    assert legacy not in {row["session_id"] for row in qa_rows.json()}
    recovered = next(row for row in study_rows.json() if row["session_id"] == str(legacy))
    assert recovered["purpose"] == "study"
    assert client.get(f"/api/chat/sessions/{legacy}/messages", params={"purpose": "qa"}).status_code == 404
    history = client.get(f"/api/chat/sessions/{legacy}/messages", params={"purpose": "study"})
    assert history.status_code == 200
    assert any("试卷预览" in row["content"] for row in history.json())
    assert client.delete(f"/api/chat/sessions/{legacy}", params={"purpose": "qa"}).status_code == 404
    with session_factory() as db:
        assert db.get(ChatSession, legacy) is not None


def test_ambiguous_legacy_mixed_session_is_not_assigned_to_either_module(client, session_factory) -> None:
    """保留混合归属的原始记录，但不把它猜成问答或首页学习历史。"""
    legacy = make_session(session_factory, mode="builtin", title="归属待核验", purpose="qa")
    add_user_message(session_factory, session_id=legacy, content="首页安排请求")
    with session_factory.begin() as db:
        db.add_all([
            ChatMessage(session_id=legacy, role="assistant", status="completed",
                content="首页试卷预览", metadata_={"home_recommendation": True}),
            ChatMessage(session_id=legacy, role="assistant", status="completed",
                content="无法确认来源的旧回答", metadata_={}),
        ])

    qa_rows = listed_ids(client, mode="builtin", purpose="qa")
    study_rows = listed_ids(client, mode="builtin", purpose="study")
    assert str(legacy) not in qa_rows
    assert str(legacy) not in study_rows
    assert client.get(f"/api/chat/sessions/{legacy}/messages", params={"purpose": "qa"}).status_code == 404
    assert client.get(f"/api/chat/sessions/{legacy}/messages", params={"purpose": "study"}).status_code == 404

    # 不确定归属只限制模块展示与访问，不删除或改写已有会话、消息。
    with session_factory() as db:
        assert db.get(ChatSession, legacy) is not None
        rows = db.scalars(select(ChatMessage).where(ChatMessage.session_id == legacy).order_by(ChatMessage.seq)).all()
        assert [row.content for row in rows] == ["首页安排请求", "首页试卷预览", "无法确认来源的旧回答"]


def test_sessions_are_ordered_by_most_recently_updated(client, session_factory) -> None:
    """列表按 updated_at 倒序：最近用过的排最前，与改动前一致。"""
    from datetime import datetime, timedelta, timezone

    old = make_session(session_factory, mode="builtin", title="先建的")
    add_user_message(session_factory, session_id=old)
    new = make_session(session_factory, mode="builtin", title="后建的")
    add_user_message(session_factory, session_id=new)

    # 手动把 old 的 updated_at 推早，确保排序依据确实是 updated_at。
    with session_factory.begin() as db:
        db.get(ChatSession, old).updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.get(ChatSession, new).updated_at = datetime.now(timezone.utc)

    assert listed_ids(client, mode="builtin") == [str(new), str(old)]


# ---------------------------------------------------------------------------
# 物理删除（D-28）
#
# 2026-09-20 之前 `DELETE /chat/sessions/{id}` 是**归档**（只置 archived_at）。
# 产品方要求列表里的 × 真的删掉记录，端点因此改为物理删除。
# 下面把「三张表都清干净」「不误伤别的会话」「删了就回不来」锁住。
# ---------------------------------------------------------------------------


def add_citation(session_factory, *, session_id: UUID) -> None:
    """给会话里第一条消息挂一张真实引用卡。

    `message_citations.chunk_id` 有外键指向 `document_chunks`，所以不能凭空造一条
    —— 得真的建资料 + 分块。这一步正是要验证「删会话会不会留下引用孤儿」。
    """
    body = "洛必达法则用于处理 0/0 型与无穷比无穷型未定式。"
    with session_factory.begin() as db:
        material = create_material(
            db, title="极限讲义", body=body, source_type="builtin", index_version="v1-test"
        )
        chunk = create_chunk(
            db,
            material,
            content=body,
            ordinal=0,
            heading_path=("极限", "洛必达法则"),
            index_version="v1-test",
        )
        message = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.seq)
        ).first()
        assert message is not None, "先 add_user_message 再挂引用"
        db.add(MessageCitation(message_id=message.id, chunk_id=chunk.id, label="C1", ordinal=1))


def test_delete_removes_session_messages_and_citations(client, session_factory) -> None:
    """× 是真删：会话、消息、引用三张表里的行都必须消失（不能留孤儿引用）。"""
    session_id = make_session(session_factory, mode="builtin", title="用完就删")
    add_user_message(session_factory, session_id=session_id)
    add_citation(session_factory, session_id=session_id)

    with session_factory() as db:
        assert db.get(ChatSession, session_id) is not None
        assert len(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)).all()) == 1
        assert len(db.scalars(select(MessageCitation)).all()) == 1

    assert client.delete(f"/api/chat/sessions/{session_id}").status_code == 204

    with session_factory() as db:
        assert db.get(ChatSession, session_id) is None
        assert db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)).all() == []
        assert db.scalars(select(MessageCitation)).all() == []


def test_delete_only_touches_the_target_session(client, session_factory) -> None:
    """删一条不影响别的会话 —— 列表里的 × 只能作用于自己那一行。"""
    doomed = make_session(session_factory, mode="builtin", title="要删的")
    kept = make_session(session_factory, mode="builtin", title="要留的")
    add_user_message(session_factory, session_id=doomed)
    add_user_message(session_factory, session_id=kept)

    assert client.delete(f"/api/chat/sessions/{doomed}").status_code == 204

    assert listed_ids(client) == [str(kept)]
    with session_factory() as db:
        assert db.get(ChatSession, kept) is not None
        assert len(db.scalars(select(ChatMessage).where(ChatMessage.session_id == kept)).all()) == 1


def test_delete_is_permanent_second_delete_is_404(client, session_factory) -> None:
    """物理删除不可逆：再删同一个 id 必须是 404，而不是「反正结果一样」的 204。

    这一条区分了归档与删除：归档是幂等的（重复置 archived_at 无害），
    物理删除第二次就找不到行了，语义上必须如实报 404。
    """
    session_id = make_session(session_factory, mode="user")
    add_user_message(session_factory, session_id=session_id)

    assert client.delete(f"/api/chat/sessions/{session_id}").status_code == 204
    assert client.delete(f"/api/chat/sessions/{session_id}").status_code == 404


def test_delete_unknown_session_is_404(client) -> None:
    """删一个不存在的会话：明确 404，不能静默成功。"""
    assert client.delete(f"/api/chat/sessions/{uuid4()}").status_code == 404
