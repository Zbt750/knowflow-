"""Read-only capability evidence, never a mastery score or grading decision."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class CapabilityDimension(BaseModel):
    key: str
    label: str
    status: Literal["not_verified", "limited_evidence", "independent_evidence", "needs_retest"]
    status_label: str
    reason: str
    evidence_scope: Literal["final_answer", "process"]
    online_question_count: int
    reliable_grading_question_count: int
    independent_question_count: int
    independent_question_ids: list[UUID] = Field(default_factory=list)
    pending_review_question_count: int
    recent_attempt_count: int
    recent_assisted_attempt_count: int
    recent_ungraded_attempt_count: int
    observed_skill_tags: list[str] = Field(default_factory=list)


class CapabilityProfile(BaseModel):
    version: str = "capability-evidence-v1"
    mapping_version: str = "question-type-role-v1"
    dimensions: list[CapabilityDimension] = Field(default_factory=list)
    history_truncated: bool = False
    confirmation_lookup_truncated: bool = False
    excluded_confirmation_count: int = 0
    unmapped_pending_review_count: int = 0
    note: str = "按题型与学习角色描述当前证据，不代表全面掌握；最终答案正确不证明推导或程序过程正确。"
