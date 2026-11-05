"""Independent personal practice plans; never formal daily-paper items."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin
from backend.models.types import uuid_pk


class PersonalTraining(Base, TimestampMixin):
    """A durable, owner-session-scoped practice run with its own lifecycle."""

    __tablename__ = "personal_trainings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','paused','completed','cancelled')",
            name="personal_training_status_valid",
        ),
        CheckConstraint("target_minutes BETWEEN 5 AND 240", name="personal_training_target_minutes_valid"),
        CheckConstraint("version >= 1", name="personal_training_version_positive"),
        Index("ix_personal_trainings_owner_status_updated", "owner_session_id", "status", "updated_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    owner_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    selected_kp_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    selection_basis: Mapped[str] = mapped_column(String(32), nullable=False, default="selected")
    requested_count: Mapped[int | None] = mapped_column(Integer)
    target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, default="any")
    question_type: Mapped[str | None] = mapped_column(String(30))
    adapted_from_training_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("personal_trainings.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    items: Mapped[list["PersonalTrainingItem"]] = relationship(
        back_populates="training", order_by="PersonalTrainingItem.ordinal", cascade="all, delete-orphan"
    )


class PersonalTrainingItem(Base, TimestampMixin):
    """An ordered, immutable binding to one exact QuestionVersion."""

    __tablename__ = "personal_training_items"
    __table_args__ = (
        UniqueConstraint("training_id", "question_id", name="personal_training_question_once"),
        UniqueConstraint("training_id", "ordinal", name="personal_training_ordinal_once"),
        ForeignKeyConstraint(
            ["question_id", "question_version_id"],
            ["question_versions.question_id", "question_versions.id"],
            name="fk_personal_training_question_version_pair",
        ),
        Index("ix_personal_training_items_training_completed", "training_id", "completed_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    training_id: Mapped[UUID] = mapped_column(
        ForeignKey("personal_trainings.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False)
    question_version_id: Mapped[UUID] = mapped_column(ForeignKey("question_versions.id", ondelete="RESTRICT"), nullable=False)
    kp_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="RESTRICT"), nullable=False)
    # Unsubmitted learner input is a resumable draft, never an attempt/evidence.
    draft_answer: Mapped[str | None] = mapped_column(Text)
    draft_selected_option: Mapped[str | None] = mapped_column(String(20))
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    draft_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    training: Mapped[PersonalTraining] = relationship(back_populates="items")
    attempts: Mapped[list["PersonalTrainingAttempt"]] = relationship(
        back_populates="item", order_by="PersonalTrainingAttempt.submitted_at"
    )


class PersonalTrainingAttempt(Base):
    """Answer evidence intentionally isolated from formal QuestionAttempt/mastery."""

    __tablename__ = "personal_training_attempts"
    __table_args__ = (
        CheckConstraint("result IN ('right','wrong','unknown')", name="personal_training_attempt_result_valid"),
        ForeignKeyConstraint(
            ["question_id", "question_version_id"],
            ["question_versions.question_id", "question_versions.id"],
            name="fk_personal_training_attempt_question_version_pair",
        ),
        Index("ix_personal_training_attempts_item_submitted", "training_item_id", "submitted_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    training_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("personal_training_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False)
    question_version_id: Mapped[UUID] = mapped_column(ForeignKey("question_versions.id", ondelete="RESTRICT"), nullable=False)
    kp_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="RESTRICT"), nullable=False)
    raw_answer: Mapped[str | None] = mapped_column(Text)
    selected_option: Mapped[str | None] = mapped_column(String(20))
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    grading_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    item: Mapped[PersonalTrainingItem] = relationship(back_populates="attempts")


class PersonalTrainingAction(Base):
    """Idempotency ledger for append/pause/resume/finish operations."""

    __tablename__ = "personal_training_actions"
    __table_args__ = (Index("ix_personal_training_actions_training", "training_id", "created_at"),)

    id: Mapped[UUID] = uuid_pk()
    training_id: Mapped[UUID] = mapped_column(
        ForeignKey("personal_trainings.id", ondelete="CASCADE"), nullable=False
    )
    request_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
