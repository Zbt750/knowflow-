from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, field_validator
from typing import Literal
from backend.schemas.capability import CapabilityProfile
from backend.schemas.question_source import QuestionSourceView
from backend.schemas.question_trust import QuestionTrustView


class GapItemView(BaseModel):
    """一条毕业条件的进度。key 是稳定机器码，页面按它决定展示方式。"""

    key: str
    label: str
    current: int
    required: int
    satisfied: bool


class KnowledgeNodeView(BaseModel):
    """知识树节点；父节点 state 必须为 None，由页面汇总 children。"""

    id: UUID
    code: str
    name: str
    subject: str
    ordinal: int
    is_assessable: bool
    # 历年题号索引叶子：没有内置题干；原卷自评可计入该叶子的掌握度与毕业条件。
    is_reference_only: bool = False
    online_question_count: int = 0
    practice_eligible_question_count: int = 0
    blocked_active_question_count: int = 0
    # Evidence-pool sufficiency describes available question opportunities, not learner mastery.
    evidence_pool_status: Literal["SUFFICIENT", "INSUFFICIENT", "UNKNOWN"] = "UNKNOWN"
    evidence_pool_reasons: list[str] = []
    verified_objective_question_count: int = 0
    distinct_objective_question_count: int = 0
    unattempted_objective_question_count: int = 0
    variation_objective_question_count: int = 0
    summary: str | None = None
    learning_goal: str | None = None
    # 只有可考核叶子才有状态；父节点的汇总由页面数 children 得到，不存第二份统计真相。
    state: str | None = None
    assessment_basis: str | None = None
    pending_review_count: int = 0
    next_review_at: str | None = None
    mastered_at: str | None = None
    node_self_grade: str | None = None
    manual_credit_count: int = 0
    effective_confirmation_count: int = 0
    has_real_variant: bool = False
    first_confirmed_on: str | None = None
    last_confirmed_on: str | None = None
    day_span: int | None = None
    # 毕业缺口明细：页面直接渲染这些条目，不在前端自己算毕业条件。
    gap_items: list[GapItemView] = []
    next_step: str | None = None
    # 该叶子自己的策略快照；字典的键是题型机器码。
    required_question_types: dict[str, int] = {}
    excluded_question_types: list[str] = []
    required_skill_tags: list[str] = []
    children: list["KnowledgeNodeView"] = []


class KnowledgeTreeResponse(BaseModel):
    nodes: list[KnowledgeNodeView]


class LessonBreadcrumb(BaseModel):
    code: str
    name: str


class KnowledgeLessonResponse(BaseModel):
    id: UUID
    code: str
    name: str
    subject: str
    is_assessable: bool
    breadcrumbs: list[LessonBreadcrumb]
    markdown: str
    question_count: int
    practice_eligible_question_count: int = 0


class NodeQuestionView(BaseModel):
    """知识节点题库里的一道题；这里绝不返回答案与解析。"""

    id: UUID
    question_type: str
    difficulty: str
    is_variant: bool
    stem: str
    options: dict[str, str] | None = None
    kp_id: UUID
    question_source: QuestionSourceView | None = None
    trust: QuestionTrustView = QuestionTrustView()


class ExamQuestionReferenceView(BaseModel):
    """历年试题的题号与来源指针，不包含题干、答案或解析。"""

    id: UUID
    subject: str
    year: int
    question_number: int
    topic_label: str
    source_topic_label: str
    question_source_url: str | None = None
    topic_source_url: str | None = None
    local_folder: str
    source_note: str


class NodeAttemptView(BaseModel):
    """练习记录：永久保存的作答历史。"""

    id: UUID
    question_id: UUID | None = None
    exam_reference_id: UUID | None = None
    question_stem: str
    self_grade: str | None
    objective_result: str
    result_state: str
    reason_code: str
    submitted_at: str
    raw_answer: str | None = None
    grading_evidence: dict | None = None

    @field_validator("grading_evidence", mode="before")
    @classmethod
    def public_evidence_only(cls, value):
        if value is None:
            return None
        if not isinstance(value, dict):
            return value  # Preserve Pydantic's type validation, do not invent evidence.
        # Keep immutable internal evidence in PG, not in the public node DTO.
        # No grading config, answer key, review identities, paths or old snapshots.
        allowed = {"version", "method", "reason", "assisted", "assistance_level", "attempt_number",
            "previous_attempt_id", "sequence_category", "history_unknown", "can_retry", "selected_option",
            "confidence", "assessment_basis", "effective_confirmation_count", "basis_changed",
            "observation_scope", "answer_revealed_at", "question_role"}
        return {key: val for key, val in value.items() if key in allowed}


class KnowledgeNodeDetail(BaseModel):
    node: KnowledgeNodeView
    questions: list[NodeQuestionView]
    attempts: list[NodeAttemptView]
    exam_references: list[ExamQuestionReferenceView] = []
    lesson_available: bool = False
    # 关联资料在阶段 C 接入检索后填充；现在明确返回空列表而不是伪造数据。
    materials_ready: bool = False
    capability_profile: CapabilityProfile | None = None


class NodeSelfAssessmentRequest(BaseModel):
    self_grade: str
    idempotency_key: str


class NodeSelfAssessmentResponse(BaseModel):
    kp_id: UUID
    state: str
    reason_code: str
    effective_confirmation_count: int
    manual_credit_count: int
    next_review_at: str | None = None


KnowledgeNodeView.model_rebuild()
