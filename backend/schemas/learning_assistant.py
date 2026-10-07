"""Versioned assistant contracts; conversation identity is not study location."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

QAAction = Literal["auto", "hint_1", "hint_2", "solution", "process_review"]


class StudyContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: Literal["study-context-v1"] = "study-context-v1"
    surface: Literal["study", "chat", "knowledge", "materials"] = "chat"
    subject: str | None = Field(default=None, max_length=80)
    knowledge_node_ids: list[UUID] = Field(default_factory=list, max_length=8)
    question_id: UUID | None = None
    attempt_id: UUID | None = None
    daily_plan_id: UUID | None = None
    practice_item_id: UUID | None = None
    material_id: UUID | None = None
    chunk_id: UUID | None = None
    conversation_id: UUID | None = None
    task_id: UUID | None = None
    origin: Literal["navigation", "practice", "knowledge", "material", "conversation"] = "conversation"
    generated_at: datetime | None = None


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=4000)
    study_context: StudyContext | None = None
    qa_action: QAAction = "auto"
    request_key: UUID | None = None
    retry_of_message_id: UUID | None = None
    current_work: str | None = Field(default=None, max_length=4000)


class PlannerHandoff(BaseModel):
    version: Literal["planner-handoff-v1"] = "planner-handoff-v1"
    source_conversation_id: UUID
    source_message_id: UUID
    source_question_id: UUID | None = None
    source_attempt_id: UUID | None = None
    target_knowledge_node_ids: list[UUID] = Field(default_factory=list)
    subject: str | None = None
    user_problem: str
    request_type: Literal["query", "recommend", "plan", "modify"]
    requested_question_count: int | None = None
    available_minutes: int = 90
    difficulty_preference: str | None = None
    assistance_context: str | None = None
    constraints: dict = Field(default_factory=dict)
    exclusions: list[UUID] = Field(default_factory=list)
    generated_at: datetime


class QAHandoff(BaseModel):
    version: Literal["qa-handoff-v1"] = "qa-handoff-v1"
    source_task_id: UUID | None = None
    knowledge_node_ids: list[UUID] = Field(default_factory=list)
    question_id: UUID | None = None
    reason: Literal["requested_concept_help", "optional_review_after_planning"]
    learning_problem: str
    suggested_mode: Literal["knowledge", "question"] = "knowledge"
    source_surface: Literal["study","chat","knowledge","materials"] = "study"
    attempt_id: UUID | None = None
    assistance_already_given: str | None = None
    bounded_summary: str | None = None
    task_facts_snapshot: dict | None = None
    origin: str = "explicit_deep_qa"
