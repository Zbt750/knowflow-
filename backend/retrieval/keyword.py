"""关键词索引：jieba 分词 + BM25。

为什么需要它：
正文向量检索擅长语义相近，但对**专有名词、公式名、代码式的精确串**经常失效；
正文 BM25 恰好相反。标题树 BM25 是独立的第三路：按资料名/章节名命中后向下扩展，
让文件与章节定位不依赖正文片段偶然命中。

实现取舍：
BM25 的语料统计需要全量文档，因此本层不做增量更新，而是从 PostgreSQL 的
document_chunks 全量重建（数据量在千级，重建很快且不可能与正文不一致）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from threading import RLock
from typing import Iterable, Sequence
from uuid import UUID

from backend.retrieval.protocols import IndexFilter, VectorRecord

# 纯标点与空白不进词表：它们只会稀释 BM25 的区分度。
PUNCTUATION_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """按词切分并过滤纯标点；分词器只在这里调用一次，保证召回与建索引口径一致。"""
    tokens: list[str] = []
    for token in _cut(text):
        stripped = token.strip().lower()
        if not stripped or PUNCTUATION_RE.match(stripped):
            continue
        tokens.append(stripped)
    return tokens


def _cut(text: str) -> list[str]:
    """延迟导入 jieba：不检索的进程（迁移、纯业务测试）不必付出首次加载成本。"""
    import jieba

    return list(jieba.lcut(text))


@dataclass
class KeywordIndex:
    """正文 BM25 与轻量标题树 BM25：支持过滤、标题节点命中和子树扩展。"""

    k1: float = 1.5
    b: float = 0.75
    # epsilon 是 rank_bm25 用来给负 IDF 设下限的系数。默认 0.25 会把「出现在
    # 超过半数文档里的词」的 IDF 直接压成 0 —— 在小语料库里这会让所有分数变 0、
    # 关键词路彻底失效。这里关掉下限（负数 IDF 保留符号），让常见词的贡献自然降低。
    epsilon: float = 0.0
    _records: dict[str, VectorRecord] = field(default_factory=dict)
    _tokens: dict[str, list[str]] = field(default_factory=dict)
    _bm25: object | None = None
    _order: list[str] = field(default_factory=list)
    _title_nodes: list[TitleNode] = field(default_factory=list)
    _title_bm25: object | None = None
    _snapshot_lock: RLock = field(default_factory=RLock, init=False, repr=False, compare=False)

    def rebuild(self, records: Sequence[VectorRecord]) -> None:
        """全量重建。重复调用得到完全相同的结果（顺序由 chunk_id 排序决定）。"""
        from rank_bm25 import BM25Okapi

        new_records = {str(record.chunk_id): record for record in records}
        new_tokens = {
            str(record.chunk_id): tokenize(_searchable_text(record)) for record in records
        }
        # 固定顺序：rank_bm25 的返回下标必须能稳定映射回 chunk_id。
        new_order = sorted(new_records)
        corpus = [new_tokens[key] for key in new_order]
        # 空语料时 BM25Okapi 会抛错，用 None 表示「没有可检索内容」。
        new_bm25 = (
            BM25Okapi(corpus, k1=self.k1, b=self.b, epsilon=self.epsilon)
            if corpus
            else None
        )
        nodes: dict[tuple[UUID, str, tuple[str, ...]], TitleNode] = {}
        for record in records:
            # 根节点代表整份资料；其下每个 heading prefix 代表一个可展开章节。
            paths = [()]
            paths.extend(record.heading_path[:depth] for depth in range(1, len(record.heading_path) + 1))
            for path in paths:
                key = (record.material_id, record.index_version, path)
                title_text = record.material_title if not path else " ".join(path)
                if title_text.strip():
                    nodes[key] = TitleNode(
                        material_id=record.material_id,
                        index_version=record.index_version,
                        source_type=record.source_type,
                        path=path,
                        text=title_text,
                    )
        new_title_nodes = sorted(
            nodes.values(),
            key=lambda node: (str(node.material_id), node.index_version, node.path),
        )
        title_corpus = [tokenize(node.text) for node in new_title_nodes]
        new_title_bm25 = (
            BM25Okapi(title_corpus, k1=self.k1, b=self.b, epsilon=self.epsilon)
            if any(title_corpus)
            else None
        )
        # Build off-lock, then publish one coherent snapshot. Readers keep their old
        # references while this tuple is swapped; no BM25 score can be paired with
        # a different record order during a background reindex.
        with self._snapshot_lock:
            self._records, self._tokens, self._order, self._bm25 = (
                new_records, new_tokens, new_order, new_bm25
            )
            self._title_nodes, self._title_bm25 = new_title_nodes, new_title_bm25

    def search(
        self,
        query: str,
        *,
        top_k: int,
        index_filter: IndexFilter | None = None,
    ) -> list[tuple[UUID, float]]:
        """返回 (chunk_id, score)，按分数降序；分数为 0 的结果不返回。"""
        if top_k <= 0:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        with self._snapshot_lock:
            bm25, order, records = self._bm25, self._order, self._records
        if bm25 is None:
            return []
        scores = bm25.get_scores(query_tokens)
        scored: list[tuple[float, str]] = []
        for position, key in enumerate(order):
            score = float(scores[position])
            if score <= 0:
                continue
            record = records[key]
            if not _passes_filter(record, index_filter):
                continue
            scored.append((score, key))
        # 同分按 chunk_id 排序，保证结果稳定。
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [(UUID(key), score) for score, key in scored[:top_k]]

    def record(self, chunk_id: UUID) -> VectorRecord | None:
        with self._snapshot_lock:
            return self._records.get(str(chunk_id))

    def search_title_tree(
        self,
        query: str,
        *,
        top_k: int,
        index_filter: IndexFilter | None = None,
    ) -> list[tuple[UUID, float]]:
        """检索标题节点并向下扩展其子树，返回去重后的 chunk 顺序。

        这是第三条独立召回路：它按资料名/章节名匹配，再把命中标题下的正文块
        展开。这样“某文件讲了什么”或“第三章的内容”不会只靠正文片段碰运气。
        """
        if top_k <= 0:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        with self._snapshot_lock:
            title_bm25, title_nodes, record_snapshot = (
                self._title_bm25, self._title_nodes, self._records
            )
        if title_bm25 is None:
            return []
        scores = title_bm25.get_scores(query_tokens)
        nodes = [
            (float(scores[position]), node)
            for position, node in enumerate(title_nodes)
            if float(scores[position]) > 0 and _node_passes_filter(node, index_filter)
        ]
        nodes.sort(
            key=lambda item: (
                -item[0], str(item[1].material_id), item[1].index_version, item[1].path
            )
        )

        expanded: list[tuple[UUID, float]] = []
        seen: set[str] = set()
        records = sorted(
            record_snapshot.values(),
            key=lambda record: (str(record.material_id), record.index_version, record.ordinal),
        )
        for score, node in nodes:
            for record in records:
                if record.material_id != node.material_id or record.index_version != node.index_version:
                    continue
                if not _passes_filter(record, index_filter):
                    continue
                if node.path and record.heading_path[: len(node.path)] != node.path:
                    continue
                key = str(record.chunk_id)
                if key in seen:
                    continue
                seen.add(key)
                expanded.append((record.chunk_id, score))
                if len(expanded) >= top_k:
                    return expanded
        return expanded

    def count(self) -> int:
        with self._snapshot_lock:
            return len(self._records)


def _searchable_text(record: VectorRecord) -> str:
    """正文 BM25 文本 = 资料名 + 标题路径 + 正文。

    标题路径里的知识点名称往往就是用户的查询词，把它排除会明显降低召回。
    """
    return "\n".join([record.material_title, *record.heading_path, record.content])


@dataclass(frozen=True)
class TitleNode:
    material_id: UUID
    index_version: str
    source_type: str
    path: tuple[str, ...]
    text: str


def _node_passes_filter(node: TitleNode, index_filter: IndexFilter | None) -> bool:
    if index_filter is None:
        return True
    if index_filter.material_ids is not None and node.material_id not in set(index_filter.material_ids):
        return False
    if node.material_id in set(index_filter.excluded_material_ids):
        return False
    if index_filter.source_types is not None and node.source_type not in set(index_filter.source_types):
        return False
    if index_filter.index_versions is not None and node.index_version not in set(index_filter.index_versions):
        return False
    return True


def _passes_filter(record: VectorRecord, index_filter: IndexFilter | None) -> bool:
    """与向量库保持同一套过滤语义，避免「向量被过滤、关键词没过滤」的不一致。"""
    if index_filter is None:
        return True
    if index_filter.material_ids is not None:
        if record.material_id not in set(index_filter.material_ids):
            return False
    if record.material_id in set(index_filter.excluded_material_ids):
        return False
    if index_filter.source_types is not None:
        if record.source_type not in set(index_filter.source_types):
            return False
    if index_filter.index_versions is not None:
        if record.index_version not in set(index_filter.index_versions):
            return False
    return True


def rebuild_from_records(records: Iterable[VectorRecord]) -> KeywordIndex:
    """便捷入口：给一批记录，得到可直接查询的索引。"""
    index = KeywordIndex()
    index.rebuild(list(records))
    return index
