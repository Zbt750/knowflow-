from __future__ import annotations

import logging
from threading import Event, Lock, Thread
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.api.routes.chat import router as chat_router
from backend.api.routes.health import router as health_router
from backend.api.routes.materials import router as materials_router
from backend.api.routes.study import router as study_router
from backend.api.routes.settings import router as settings_router
from backend.services.model_settings_service import load_local_settings
from backend.services.model_settings_service import is_loopback
from urllib.parse import urlsplit
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.errors import AppError, ErrorResponse, register_error_handlers
from backend.jobs.runner import MaterialJobRunner
from backend.models.chat import ChatMessage
from backend.retrieval.protocols import EmbeddingUnavailableError, VectorStoreError
from backend.retrieval.stack import build_retrieval_stack

logger = logging.getLogger(__name__)
INSTANCE_LOCK_HEARTBEAT_SECONDS = 10.0


def _watch_instance_lock(app: FastAPI, connection, stop: Event, io_lock: Lock) -> None:
    """Keep the advisory-lock session active and fail closed if its connection dies."""
    while not stop.wait(INSTANCE_LOCK_HEARTBEAT_SECONDS):
        try:
            with io_lock:
                connection.execute(text("SELECT 1"))
                connection.commit()
        except Exception:
            logger.exception("后端独占锁连接失效；本实例将停止接受请求")
            app.state.instance_lock_lost = True
            runner = getattr(app.state, "job_runner", None)
            if runner is not None:
                try:
                    runner.stop(timeout=1.0)
                except Exception:
                    logger.exception("独占锁丢失后停止资料任务线程失败")
            return


def _try_build_retrieval_stack(app: FastAPI, settings) -> bool:
    """尝试装配检索栈。

    启动时模型或向量库可能不可用（离线环境、模型缺失、索引损坏），但这**不能**
    让后端起不来：学习闭环与知识树完全不依赖检索。因此这里只记录原因，
    把「检索不可用」留到真正调用检索接口时以 503 返回。

    为什么必须在这里就把向量库打开并读一次：向量索引损坏时，
    后台任务线程第一次碰到它会让**整个进程消失**（无 traceback），
    症状是「后端跑着跑着就没了」，完全看不出与索引有关。
    启动时主动打开一次，就能把它变成一条明确的日志与一个 503。
    """
    try:
        stack = build_retrieval_stack(
            embedding_model=settings.embedding_model,
            reranker_model=settings.reranker_model,
            chroma_dir=settings.chroma_dir,
            model_cache_dir=settings.model_cache_dir,
        )
    except (EmbeddingUnavailableError, VectorStoreError) as error:
        # 只记异常类型与我们的安全文案，绝不记录可能含路径的底层异常全文。
        app.state.retrieval_stack = None
        app.state.retrieval_error = f"{type(error).__name__}: {error}"
        logger.warning("检索栈不可用，检索接口将返回 503：%s", error)
        return False
    except Exception as error:  # noqa: BLE001 - 原生库异常类型随版本变化
        # 兜底：宁可「检索不可用」，也不能让一个原生库异常把启动流程带走。
        app.state.retrieval_stack = None
        app.state.retrieval_error = f"{type(error).__name__}"
        logger.warning("装配检索栈时出现未预期错误，检索接口将返回 503：%s", type(error).__name__)
        return False

    app.state.retrieval_stack = stack
    app.state.retrieval_error = None
    return True


