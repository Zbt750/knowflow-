"""A learning request, never an Attempt, Evidence or committed plan."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import String,Text,JSON,DateTime,ForeignKey,CheckConstraint,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from backend.models.base import Base,TimestampMixin
from backend.models.types import uuid_pk

class PracticeRequest(Base,TimestampMixin):
    __tablename__="practice_requests"
    __table_args__=(CheckConstraint("status IN ('draft','pending','planning','proposed','accepted','declined','expired','failed')",name="practice_request_status_valid"),UniqueConstraint("source_message_id",name="practice_request_source_once"))
    id:Mapped[UUID]=uuid_pk()
    status:Mapped[str]=mapped_column(String(20),default="draft",nullable=False)
    source_conversation_id:Mapped[UUID|None]=mapped_column(ForeignKey("chat_sessions.id",ondelete="SET NULL"))
    source_message_id:Mapped[UUID|None]=mapped_column(ForeignKey("chat_messages.id",ondelete="SET NULL"))
    request:Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    user_request:Mapped[str]=mapped_column(Text,nullable=False)
    handled_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    planner_task_id:Mapped[UUID|None]=mapped_column(ForeignKey("learning_tasks.id",ondelete="SET NULL"))
    daily_plan_id:Mapped[UUID|None]=mapped_column(ForeignKey("daily_plans.id",ondelete="SET NULL"))
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    error_code:Mapped[str|None]=mapped_column(String(80))
