"""重排：默认不重排（按融合分），配置了模型才启用 cross-encoder。

降级原则：
- `RERANKER_MODEL` 为空 → 直接用融合顺序，这不是「失败」而是正常配置；
- 配置了模型但加载失败 → 记录降级原因，仍然返回融合顺序的结果，
  绝不因为重排不可用就让整个检索失败。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol, Sequence

from backend.retrieval.protocols import RetrievalHit


@dataclass(frozen=True)
class RerankOutcome:
    """重排结果：命中列表 + 是否发生了降级 + 降级原因。"""

    hits: list[RetrievalHit]
    degraded: bool = False
    degraded_reason: str | None = None
    model_name: str | None = None


class Reranker(Protocol):
    """按「查询与文档的相关性」重新排序。"""

    @property
    def model_name(self) -> str | None: ...

    def rerank(
        self, query: str, hits: Sequence[RetrievalHit], *, top_k: int
    ) -> RerankOutcome: ...


class IdentityReranker:
    """不重排：保持融合顺序。这是默认配置，也是内存/离线场景的降级目标。"""

    @property
    def model_name(self) -> str | None:
        return None

    def rerank(
        self, query: str, hits: Sequence[RetrievalHit], *, top_k: int
    ) -> RerankOutcome:
        # query 未使用；保留参数是为了与真实重排器保持同一接口。
        del query
        return RerankOutcome(hits=list(hits)[:top_k], model_name=None)


class CrossEncoderReranker:
    """cross-encoder 重排。模型延迟加载，加载失败时自动降级为不重排。"""

    def __init__(self, model_name: str, *, cache_dir: str | None = None) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()
        self._degraded_reason: str | None = None

    @property
    def model_name(self) -> str | None:
        return self._model_name

    def _ensure_model(self) -> object | None:
        """加载模型；失败时返回 None 并把原因记下来（只记录，不抛错）。"""
        if self._model is not None:
            return self._model
        if self._degraded_reason is not None:
            return None
        with self._lock:
            if self._model is not None:
                return self._model
            if self._degraded_reason is not None:
                return None
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(self._model_name, cache_folder=self._cache_dir)
            except Exception as error:  # noqa: BLE001 - 任何失败都必须降级而不是中断检索
                self._degraded_reason = f"reranker_unavailable:{type(error).__name__}"
                return None
        return self._model

    def rerank(
        self, query: str, hits: Sequence[RetrievalHit], *, top_k: int
    ) -> RerankOutcome:
        candidates = list(hits)
        if not candidates:
            return RerankOutcome(hits=[], model_name=self._model_name)

        model = self._ensure_model()
        if model is None:
            # 降级：顺序不变，但把原因带出去，方便接口层与日志说明「为什么没有重排」。
            return RerankOutcome(
                hits=candidates[:top_k],
                degraded=True,
                degraded_reason=self._degraded_reason,
                model_name=self._model_name,
            )

        pairs = [
            (
                query,
                "\n".join(
                    part
                    for part in (
                        hit.material_title,
                        " › ".join(hit.heading_path),
                        hit.content,
                    )
                    if part
                ),
            )
            for hit in candidates
        ]
        scores = model.predict(pairs)
        scored = [
            (float(score), position, hit)
            for position, (score, hit) in enumerate(zip(scores, candidates))
        ]
        # 分数降序；同分回到融合顺序，保证结果稳定。
        scored.sort(key=lambda item: (-item[0], item[1]))
        reranked = [
            _with_rerank_score(hit, score) for score, _, hit in scored[:top_k]
        ]
        return RerankOutcome(hits=reranked, model_name=self._model_name)


def _with_rerank_score(hit: RetrievalHit, score: float) -> RetrievalHit:
    """复制一份并写入重排分。

    `score` 会被改写成重排分（它是排序依据分），但必须把
    **融合分与原始余弦**一起带过去 —— 那两个是排查「它凭什么排这儿」
    以及上层判断相关性是否达标的依据，丢了就再也还原不出来。
    """
    return RetrievalHit(
        chunk_id=hit.chunk_id,
        material_id=hit.material_id,
        material_title=hit.material_title,
        source_type=hit.source_type,
        index_version=hit.index_version,
        ordinal=hit.ordinal,
        content=hit.content,
        heading_path=hit.heading_path,
        kp_ids=hit.kp_ids,
        score=score,
        fused_score=hit.fused_score,
        vector_score=hit.vector_score,
        vector_rank=hit.vector_rank,
        title_rank=hit.title_rank,
        keyword_rank=hit.keyword_rank,
        rerank_score=score,
    )


def build_reranker(model_name: str | None, *, cache_dir: str | None = None) -> Reranker:
    """按配置选择重排器；未配置时明确返回「不重排」。"""
    if not model_name:
        return IdentityReranker()
    return CrossEncoderReranker(model_name, cache_dir=cache_dir)
