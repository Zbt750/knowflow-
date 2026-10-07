"""embedding 实现。

三种实现共用同一协议：
- `SentenceTransformerEmbedder`：真实模型，进程内只加载一次并缓存；
- `FakeEmbedder`：测试用可控实现，词袋哈希 + 归一化，确定性且不依赖网络；
- `__getattr__` 风格的工厂 `get_embedder()`：按配置选择，模型不可用时抛
  `EmbeddingUnavailableError`，让上层给出「检索不可用」而不是 500 崩溃。
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import OrderedDict
from typing import Sequence

from backend.retrieval.protocols import EmbeddingUnavailableError

# 一份文本最多缓存多少个向量。检索与摄取都会重复编码相同文本，缓存能省下大量时间。
EMBEDDING_CACHE_SIZE = 4096


class FakeEmbedder:
    """确定性假 embedding：把文本映射到固定维度，语义无关但可比较。

    用途：在没有模型/网络的环境里验证检索链路的「接线」是否 Correct。
    它**不能**用来评价检索质量，任何质量结论都必须用真实模型跑。
    """

    def __init__(
        self,
        model_name: str = "fake-embedder-v1",
        dimension: int = 64,
        *,
        overrides: dict[str, list[float]] | None = None,
    ) -> None:
        if dimension <= 0:
            raise ValueError("dimension 必须为正")
        self._model_name = model_name
        self._dimension = dimension
        # 需要精确控制相似度的测试用它：给指定文本直接指定向量，
        # 否则「哪一路命中了」只能靠巧合，测不出真正的融合行为。
        self._overrides = {key: list(value) for key, value in (overrides or {}).items()}
        for vector in self._overrides.values():
            if len(vector) != dimension:
                raise ValueError("override 向量维度与 dimension 不一致")
        self.encode_calls: list[str] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> list[float]:
        if text in self._overrides:
            return list(self._overrides[text])
        vector = [0.0] * self._dimension
        # 按字符 bigram 投桶：相同文本得到相同向量，相似文本会有一部分重叠。
        normalized = text.strip()
        if not normalized:
            return vector
        grams = [normalized[i : i + 2] for i in range(max(len(normalized) - 1, 1))]
        for gram in grams:
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        self.encode_calls.extend(texts)
        return [self._vector(text) for text in texts]


class SentenceTransformerEmbedder:
    """真实模型实现。模型只在第一次 encode 时加载，失败时抛可识别的错误。"""

    def __init__(self, model_name: str, *, cache_dir: str | None = None) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model = None
        self._dimension: int | None = None
        self._lock = threading.Lock()
        # 相同文本重复编码很常见（同一 chunk 反复检索），用小容量 LRU 省时间。
        self._cache: "OrderedDict[str, list[float]]" = OrderedDict()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        # 尺寸要等模型加载后才知道；调用方在写入向量库前会先 encode 一次。
        if self._dimension is None:
            self._ensure_model()
        assert self._dimension is not None
        return self._dimension

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                # 延迟导入：不检索的进程（例如只跑迁移）不必付出加载代价。
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(
                    self._model_name,
                    cache_folder=self._cache_dir,
                    # 只用本地缓存，**不要联网探测**。
                    #
                    # 为什么必须显式加：`cache_folder` 里有模型时，sentence-transformers
                    # 仍然会去 huggingface.co 发 HEAD 请求（Hub 会检查是否有更新版本）。
                    # 本机实测这条请求在离线/被墙时不是立刻失败，而是**卡到 TCP 超时**
                    # （日志里的 `WinError 10060 ... huggingface.co`），单次几十秒；
                    # 叠加检索路径上的多次调用，一次问答的首字延迟被拖到 20~180 秒。
                    # 症状极具误导性：模型明明就在本地、数据库完全正常，页面却像卡死。
                    local_files_only=True,
                )
            except Exception as error:  # noqa: BLE001 - 任何加载失败都必须变成可降级错误
                # 依赖缺失与模型文件缺失要分开报，否则运维会被误导。
                # 实测踩过（Docker 部署）：容器里根本没装 sentence-transformers
                # （INSTALL_EMBED=0 是默认值），却报成「模型不可用」，
                # 于是排查方向全跑到模型文件上，而真正要做的是重建镜像。
                try:
                    import sentence_transformers  # noqa: F401
                except ImportError:
                    raise EmbeddingUnavailableError(
                        "embedding 依赖未安装（缺少 sentence-transformers）。"
                        "源码运行时执行 pip install -r requirements-embed.txt；"
                        "容器部署时要用 INSTALL_EMBED=1 重新构建镜像。"
                    ) from error
                raise EmbeddingUnavailableError(
                    f"embedding 模型不可用：{self._model_name}（依赖已装，"
                    f"模型文件缺失或不可读；请把模型预置到缓存目录）"
                ) from error
            self._model = model
            # sentence-transformers 6.x 把方法改名为 get_embedding_dimension，
            # 但旧版本只有旧名字；两个都试一次，避免因版本差异直接加载失败。
            get_dimension = getattr(model, "get_embedding_dimension", None) or getattr(
                model, "get_sentence_embedding_dimension"
            )
            self._dimension = int(get_dimension())

    def probe(self) -> str | None:
        """启动期探活：返回 None 表示可用，否则返回**不含敏感信息**的原因。

        为什么需要它（真实缺陷）：
        `RetrievalStack` 只是把 `SentenceTransformerEmbedder` 装配起来，而真正的
        模型加载是懒加载的（第一次 encode 才发生）。于是 `/api/health` 里那句
        `retrieval="ready" if stack is not None else "unavailable"` 永远报 ready ——
        哪怕依赖根本没装、模型文件也不在。

        实测后果（Docker 部署）：`/api/health` 返回 `retrieval: ready`，
        而资料摄取全部失败在 `embedding_unavailable`。两个信号互相矛盾，
        排查时先怀疑模型文件、再怀疑向量库，最后才发现是镜像里没有依赖。
        健康检查必须能回答「检索到底能不能用」，否则它只是在骗人。

        边界：这里只确认**依赖可导入**，不会真的把模型加载进内存
        （加载要 20 秒左右、几百 MB 常驻）。模型文件是否齐全会由第一次
        真实 encode 暴露，届时依然走既有的降级路径。只记异常类型名，
        绝不记完整异常文本（可能带路径）。
        """
        if self._model is not None:
            return None
        try:
            import sentence_transformers  # noqa: F401
        except ImportError as error:
            return f"missing_dependency:{type(error).__name__}"
        return None

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        self._ensure_model()
        assert self._model is not None

        pending = [text for text in texts if text not in self._cache]
        if pending:
            vectors = self._model.encode(
                pending,
                batch_size=16,
                # 归一化后余弦相似度与点积一致，向量库用 cosine 空间才是自洽的。
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            for text, vector in zip(pending, vectors):
                self._cache[text] = [float(value) for value in vector]
                if len(self._cache) > EMBEDDING_CACHE_SIZE:
                    self._cache.popitem(last=False)
        return [list(self._cache[text]) for text in texts]


_default_embedder: object | None = None
_default_lock = threading.Lock()


def get_embedder(model_name: str, *, cache_dir: str | None = None) -> object:
    """进程级单例：同一模型只加载一次，避免每个请求都付一次加载成本。"""
    global _default_embedder
    with _default_lock:
        if _default_embedder is None:
            _default_embedder = SentenceTransformerEmbedder(model_name, cache_dir=cache_dir)
        return _default_embedder


def reset_embedder_cache() -> None:
    """测试与脚本用：丢弃已缓存的模型实例。"""
    global _default_embedder
    with _default_lock:
        _default_embedder = None