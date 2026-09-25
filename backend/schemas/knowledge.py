from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


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
    summary: str | None = None
    learning_goal: str | None = None
    # 只有可考核叶子才有状态；父节点的汇总由页面数 children 得到，不存第二份统计真相。
    state: str | None = None
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


class NodeQuestionView(BaseModel):
    """知识节点题库里的一道题；这里绝不返回答案与解析。"""

    id: UUID
    question_type: str
    difficulty: str
    is_variant: bool
    stem: str
    kp_id: UUID


class NodeAttemptView(BaseModel):
    """练习记录：永久保存的作答历史。"""

    id: UUID
    question_id: UUID
    question_stem: str
    self_grade: str
    objective_result: str
    result_state: str
    reason_code: str
    submitted_at: str
    raw_answer: str | None = None


class KnowledgeNodeDetail(BaseModel):
    node: KnowledgeNodeView
    questions: list[NodeQuestionView]
    attempts: list[NodeAttemptView]
    # 关联资料在阶段 C 接入检索后填充；现在明确返回空列表而不是伪造数据。
    materials_ready: bool = False


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