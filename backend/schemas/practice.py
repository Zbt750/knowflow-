from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from backend.schemas.knowledge import ExamQuestionReferenceView


class RecommendationItem(BaseModel):
    """准备页的一条推荐；reason 是稳定层级码，页面负责映射成中文。"""

    kp_id: UUID
    name: str
    state: str
    # 层级码：not_mastered / overdue_review / partial_mastery /
    # insufficient_evidence / preview / consolidating
    reason: str
    # 来自毕业缺口的「下一步」，例如「完成 1 道填空题」。
    next_step: str = ""
    # 还缺哪些题型；页面可以据此提示「预计加入」。
    missing_types: list[str] = []


class PlanItemView(BaseModel):
    """今日练习卷里的一道题或一个外部原卷任务。

    普通题这里绝不返回 correct_answer / explanation；外部原卷任务不含题干，
    只有普通题可以通过 GET /api/practice-items/{item_id}/answer 读取答案与解析。
    """

    id: UUID
    ordinal: int
    kp_id: UUID
    kp_name: str
    question_id: UUID | None = None
    question_type: str
    # 学习角色（基础/典型/变式/综合）与考法标签；用于让用户看懂这道题在补什么。
    question_role: str | None = "basic"
    difficulty: str | None = None
    # 外部原卷任务只显示来源，不伪造或拼接题干。
    stem: str | None = None
    options: dict[str, str] | None = None
    skill_tags: list[str] = []
    is_variant: bool = False
    estimated_minutes: int = 5
    completed: bool
    completed_at: str | None = None
    latest_self_grade: str | None = None
    # 该题之前练过：题库耗尽时系统给的是复测题，页面要明确区分新题与复测。
    is_review: bool = False
    is_external_reference: bool = False
    exam_reference: ExamQuestionReferenceView | None = None


class TodaySummaryKp(BaseModel):
    kp_id: UUID
    name: str
    completed_count: int
    total_count: int


class TodaySetup(BaseModel):
    """当天还没有活动练习卷：展示准备页，等用户确认后才生成。"""

    status: str = "setup"
    study_date: str
    recommendations: list[RecommendationItem]


class TodayActive(BaseModel):
    """已有活动练习卷（或已完成）。"""

    status: str
    plan_id: UUID
    study_date: str
    completed_count: int
    total_count: int
    items: list[PlanItemView]
    # 专注模式要用的下一个未完成项；全部完成时为 None。
    focus_item_id: UUID | None = None
    summary_kps: list[TodaySummaryKp]
    # 卷子构成：题型 → 道数；以及按题目 estimated_minutes 汇总的预计总时长。
    type_summary: dict[str, int] = {}
    estimated_minutes: int = 0
    # 待做部分的预计剩余时长；已完成题不再计入。
    remaining_minutes: int = 0


class GeneratePlanRequest(BaseModel):
    selected_kp_ids: list[UUID] = Field(min_length=1)
    # 时间预算决定卷子总时长上限：轻量 45 / 标准 90 / 深度 120 分钟。
    budget: str = Field(default="standard", pattern="^(light|standard|deep)$")


class AppendQuestionsRequest(BaseModel):
    question_ids: list[UUID] = Field(min_length=1)


class AppendExamReferencesRequest(BaseModel):
    reference_ids: list[UUID] = Field(min_length=1)


class SubmitSelfAssessmentRequest(BaseModel):
    # skip 不写 QuestionAttempt，也不改变任何状态。
    self_grade: str = Field(pattern="^(mastered|partial|not_mastered|skip)$")
    # 幂等键过短会导致网络重试时产生重复历史，因此要求至少 8 位。
    idempotency_key: str = Field(min_length=8)
    # 用户输入只用于练习历史回看，绝不参与掌握度与毕业计算。
    raw_answer: str | None = None
    # 选择题选了哪个选项；服务端据此写 objective_result，但它同样不参与毕业判定。
    selected_option: str | None = Field(default=None, max_length=8)


class AssessmentResponse(BaseModel):
    practice_item_id: UUID
    kp_id: UUID
    state: str
    reason_code: str
    effective_confirmation_count: int
    manual_credit_count: int
    next_review_at: str | None = None


class PracticeItemAnswer(BaseModel):
    """答案与解析；纯读取，不写 revealed_at，不影响掌握度与毕业。"""

    practice_item_id: UUID
    question_id: UUID
    stem: str
    options: dict[str, str] | None = None
    correct_answer: str | None = None
    explanation: str
    question_type: str
    grading_mode: str
