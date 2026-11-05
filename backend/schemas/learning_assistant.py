"""Versioned assistant contracts; conversation identity is not study location."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.schemas.personal_questions import GenerationTarget

QAAction = Literal["auto", "hint_1", "hint_2", "solution", "process_review"]


class StudyContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: Literal["study-context-v1"] = "study-context-v1"
    surface: Literal["study", "chat", "knowledge", "materials"] = "chat"
    subject: str | None = Field(default=None, max_length=80)
    knowledge_node_ids: list[UUID] = Field(default_factory=list, max_length=8)
    question_id: UUID | None = None
    # Exact immutable snapshot; the server derives this from PracticeItem when omitted.
    question_version_id: UUID | None = None
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
    # Applies only when the explicit personal-question generation route is taken.
    personal_generation_mode: Literal["ai_generated", "ai_enhanced", "deterministic_fast"] = "ai_generated"
    personal_generation_confirmed_kp_id: UUID | None = None
    # Whole server-issued allocation for explicit multi-knowledge-point cards.
    # The assistant service verifies every field against that card before use.
    personal_generation_confirmed_targets: list[GenerationTarget] | None = Field(default=None, max_length=5)
    # A knowledge-node confirmation continues its original user turn. The
    # assistant message is the server-owned confirmation token, not a new goal.
    personal_generation_confirmation_message_id: UUID | None = None

    @model_validator(mode="after")
    def validate_generation_confirmation(self):
        if self.personal_generation_confirmed_kp_id and self.personal_generation_confirmed_targets:
            raise ValueError("generation_confirmation_must_select_one_contract")
        if self.personal_generation_confirmed_targets and sum(
                target.count for target in self.personal_generation_confirmed_targets) > 5:
            raise ValueError("generation_confirmation_count_limit")
        if self.personal_generation_confirmed_targets and not self.personal_generation_confirmation_message_id:
            raise ValueError("generation_confirmation_message_required")
        return self


class PlannerHandoff(BaseModel):
    version: Literal["planner-handoff-v1"] = "planner-handoff-v1"
    source_conversation_id: UUID
    source_message_id: UUID | None = None
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
