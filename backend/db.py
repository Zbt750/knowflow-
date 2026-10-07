from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# 建连超时（秒）。数据库主机不可达时驱动默认会长时间挂起；本项目是单进程 uvicorn，
# 一旦建连阻塞住事件循环，连 /api/health 的 503 都返回不了（实测 >90 秒无任何响应）。
DB_CONNECT_TIMEOUT_SECONDS = 5
# 从连接池取连接的等待上限（秒），避免请求在池上排队过久。
DB_POOL_TIMEOUT_SECONDS = 10


def create_db_engine(database_url: str) -> Engine:
    """创建共享 Engine；它管理连接池，不代表一次业务请求。"""
    return create_engine(
        database_url,
        # 取连接前先探活，避免连接失效后才在业务中报错。
        pool_pre_ping=True,
        # 单人本地开发的保守连接池上限。
        pool_size=5,
        max_overflow=5,
        # 让探活在数据库不可用时快速失败，从而如实返回 503 而不是把请求挂死。
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS},
        pool_timeout=DB_POOL_TIMEOUT_SECONDS,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """创建 Session 工厂；调用 factory() 才产生具体 Session。"""
    return sessionmaker(
        bind=engine,
        # 业务代码显式 flush/commit，避免一次查询意外把半成品写入数据库。
        autoflush=False,
        # SQLAlchemy 2.x 中保持显式事务语义，service 决定何时提交。
        autocommit=False,
        # commit 后响应转换仍可读取刚写入对象的字段，不会自动过期重查。
        expire_on_commit=False,
    )


def get_db(request: Request) -> Iterator[Session]:
    """为普通短请求提供 Session，异常时回滚，结束时关闭。"""
    # factory 在 lifespan 中只创建一次并保存到当前应用。
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    # 每个请求取得自己的 Session；这里不会自动提交事务。
    db = session_factory()

    try:
        # FastAPI 把 db 注入路由；路由结束后继续执行 finally。
        yield db
    except Exception:
        # service 或路由失败时撤销未提交的数据库改动。
        db.rollback()
        raise
    finally:
        # 关闭 Session，把连接归还给 Engine 的连接池。
        db.close()