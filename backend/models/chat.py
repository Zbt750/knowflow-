from __future__ import annotations
from datetime import datetime
from uuid import UUID
import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.models.base import Base, TimestampMixin
from backend.models.types import uuid_pk

class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (CheckConstraint("mode IN ('builtin', 'user')", name="chat_session_mode_valid"),)
    id: Mapped[UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default="新对话", default="新对话")
    mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="builtin", default="builtin")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="chat_message_role_valid"),
        CheckConstraint(
            "status IN ('completed', 'generating', 'cancelled', 'failed')",
            name="chat_message_status_valid",
        ),
        # 复合索引而不是只索引 seq：真实查询是「按会话过滤 + 按 seq 排序」
        # （取某会话的历史消息、以及拼接 prompt 用的最近若干条）。
        Index("ix_chat_messages_session_id_seq", "session_id", "seq"),
    )
    id: Mapped[UUID] = uuid_pk()
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="generating", default="generating")
    # 插入序号：同一会话内单调递增。由数据库 identity 生成，业务代码不赋值。
    # 为什么需要：user 与 assistant 在同一事务里写入，created_at 完全相同，
    # 只按时间排序时两者先后不确定（刷新后可能出现「回答在问题前面」）。
    # 用 Identity() 而不是 autoincrement=True：
    # 后者在 PostgreSQL 下仍会把 seq 写进 INSERT 且值为 NULL，
    # 直接撞上 NOT NULL 约束；Identity() 才让 SQLAlchemy 知道
    # 「这一列由数据库生成」，从而不把它放进 INSERT 并用 RETURNING 取回。
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=False), nullable=False)
    matched_kp_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_points.id"))
    # matched_kp 的归因依据：{source_chunk_id, source_rank, score, total, runner_up_total}。
    #
    # 为什么要单独存，而不是只留 matched_kp_id：
    # 归因决定推荐哪些追练题，用户有权知道「凭什么归到这个知识点」。
    # 只存结论时，事后既没法向用户解释，也没法排查错归因 ——
    # 而重新跑一次检索并不等于当时的检索（资料可能已重建索引）。
    # 空 dict 表示「这次回答没有归因」（拒答、或没有知识点过阈值）。
    matched_kp_basis: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, server_default=sa.text("'{}'::json"), default=dict
    )
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSON, nullable=False, server_default=sa.text("'{}'::json"), default=dict)

class MessageCitation(Base):
    __tablename__ = "message_citations"
    __table_args__ = (UniqueConstraint("message_id", "label", name="citation_label_once"), UniqueConstraint("message_id", "chunk_id", name="citation_chunk_once"))
    id: Mapped[UUID] = uuid_pk()
    message_id: Mapped[UUID] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("document_chunks.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
