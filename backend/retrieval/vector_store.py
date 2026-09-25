"""向量库：Chroma 持久实现 + 内存实现（测试与无磁盘场景）。

设计要点：
- 向量库只是**可重建的派生索引**：正文权威在 PostgreSQL，删掉整个目录也不丢数据；
- 写入时必须带 `index_version`，查询时可按版本过滤，这样「新版本构建中」的
  向量绝不会混进检索结果；
- collection 元数据记录 `embedding_model`，查询前核对，
  避免用 A 模型写入、用 B 模型查询导致分数完全失真。
"""

from __future__ import annotations

import gc
import math
from pathlib import Path
from typing import Sequence
from uuid import UUID

from backend.retrieval.protocols import (
    IndexFilter,
    VectorHit,
    VectorRecord,
    VectorStoreError,
)

COLLECTION_NAME = "kaoyan_chunks"
# 余弦空间：与 embedding 的 normalize_embeddings=True 配套，点积即相似度。
COLLECTION_SPACE = "cosine"


def _filter_where(index_filter: IndexFilter | None) -> dict[str, object] | None:
    """把 IndexFilter 转成 Chroma 的 where 子句（只下推可表达的部分）。"""
    if index_filter is None:
        return None
    clauses: list[dict[str, object]] = []
    if index_filter.material_ids is not None:
        clauses.append({"material_id": {"$in": [str(v) for v in index_filter.material_ids]}})
    if index_filter.source_types is not None:
        clauses.append({"source_type": {"$in": list(index_filter.source_types)}})
    if index_filter.index_versions is not None:
        clauses.append({"index_version": {"$in": list(index_filter.index_versions)}})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _matches(metadata: dict[str, object], index_filter: IndexFilter | None) -> bool:
    """在 Python 侧复核对过滤条件。

    为什么不只依赖 Chroma 的 where：`$nin` 在元数据缺失时的行为不够直观，
    而且过滤是「宁可少召回也不能召回不该召回的」，需要一个显式、可测的判断。
    """
    if index_filter is None:
        return True
    material_id = str(metadata.get("material_id", ""))
    if index_filter.material_ids is not None:
        if material_id not in {str(v) for v in index_filter.material_ids}:
            return False
    if material_id and material_id in {str(v) for v in index_filter.excluded_material_ids}:
        return False
    if index_filter.source_types is not None:
        if str(metadata.get("source_type", "")) not in set(index_filter.source_types):
            return False
    if index_filter.index_versions is not None:
        if str(metadata.get("index_version", "")) not in set(index_filter.index_versions):
            return False
    return True


def record_metadata(record: VectorRecord) -> dict[str, object]:
    """写入向量库的元数据。

    只放检索与过滤真正需要的字段：正文放在 documents，其余留在 PostgreSQL。
    Chroma 元数据不接受 None，因此可空字段缺省时不写。
    """
    metadata: dict[str, object] = {
        "chunk_id": str(record.chunk_id),
        "material_id": str(record.material_id),
        "index_version": record.index_version,
        "ordinal": record.ordinal,
        "source_type": record.source_type,
        "heading_path": "\u001f".join(record.heading_path),
    }
    if record.kp_hint_code:
        metadata["kp_hint_code"] = record.kp_hint_code
    return metadata


def ensure_normalized(vector: Sequence[float]) -> None:
    """契约检查：写入/查询向量必须是归一化的有限值。

    非归一化向量在 cosine 空间里仍会被后端接受，但分数会失真 ——
    这种错误不报错却会悄悄毁掉排序，所以必须在入口拦住。
    """
    if not vector:
        raise VectorStoreError("向量不能为空")
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if not math.isfinite(norm) or norm == 0.0:
        raise VectorStoreError("向量包含非法数值")
    if abs(norm - 1.0) > 1e-3:
        raise VectorStoreError("向量必须归一化后才能写入 cosine 空间")


