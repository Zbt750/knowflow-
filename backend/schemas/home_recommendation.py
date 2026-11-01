from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from backend.schemas.learning_task import PaperValidation


class HomePaperValidation(PaperValidation):
    """Internal homepage envelope; the public chat tool remains capped at 12.

    The homepage validates a complete collection, without the chat tool list cap.
    All other inherited fields and shared business validation rules still apply.
    """
    question_ids: list[UUID] = Field(default_factory=list)


from backend.schemas.learning_task import FindQuestions


class HomeBankQuery(FindQuestions):
    # Internal exact-paper exclusion list, not the public chat tool schema.
    kp_ids: list[UUID] = Field(default_factory=list)
    exclude_question_ids: list[UUID] = Field(default_factory=list)


class HomeRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    session_id: UUID
    request_key: str = Field(min_length=8, max_length=100)
    goal: str = Field(default="", max_length=1200)
    action: Literal["adjust", "default", "restore", "cancel", "explain", "accept_workload", "dismiss_workload", "undo", "redo"] = "adjust"
    selected_kp_ids: list[UUID] | None = Field(default=None, max_length=80)
    budget_minutes: int | None = Field(default=None, ge=5, le=240, strict=True)
    expected_version: str | None = None
    target_task_id: UUID | None = None


class HomeRecommendationConfirm(BaseModel):
    accept_workload_increase: bool = False
    session_id: UUID
    draft_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm_legacy_set_transition_ids: list[UUID] = Field(default_factory=list, max_length=80)


class HomeDifficultyRequest(BaseModel):
    """整卷难度调整只允许真实候选题替换，不接受任何 difficulty 字段写入。"""

    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    direction: Literal["harder", "easier"]
    request_key: str = Field(min_length=8, max_length=100)
