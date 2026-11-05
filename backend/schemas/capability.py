"""Read-only capability evidence, never a mastery score or grading decision."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class LearningProgress(BaseModel):
    version: Literal["learning_progress_v1"] = "learning_progress_v1"
    status: Literal["NOT_STARTED", "PRACTICING", "NEEDS_CONSOLIDATION", "IMPROVING", "RETEST_RECOMMENDED", "STABLE_PRACTICE"]
    label: str
    reason: str
    reliability_note: str
    next_action: Literal["read_lesson", "practice", "consolidate", "delayed_retest", "validate_with_other_questions", "spaced_review"]
    next_step: str
    limitations: list[str] = Field(default_factory=list)
    observed_attempt_count: int = 0
    distinct_question_count: int = 0
    assisted_correct_question_count: int = 0
    reference_wrong_count: int = 0
    reliable_wrong_count: int = 0
    unknown_count: int = 0
    history_truncated: bool = False
    # Stable is a bounded practice observation, never a replacement graduation.
    strict_graduation_unchanged: bool = True


class PostGraduationPractice(BaseModel):
    version: Literal['post-graduation-practice-v1']='post-graduation-practice-v1'
    applicable: bool=False
    status: Literal['NOT_APPLICABLE','INSUFFICIENT','GOOD','CONSOLIDATE','REVIEW']
    label: str
    reason: str
    next_action: str
    foundation_unchanged: bool=True
    graduated_at: str | None=None
    last_reliable_practice_at: str | None=None
    observed_attempt_count: int=0
    reliable_attempt_count: int=0
    distinct_question_count: int=0
    independent_correct_count: int=0
    independent_wrong_count: int=0
    assisted_correct_count: int=0
    excluded_attempt_count: int=0
    history_truncated: bool=False
    evidence_summary: str=''
    limitations: list[str]=Field(default_factory=list)


class GraduationQuestionStatus(BaseModel):
    question_id: UUID
    ordinal: int
    status: Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED"]


class GraduationProgress(BaseModel):
    version: Literal["frozen_question_set_v1"] = "frozen_question_set_v1"
    configured: bool = False
    graduated: bool = False
    graduated_at: str | None = None
    completed_question_count: int = 0
    required_question_count: int = 0
    questions: list[GraduationQuestionStatus] = Field(default_factory=list)
    note: str = "题目进度只汇总该节点冻结的公共正式题；新题和个人 AI 题不会自动加入。"


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
    learning_progress: LearningProgress | None = None
    post_graduation: PostGraduationPractice | None = None
    graduation_progress: GraduationProgress | None = None
    note: str = "按题型与学习角色描述当前证据，不代表全面掌握；最终答案正确不证明推导或程序过程正确。"