class InMemoryVectorStore:
    """内存向量库：接口与 Chroma 实现完全一致，供测试与降级使用。"""

    def __init__(self, *, embedding_model: str) -> None:
        self._embedding_model = embedding_model
        self._records: dict[str, tuple[VectorRecord, list[float]]] = {}

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    def upsert(
        self, records: Sequence[VectorRecord], embeddings: Sequence[Sequence[float]]
    ) -> None:
        if len(records) != len(embeddings):
            raise VectorStoreError("records 与 embeddings 数量不一致")
        for record, embedding in zip(records, embeddings):
            ensure_normalized(embedding)
            self._records[str(record.chunk_id)] = (record, [float(v) for v in embedding])

    def delete_by_material(self, material_id: UUID, index_version: str) -> int:
        targets = [
            key
            for key, (record, _) in self._records.items()
            if record.material_id == material_id and record.index_version == index_version
        ]
        for key in targets:
            del self._records[key]
        return len(targets)

    def delete_material_all_versions(self, material_id: UUID) -> int:
        """删除一份资料的所有版本向量；资料被删除时必须调用。"""
        targets = [
            key for key, (record, _) in self._records.items() if record.material_id == material_id
        ]
        for key in targets:
            del self._records[key]
        return len(targets)

    def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int,
        index_filter: IndexFilter | None = None,
    ) -> list[VectorHit]:
        ensure_normalized(embedding)
        if top_k <= 0:
            return []
        scored: list[tuple[float, VectorRecord]] = []
        for record, vector in self._records.values():
            metadata = record_metadata(record)
            if not _matches(metadata, index_filter):
                continue
            # 归一化向量的点积就是余弦相似度，范围约 [-1, 1]，越大越相关。
            score = sum(float(a) * float(b) for a, b in zip(embedding, vector))
            scored.append((score, record))
        # 分数降序；同分按 chunk_id 排序，保证同一次查询的结果稳定可复现。
        scored.sort(key=lambda item: (-item[0], str(item[1].chunk_id)))
        return [
            VectorHit(
                chunk_id=record.chunk_id,
                score=score,
                document=record.content,
                metadata=record_metadata(record),
            )
            for score, record in scored[:top_k]
        ]

    def count(self) -> int:
        return len(self._records)


