"""索引构建：解析 → 分块 → 写库 → 建向量 → 切换激活版本。

三条必须守住的性质：
1. **正文权威在 PostgreSQL**：先写 `document_chunks`，向量库只是派生索引；
2. **切换是原子的**：只有全部步骤成功才把 `active_index_version` 指向新版本，
   中途失败时旧版本继续可检索（`status` 保持 ready）；
3. **失败不留半个版本**：新版本的 chunks 与向量会被清理掉，重试不会累积垃圾。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.ingestion.chunker import DEFAULT_MAX_CHARS, ChunkDraft, build_chunk_drafts
from backend.ingestion.document_parsers import DocumentParseError, parse_source
from backend.ingestion.source_io import resolve_source_path
from backend.ingestion.text_normalize import material_content_hash
from backend.ingestion.title_tree import source_blocks_from_title_tree
from backend.models.chat import MessageCitation
from backend.models.learning import KnowledgePoint
from backend.models.rag import ChunkKnowledgePoint, DocumentChunk, Material
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.protocols import Embedder, VectorRecord, VectorStore

# 分块算法版本。任何会改变分块结果的修改都必须提升它，否则新旧 chunk 会混在一起。
CHUNK_ALGORITHM_VERSION = "chunk-v1"


class IngestionError(RuntimeError):
    """摄取失败；message 只允许放稳定错误码。"""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True)
class SourcePlan:
    """解析与分块的**纯内存**结果，尚未写任何库。

    存在的理由：索引版本号依赖 `content_hash`，而 `content_hash` 只有解析之后
    才知道。若先写库再算版本号，就会出现「先用占位版本写一遍、再用真实版本写一遍」，
    库里留下两倍块数。拆出这一步后就能先算版本号、再一次性写入。
    """

    normalized_text: str
    content_hash: str
    parser_version: str
    drafts: tuple[ChunkDraft, ...]
    diagnostics: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ParseOutcome:
    """解析+分块结果：已写库的 chunks 与解析诊断。"""

    normalized_text: str
    parser_version: str
    chunk_count: int
    diagnostics: tuple[str, ...] = field(default_factory=tuple)
    # 命中但未在知识点表里找到的 kp hint code；只做记录，不影响入库。
    unresolved_kp_codes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IndexOutcome:
    """一次索引构建的结果。"""

    index_version: str
    chunk_count: int
    embedded_count: int
    # 与上一版本内容完全相同的 chunk 数（重跑时应当等于总数）。
    reused_count: int = 0


def compute_index_version(content_hash: str, embedding_model: str) -> str:
    """索引版本号：只依赖「正文 hash + embedding 模型 + 分块算法版本」。

    刻意不掺入时间或随机值，因此同样的输入总是得到同一个版本号 ——
    重建索引时可以直接判断「这个版本已经建好了」，而不是盲目重跑。

    格式契约：`v1-<16 位十六进制>`。任何人解析这个字符串都必须能依赖该格式。
    """
    canonical = f"{content_hash}|{embedding_model}|{CHUNK_ALGORITHM_VERSION}|{DEFAULT_MAX_CHARS}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"v1-{digest}"


def is_valid_index_version(value: str) -> bool:
    """校验版本号格式：16 位小写十六进制前缀 v1-。"""
    if not value.startswith("v1-"):
        return False
    suffix = value[3:]
    return len(suffix) == 16 and all(char in "0123456789abcdef" for char in suffix)


def plan_material(material: Material, *, materials_root: Path) -> SourcePlan:
    """读取并解析源文件、切好块，但**不碰数据库**。

    这是唯一负责「文件 → 规范化文本 + 块」的地方；写库交给 `parse_material`。
    """
    try:
        source_path = resolve_source_path(materials_root, material.stored_path)
    except ValueError as error:
        raise IngestionError(str(error)) from error

    try:
        parsed = parse_source(source_path)
    except DocumentParseError as error:
        # code 是稳定业务码（会进数据库与界面），detail 只进日志。
        raise IngestionError(error.code, error.detail) from error
    except ValueError as error:
        # 其余解析器异常也是稳定错误码（unsupported_type / scanned_pdf / ...）。
        raise IngestionError(str(error)) from error

    normalized = parsed.normalized_text
    blocks = source_blocks_from_title_tree(normalized)
    drafts = build_chunk_drafts(normalized, blocks)
    return SourcePlan(
        normalized_text=normalized,
        content_hash=material_content_hash(normalized),
        parser_version=parsed.parser_version,
        drafts=tuple(drafts),
        diagnostics=parsed.diagnostics,
    )


def parse_material(
    session: Session,
    material: Material,
    *,
    plan: SourcePlan,
    index_version: str,
) -> ParseOutcome:
    """按 `index_version` 把 plan 里的块写入数据库（幂等：先删同版本旧块）。

    但**版本已存在且块数一致时不做删除重建**，直接复用现有块。
    为什么（真实缺陷，实测抓到）：删块会撞上 `message_citations.chunk_id` 的
    外键 —— 只要这份资料被问答引用过，旧的块就被聊天记录引用着，
    `DELETE FROM document_chunks` 直接抛 ForeignKeyViolation。
    后果是「重建索引」与「失败重试」对被引用过的资料**永久失败**，
    向量一条都写不进去（实测：向量库 0 条，任务 attempts=3 全 failed）。
    而重建的含义本来就是「同一份正文、同一套分块、同一个版本」，
    复用既保住块 id（聊天引用依然有效），又完全避免了这个冲突。
    """
    normalized = plan.normalized_text
    drafts = list(plan.drafts)

    # 版本已存在且块数一致 → 复用，什么都不动。
    existing_count = session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(
            DocumentChunk.material_id == material.id,
            DocumentChunk.index_version == index_version,
        )
    )
    if existing_count == len(drafts):
        # 元数据也要跟着更新时间戳：这仍是「一次成功的重建」，
        # 只是没有重新写块而已。
        material.normalized_text = normalized
        material.content_hash = plan.content_hash
        session.flush()
        return ParseOutcome(
            normalized_text=normalized,
            parser_version=plan.parser_version,
            chunk_count=existing_count,
            diagnostics=plan.diagnostics,
            unresolved_kp_codes=(),
        )

    # 块数不一致（分块逻辑变了，或上一轮是半成品）→ 必须先清干净再写。
    # 清之前要处理引用：被聊天记录引用着的块删不掉，而且它们引用的本来就是
    # 一个即将被替换的旧版本，留着只会让「删资料」这类操作继续被外键挡住。
    # 与 prepare_e2e_data.py 同一原则：先清引用、再清块。
    session.execute(
        delete(MessageCitation).where(
            MessageCitation.chunk_id.in_(
                select(DocumentChunk.id).where(
                    DocumentChunk.material_id == material.id,
                    DocumentChunk.index_version == index_version,
                )
            )
        )
    )
    _delete_chunks(session, material.id, index_version)

    # kp hint → 知识点 id；一次查清，避免每个块都查一次库。
    kp_ids_by_code = _load_kp_ids(session, {draft.kp_hint_code for draft in drafts})
    unresolved: set[str] = set()

    for draft in drafts:
        chunk = _insert_chunk(session, material, draft, index_version)
        if draft.kp_hint_code:
            kp_id = kp_ids_by_code.get(draft.kp_hint_code)
            if kp_id is None:
                unresolved.add(draft.kp_hint_code)
            else:
                # 显式标记 confidence=1.0：这是人工写的关联，不是模型猜的。
                session.add(
                    ChunkKnowledgePoint(chunk_id=chunk.id, kp_id=kp_id, confidence=1.0)
                )

    material.normalized_text = normalized
    material.content_hash = plan.content_hash
    session.flush()

    return ParseOutcome(
        normalized_text=normalized,
        parser_version=plan.parser_version,
        chunk_count=len(drafts),
        diagnostics=plan.diagnostics,
        unresolved_kp_codes=tuple(sorted(unresolved)),
    )


def build_index(
    session: Session,
    material: Material,
    *,
    index_version: str,
    embedder: Embedder,
    vector_store: VectorStore,
    keyword_index: KeywordIndex | None = None,
) -> IndexOutcome:
    """为已写库的某个版本建向量索引；全部成功才由调用方切换激活版本。"""
    chunks = list(
        session.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.material_id == material.id,
                DocumentChunk.index_version == index_version,
            )
            .order_by(DocumentChunk.ordinal)
        ).all()
    )
    if not chunks:
        raise IngestionError("no_chunk_to_index")

    records = [
        VectorRecord(
            chunk_id=chunk.id,
            material_id=material.id,
            index_version=index_version,
            ordinal=chunk.ordinal,
            content=chunk.content,
            heading_path=tuple(chunk.heading_path or ()),
            source_type=material.source_type,
            kp_hint_code=chunk.kp_hint_code,
            material_title=material.title,
        )
        for chunk in chunks
    ]

    try:
        embeddings = embedder.encode([record.content for record in records])
    except Exception as error:  # noqa: BLE001 - 模型不可用必须变成可识别错误码
        raise IngestionError("embedding_unavailable", str(error)) from error

    expected_dimension = getattr(embedder, "dimension", None)
    if expected_dimension is not None:
        for vector in embeddings:
            if len(vector) != expected_dimension:
                raise IngestionError("embedding_dimension_mismatch")

    vector_store.upsert(records, embeddings)

    # 注意：这里**不重建关键词索引**。此时资料状态还是 indexing，
    # 而关键词索引只收录 ready + 当前激活版本的块，此刻重建会得到空索引。
    # 正确时机是版本激活之后，由调用方显式调用 rebuild_keyword_index()。

    return IndexOutcome(
        index_version=index_version,
        chunk_count=len(records),
        embedded_count=len(embeddings),
    )


def activate_version(session: Session, material: Material, index_version: str) -> None:
    """把资料切到新版本。

    切换前必须确认新版本的块真的都在库里 —— 否则会出现「激活了一个空版本」，
    用户看到资料是 ready 却检索不到任何内容。
    """
    indexed = session.scalar(
        select(DocumentChunk.id)
        .where(
            DocumentChunk.material_id == material.id,
            DocumentChunk.index_version == index_version,
        )
        .limit(1)
    )
    if indexed is None:
        raise IngestionError("index_version_has_no_chunk")

    material.active_index_version = index_version
    material.status = "ready"
    material.last_error_code = None
    material.last_error_message = None
    session.flush()


def drop_version(
    session: Session,
    material: Material,
    *,
    index_version: str,
    vector_store: VectorStore,
) -> None:
    """丢弃一个未激活的版本（失败清理用）；已激活的版本不会被删。"""
    if material.active_index_version == index_version:
        return
    vector_store.delete_by_material(material.id, index_version)
    _delete_chunks(session, material.id, index_version)
    session.flush()


def _delete_chunks(session: Session, material_id: UUID, index_version: str) -> None:
    session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.material_id == material_id,
            DocumentChunk.index_version == index_version,
        )
    )


def _insert_chunk(
    session: Session,
    material: Material,
    draft: ChunkDraft,
    index_version: str,
) -> DocumentChunk:
    chunk = DocumentChunk(
        material_id=material.id,
        index_version=index_version,
        ordinal=draft.ordinal,
        content=draft.content,
        start_offset=draft.start_offset,
        end_offset=draft.end_offset,
        heading_path=list(draft.heading_path),
        content_hash=draft.content_hash,
        kp_hint_code=draft.kp_hint_code,
    )
    session.add(chunk)
    session.flush()
    return chunk


def _load_kp_ids(session: Session, codes: set[str | None]) -> dict[str, UUID]:
    wanted = {code for code in codes if code}
    if not wanted:
        return {}
    rows = session.execute(
        select(KnowledgePoint.code, KnowledgePoint.id).where(KnowledgePoint.code.in_(wanted))
    ).all()
    return {code: kp_id for code, kp_id in rows}


def _load_keyword_records(session: Session) -> list[VectorRecord]:
    """加载全部可检索记录（ready + 当前激活版本），用于重建关键词索引。"""
    rows = session.execute(
        select(DocumentChunk, Material)
        .join(Material, Material.id == DocumentChunk.material_id)
        .where(
            Material.status == "ready",
            Material.active_index_version.is_not(None),
            DocumentChunk.index_version == Material.active_index_version,
        )
    ).all()
    return [
        VectorRecord(
            chunk_id=chunk.id,
            material_id=material.id,
            index_version=chunk.index_version,
            ordinal=chunk.ordinal,
            content=chunk.content,
            heading_path=tuple(chunk.heading_path or ()),
            source_type=material.source_type,
            kp_hint_code=chunk.kp_hint_code,
            material_title=material.title,
        )
        for chunk, material in rows
    ]


def rebuild_keyword_index(session: Session, keyword_index: KeywordIndex) -> int:
    """从数据库重建关键词索引；返回纳入的记录数。"""
    records = _load_keyword_records(session)
    keyword_index.rebuild(records)
    return len(records)
