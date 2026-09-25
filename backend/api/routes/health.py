from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.errors import SAFE_MESSAGES

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str
    # 只暴露 dev/test/prod 这种无敏感信息的环境标识。端到端测试用它拒绝误连开发库。
    environment: Literal["dev", "test", "prod"]
    # 检索栈状态：ready 表示模型与向量库都已就绪；unavailable 表示检索接口会返回 503。
    # 这两个字段只含状态与错误类型名，绝不含路径、连接串或密钥。
    retrieval: str = "unknown"
    # 为什么不可用（例如 missing_dependency:ModuleNotFoundError）。
    # 只含状态与异常类型名，绝不含路径、连接串或密钥。
    retrieval_reason: str | None = None
    worker: str = "unknown"
    # 只报告环境变量是否齐全与模型名；不返回密钥或接口地址。
    llm_configured: bool = False
    llm_model: str | None = None

def check_database(db: Session) -> bool:
    """只读探活：不碰业务表，失败返回 False，不把驱动异常抛给调用者。"""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # 只记录异常类型，绝不记录完整异常文本（可能含 URL 与密码）。
        logger.warning("database health check failed: %s", type(exc).__name__)
        return False
    return True


@router.get("/health", response_model=HealthResponse)
def health(
    request: Request, db: Session = Depends(get_db)
) -> HealthResponse | JSONResponse:
    """数据库可用返回 200，不可用返回统一的 503 错误契约。"""
    if not check_database(db):
        # 数据库不可用必须是 503，错误结构遵守唯一契约表。
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "database_unavailable",
                    "message": SAFE_MESSAGES["database_unavailable"],
                }
            },
        )
    stack = getattr(request.app.state, "retrieval_stack", None)
    runner = getattr(request.app.state, "job_runner", None)
    # 判定依据分两层：
    #   1) 栈在不在（装配失败时 app.state 里根本没有它）；
    #   2) 栈自己的探活结论 —— 模型是懒加载的，装配成功**不等于**能用。
    # 只判断第 1 层就是之前的真实缺陷：容器里没装 sentence-transformers、
    # 模型目录也是空的，health 却一直报 `retrieval: ready`，
    # 而资料摄取全部失败在 `embedding_unavailable`。两个信号互相矛盾，
    # 让部署排查从「模型文件」一路误查到「向量库」，最后才发现是镜像里没依赖。
    if stack is None:
        retrieval = "unavailable"
        # app.py 装配失败时已经把原因写进 app.state.retrieval_error
        # （形如 `VectorStoreError: <安全文案>`）。这里**只取异常类型名**，
        # 丢掉后半段文案：原生库的错误文本可能带绝对路径，
        # 而这是会暴露给浏览器/运维的健康检查响应。
        recorded = getattr(request.app.state, "retrieval_error", None)
        retrieval_reason = recorded.split(":", 1)[0] if recorded else "stack_not_built"
    else:
        available = bool(getattr(stack, "available", True))
        retrieval = "ready" if available else "unavailable"
        retrieval_reason = getattr(stack, "unavailable_reason", None)
    return HealthResponse(
        status="ok",
        database="connected",
        environment=request.app.state.settings.app_env,
        retrieval=retrieval,
        retrieval_reason=retrieval_reason,
        # 只有线程真的活着才算 running，避免「启动了但已经死掉」被报成正常。
        worker="running" if runner is not None and runner.health()["alive"] else "stopped",
        llm_configured=bool(
            request.app.state.settings.llm_api_key
            and request.app.state.settings.llm_api_key.get_secret_value()
            and request.app.state.settings.llm_base_url
            and request.app.state.settings.llm_model
        ),
        llm_model=request.app.state.settings.llm_model,
    )