class ChromaVectorStore:
    """Chroma 持久实现。"""

    def __init__(
        self,
        *,
        persist_directory: Path,
        embedding_model: str,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        try:
            import chromadb
        except ImportError as error:  # pragma: no cover - 依赖缺失属于环境问题
            raise VectorStoreError("chromadb 未安装，向量检索不可用") from error

        self._embedding_model = embedding_model
        persist_directory.mkdir(parents=True, exist_ok=True)
        try:
            self._client = chromadb.PersistentClient(path=str(persist_directory))
            self._collection_name = collection_name
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={
                    "hnsw:space": COLLECTION_SPACE,
                    # 记录写入时使用的模型，用来判断索引是否需要用当前配置重建。
                    "embedding_model": embedding_model,
                },
            )
            # 立刻读一次计数：这一步会真正打开 HNSW 段文件。
            # 索引损坏时（例如上次写入被强杀中断）必须在这里就抛出来，
            # 否则症状是「后端跑着跑着整个进程消失」，完全看不出与索引有关。
            self._collection.count()
        except Exception as error:  # noqa: BLE001 - 底层是 Rust 绑定，异常类型不稳定
            raise VectorStoreError(
                "向量索引无法打开（可能已损坏）。"
                "删除 storage/chroma 目录后重建索引即可恢复："
                f"{type(error).__name__}"
            ) from error

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    @property
    def collection_metadata(self) -> dict[str, object]:
        return dict(self._collection.metadata or {})

    def embedding_dimension(self) -> int | None:
        """集合实际使用的向量维度；集合里还没有向量时返回 None。

        为什么需要它（真实缺陷，实测踩到）：Chroma 的集合维度在**第一次写入时**
        由向量长度固化，之后写入维度不一致就直接抛
        `InvalidArgumentError: expecting embedding with dimension of 384, got 512`。
        这条错误发生在资料索引的深处，对外只表现为「任务 attempts 打满 + 向量库 0 条」，
        实测让排查先后误判成模型文件缺失、向量库损坏、外键冲突。

        查询顺序：
        1. `hnsw:dim` 元数据（不是所有 Chroma 版本都写这个键）；
        2. 读一条真实向量的长度 —— 最可靠，空集合时返回 None。
        """
        metadata = dict(self._collection.metadata or {})
        raw = metadata.get("hnsw:dim")
        if raw not in (None, 0, "0"):
            try:
                return int(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass
        try:
            sample = self._collection.get(limit=1, include=["embeddings"])
        except Exception:  # noqa: BLE001 - 老版本不支持 include 组合时不该让装配失败
            return None
        embeddings = sample.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            return None
        return len(embeddings[0])

    def assert_model_matches(self) -> None:
        """确认索引是用同一个模型建的；不一致时报错，而不是给出无意义的分数。"""
        stored = (self._collection.metadata or {}).get("embedding_model")
        if stored is not None and str(stored) != self._embedding_model:
            raise VectorStoreError(
                f"索引由 {stored} 建立，当前配置为 {self._embedding_model}，必须重建索引"
            )

    def upsert(
        self, records: Sequence[VectorRecord], embeddings: Sequence[Sequence[float]]
    ) -> None:
        if len(records) != len(embeddings):
            raise VectorStoreError("records 与 embeddings 数量不一致")
        if not records:
            return
        # 写入前先比一次维度：底层的报错是
        # `InvalidArgumentError: Collection expecting embedding with dimension
        # of 384, got 512` —— 它只说结果，不说原因（模型被换成了别的维度）。
        # 而这条错误会一路冒泡成「资料索引失败」，排查代价极高（实测花了很久）。
        if embeddings and len(embeddings[0]) != len(embeddings[-1]):
            raise VectorStoreError("同一批 embeddings 维度不一致，拒绝写入")
        existing = self.embedding_dimension()
        actual = len(embeddings[0])
        if existing is not None and existing != actual:
            raise VectorStoreError(
                f"向量库集合维度是 {existing}，本次要写入 {actual} 维 —— "
                f"说明 MODEL_CACHE_DIR 里的模型与建库时用的不是同一个"
                f"（不同模型的输出维度可能不同：bge-small-zh-v1.5 是 512 维，"
                f"bge-small-en-v1.5 是 384 维）。"
                f"请统一后重建索引（清空向量目录 + scripts/rebuild_all_indexes.py）"
            )
        for embedding in embeddings:
            ensure_normalized(embedding)
        # 向量 id 就是 chunk.id：重跑同一版本的索引是幂等覆盖，不会产生重复。
        self._collection.upsert(
            ids=[str(record.chunk_id) for record in records],
            embeddings=[[float(v) for v in embedding] for embedding in embeddings],
            metadatas=[record_metadata(record) for record in records],
            documents=[record.content for record in records],
        )

    def delete_by_material(self, material_id: UUID, index_version: str) -> int:
        where = {"$and": [{"material_id": str(material_id)}, {"index_version": index_version}]}
        existing = self._collection.get(where=where, include=[])
        ids = list(existing.get("ids") or [])
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def delete_material_all_versions(self, material_id: UUID) -> int:
        where = {"material_id": str(material_id)}
        existing = self._collection.get(where=where, include=[])
        ids = list(existing.get("ids") or [])
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int,
        index_filter: IndexFilter | None = None,
    ) -> list[VectorHit]:
        ensure_normalized(embedding)
        if top_k <= 0:
            return []
        # 过滤条件可能让真正可用的条数远少于 top_k，因此多取一些再在 Python 侧裁剪。
        fetch_k = max(top_k * 4, top_k)
        result = self._collection.query(
            query_embeddings=[[float(v) for v in embedding]],
            n_results=fetch_k,
            where=_filter_where(index_filter),
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: list[VectorHit] = []
        for index, chunk_id in enumerate(ids):
            metadata = dict(metadatas[index] or {}) if index < len(metadatas) else {}
            if not _matches(metadata, index_filter):
                continue
            distance = float(distances[index]) if index < len(distances) else 1.0
            hits.append(
                VectorHit(
                    chunk_id=UUID(str(chunk_id)),
                    # cosine 距离 → 相似度；越大越相关。
                    score=1.0 - distance,
                    document=documents[index] if index < len(documents) else None,
                    metadata=metadata,
                )
            )
            if len(hits) >= top_k:
                break
        return hits

    def count(self) -> int:
        return int(self._collection.count())

    def clear(self) -> int:
        """清空本 collection 的**全部**向量，返回清掉的条数。

        为什么需要它（而不是逐个 material 删）：
        `delete_material_all_versions` 只能按已知的 material_id 删。测试数据准备
        每轮都会用**新 UUID** 建资料，于是上一轮那批资料的向量再也无人认领 ——
        实测累积到 85 条（正常应为 17），而残留会拖慢检索、也让排查时的数据不可信。

        注意：清空的是**内容**、不是删掉 collection 本身。重建 collection 会让
        已经持有旧句柄的后端进程失效（实测表现为所有检索 500），
        所以这里只 `delete()` 里面的行。
        """
        existing = self._collection.get(include=[])
        ids = list(existing.get("ids") or [])
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def close(self) -> None:
        """释放底层文件句柄。

        Chroma 的持久客户端持有 sqlite3 连接与 mmap 文件；在 Windows 上
        只要不释放，包含它的临时目录就无法删除（WinError 32）。
        评估脚本与测试用临时目录建库，因此必须能显式关闭。
        """
        collection = getattr(self, "_collection", None)
        client = getattr(self, "_client", None)
        # 先断开引用，再触发一次回收，让底层连接随对象一起释放。
        self._collection = None  # type: ignore[assignment]
        self._client = None  # type: ignore[assignment]
        for target in (collection, client):
            reset = getattr(target, "reset", None)
            if callable(reset):
                try:
                    reset()
                except Exception:  # noqa: BLE001 - 释放失败不能影响调用方
                    pass
        gc.collect()
