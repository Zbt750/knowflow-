"""Real isolated retrieval; strict private bindings, no model/general fallbacks."""
from uuid import UUID
import pytest
from sqlalchemy import select
from tests.integration.test_chat_flow import session_factory,clean_tables,stack,embedder,FakeProvider,seed_builtin_material
from tests.retrieval.conftest import create_material,create_chunk
from backend.models.chat import ChatSession
from backend.retrieval.protocols import VectorRecord
from backend.chat.service import answer

@pytest.mark.parametrize('scope_size',[1,2])
def test_bound_private_scope_excludes_other_private_and_builtin_context(session_factory,stack,scope_size):
    records=[]
    with session_factory.begin() as db:
        for title,content,source in (("所选笔记","洛必达法则适用于0/0型，先核验条件。","user"),
            ("未选笔记","洛必达法则秘密标记PRIVATE_OTHER_319。","user"),
            ("内置讲义","洛必达法则秘密标记BUILTIN_OTHER_792。","builtin")):
            material=create_material(db,title=title,body=content,source_type=source)
            chunk=create_chunk(db,material,content=content,ordinal=0)
            records.append(VectorRecord(chunk_id=chunk.id,material_id=material.id,index_version=chunk.index_version,ordinal=0,content=content,heading_path=(),source_type=source))
        session=ChatSession(mode="user",purpose="materials",material_scope_ids=[str(r.material_id) for r in records[:scope_size]]);db.add(session);db.flush();sid=session.id
    stack.vector_store.upsert(records,stack.embedder.encode([r.content for r in records]));stack.keyword_index.rebuild(records)
    class Capture(FakeProvider):
        def complete(self,messages,*,attempt=1):self.messages=messages;return super().complete(messages,attempt=attempt)
    provider=Capture("所选资料说明先核验条件 [C1]。")
    result,citations,_=answer(session_factory,session_id=sid,question="洛必达法则怎样使用？",stack=stack,provider=provider)
    assert citations
    prompt="\n".join(m["content"] for m in provider.messages)
    if scope_size==1:assert "PRIVATE_OTHER_319" not in prompt
    assert "BUILTIN_OTHER_792" not in prompt
    with session_factory() as db:
        from backend.models.rag import DocumentChunk
        assert all(db.get(DocumentChunk,chunk_id).material_id in {r.material_id for r in records[:scope_size]} for _,chunk_id in citations)

def test_private_empty_evidence_cannot_use_builtin_or_general(session_factory,stack):
    seed_builtin_material(session_factory,stack)
    with session_factory.begin() as db:
        material=create_material(db,title="空范围",body="另一个主题",source_type="user")
        session=ChatSession(mode="user",purpose="materials",material_scope_ids=[str(material.id)]);db.add(session);db.flush();sid=session.id
    provider=FakeProvider("不应该调用常识模型")
    result,citations,_=answer(session_factory,session_id=sid,question="洛必达法则用于什么？",stack=stack,provider=provider)
    assert not citations and provider.calls==0 and result.metadata_["answer_source"]=="notice"

def test_unbound_legacy_private_session_cannot_bypass_scope_guard(session_factory,stack,monkeypatch):
    from backend.chat import service
    seed_builtin_material(session_factory,stack)
    with session_factory.begin() as db:
        session=ChatSession(mode='user');db.add(session);db.flush();sid=session.id
    def no_search(*a,**k):raise AssertionError('must not search unspecified private library')
    monkeypatch.setattr(service,'search_chunks',no_search)
    p=FakeProvider();result,citations,_=answer(session_factory,session_id=sid,question='我上传的资料如何定义极限？',stack=stack,provider=p)
    assert not citations and p.calls==0 and '选择具体资料' in result.content
