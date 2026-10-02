"""学习任务工作状态；不作为学习结果或掌握度证据。"""
from datetime import datetime
from uuid import UUID
from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.models.base import Base, TimestampMixin
from backend.models.types import uuid_pk


class LearningTask(Base, TimestampMixin):
    __tablename__ = "learning_tasks"
    __table_args__ = (CheckConstraint("status IN ('created','running','ready','needs_info','failed','cancelled')", name="learning_task_status_valid"),
                     CheckConstraint("budget_minutes >= 5 AND budget_minutes <= 240", name="learning_task_budget_valid"))
    id: Mapped[UUID] = uuid_pk()
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("chat_sessions.id", ondelete="SET NULL"))
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    budget_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="created", nullable=False)
    run_token: Mapped[str | None] = mapped_column(String(36))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    draft: Mapped[dict | None] = mapped_column(JSON)
    context: Mapped[dict | None] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
