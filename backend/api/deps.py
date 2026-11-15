from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from collections.abc import Callable

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker


def get_now() -> datetime:
    """当前时刻的唯一来源；直接调用时返回 UTC 当前时间。

    2026-11-13 R80：增加受控时钟偏移，用于跨天/七日调度验收。
    只在非生产环境生效；生产（APP_ENV=production）永远忽略该变量。
    偏移量随返回值生效，便于在报告里明确区分“真实等待”与“受控时钟模拟”。
    """
    import os
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    if os.environ.get("APP_ENV", "dev") == "production":
        return now
    offset = os.environ.get("KAOYAN_CLOCK_OFFSET_DAYS")
    if not offset:
        return now
    try:
        days = float(offset)
    except (TypeError, ValueError):
        return now
    return now + timedelta(days=days)


def get_time_provider() -> Callable[[], datetime]:
    """路由注入的是「取当前时间的函数」而不是某一个时刻。

    这样一个请求处理过程中所有 now 取值一致（可预期），同时测试可以整体替换时钟，
    不需要改系统时间就能验证跨天毕业。
    """
    return get_now


def get_db(request: Request) -> Iterator[Session]:
    """公共请求级 Session 依赖；转发到 backend.db.get_db。"""
    # 单独包一层，让路由只 import 本模块，测试覆盖依赖时目标唯一。
    from backend.db import get_db as _get_db

    yield from _get_db(request)


def get_session_factory(request: Request) -> sessionmaker[Session]:
    """后台任务与 SSE 需要独立会话时从这里取 factory，而不是请求级 Session。"""
    return request.app.state.session_factory