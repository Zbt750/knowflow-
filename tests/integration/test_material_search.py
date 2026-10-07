"""Material Search lifecycle and real retrieval regression, with no paid model."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.integration.test_chat_flow import session_factory, clean_tables, stack, embedder, FakeProvider
from tests.retrieval.conftest import create_material, create_chunk
from backend.models.chat import ChatSession, ChatMessage, MessageCitation
from backend.models.rag import Material, DocumentChunk
from backend.retrieval.protocols import VectorRecord
from backend.services.material_search_service import daily_session, update_scope, guard_answer, local_day
from backend.chat.service import answer, stream_answer
from backend.errors import AppError


def seed_personal(factory, stack):
    rows = []
    with factory.begin() as db:
        for name, body, source, status in (
            ("相似笔记", "矩阵相似需要存在可逆矩阵P，使B=P逆乘A乘P。标记SIMILAR_A_201。", "user", "ready"),
            ("合同笔记", "矩阵合同需要存在可逆矩阵P，使B=P转置乘A乘P。标记CONGRUENT_B_202。", "user", "ready"),
            ("咖啡笔记", "咖啡浸泡记录COFFEE_C_203。", "user", "ready"),
            ("系统讲解", "矩阵相似系统专属秘密BUILTIN_204。", "builtin", "ready"),
            ("处理中", "矩阵相似尚未索引INDEXING_205。", "user", "indexing"),
            ("失败文件", "矩阵合同解析失败FAILED_206。", "user", "failed"),
        ):
            m = create_material(db, title=name, body=body, source_type=source, status=status)
            c = create_chunk(db, m, content=body, ordinal=0)
            rows.append((m.id, c.id, body, source, c.index_version))
    records = [VectorRecord(chunk_id=c, material_id=m, content=body, source_type=source,
        index_version=version, ordinal=0, heading_path=()) for m,c,body,source,version in rows]
    stack.vector_store.upsert(records, stack.embedder.encode([r.content for r in records]))
    stack.keyword_index.rebuild(records)
    return rows


class Capture(FakeProvider):
    def complete(self, messages, *, attempt=1):
        self.messages = messages
        return super().complete(messages, attempt=attempt)


def test_default_all_ready_user_materials_without_selection(session_factory, stack):
    rows = seed_personal(session_factory, stack)
    session = daily_session(session_factory)
    assert session["scope_mode"] == "all" and not session["selected_file_ids"]
    p = Capture("两份笔记分别说明相似与合同 [C1]。"); sid = UUID(session["session_id"])
    message, citations, _ = answer(session_factory, session_id=sid,
        question="矩阵相似和合同的定义分别是什么？", stack=stack, provider=p)
    prompt = "\n".join(m["content"] for m in p.messages)
    assert "SIMILAR_A_201" in prompt and "CONGRUENT_B_202" in prompt
    assert all(marker not in prompt for marker in ("BUILTIN_204", "INDEXING_205", "FAILED_206"))
    assert citations and message.matched_kp_id is None
    assert "禁止用模型常识" in p.messages[0]["content"]


def test_selected_scope_and_return_to_all(session_factory, stack):
    rows = seed_personal(session_factory, stack); view = daily_session(session_factory); sid = UUID(view["session_id"])
    update_scope(session_factory, session_id=sid, scope_mode="selected", selected_file_ids=[rows[0][0]])
    p = Capture("所选相似笔记有可逆条件 [C1]。")
    _, citations, _ = answer(session_factory, session_id=sid, question="相似和合同有什么区别？", stack=stack, provider=p)
    assert "CONGRUENT_B_202" not in str(p.messages) and "BUILTIN_204" not in str(p.messages)
    with session_factory() as db:
        assert all(db.get(DocumentChunk, cid).material_id == rows[0][0] for _,cid in citations)
    update_scope(session_factory, session_id=sid, scope_mode="all", selected_file_ids=[])
    p = Capture("合同笔记给出转置 [C1]。")
    answer(session_factory, session_id=sid, question="矩阵合同的定义是什么？", stack=stack, provider=p)
    assert "CONGRUENT_B_202" in str(p.messages)


@pytest.mark.parametrize("invalid", ["empty", "missing", "builtin", "indexing", "failed"])
def test_server_validates_selected_scope(session_factory, stack, invalid):
    rows = seed_personal(session_factory, stack); sid = UUID(daily_session(session_factory)["session_id"])
    ids = {"empty": [], "missing": [uuid4()], "builtin": [rows[3][0]], "indexing": [rows[4][0]], "failed": [rows[5][0]]}[invalid]
    with pytest.raises(AppError):
        update_scope(session_factory, session_id=sid, scope_mode="selected", selected_file_ids=ids)
    assert daily_session(session_factory)["scope_mode"] == "all"


def test_empty_materials_have_no_model_or_builtin_fallback(session_factory, stack):
    with session_factory.begin() as db:
        m = create_material(db, title="系统资料", body="仅系统资料", source_type="builtin")
        create_chunk(db, m, content="仅系统资料", ordinal=0)
    p = FakeProvider("不该调用")
    m,c,_ = answer(session_factory, session_id=UUID(daily_session(session_factory)["session_id"]),
        question="解释红黑树", stack=stack, provider=p)
    assert p.calls == 0 and not c and "还没有可检索的个人资料" in m.content


def test_followup_retrieves_again_with_bounded_current_day_context(session_factory, stack, monkeypatch):
    seed_personal(session_factory, stack); sid = UUID(daily_session(session_factory)["session_id"])
    from backend.chat import service
    queries = []; original = service.search_chunks
    def capture(db, **kwargs):
        queries.append(kwargs["request"])
        return original(db, **kwargs)
    monkeypatch.setattr(service, "search_chunks", capture)
    answer(session_factory, session_id=sid, question="矩阵相似的条件是什么？", stack=stack, provider=FakeProvider("可逆条件 [C1]。"))
    p = Capture("合同使用转置 [C1]。")
    answer(session_factory, session_id=sid, question="那它和合同有什么区别？", stack=stack, provider=p)
    assert len(queries) == 2 and "矩阵相似的条件" in queries[-1].query and "合同" in queries[-1].query
    assert "CONGRUENT_B_202" in str(p.messages)
    with session_factory.begin() as db:
        for i in range(30): db.add(ChatMessage(session_id=sid, role="assistant", status="completed", content="长记录" * 500))
    p = Capture("相似需要可逆变换 [C1]。")
    answer(session_factory, session_id=sid, question="相似的条件是什么？", stack=stack, provider=p)
    assert len(p.messages) <= 15 and sum(m["content"].count("长记录") for m in p.messages) < 3000


def test_same_day_restores_single_session_and_messages(session_factory):
    now = datetime.now(timezone.utc); first = daily_session(session_factory, now=now)
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=UUID(first["session_id"]), role="user", status="completed", content="当天问题"))
    for _ in range(3): assert daily_session(session_factory, now=now)["session_id"] == first["session_id"]
    with session_factory() as db:
        assert len(list(db.scalars(select(ChatSession).where(ChatSession.purpose=="material_search")))) == 1
        assert db.scalar(select(ChatMessage).where(ChatMessage.session_id==UUID(first["session_id"]))).content == "当天问题"


def test_calendar_cleanup_deletes_only_material_search_and_preserves_files(session_factory, stack, tmp_path):
    rows = seed_personal(session_factory, stack)
    # Only twenty minutes apart but on opposite local calendar dates.
    start = datetime(2026,10,7,15,50,tzinfo=timezone.utc); end = start + timedelta(minutes=20)
    first = daily_session(session_factory, now=start); old_id = UUID(first["session_id"])
    disk = tmp_path / "personal.md"; disk.write_text(rows[0][2], encoding="utf-8")
    with session_factory.begin() as db:
        reply = ChatMessage(session_id=old_id, role="assistant", status="completed", content="依据 [C1]。")
        db.add(reply); db.flush(); reply_id = reply.id
        db.add(MessageCitation(message_id=reply.id, chunk_id=rows[0][1], label="C1", ordinal=1))
        keep = []
        for purpose in ("qa", "study", "materials"):
            s=ChatSession(mode="builtin" if purpose!="materials" else "user", purpose=purpose, study_date=first["study_date"])
            db.add(s); db.flush(); keep.append(s.id)
            db.add(ChatMessage(session_id=s.id, role="user", status="completed", content="其他会话保留"))
        before_files=[(m.id,m.normalized_text,m.active_index_version,m.content_hash) for m in db.scalars(select(Material))]
        before_chunks=[(c.id,c.content,c.index_version) for c in db.scalars(select(DocumentChunk))]
    new = daily_session(session_factory, now=end)
    assert local_day(start) != local_day(end) and new["session_id"] != first["session_id"]
    assert daily_session(session_factory, now=end)["session_id"] == new["session_id"]
    with session_factory() as db:
        assert db.get(ChatSession, old_id) is None and db.get(ChatMessage, reply_id) is None
        assert not list(db.scalars(select(MessageCitation).where(MessageCitation.message_id==reply_id)))
        assert all(db.get(ChatSession, sid) for sid in keep)
        assert before_files==[(m.id,m.normalized_text,m.active_index_version,m.content_hash) for m in db.scalars(select(Material))]
        assert before_chunks==[(c.id,c.content,c.index_version) for c in db.scalars(select(DocumentChunk))]
    assert disk.read_text(encoding="utf-8") == rows[0][2] and stack.keyword_index.count()==6


def test_deleted_selected_file_cannot_be_retrieved_and_history_survives(session_factory, stack):
    rows = seed_personal(session_factory, stack); sid = UUID(daily_session(session_factory)["session_id"])
    update_scope(session_factory, session_id=sid, scope_mode="selected", selected_file_ids=[rows[0][0]])
    answer(session_factory, session_id=sid, question="相似是什么？", stack=stack, provider=FakeProvider("相似条件 [C1]。"))
    from backend.services.material_service import delete_material
    from pathlib import Path
    with session_factory() as db:
        delete_material(db, material_id=rows[0][0], materials_root=Path("storage/tests"), vector_store=stack.vector_store, keyword_index=stack.keyword_index)
    p=FakeProvider("不应该使用旧资料回答")
    m,c,_=answer(session_factory, session_id=sid, question="那它的条件呢？", stack=stack, provider=p)
    assert p.calls==0 and not c and "已删除" in m.content
    with session_factory() as db: assert db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid, ChatMessage.content=="相似条件 [C1]。"))


def test_material_model_cannot_output_a_general_reference(session_factory, stack):
    seed_personal(session_factory,stack); sid=UUID(daily_session(session_factory)["session_id"])
    p=FakeProvider("## 通用知识参考\n我可以根据常识编一个说明。")
    message,c,_=answer(session_factory,session_id=sid,question="相似是什么？",stack=stack,provider=p)
    assert "通用知识参考" not in message.content and not c and "没有在你的资料" in message.content


def test_stream_does_not_leak_unsupported_background(session_factory,stack):
    seed_personal(session_factory,stack);sid=UUID(daily_session(session_factory)["session_id"])
    class Request:
        async def is_disconnected(self): return False
    async def run():
        return b"".join([f async for f in stream_answer(session_factory,request=Request(),session_id=sid,
            question="相似是什么？",stack=stack,provider=FakeProvider("相似条件 [C1]。\n## 通用知识参考\nEXTERNAL_SECRET"))]).decode()
    frames=asyncio.run(run())
    assert "EXTERNAL_SECRET" not in frames and "通用知识参考" not in frames and "相似条件" in frames


def test_api_daily_scope_and_history_visibility(session_factory,stack):
    from backend.app import create_app
    from backend.config import get_settings
    app=create_app(); app.state.session_factory=session_factory;app.state.settings=get_settings();app.state.instance_lock_lost=False
    app.state.retrieval_stack=stack
    with session_factory.begin() as db:
        s=ChatSession(mode="builtin",purpose="qa"); db.add(s);db.flush()
        db.add(ChatMessage(session_id=s.id,role="user",status="completed",content="普通问答"))
    client=TestClient(app)
    view=client.post("/api/chat/material-search/session").json()
    assert view["scope_mode"]=="all"
    assert client.post("/api/chat/material-search/session").json()["session_id"]==view["session_id"]
    bad=client.patch("/api/chat/material-search/scope",json={"session_id":view["session_id"],"scope_mode":"selected","selected_file_ids":[]})
    assert bad.status_code==422
    response=client.post(f'/api/chat/sessions/{view["session_id"]}/answers:stream',json={"question":"解释红黑树"})
    assert response.status_code==200 and "还没有可检索的个人资料" in response.text
    assert all(s["purpose"]!="material_search" for s in client.get("/api/chat/sessions").json())
