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


class TaskView(BaseModel):
    task_id: UUID
    session_id: UUID | None
    goal: str
    budget_minutes: int
    status: Literal["created", "running", "ready", "needs_info", "failed", "cancelled"]
    trace: list[dict]
    draft: dict | None
    message: str
    error_code: str | None
    metrics: dict
    draft_version: str | None = None


class ConfirmTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_version: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]+$")


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchKnowledge(ToolArgs):
    query: str = Field(min_length=1, max_length=80)


class NodeIds(ToolArgs):
    kp_ids: list[UUID] = Field(min_length=1, max_length=8)


class FindQuestions(NodeIds):
    question_type: Literal["single_choice", "fill_blank", "calculation", "proof", "discussion", "program"] | None = None


class ReadLesson(ToolArgs):
    kp_id: UUID


class ValidatePlan(ToolArgs):
    question_ids: list[UUID] = Field(default_factory=list, max_length=12)
    review_kp_ids: list[UUID] = Field(default_factory=list, max_length=4, description="不安排知识复习时必须为空列表；只选择有可用讲解的节点")
    review_minutes: int = Field(default=0, ge=0, le=120, strict=True, description="复习节点为空时必须为0，有复习节点时必须为正数")
    rationale: str = Field(default="", max_length=400)


class TaskConclusion(ToolArgs):
    message: str = Field(min_length=1, max_length=800)
    needs_clarification: bool = False
