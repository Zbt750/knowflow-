"""资料服务：上传、列表、详情、删除、重建与重试。

状态机（与文档契约一致）：
    pending → indexing → ready
                       ↘ failed（可重试回 indexing）

关键约定：
- 资料记录与磁盘文件必须同时成功或同时失败，不留「有记录没文件」的孤儿；
- 删除资料时向量库也要清干净，否则会留下永远召不回、也删不掉的残影；
- 任何对外文本（错误摘要）都只放稳定错误码，绝不放绝对路径或堆栈。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.errors import AppError
from backend.ingestion.file_storage import delete_stored_file, save_upload_streaming
from backend.models.chat import MessageCitation
from backend.models.jobs import DocumentJob
from backend.models.rag import DocumentChunk, Material
from backend.retrieval.protocols import VectorStore
from backend.services.ingestion_service import compute_index_version

logger = logging.getLogger(__name__)

# 一次列表返回的最大条数：避免一次把整库拉进内存。
MAX_LIST_LIMIT = 100
# 详情页预览的 chunk 数上限。
DETAIL_CHUNK_PREVIEW = 5

# 落盘阶段可能抛出的错误码（来自 file_storage / source_io 的 ValueError）。
# 显式列出而不是直接把异常文本当错误码：只有白名单内的字符串才会成为对外错误码。
UPLOAD_ERROR_CODES = frozenset(
    {
        "unsupported_type",
        "file_too_large",
        "empty_file",
        "unsafe_storage_path",
        "material_file_not_found",
    }
)


def _upload_error_code(raw: str) -> str:
    """把落盘异常映射成白名单错误码；未知一律归为 invalid_request。"""
    return raw if raw in UPLOAD_ERROR_CODES else "invalid_request"


@dataclass(frozen=True)
class MaterialCreated:
    material_id: UUID
    title: str
    job_id: UUID
    stored_path: str
    file_size: int


async def create_material_record(
    session: Session,
    *,
    upload: UploadFile,
    title: str,
    materials_root: Path,
    source_type: str = "user",
    max_attempts: int = 3,
) -> MaterialCreated:
    """落盘 + 建记录 + 入队，三者顺序有意为之。

    顺序：先落盘 → 再建记录。反过来的话，落盘失败会留下指向不存在文件的记录。
    """
    if not title.strip():
        raise AppError("invalid_request", detail="资料标题不能为空")
    if source_type not in {"user", "builtin"}:
        raise AppError("invalid_request", detail="source_type 只能是 user 或 builtin")

    from backend.jobs.worker import enqueue_job

    material = Material(
        title=title.strip()[:200],
        source_type=source_type,
        original_filename=Path(upload.filename or "untitled").name,
        # 先占位，落盘拿到真实相对路径后覆盖；该字段非空所以不能留空字符串。
        stored_path="pending",
        status="pending",
    )
    session.add(material)
    session.flush()

    try:
        stored_path, file_size, raw_hash = await save_upload_streaming(
            upload, material_id=material.id, root=materials_root
        )
    except ValueError as error:
        # 大小超限、空文件、后缀不合法：把已建的占位记录回滚掉，不留孤儿。
        session.rollback()
        raise AppError(_upload_error_code(str(error)), detail=str(error)) from error

    material.stored_path = stored_path
    material.file_size = file_size
    material.raw_hash = raw_hash
    session.flush()

    job = enqueue_job(
        session, material_id=material.id, job_type="ingest", max_attempts=max_attempts
    )
    return MaterialCreated(
        material_id=material.id,
        title=material.title,
        job_id=job.id,
        stored_path=stored_path,
        file_size=file_size,
    )


def _material_list_conditions(
    *,
    status: str | None = None,
    source_type: str | None = None,
    q: str | None = None,
):
    conditions = []
    if status:
        conditions.append(Material.status == status)
    if source_type:
        conditions.append(Material.source_type == source_type)
    if q and q.strip():
        # autoescape 让输入的 %、_ 等字符按字面搜索，而不是成为 SQL 通配符。
        conditions.append(Material.title.icontains(q.strip(), autoescape=True))
    return conditions


def list_materials(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    source_type: str | None = None,
    q: str | None = None,
) -> list[Material]:
    # 新上传的排在前面，符合「我刚传的东西在哪」的使用直觉。
    statement = select(Material).where(*_material_list_conditions(status=status, source_type=source_type, q=q))
    statement = statement.order_by(Material.created_at.desc(), Material.id)
    return list(session.scalars(statement.offset(max(offset, 0)).limit(min(max(limit, 1), MAX_LIST_LIMIT))).all())


def count_materials(
    session: Session,
    *,
    status: str | None = None,
    source_type: str | None = None,
    q: str | None = None,
) -> int:
    statement = select(func.count()).select_from(Material).where(
        *_material_list_conditions(status=status, source_type=source_type, q=q)
    )
    return int(session.scalar(statement) or 0)


def get_material(session: Session, material_id: UUID) -> Material:
    material = session.get(Material, material_id)
    if material is None:
        raise AppError("material_not_found")
    return material


def material_chunk_count(session: Session, material_id: UUID) -> int:
    """只统计当前激活版本的块数：旧版本残留会让「块数」看起来对不上正文。"""
    material = session.get(Material, material_id)
    if material is None or not material.active_index_version:
        return 0
    return int(
        session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.material_id == material_id,
                DocumentChunk.index_version == material.active_index_version,
            )
        )
        or 0
    )


def list_chunks_preview(
    session: Session, material_id: UUID, *, limit: int = DETAIL_CHUNK_PREVIEW
) -> list[DocumentChunk]:
    material = session.get(Material, material_id)
    if material is None or not material.active_index_version:
        return []
    return list(
        session.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.material_id == material_id,
                DocumentChunk.index_version == material.active_index_version,
            )
            .order_by(DocumentChunk.ordinal)
            .limit(limit)
        ).all()
    )


def latest_job(session: Session, material_id: UUID) -> DocumentJob | None:
    """最近一次任务：详情页用它显示进度与错误码。"""
    return session.scalars(
        select(DocumentJob)
        .where(DocumentJob.material_id == material_id)
        .order_by(DocumentJob.created_at.desc(), DocumentJob.id.desc())
        .limit(1)
    ).first()


def delete_material(
    session: Session,
    *,
    material_id: UUID,
    materials_root: Path,
    vector_store: VectorStore,
    keyword_index=None,
) -> None:
    """删除资料：数据库记录 → 向量 → 关键词索引 → 磁盘文件。

    **顺序很关键：必须先删数据库记录，再清向量。**

    为什么不能反过来「先清向量、再删记录」：
    后台索引任务可能正在处理这份资料（例如用户刚点过「重建索引」）。
    如果先清向量，任务在它自己的检查点看到的资料仍然存在，于是继续往下写，
    等它写完向量时记录才被删掉 —— 结果就是一批**永远召不回、也无人清理**的
    孤儿向量。这个窗口正是「解析 + embedding 编码」的耗时，宽到足以稳定复现。

    数据库记录先消失之后，任务在写库前的检查会看到资料已不存在而直接收尾，
    竞态从根上消失；即使它已经开始写，这次清理也会把刚写的向量删掉。

    代价：极端情况下（清理向量时进程被杀）会留下孤儿向量。但那是**可恢复的**——
    `scripts/check_vector_orphans.py --clean` 能清掉，而且它们不会被检索到
    （检索层查不到正文会丢弃）。相比之下，反向顺序会稳定产生孤儿，必须避免。
    """
    material = get_material(session, material_id)
    stored_path = material.stored_path

    # 第零步：先清掉**指向这份资料分块的聊天引用**。
    #
    # 为什么必须在删记录之前做（用户可见缺陷，实测撞到）：
    # 三个约束凑在一起会让「被引用过的资料」永远删不掉 ——
    #   1. message_citations.chunk_id → document_chunks.id 是 **NO ACTION**（无 ON DELETE）；
    #   2. document_chunks.material_id → materials.id 是 **ON DELETE CASCADE**；
    #   3. message_citations.chunk_id 是 **NOT NULL**（也不能置空）。
    # 于是 `DELETE FROM materials` 会级联去删 document_chunks，而分块仍被引用着，
    # 直接抛 ForeignKeyViolation，接口返回 500。
    #
    # 与 D-46 是**同一个外键**：那次只修了「重建索引」这条路径（改成版本相同时复用块），
    # 删除路径漏了 —— 同一个根因只补了一半。
    #
    # 语义取舍（方案 A）：被删资料的历史引用一并清掉。理由是该引用指向的来源
    # 已被用户主动删除，留着它也没有可核验的对象，与产品「引用必须可核验」一致；
    # 老回答正文里的 `[C1]` 标记会成为悬空标记，这正是「来源已删除」的事实表现。
    chunk_ids = list(
        session.scalars(
            select(DocumentChunk.id).where(DocumentChunk.material_id == material_id)
        ).all()
    )
    if chunk_ids:
        removed = session.execute(
            delete(MessageCitation).where(MessageCitation.chunk_id.in_(chunk_ids))
        ).rowcount
        if removed:
            logger.info(
                "删除资料前清理聊天引用 material=%s citations=%d（引用指向的来源即将消失）",
                material_id,
                removed,
            )

    # 第一步：删掉数据库记录并立即提交，让后台任务尽早看到「资料已不存在」。
    session.delete(material)
    session.flush()
    session.commit()

    # 第二步：清理向量。失败不能静默吞掉 —— 向量库是派生索引，
    # 但残留会成为孤儿，所以记录警告并且仍然继续完成删除。
    try:
        vector_store.delete_material_all_versions(material_id)
    except Exception as error:  # noqa: BLE001 - 向量库是派生索引，失败不该阻断删除
        logger.warning(
            "删除资料时清理向量失败 material=%s error=%s；"
            "该资料的向量可能成为孤儿，可用 scripts/check_vector_orphans.py 检查",
            material_id,
            type(error).__name__,
        )

    # 第三步：关键词索引是内存索引，必须刷新，否则已删资料仍会被 BM25 召回，
    # 而检索层又会因为查不到正文把它丢掉，表现为「召回 N 条、最终 0 条」。
    if keyword_index is not None:
        from backend.services.ingestion_service import rebuild_keyword_index

        rebuild_keyword_index(session, keyword_index)

    # 文件删除失败不阻断：数据库记录已经没了，残留文件只是占空间，可由巡检清理。
    if stored_path and stored_path != "pending":
        try:
            delete_stored_file(materials_root, stored_path)
        except (OSError, ValueError):
            pass


def reindex_material(
    session: Session,
    *,
    material_id: UUID,
    max_attempts: int = 3,
) -> DocumentJob:
    """重建索引：新建一条 reindex 任务。

    为什么新建任务行而不是复用：任务行是「一次命令」的历史记录，
    复用会让「重试了几次、分别失败在哪」彻底丢失。
    """
    from backend.jobs.worker import enqueue_job

    material = get_material(session, material_id)
    material.status = "pending"
    material.last_error_code = None
    material.last_error_message = None
    session.flush()
    return enqueue_job(
        session, material_id=material.id, job_type="reindex", max_attempts=max_attempts
    )


def retry_material(
    session: Session,
    *,
    material_id: UUID,
    max_attempts: int = 3,
) -> DocumentJob:
    """重试失败资料：等价于再建一条 ingest 任务。"""
    from backend.jobs.worker import enqueue_job

    material = get_material(session, material_id)
    material.status = "pending"
    material.last_error_code = None
    material.last_error_message = None
    session.flush()
    return enqueue_job(
        session, material_id=material.id, job_type="ingest", max_attempts=max_attempts
    )


def material_stats(session: Session) -> dict[str, int]:
    """按状态统计资料数，供资料页顶部的概况显示。"""
    rows = session.execute(
        select(Material.status, func.count()).group_by(Material.status)
    ).all()
    stats = {"pending": 0, "indexing": 0, "ready": 0, "failed": 0}
    for status, count in rows:
        stats[str(status)] = int(count)
    stats["total"] = sum(value for key, value in stats.items() if key != "total")
    return stats


def expected_index_version(material: Material, embedding_model: str) -> str | None:
    """当前正文与模型对应的版本号；资料还没解析过则返回 None。

    用途：判断一份 ready 资料是不是「已经过期」（正文变了但索引还没重建）。
    """
    if not material.content_hash:
        return None
    return compute_index_version(material.content_hash, embedding_model)
