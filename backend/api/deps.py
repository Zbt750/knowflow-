from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from collections.abc import Callable

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker


def get_now() -> datetime:
    """当前时刻的唯一来源；直接调用时返回 UTC 当前时间。"""
    # 不要把 datetime.now() 直接写在路由里——那样跨天毕业就只能靠改系统时间测。
    return datetime.now(timezone.utc)


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