def _start_job_runner(app: FastAPI, settings) -> None:
    """启动资料处理线程，并把关键词索引先重建起来。

    关键词索引保存在内存里，进程重启就丢了；这里在启动时重建一次，
    否则「资料是 ready 的，但检索一个结果都没有」。
    """
    stack = app.state.retrieval_stack
    if stack is None:
        return
    session_factory = app.state.session_factory
    try:
        with session_factory() as session:
            indexed = stack.rebuild_keyword_index(session)
        logger.info("关键词索引已重建，纳入 %s 个块", indexed)
    except Exception:  # noqa: BLE001 - 索引重建失败不应阻止服务启动
        logger.exception("关键词索引重建失败；检索会退化为仅向量路")

    runner = MaterialJobRunner(
        session_factory=session_factory,
        stack=stack,
        materials_root=settings.upload_dir,
    )
    runner.start()
    app.state.job_runner = runner


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """管理应用进程中的连接池、本地目录、检索栈与后台任务线程。"""
    settings = load_local_settings(get_settings())

    # 可以重复创建；只创建目录，不下载模型或初始化 Chroma。
    for directory in (settings.upload_dir, settings.chroma_dir, settings.model_cache_dir):
        # parents=True 同时补齐 storage 等父目录；exist_ok=True 允许重启重复执行。
        directory.mkdir(parents=True, exist_ok=True)

    engine = create_db_engine(str(settings.active_database_url))
    ownership = None
    ownership_monitor = None
    ownership_stop = Event()
    ownership_io_lock = Lock()
    try:
        # 启动时先验证 URL、端口和密码，避免首个请求才暴露错误。
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        # 会话级 PostgreSQL 锁随连接/进程退出释放；禁止第二实例误恢复正在运行的任务。
        ownership = engine.connect()
        acquired = ownership.scalar(text("SELECT pg_try_advisory_lock(75020260927)"))
        ownership.commit()
        if not acquired:
            raise RuntimeError("同一数据库已有后端运行，请关闭重复实例")

        # 保存的不是业务数据，而是本进程共享的基础设施对象。
        app.state.settings = settings
        app.state.engine = engine
        app.state.instance_lock_lost = False
        app.state.session_factory = create_session_factory(engine)
        # 进程在 SSE 途中被停止时，生成占位没有机会走请求 finally；启动时恢复为可解释终态。
        with app.state.session_factory.begin() as session:
            session.query(ChatMessage).filter(ChatMessage.status == "generating").update({"status": "cancelled"})
        app.state.job_runner = None

        ownership_monitor = Thread(
            target=_watch_instance_lock,
            args=(app, ownership, ownership_stop, ownership_io_lock),
            name="database-instance-lock-heartbeat",
            daemon=True,
        )
        ownership_monitor.start()

        if _try_build_retrieval_stack(app, settings):
            _start_job_runner(app, settings)

        yield
    finally:
        ownership_stop.set()
        if ownership_monitor is not None:
            ownership_monitor.join(timeout=15.0)
        # 先停线程再放连接池，避免线程还在用已经 dispose 的 engine。
        try:
            runner = getattr(app.state, "job_runner", None)
            if runner is not None:
                runner.stop()
        finally:
            try:
                if ownership is not None:
                    try:
                        with ownership_io_lock:
                            ownership.execute(text("SELECT pg_advisory_unlock(75020260927)"))
                            ownership.commit()
                    finally:
                        ownership.close()
            finally:
                engine.dispose()


def create_app() -> FastAPI:
    """创建可测试的 FastAPI 实例。"""
    # 传入 lifespan 后，TestClient/uvicorn 都会在启动和关闭时执行上面的资源管理。
    app = FastAPI(title="Kaoyan KB", version="0.1.0", lifespan=lifespan,
        responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 405, 409, 422, 500, 503)})
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().allowed_web_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    @app.middleware("http")
    async def protect_mutations(request, call_next):
        if getattr(app.state, "instance_lock_lost", False):
            return JSONResponse(
                status_code=503,
                content=AppError("instance_lock_lost").to_payload(),
            )
        settings = getattr(app.state, "settings", get_settings())
        if settings.app_env == "dev" and request.url.path.startswith("/api/"):
            try:
                hostname = urlsplit("//" + request.headers.get("host", "")).hostname or ""
            except ValueError:
                hostname = ""
            if not is_loopback(hostname):
                return JSONResponse(status_code=403, content={"error": {"code": "invalid_request", "message": "本地服务不接受此主机的请求"}})
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/settings/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            # Origin 必须来自管理员配置的精确白名单；反向代理的 Host/base_url
            # 可能被 DNS rebinding 控制，不能自动把当前请求来源加入信任集合。
            permitted = set(settings.allowed_web_origins)
            if (origin is not None and origin not in permitted) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(status_code=403, content={"error": {"code": "invalid_request", "message": "不允许来自此页面的修改请求"}})
        return await call_next(request)
    # 所有 API 统一从 /api 开始；health 路由本身只声明 /health。
    app.include_router(health_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    # 学习闭环：今日练习卷、答案、自评与知识树。
    app.include_router(study_router, prefix="/api")
    # 资料库：上传、列表、详情、删除、重建与调试检索。
    app.include_router(materials_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    return app
