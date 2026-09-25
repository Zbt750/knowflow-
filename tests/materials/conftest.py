"""资料接口与摄取流程测试的共享夹具。

这些测试覆盖「上传 → 队列 → 解析 → 建索引 → 可检索」的完整链路。
embedding 与向量库使用可控替身（真实模型太大、太慢，也不该出现在单元测试里），
其余全部打真实 PostgreSQL 与真实文件系统。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

# 必须在导入应用之前设置：测试绝不允许联网下载模型。
# 离线模式下模型加载会立刻失败，lifespan 会记录「检索不可用」并由夹具替换成替身，
# 既快又不会因为网络状况让测试变成偶发失败。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app import create_app
from backend.jobs.runner import MaterialJobRunner
from backend.retrieval.embedding import FakeEmbedder
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.rerank import IdentityReranker
from backend.retrieval.stack import RetrievalStack
from backend.retrieval.vector_store import InMemoryVectorStore

from tests.conftest import TEST_DATABASE_URL

RAG_TABLES = (
    "document_jobs",
    "chunk_knowledge_points",
    "document_chunks",
    "materials",
)


@pytest.fixture
def session_factory():
    from backend.db import create_db_engine, create_session_factory

    engine = create_db_engine(TEST_DATABASE_URL)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_rag_tables(session_factory) -> Iterator[None]:
    """清空资料相关表，并确保知识点树与策略存在（kp 关联要用到它们）。"""
    from scripts.seed import seed_all

    with session_factory() as db:
        db.execute(
            text("TRUNCATE TABLE " + ", ".join(RAG_TABLES) + " RESTART IDENTITY CASCADE")
        )
        # 知识点可能在别的测试里被清掉，这里保证基线存在且是幂等的。
        seed_all(db)
        db.commit()
    yield


@pytest.fixture
def materials_root(tmp_path: Path) -> Path:
    root = tmp_path / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder(dimension=64)


@pytest.fixture
def stack(embedder: FakeEmbedder) -> RetrievalStack:
    return RetrievalStack(
        embedder=embedder,
        vector_store=InMemoryVectorStore(embedding_model=embedder.model_name),
        keyword_index=KeywordIndex(),
        reranker=IdentityReranker(),
    )


@pytest.fixture
def client(
    session_factory, stack: RetrievalStack, materials_root: Path
) -> Iterator[TestClient]:
    """真实 lifespan（真数据库），但检索栈与资料目录换成测试专用。

    任务线程**不启动**：测试自己调用 `runner.run_once()`，
    断言才是确定性的，不会因为后台线程抢跑而变成偶发失败。
    """
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        # lifespan 已经起了一个真实的后台线程；必须立刻停掉它，
        # 否则它会和测试抢任务，断言结果时任务可能已经被它处理完，
        # 变成「任务凭空消失」的偶发失败。
        started_runner = getattr(app.state, "job_runner", None)
        if started_runner is not None:
            started_runner.stop()

        settings = app.state.settings
        original_upload_dir = settings.upload_dir
        # 上传接口读取的是 app.state.settings.upload_dir，因此这里必须一起改，
        # 否则文件会落到项目里的真实 storage/ 目录。
        settings.upload_dir = materials_root
        app.state.retrieval_stack = stack
        app.state.retrieval_error = None
        app.state.job_runner = MaterialJobRunner(
            session_factory=session_factory, stack=stack, materials_root=materials_root
        )
        try:
            yield test_client
        finally:
            settings.upload_dir = original_upload_dir
            app.state.job_runner = None


@pytest.fixture
def runner(
    client: TestClient, session_factory, stack: RetrievalStack, materials_root: Path
) -> MaterialJobRunner:
    """指向临时资料根目录的运行器：测试里直接 run_once() 把队列跑干。"""
    del client  # 仅用于确保应用已启动并且资料目录已就位
    return MaterialJobRunner(
        session_factory=session_factory,
        stack=stack,
        materials_root=materials_root,
        worker_id="test-worker",
    )
