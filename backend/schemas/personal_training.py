from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


QuestionType = Literal[
    "single_choice", "fill_blank", "calculation", "proof", "discussion", "program", "subjective"
]
Difficulty = Literal["any", "basic", "improved", "comprehensive"]


class PersonalTrainingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    owner_session_id: UUID
    request_key: str = Field(min_length=8, max_length=100)
    title: str = Field(default="个人专项训练", min_length=1, max_length=160)
    knowledge_point_ids: list[UUID] = Field(default_factory=list, max_length=20)
    question_count: int | None = Field(default=None, ge=1, le=30)
    target_minutes: int = Field(ge=5, le=240)
    difficulty: Difficulty = "any"
    question_type: QuestionType | None = None
    basis: Literal["selected", "recent_mistakes"] = "selected"
    question_ids: list[UUID] = Field(default_factory=list, max_length=30)


class PersonalTrainingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_session_id: UUID
    request_key: str = Field(min_length=8, max_length=100)
    expected_version: int = Field(ge=1)


class PersonalTrainingAppend(PersonalTrainingAction):
    question_count: int = Field(ge=1, le=30)


class PersonalTrainingAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    owner_session_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=100)
    expected_version: int = Field(ge=1)
    raw_answer: str | None = Field(default=None, max_length=4000)
    selected_option: str | None = Field(default=None, max_length=20)


class PersonalTrainingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    owner_session_id: UUID
    draft_answer: str | None = Field(default=None, max_length=4000)
    draft_selected_option: str | None = Field(default=None, max_length=20)
    expected_draft_revision: int = Field(ge=0)


class PersonalTrainingNext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_session_id: UUID
    request_key: str = Field(min_length=8, max_length=100)
    question_count: int | None = Field(default=None, ge=1, le=30)
    target_minutes: int | None = Field(default=None, ge=5, le=240)
