from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ReplacementReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question_id: UUID
    question_version_id: UUID


class PaperAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: UUID
    plan_id: UUID
    # Empty is valid only for an append-only adjustment. The service rejects a
    # request with neither removals nor additions, so this cannot become a no-op.
    remove_item_ids: list[UUID] = Field(default_factory=list,max_length=100)
    replacements: list[ReplacementReference] = Field(default_factory=list,max_length=100)
    budget_minutes: int = Field(ge=5,le=240)


class PaperAdjustmentConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: UUID
    draft_version: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirm_viewed: bool = Field(default=False, strict=True)
    accept_budget_overrun: bool = Field(default=False, strict=True)
