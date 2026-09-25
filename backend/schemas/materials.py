"""资料相关接口的请求/响应模型。

契约约定：
- 只暴露安全字段：绝不含 stored_path、绝对路径、文件 hash 之外的内部信息；
- 错误只以稳定错误码出现（`last_error_code`），前端按 code 分支，不解析文案。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# 与数据库 CHECK 约束保持一致的状态取值。
MaterialStatus = str


class MaterialJobView(BaseModel):
    """最近一次处理任务的状态。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    error_code: str | None = None
    result_index_version: str | None = None
    created_at: datetime


class MaterialView(BaseModel):
    """资料列表项。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    source_type: str
    original_filename: str | None = None
    status: str
    file_size: int | None = None
    active_index_version: str | None = None
    last_error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class MaterialDetail(MaterialView):
    """资料详情：额外带上块数与最近任务。"""

    chunk_count: int = 0
    latest_job: MaterialJobView | None = None


class MaterialContentResponse(BaseModel):
    """资料的规范化全文，仅用于阅读；不暴露磁盘路径。"""

    title: str
    text: str | None = None

class MaterialListResponse(BaseModel):
    items: list[MaterialView]
    total: int
    stats: dict[str, int]


class ChunkPreviewView(BaseModel):
    """块预览：用于「资料到底被切成了什么」的自查。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ordinal: int
    heading_path: list[str]
    char_count: int
    preview: str
    kp_hint_code: str | None = None


class MaterialChunkListResponse(BaseModel):
    items: list[ChunkPreviewView]
    total: int


class MaterialUploadResponse(BaseModel):
    """上传成功后的即时响应：任务在后台执行，前端轮询详情即可。"""

    material: MaterialView
    job_id: UUID
    message: str


class SearchRequest(BaseModel):
    """检索请求。"""

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=6, ge=1, le=20)
    candidate_k: int = Field(default=20, ge=1, le=50)
    material_ids: list[UUID] | None = None
    source_types: list[str] | None = None
    kp_ids: list[UUID] | None = None


class SearchHitView(BaseModel):
    """一条检索结果：正文 + 出处，供前端做引用卡片与回跳。"""

    chunk_id: UUID
    material_id: UUID
    material_title: str
    source_type: str
    index_version: str
    ordinal: int
    content: str
    heading_path: list[str]
    kp_ids: list[UUID]
    score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHitView]
    # 检索链路的诊断信息：降级原因对排查「为什么结果不对」至关重要。
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)
    vector_candidates: int = 0
    keyword_candidates: int = 0
    reranked: bool = False
