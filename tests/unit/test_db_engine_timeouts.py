"""数据库探活的超时契约回归测试。

背景（阶段 A 实测缺陷）：系统 PostgreSQL 被停止后，`GET /api/health` 既不返回 200 也不返回 503，
而是**超过 90 秒无任何响应**。原因是 psycopg 在没有 `connect_timeout` 时建连会长时间挂起，
而本项目是单进程 uvicorn，建连阻塞会占住事件循环，连 503 都发不出去。

修复：`create_db_engine()` 显式设置建连超时与连接池等待上限。
下面的测试锁死这条契约，防止有人把它改回去。

说明：`connect_args` 不会出现在 `dialect.create_connect_args()` 的返回值里（那是从 URL 推导的
参数）。SQLAlchemy 把 `connect_args` 绑定在连接池的 creator 闭包上，所以这里按实际存放位置断言，
并用“连到必然拒绝的端口必须快速失败”做行为验证。
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.db import (
    DB_CONNECT_TIMEOUT_SECONDS,
    DB_POOL_TIMEOUT_SECONDS,
    create_db_engine,
)

from tests.conftest import TEST_DATABASE_URL

# 必然不会有 PostgreSQL 监听的地址，用于验证“快速失败而不是挂死”。
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:1/kaoyan"


def _creator_connect_args(engine) -> dict[str, object]:
    """取出连接池 creator 闭包里的 DBAPI 连接参数。"""
    creator = engine.pool._creator  # type: ignore[attr-defined]
    closure = getattr(creator, "__closure__", None) or ()
    for cell in closure:
        value = cell.cell_contents
        if isinstance(value, dict):
            return value
    raise AssertionError("未能在连接池 creator 闭包中找到 connect_args")


def test_engine_passes_connect_timeout_to_driver() -> None:
    engine = create_db_engine(TEST_DATABASE_URL)
    try:
        # 缺少 connect_timeout 就会重现“挂死而不是 503”的缺陷。
        assert _creator_connect_args(engine)["connect_timeout"] == DB_CONNECT_TIMEOUT_SECONDS
        assert DB_CONNECT_TIMEOUT_SECONDS > 0
    finally:
        engine.dispose()


def test_engine_sets_pool_timeout() -> None:
    engine = create_db_engine(TEST_DATABASE_URL)
    try:
        assert engine.pool._timeout == DB_POOL_TIMEOUT_SECONDS  # type: ignore[attr-defined]
        assert DB_POOL_TIMEOUT_SECONDS >= DB_CONNECT_TIMEOUT_SECONDS
    finally:
        engine.dispose()


def test_unreachable_database_raises_quickly_instead_of_hanging() -> None:
    """连到必然拒绝的端口必须在远小于建连超时上限的时间内失败。"""
    engine = create_db_engine(UNREACHABLE_DATABASE_URL)
    try:
        started = time.monotonic()
        with pytest.raises(SQLAlchemyError):
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        elapsed = time.monotonic() - started
        # 留出充裕余量，但必须远小于“无限挂起”。
        assert elapsed < DB_CONNECT_TIMEOUT_SECONDS + 5, f"建连耗时 {elapsed:.1f}s 过久"
    finally:
        engine.dispose()
