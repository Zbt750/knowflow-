from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class MaterialSearchSession(BaseModel):
    session_id: UUID
    title: str
    mode: Literal["user"]
    purpose: Literal["material_search"]
    study_date: str
    scope_mode: Literal["all", "selected"]
    selected_file_ids: list[UUID]


class MaterialSearchScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    scope_mode: Literal["all", "selected"] = "all"
    selected_file_ids: list[UUID] = Field(default_factory=list, max_length=8)
