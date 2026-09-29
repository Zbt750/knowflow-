"""资料库接口：上传、列表、详情、删除、重建、重试与调试检索。

设计要点：
- 上传接口**只负责落盘与入队**，立刻返回；索引构建在后台线程里做，
  否则用户要对着一个转圈的上传按钮等模型加载完；
- 检索接口的降级信息如实返回（`degraded` / `degraded_reasons`），
  不把「只有关键词路」伪装成完整检索；
- 所有对外字段都不含 stored_path 与任何绝对路径。
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.errors import AppError
from backend.jobs.runner import MaterialJobRunner
from backend.models.rag import DocumentChunk
from backend.retrieval.protocols import (
    EmbeddingUnavailableError,
    RetrievalRequest,
    SearchFilters,
    VectorStoreError,
)
from backend.retrieval.stack import RetrievalStack, build_retrieval_stack
from backend.schemas.materials import (
    ChunkPreviewView,
    MaterialChunkListResponse,
    MaterialDetail,
    MaterialContentResponse,
    MaterialJobView,
    MaterialListResponse,
    MaterialUploadResponse,
    MaterialView,
    SearchHitView,
    SearchRequest,
    SearchResponse,
)
from backend.services import material_service
from backend.services.retrieval_service import search_chunks

router = APIRouter(prefix="/materials", tags=["materials"])

# 块预览的截断长度：列表只需要一眼看清内容，不必回传全文。
PREVIEW_CHARS = 160


def get_materials_root(request: Request) -> Path:
    """资料根目录来自应用配置，绝不接受请求参数 —— 否则就成了任意文件读取。"""
    return Path(request.app.state.settings.upload_dir)


def get_retrieval_stack(request: Request) -> RetrievalStack:
    """取得检索栈；启动时装配失败的话在这里懒加载重试一次。

    为什么懒加载也要做：模型首次下载失败往往只是一次性网络问题，
    让用户必须重启后端才能用检索太苛刻。失败仍然如实返回 503。
    """
    stack = getattr(request.app.state, "retrieval_stack", None)
    if stack is not None:
        return stack

    settings = request.app.state.settings
    try:
        stack = build_retrieval_stack(
            embedding_model=settings.embedding_model,
            reranker_model=settings.reranker_model,
            chroma_dir=settings.chroma_dir,
            model_cache_dir=settings.model_cache_dir,
        )
    except (EmbeddingUnavailableError, VectorStoreError) as error:
        raise AppError("retrieval_unavailable", detail=str(error)) from error
    request.app.state.retrieval_stack = stack
    request.app.state.retrieval_error = None
    return stack


def get_job_runner(request: Request) -> MaterialJobRunner:
    runner = getattr(request.app.state, "job_runner", None)
    if runner is None:
        # 正常情况下 lifespan 一定建好了；缺失说明检索栈装配失败。
        raise AppError("retrieval_unavailable", detail="job runner is not started")
    return runner


def _to_view(material) -> MaterialView:
    return MaterialView.model_validate(material)


@router.post("", response_model=MaterialUploadResponse, status_code=201)
async def upload_material(
    request: Request,
    file: UploadFile,
    title: str = Query(min_length=1, max_length=200),
    source_type: str = Query(default="user"),
    db: Session = Depends(get_db),
    runner: MaterialJobRunner = Depends(get_job_runner),
    materials_root: Path = Depends(get_materials_root),
) -> MaterialUploadResponse:
    """上传一份资料并立即入队处理。"""
    created = await material_service.create_material_record(
        db,
        upload=file,
        title=title,
        materials_root=materials_root,
        source_type=source_type,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        # COMMIT 的连接错误可能发生在服务端提交后；不能盲删已成功提交的源文件。
        try:
            from backend.models.rag import Material
            with request.app.state.session_factory() as check:
                committed = check.get(Material, created.material_id) is not None
            if not committed:
                material_service.delete_stored_file(materials_root, created.stored_path)
        except Exception:
            # 数据库仍不可达时保留文件，比破坏可能已提交的记录更安全。
            import logging
            logging.getLogger(__name__).warning("上传提交失败，无法确认补偿状态，源文件待核对")
        raise

    material = material_service.get_material(db, created.material_id)
    # 唤醒后台线程：不依赖轮询周期，用户能立刻看到状态从 pending 变化。
    runner.notify()
    return MaterialUploadResponse(
        material=_to_view(material),
        job_id=created.job_id,
        message="已加入处理队列，状态会从 pending 变为 ready",
    )


@router.get("", response_model=MaterialListResponse)
def list_materials(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
) -> MaterialListResponse:
    materials = material_service.list_materials(
        db, limit=limit, offset=offset, status=status, source_type=source_type, q=q
    )
    stats = material_service.material_stats(db)
    return MaterialListResponse(
        items=[_to_view(material) for material in materials],
        total=material_service.count_materials(db, status=status, source_type=source_type, q=q),
        stats=stats,
    )


# 注意顺序：/search 必须在 /{material_id} 之前注册，
# 否则 "search" 会被当作 UUID 去解析而返回 422。
@router.post("/search", response_model=SearchResponse)
def search_materials(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    stack: RetrievalStack = Depends(get_retrieval_stack),
) -> SearchResponse:
    """调试用混合检索：与后续问答用的是同一条检索链路。"""
    retrieval_request = RetrievalRequest(
        query=payload.query,
        top_k=payload.top_k,
        candidate_k=payload.candidate_k,
        filters=SearchFilters(
            material_ids=tuple(payload.material_ids) if payload.material_ids else None,
            source_types=tuple(payload.source_types) if payload.source_types else None,
        ),
        kp_ids=tuple(payload.kp_ids) if payload.kp_ids else None,
    )
    try:
        outcome = search_chunks(
            db,
            request=retrieval_request,
            embedder=stack.embedder,
            vector_store=stack.vector_store,
            keyword_index=stack.keyword_index,
            reranker=stack.reranker,
        )
    except (EmbeddingUnavailableError, VectorStoreError) as error:
        raise AppError("retrieval_unavailable", detail=str(error)) from error
    except ValueError as error:
        raise AppError(str(error)) from error

    return SearchResponse(
        query=payload.query,
        hits=[
            SearchHitView(
                chunk_id=hit.chunk_id,
                material_id=hit.material_id,
                material_title=hit.material_title,
                source_type=hit.source_type,
                index_version=hit.index_version,
                ordinal=hit.ordinal,
                content=hit.content,
                heading_path=list(hit.heading_path),
                kp_ids=list(hit.kp_ids),
                score=hit.score,
                vector_rank=hit.vector_rank,
                keyword_rank=hit.keyword_rank,
                rerank_score=hit.rerank_score,
            )
            for hit in outcome.hits
        ],
        degraded=outcome.degraded,
        degraded_reasons=list(outcome.degraded_reasons),
        vector_candidates=outcome.vector_candidates,
        keyword_candidates=outcome.keyword_candidates,
        reranked=outcome.reranked,
    )


@router.get("/{material_id}", response_model=MaterialDetail)
def get_material(material_id: UUID, db: Session = Depends(get_db)) -> MaterialDetail:
    material = material_service.get_material(db, material_id)
    job = material_service.latest_job(db, material_id)
    return MaterialDetail.model_validate(
        {
            **_to_view(material).model_dump(),
            "chunk_count": material_service.material_chunk_count(db, material_id),
            "latest_job": MaterialJobView.model_validate(job) if job else None,
        }
    )


@router.get("/{material_id}/content", response_model=MaterialContentResponse)
def get_material_content(material_id: UUID, db: Session = Depends(get_db)) -> MaterialContentResponse:
    """读取已入库的规范化正文；文件路径与原始二进制不对外暴露。"""
    material = material_service.get_material(db, material_id)
    return MaterialContentResponse(title=material.title, text=material.normalized_text)

@router.get("/{material_id}/chunks", response_model=MaterialChunkListResponse)
def list_material_chunks(
    material_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    focus_chunk_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> MaterialChunkListResponse:
    """块预览：用来核对「这份资料实际被切成了什么」。"""
    material_service.get_material(db, material_id)
    total = material_service.material_chunk_count(db, material_id)
    chunks = material_service.list_chunks_preview(db, material_id, limit=limit)
    if focus_chunk_id is not None and all(chunk.id != focus_chunk_id for chunk in chunks):
        material = material_service.get_material(db, material_id)
        focused = db.scalar(
            select(DocumentChunk).where(
                DocumentChunk.id == focus_chunk_id,
                DocumentChunk.material_id == material_id,
                DocumentChunk.index_version == material.active_index_version,
            )
        )
        if focused is None:
            raise AppError("chunk_not_found")
        chunks.append(focused)
    items = [
        ChunkPreviewView(
            id=chunk.id,
            ordinal=chunk.ordinal,
            heading_path=list(chunk.heading_path or []),
            char_count=len(chunk.content),
            preview=chunk.content[:PREVIEW_CHARS],
            kp_hint_code=chunk.kp_hint_code,
        )
        for chunk in chunks
    ]
    return MaterialChunkListResponse(items=items, total=total)


@router.delete("/{material_id}", status_code=204)
def delete_material(
    request: Request,
    material_id: UUID,
    db: Session = Depends(get_db),
    stack: RetrievalStack = Depends(get_retrieval_stack),
) -> None:
    material_service.delete_material(
        db,
        material_id=material_id,
        materials_root=Path(request.app.state.settings.upload_dir),
        vector_store=stack.vector_store,
        keyword_index=stack.keyword_index,
    )
    db.commit()


@router.post("/{material_id}/reindex", response_model=MaterialJobView, status_code=202)
def reindex_material(
    material_id: UUID,
    db: Session = Depends(get_db),
    runner: MaterialJobRunner = Depends(get_job_runner),
) -> MaterialJobView:
    job = material_service.reindex_material(db, material_id=material_id)
    db.commit()
    runner.notify()
    return MaterialJobView.model_validate(job)


@router.post("/{material_id}/retry", response_model=MaterialJobView, status_code=202)
def retry_material(
    material_id: UUID,
    db: Session = Depends(get_db),
    runner: MaterialJobRunner = Depends(get_job_runner),
) -> MaterialJobView:
    job = material_service.retry_material(db, material_id=material_id)
    db.commit()
    runner.notify()
    return MaterialJobView.model_validate(job)
