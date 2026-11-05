from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin
from backend.models.types import uuid_pk


class Material(Base, TimestampMixin):
    """一份资料：位置、来源、规范化全文 hash、处理状态与当前激活索引版本。

    PostgreSQL 是正文与版本的权威来源；Chroma 只是可重建的派生索引。
    """

    __tablename__ = "materials"

    id: Mapped[UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # builtin = 随仓库提供的讲义；user = 用户上传。
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # 上传时的原始文件名（只保留文件名，不含任何路径成分）。
    original_filename: Mapped[str | None] = mapped_column(String(255))
    # 相对资料根目录的路径；服务层会校验解析结果仍在根目录内。
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # 规范化全文：offset 的唯一坐标系。绝对路径与上传时间都不写进 hash。
    normalized_text: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    raw_hash: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(Integer)
    # pending → indexing → ready / failed；只有 ready 可被检索。
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    # 最后验证通过的版本。旧版本切换前始终不改它。
    active_index_version: Mapped[str | None] = mapped_column(String(64))
    # 只保存稳定错误码与安全摘要；堆栈、路径与密钥一律留在日志。
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(1000))

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="material", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    """某份资料、某个索引版本中的一段正文；PostgreSQL 的权威正文来源。"""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "material_id", "index_version", "ordinal", name="chunk_material_version_ordinal"
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    material_id: Mapped[UUID] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 同一资料可以保留旧版本；切换时不删旧块，失败也不影响旧索引。
    index_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    # 纯正文，不含额外 prompt 前缀；必须等于 normalized_text[start:end]。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    # JSON 数组，例如 ["高等数学", "函数与极限", "洛必达法则"]。
    heading_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Markdown 中 <!-- kp:code --> 明确标记的知识点；保守关联用，不靠模型猜。
    kp_hint_code: Mapped[str | None] = mapped_column(String(120))

    material: Mapped[Material] = relationship(back_populates="chunks")
    knowledge_points: Mapped[list["ChunkKnowledgePoint"]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan"
    )


class ChunkKnowledgePoint(Base):
    """一个 chunk 与一个知识点的显式关联；matched_kp 的唯一可信来源。"""

    __tablename__ = "chunk_knowledge_points"
    __table_args__ = (UniqueConstraint("chunk_id", "kp_id", name="chunk_kp_unique"),)

    id: Mapped[UUID] = uuid_pk()
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 显式标记为 1.0；保守规则可以更低，但不与人工标记同权。
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    chunk: Mapped[DocumentChunk] = relationship(back_populates="knowledge_points")
