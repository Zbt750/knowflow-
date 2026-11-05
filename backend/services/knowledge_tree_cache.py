"""短时缓存已组装的知识树读取模型。

缓存只用于减少重复的只读资格计算；相关业务表的 SQLAlchemy 提交后会失效。
HTTP 层共享不可变序列化字节，内部模型读取仍返回防御副本。数据库引擎也
作为缓存键的一部分，避免测试或多应用实例串用数据。
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session


# 本地单用户实例中，题目/学习相关ORM写入会立即失效；较长TTL让用户隔一段时间
# 再打开页面仍命中缓存。日期桶避免跨上海自然日复用时间相关的进度投影。
KNOWLEDGE_TREE_TTL_SECONDS = 3600.0
_INVALIDATION_FLAG = "knowledge_tree_cache_must_invalidate"
_TREE_TABLES = frozenset({
    # 树结构、知识状态与毕业策略/冻结题集。
    "knowledge_points", "kp_states", "kp_mastery_policies",
    "kp_graduation_question_set_versions",
    # 可练题资格、题目版本与审核依据。
    "questions", "question_versions", "question_auto_review_events",
    "question_answer_verification_events", "question_source_attestations",
    "question_answer_consistency_runs",
    # 节点活动、掌握证据和毕业后熟练度投影。
    "practice_items", "question_attempts", "learning_events",
})


@dataclass
class _Entry:
    bind: Any
    day_bucket: Any
    expires_at: float
    generation: int
    value: Any
    json_body: bytes | None
    etag: str | None


_LOCK = RLock()
_GENERATION = 0
_ENTRY: _Entry | None = None


def cache_generation() -> int:
    """记录开始构建时的提交世代，避免并发提交后写入过期快照。"""
    with _LOCK:
        return _GENERATION


def get_cached_knowledge_tree(*, bind: Any, day_bucket: Any) -> Any | None:
    """返回隔离副本，调用方修改响应对象也不会污染缓存。"""
    with _LOCK:
        entry = _ENTRY
        if (
            entry is None
            or entry.bind is not bind
            or entry.day_bucket != day_bucket
            or entry.expires_at <= monotonic()
            or entry.generation != _GENERATION
        ):
            return None
        return deepcopy(entry.value)


def get_cached_knowledge_tree_http(*, bind: Any, day_bucket: Any) -> tuple[bytes, str] | None:
    """HTTP readers share immutable bytes, never a mutable learning projection."""
    with _LOCK:
        entry = _ENTRY
        if (entry is None or entry.bind is not bind or entry.day_bucket != day_bucket
                or entry.expires_at <= monotonic() or entry.generation != _GENERATION
                or entry.json_body is None or entry.etag is None):
            return None
        return entry.json_body, entry.etag


def cache_knowledge_tree(*, bind: Any, day_bucket: Any, generation: int, value: Any) -> None:
    """仅缓存仍处于同一提交世代的完整结果。"""
    global _ENTRY
    with _LOCK:
        if generation != _GENERATION:
            return
        body = value.model_dump_json().encode('utf-8') if hasattr(value, 'model_dump_json') else None
        _ENTRY = _Entry(
            bind=bind,
            day_bucket=day_bucket,
            expires_at=monotonic() + KNOWLEDGE_TREE_TTL_SECONDS,
            generation=generation,
            value=deepcopy(value),
            json_body=body,
            etag='"' + sha256(body).hexdigest() + '"' if body is not None else None,
        )


def invalidate_knowledge_tree_cache() -> None:
    """显式失效缓存；每次成功数据库提交都会调用。"""
    global _ENTRY, _GENERATION
    with _LOCK:
        _GENERATION += 1
        _ENTRY = None


@event.listens_for(Session, "before_flush")
def _mark_tree_change_before_flush(session: Session, _flush_context, _instances) -> None:
    """只标记可能影响树响应的业务写入，避免资料worker的空提交冲掉缓存。"""
    if session.info.get(_INVALIDATION_FLAG):
        return
    for obj in (*session.new, *session.dirty, *session.deleted):
        table_name = getattr(getattr(type(obj), "__table__", None), "name", None)
        if table_name not in _TREE_TABLES:
            continue
        if obj not in session.dirty or session.is_modified(obj, include_collections=True):
            session.info[_INVALIDATION_FLAG] = True
            return


@event.listens_for(Session, "do_orm_execute")
def _mark_tree_bulk_dml(state) -> None:
    """覆盖 Session.execute/Query.update 等绕过普通 ORM dirty 集合的写入。"""
    if not (state.is_insert or state.is_update or state.is_delete):
        return
    mapper = state.bind_mapper
    table = getattr(mapper, "local_table", None)
    if table is None:
        table = getattr(state.statement, "table", None)
    if getattr(table, "name", None) in _TREE_TABLES:
        state.session.info[_INVALIDATION_FLAG] = True


@event.listens_for(Session, "after_commit")
def _invalidate_after_relevant_commit(session: Session) -> None:
    # 资料处理worker每秒会做空轮询提交；无关提交不能让知识树缓存永远失效。
    # 但所有能改变树投影的ORM与批量DML写入都会被前置事件标记。
    if session.info.pop(_INVALIDATION_FLAG, False):
        invalidate_knowledge_tree_cache()


@event.listens_for(Session, "after_rollback")
def _clear_rolled_back_change_marker(session: Session) -> None:
    session.info.pop(_INVALIDATION_FLAG, None)


def _reset_knowledge_tree_cache_for_tests() -> None:
    """测试专用的确定性清理入口。"""
    invalidate_knowledge_tree_cache()
