"""Local installation-owned generation ledger, not another question/attempt bank."""
from uuid import UUID
from sqlalchemy import JSON, String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from backend.models.base import Base, TimestampMixin
from backend.models.types import uuid_pk


class PersonalGenerationBatch(Base, TimestampMixin):
    __tablename__ = "personal_generation_batches"
    id: Mapped[UUID] = uuid_pk()
    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    study_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    reserved_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
