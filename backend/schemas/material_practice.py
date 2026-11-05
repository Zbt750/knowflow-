"""从指定资料生成个人练习题：范围、知识点、题量与难度都显式传入。"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Difficulty = Literal["basic", "improved", "comprehensive"]
QuestionType = Literal["single_choice", "fill_blank", "calculation", "proof", "subjective"]


class MaterialPracticeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: UUID
    knowledge_point_ids: list[UUID] = Field(min_length=1, max_length=5)
    question_count: int = Field(default=3, ge=1, le=5)
    difficulty: Difficulty = "basic"
    question_type: QuestionType = "single_choice"
    user_requirement: str | None = Field(default=None, max_length=4000)


class MaterialPracticeResponse(BaseModel):
    material_id: UUID
    material_title: str
    request_key: UUID
    batch_id: UUID | None = None
    status: str
    question_ids: list[UUID] = Field(default_factory=list)
    failures: list[dict] = Field(default_factory=list)
    message: str | None = None
