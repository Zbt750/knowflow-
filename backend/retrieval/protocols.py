"""检索层的协议与数据结构。

为什么先定协议：
- 真实向量库与真实 embedding 模型在测试机上都可能不可用，
  检索链路的正确性（融合、过滤、重排、引用）必须能用可控替身验证；
- 上层服务只依赖这些协议，不直接依赖 chromadb / sentence_transformers。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence
from uuid import UUID


class EmbeddingUnavailableError(RuntimeError):
    """embedding 模型无法加载或不可用；上层必须降级而不是崩溃。"""


class VectorStoreError(RuntimeError):
    """向量库不可用或返回了不符合契约的数据。"""


@dataclass(frozen=True)
class IndexFilter:
    """向量库查询过滤条件。

    与文档契约的 SearchFilters 对应，四个字段都必须真正生效：
    - `material_ids`：只在指定资料内检索；
    - `excluded_material_ids`：显式排除（例如重新索引中的资料）；
    - `source_types`：builtin / user 过滤；
    - `index_versions`：只检索指定索引版本，避免把正在构建的版本混进结果。
    """

    material_ids: tuple[UUID, ...] | None = None
    excluded_material_ids: tuple[UUID, ...] = ()
    source_types: tuple[str, ...] | None = None
    index_versions: tuple[str, ...] | None = None

    def is_empty(self) -> bool:
        """过滤条件是否不可能匹配到任何东西（调用方可直接返回空结果）。"""
        if self.material_ids is not None and not self.material_ids:
            return True
        if self.source_types is not None and not self.source_types:
            return True
        if self.index_versions is not None and not self.index_versions:
            return True
        return False


@dataclass(frozen=True)
class VectorRecord:
    """写入向量库的一条记录；正文留在 PostgreSQL，向量库只存可检索的派生信息。"""

    chunk_id: UUID
    material_id: UUID
    index_version: str
    ordinal: int
    content: str
    heading_path: tuple[str, ...]
    source_type: str
    kp_hint_code: str | None = None
    # 资料名作为标题树根节点参与召回；正文向量仍只编码 content。
    material_title: str = ""


@dataclass(frozen=True)
class VectorHit:
    """向量检索命中的一条结果。"""

    chunk_id: UUID
    score: float
    # 向量库返回的原文；用于与 PostgreSQL 正文核对，防止索引陈旧。
    document: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class Embedder(Protocol):
    """把文本变成向量。实现必须保证同一文本永远得到同一向量。"""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    """向量库：写入、删除、查询、计数。"""

    def upsert(
        self, records: Sequence[VectorRecord], embeddings: Sequence[Sequence[float]]
    ) -> None: ...

    def delete_by_material(self, material_id: UUID, index_version: str) -> int: ...

    def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int,
        index_filter: IndexFilter | None = None,
    ) -> list[VectorHit]: ...

    def count(self) -> int: ...


@dataclass(frozen=True)
class SearchFilters:
    """对外检索过滤条件（API 层使用的稳定契约）。"""

    material_ids: tuple[UUID, ...] | None = None
    source_types: tuple[str, ...] | None = None
    index_versions: tuple[str, ...] | None = None
    excluded_material_ids: tuple[UUID, ...] = ()

    def to_index_filter(self) -> IndexFilter:
        return IndexFilter(
            material_ids=self.material_ids,
            excluded_material_ids=self.excluded_material_ids,
            source_types=self.source_types,
            index_versions=self.index_versions,
        )


@dataclass(frozen=True)
class RetrievalRequest:
    """一次检索请求。"""

    query: str
    top_k: int = 6
    candidate_k: int = 20
    filters: SearchFilters | None = None
    # 知识点过滤：只保留与这些知识点显式关联的 chunk。
    kp_ids: tuple[UUID, ...] | None = None
    # 多项/综合问题允许重排器先返回候选池，再用 MMR 选出相关且不重复的最终结果。
    diversify: bool = False


@dataclass(frozen=True)
class RetrievalHit:
    """检索结果：正文与出处，供引用回跳。"""

    chunk_id: UUID
    material_id: UUID
    material_title: str
    source_type: str
    index_version: str
    ordinal: int
    content: str
    heading_path: tuple[str, ...]
    kp_ids: tuple[UUID, ...]
    # **排序依据分**：默认等于 RRF 融合分；启用重排后会被改写成重排分。
    # 它的量纲随配置变化，因此**不要**用它做「相关性够不够」的阈值判断 ——
    # 那种判断要建在 vector_score（原始余弦）上。
    score: float
    # RRF 融合分（只由名次决定）。
    # 单独留一份，是为了启用重排时仍然看得到「融合阶段它排第几、得多少分」。
    fused_score: float | None = None
    # 原始向量余弦相似度，范围约 [-1, 1]。
    #
    # 为什么必须保留它：
    # RRF 完全按名次给分 —— 只要是第一名就必然拿到约 1/(60+1) ≈ 0.0164，
    # 与语义相不相关毫无关系。实测同一批数据（真实 embedding 模型）：
    #   正常问题（13 条）最高 cosine 0.5673~0.8253，融合分 0.0164~0.0328；
    #   越界问题（知识库里根本没有）cosine 0.3368，融合分却有 0.0315 ——
    # 越界用例的融合分比正常用例的**最低值还高**，完全无法区分；
    # 而 cosine 能把两者干净分开（0.3368 vs 最低 0.5673）。
    # 因此「相关性够不够」这类阈值只能建在 cosine 上。
    # 为 None 表示该块没有被向量路召回（纯关键词命中）。
    vector_score: float | None = None
    # 各路召回的原始名次（None 表示该路没召回），便于排查「为什么它排这么前」。
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None
    # 标题树路扩展得到的名次；None 表示未命中标题节点。
    title_rank: int | None = None
