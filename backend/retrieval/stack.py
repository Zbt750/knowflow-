"""检索栈组装：把 embedder / 向量库 / 关键词索引 / 重排器装配成一个整体。

为什么需要这一层：
- 这四样都有「加载昂贵或需要共享状态」的特点（模型加载、索引缓存、向量目录），
  必须在一个进程里只建一次；
- 应用启动（lifespan）、后台 worker 与 API 请求必须用**同一个**实例，
  否则 worker 写进的索引在 API 侧看不见。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from backend.retrieval.embedding import SentenceTransformerEmbedder
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.protocols import Embedder, VectorStore, VectorStoreError
from backend.retrieval.rerank import Reranker, build_reranker
from backend.retrieval.vector_store import ChromaVectorStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievalStack:
    """一个进程内共享的检索组件集合。"""

    embedder: Embedder
    vector_store: VectorStore
    keyword_index: KeywordIndex
    reranker: Reranker
    # 启动时的一次性告警（例如重排模型不可用）会累积在这里，供健康检查暴露。
    startup_warnings: list[str] = field(default_factory=list)
    # 检索是否**真的**可用。默认 True，由 build 时的探活结果改写。
    # 为什么不能只看 `stack is not None`：模型是懒加载的，装配成功不等于能用，
    # 实测容器里连 sentence-transformers 都没装，health 却报 ready。
    available: bool = True
    # 探活失败的原因（只含状态与异常类型名，不含路径/连接串/密钥）。
    unavailable_reason: str | None = None
    availability_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_availability(self, available: bool, reason: str | None) -> None:
        with self.availability_lock:
            self.unavailable_reason = reason
            self.available = available

    def availability_snapshot(self) -> tuple[bool, str | None]:
        with self.availability_lock:
            return self.available, self.unavailable_reason

    def rebuild_keyword_index(self, session: Session) -> int:
        """从数据库全量重建关键词索引。

        关键词索引保存在内存里，进程重启就没了；启动时重建一次，
        之后每次索引构建都会顺带刷新。
        """
        from backend.services.ingestion_service import rebuild_keyword_index

        return rebuild_keyword_index(session, self.keyword_index)


def build_retrieval_stack(
    *,
    embedding_model: str,
    reranker_model: str | None,
    chroma_dir: Path,
    model_cache_dir: Path | None,
) -> RetrievalStack:
    """按配置装配检索栈。向量库不可用时会抛错，由调用方决定是否降级。"""
    cache = str(model_cache_dir) if model_cache_dir else None
    embedder = SentenceTransformerEmbedder(embedding_model, cache_dir=cache)
    vector_store = ChromaVectorStore(
        persist_directory=chroma_dir, embedding_model=embedding_model
    )
    # 模型一致性必须在这里就校验：不然后面每次检索都在给错分数。
    vector_store.assert_model_matches()
    # 冷启动不要为了读取输出维度就导入 PyTorch 或加载模型权重。
    # 已加载模型仍会与持久索引即时核对；真实写入/查询入口负责核验惰性维度。
    if isinstance(embedder, SentenceTransformerEmbedder):
        embedding_dimension = embedder.loaded_dimension
    else:
        embedding_dimension = embedder.dimension
    stored_dimension = vector_store.embedding_dimension()
    if (stored_dimension is not None and embedding_dimension is not None
            and stored_dimension != embedding_dimension):
        raise VectorStoreError(
            f"向量库集合维度 {stored_dimension} 与当前 embedding 模型 "
            f"{embedding_model} 的输出维度 {embedding_dimension} 不一致："
            f"请确认 MODEL_CACHE_DIR 里的模型就是建库时用的那一个，"
            f"或清空向量目录后按当前模型重建索引"
        )
    stack = RetrievalStack(
        embedder=embedder,
        vector_store=vector_store,
        keyword_index=KeywordIndex(),
        reranker=build_reranker(reranker_model, cache_dir=cache),
    )
    # 快速缺包检查在启动线程执行；存在时，再用后台线程验证真实依赖导入。
    # 依赖导入完成前保持 unavailable，避免健康检查把「包文件存在」误报成 ready。
    # 该检查不加载模型权重，也不阻塞学习服务启动。
    reason = embedder.probe()
    if reason is not None:
        stack.set_availability(False, reason)
        stack.startup_warnings.append(f"retrieval_degraded:{reason}")
    else:
        stack.set_availability(False, "dependency_probe_pending")

        def complete_probe(result: str | None) -> None:
            stack.set_availability(result is None, result)
            if result is not None:
                stack.startup_warnings.append(f"retrieval_degraded:{result}")

        embedder.probe_runtime_async(complete_probe)
    return stack


_lock = threading.Lock()
_cached: RetrievalStack | None = None


def get_retrieval_stack(
    *,
    embedding_model: str,
    reranker_model: str | None,
    chroma_dir: Path,
    model_cache_dir: Path | None,
) -> RetrievalStack:
    """进程级单例：多个请求与后台线程共享同一套索引与模型。"""
    global _cached
    with _lock:
        if _cached is None:
            _cached = build_retrieval_stack(
                embedding_model=embedding_model,
                reranker_model=reranker_model,
                chroma_dir=chroma_dir,
                model_cache_dir=model_cache_dir,
            )
        return _cached


def reset_retrieval_stack() -> None:
    """测试用：丢弃缓存的检索栈（例如换了临时目录）。"""
    global _cached
    with _lock:
        _cached = None
