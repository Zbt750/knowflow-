from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    goal: str = Field(min_length=2, max_length=1200)
    budget_minutes: int = Field(ge=5, le=240, strict=True)


class CreateTask(TaskInput):
    mode: Literal["builtin"] = "builtin"
    session_id: UUID | None = None
    current_plan_id: UUID | None = None


class TaskView(BaseModel):
    task_id: UUID
    session_id: UUID | None
    goal: str
    budget_minutes: int
    status: Literal["created", "running", "ready", "needs_info", "answered", "failed", "cancelled"]
    trace: list[dict]
    draft: dict | None
    message: str
    error_code: str | None
    metrics: dict
    draft_version: str | None = None
    append_result: dict | None = None


class ConfirmTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_version: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]+$")
    # Required by the service for same-session confirmations that append to an
    # already materialized plan; optional only for legacy first-paper confirmations.
    session_id: UUID | None = None


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchKnowledge(ToolArgs):
    query: str = Field(min_length=1, max_length=80)


class NodeIds(ToolArgs):
    kp_ids: list[UUID] = Field(min_length=1, max_length=8)


class FindQuestions(ToolArgs):
    kp_ids: list[UUID] = Field(default_factory=list, max_length=8)
    question_type: Literal["single_choice", "fill_blank", "calculation", "proof", "discussion", "program"] | None = None
    exclude_question_ids: list[UUID] = Field(default_factory=list, max_length=100)


class ReviewNeedsQuery(ToolArgs):
    subject: str | None = Field(default=None,max_length=80)
    limit: int = Field(default=10,ge=1,le=30)


class QuestionAvailabilityQuery(ToolArgs):
    subject: str | None = Field(default=None, min_length=1, max_length=80)
    kp_ids: list[UUID] = Field(default_factory=list, max_length=8)
    exclude_kp_ids: list[UUID] = Field(default_factory=list, max_length=8)
    exclude_question_ids: list[UUID] = Field(default_factory=list, max_length=100)
    question_type: Literal["single_choice", "fill_blank", "calculation", "proof", "discussion", "program"] | None = None


class ReadLesson(ToolArgs):
    kp_id: UUID


class PaperValidation(ToolArgs):
    """Complete persisted paper; transport call limits are not business limits."""
    question_ids: list[UUID] = Field(default_factory=list)
    review_kp_ids: list[UUID] = Field(default_factory=list, max_length=4, description="不安排知识复习时必须为空列表；只选择有可用讲解的节点")
    review_minutes: int = Field(default=0, ge=0, le=120, strict=True, description="复习节点为空时必须为0，有复习节点时必须为正数")
    rationale: str = Field(default="", max_length=400)


class ValidatePlan(PaperValidation):
    """Bounded model-tool input; never use to revalidate a saved whole paper."""
    question_ids: list[UUID] = Field(default_factory=list, max_length=12)


class TaskConclusion(ToolArgs):
    message: str = Field(min_length=1, max_length=800)
    needs_clarification: bool = False
