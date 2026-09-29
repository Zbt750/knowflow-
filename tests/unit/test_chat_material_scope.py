"""Named-file detail questions must not mix evidence from peer documents."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.chat import service


def material(title, filename=None):
    return SimpleNamespace(id=uuid4(), title=title, original_filename=filename)


@pytest.mark.parametrize("mode", ["user", "builtin"])
def test_named_file_detail_passes_file_and_mode_filters_to_retrieval(monkeypatch, mode):
    target = material("阶段A验收笔记", "验收.md")
    peer = material("网络笔记")
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [target, peer])
    monkeypatch.setattr(service, "_personal_file_scope_notice", lambda *_, **__: None)
    monkeypatch.setattr(service, "_overview_hits", lambda *_, **__: None)
    captured = []

    def search(_db, *, request, **_kwargs):
        captured.append(request)
        return SimpleNamespace(hits=[])

    monkeypatch.setattr(service, "search_chunks", search)
    db = SimpleNamespace(scalars=lambda *_: SimpleNamespace(all=lambda: []))
    service._search_pending(
        db, session_id=uuid4(), assistant_id=uuid4(), mode=mode,
        question="阶段A验收笔记里，健康检查应该怎样表现？",
        stack=SimpleNamespace(embedder=None, vector_store=None, keyword_index=None, reranker=None),
        history_token_budget=0,
    )

    assert len(captured) == 1
    assert captured[0].filters.material_ids == (target.id,)
    assert captured[0].filters.source_types == (mode,)


def test_file_reference_followup_uses_last_named_user_file(monkeypatch):
    target, peer = material("验收笔记"), material("数学讲义")
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [target, peer])
    monkeypatch.setattr(service, "_recent_user_context", lambda *_, **__: ["验收笔记讲了什么？"])

    ids, notice = service._detail_material_scope(
        None, session_id=uuid4(), question="这份文件的健康检查应该怎样表现？", mode="user"
    )

    assert ids == (target.id,)
    assert notice is None


@pytest.mark.parametrize("question", ["《不存在的文件》里健康检查怎么做？", "不存在.pdf 里面如何求导？"])
def test_missing_explicit_file_does_not_fall_back_to_only_available_file(monkeypatch, question):
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [material("数学讲义")])

    ids, notice = service._detail_material_scope(None, session_id=uuid4(), question=question, mode="user")

    assert ids is None
    assert notice is not None


def test_duplicate_named_files_require_disambiguation(monkeypatch):
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [material("验收笔记"), material("验收笔记")])

    ids, notice = service._detail_material_scope(
        None, session_id=uuid4(), question="验收笔记里健康检查怎么做？", mode="user"
    )

    assert ids is None
    assert notice is not None


def test_new_topic_without_file_reference_searches_whole_mode(monkeypatch):
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [material("验收笔记"), material("洛必达法则")])

    def unexpected_history_lookup(*_args, **_kwargs):
        raise AssertionError("A new topic must not inherit the previous file scope")

    monkeypatch.setattr(service, "_recent_user_context", unexpected_history_lookup)
    ids, notice = service._detail_material_scope(
        None, session_id=uuid4(), question="什么是洛必达法则？", mode="user"
    )

    assert ids is None
    assert notice is None


def test_quoted_topic_is_not_mistaken_for_missing_file(monkeypatch):
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [material("语文讲义")])
    ids, notice = service._detail_material_scope(
        None, session_id=uuid4(), question="解释《春江花月夜》的写作手法", mode="user"
    )
    assert ids is None
    assert notice is None
