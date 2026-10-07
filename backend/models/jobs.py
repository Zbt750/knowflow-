from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin
from backend.models.types import uuid_pk


class DocumentJob(Base, TimestampMixin):
    """把一次 ingest/reindex/delete 保存为重启后仍可领取的持久命令。

    一行只代表一次命令；用户点重试时应新建行，不能把失败记录改回 pending。
    """

    __tablename__ = "document_jobs"
    __table_args__ = (
        # 用数据库 CHECK 锁死 job_type 与 status 取值，worker 无法写入契约外的状态。
        CheckConstraint("job_type IN ('ingest','reindex','delete')", name="job_type_valid"),
        CheckConstraint(
            "status IN ('pending','running','retry','succeeded','failed')",
            name="job_status_valid",
        ),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="job_attempt_range"),
    )

    id: Mapped[UUID] = uuid_pk()
    # 资料删除时级联清理任务行。
    material_id: Mapped[UUID] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 领取与恢复都按 status 筛选。
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    # attempts 与 max_attempts 共同决定是重试还是终态失败，坏文件不会无限占用模型。
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(100))
    # 过期后允许被其他 worker 回收。
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # 退避到期才可领取。
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    # 本次 job 激活的版本，便于追溯“这次重建产生了哪个索引”。
    result_index_version: Mapped[str | None] = mapped_column(String(64))