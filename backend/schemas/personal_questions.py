from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.schemas.generation_difficulty import DifficultyRequirement

DEFAULT_GENERATION_COUNT = 1


class GenerationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kp_id: UUID
    question_type: Literal["single_choice", "fill_blank", "calculation", "proof", "subjective"] = "single_choice"
    count: int = Field(default=DEFAULT_GENERATION_COUNT, ge=1, le=5)
    difficulty: Literal["basic", "improved", "comprehensive"] = "basic"


class PersonalGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    generation_mode: Literal["ai_generated", "ai_enhanced", "deterministic_fast"] = "ai_generated"
    # This is an explicit user generation action, never implicit stock fallback.
    targets: list[GenerationTarget] = Field(min_length=1, max_length=5)
    surface: Literal["study", "chat", "knowledge"] = "chat"
    plan_id: UUID | None = None
    append_to_today: bool = False
    reference_question_id: UUID | None = None
    # An original pasted in chat is not itself a saved Question. Preserve its
    # text and provenance separately; it never becomes graduation evidence.
    reference_text: str | None = Field(default=None, max_length=6000)
    reference_source: dict | None = None
    user_requirement: str | None = Field(default=None, max_length=4000)
    difficulty_requirement: DifficultyRequirement | None = None

    @model_validator(mode="after")
    def bounded(self):
        if sum(t.count for t in self.targets) > 5:
            raise ValueError("单次最多生成5道题")
        return self


class HiddenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden: bool


class PersonalAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID | None = None
    question_ids: list[UUID] = Field(min_length=1, max_length=5)
