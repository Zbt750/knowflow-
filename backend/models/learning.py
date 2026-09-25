from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin
from backend.models.types import uuid_pk


class KnowledgePoint(Base, TimestampMixin):
    """知识点树节点；父节点只汇总，只有 is_assessable 叶子可考核。"""

    __tablename__ = "knowledge_points"

    id: Mapped[UUID] = uuid_pk()
    # code 是稳定业务主键：脚本按 code 决定新建还是更新，名字可以改。
    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(80), nullable=False)
    # 自引用父节点；根节点为 NULL。父节点不绑定题目。
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_points.id"))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 只有 True 的叶子才能绑定题目、记录练习、自评和毕业。
    is_assessable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    summary: Mapped[str | None] = mapped_column(Text)
    learning_goal: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    children: Mapped[list["KnowledgePoint"]] = relationship(
        back_populates="parent", order_by="KnowledgePoint.ordinal"
    )
    parent: Mapped["KnowledgePoint | None"] = relationship(
        back_populates="children", remote_side="KnowledgePoint.id"
    )


class KpState(Base, TimestampMixin):
    """一个可考核叶子节点只有一行当前状态投影；可由 learning_events 重放。"""

    __tablename__ = "kp_states"

    # kp_id 同时是主键和外键：一个叶子至多一行状态。
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="unseen")
    # evidence_window 只存真实题目的 mastered 确认（question_id + 上海日期）。
    evidence_window: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    review_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mastered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 叶子整体自评结果；不伪造 QuestionAttempt。
    node_self_grade: Mapped[str | None] = mapped_column(String(30))
    # 透明基础确认数：节点整体自评「我已掌握」时写 2。
    manual_credit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Question(Base, TimestampMixin):
    """一道题只属于一个叶子知识点；题干不复制进练习记录。"""

    __tablename__ = "questions"

    id: Mapped[UUID] = uuid_pk()
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_type: Mapped[str] = mapped_column(String(30), nullable=False)
    grading_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="self_assessed"
    )
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[Any] | None] = mapped_column(JSON)
    correct_answer: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    # 学习角色：basic / typical / variant / comprehensive。
    # 它决定这道题在学习中的作用；与 question_type（作答形式）互不替代。
    question_role: Mapped[str] = mapped_column(String(30), nullable=False, default="basic")
    # 考法标签，例如 ["适用条件", "0/0 型"]；用于判断必考考法是否覆盖。
    skill_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 预计完成时间（分钟）；时间预算与组卷长度控制依赖它。
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # 变式题是毕业的硬条件：每个演示叶子至少一道（具体数量由该知识点策略决定）。
    is_variant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    kp: Mapped[KnowledgePoint] = relationship()
    variant_group: Mapped[str | None] = mapped_column(String(120))
    difficulty: Mapped[str] = mapped_column(String(30), nullable=False, default="basic")


class KpMasteryPolicy(Base, TimestampMixin):
    """每个可考核叶子的独立毕业策略。

    毕业不再只看题目总数：还要看真实题量、必考题型、必考考法、变式题与跨天确认。
    策略按知识点存储，因此「只考选择题」与「只考大题」的叶子可以有不同的门槛。
    """

    __tablename__ = "kp_mastery_policies"
    __table_args__ = (
        CheckConstraint("min_confirmations >= 1", name="kp_policy_min_confirmations"),
        CheckConstraint("min_real_questions >= 1", name="kp_policy_min_real_questions"),
        CheckConstraint("required_variant_count >= 0", name="kp_policy_variant_count"),
        CheckConstraint("min_day_span >= 0", name="kp_policy_day_span"),
        CheckConstraint("manual_mastered_credit >= 0", name="kp_policy_manual_credit"),
    )

    # 一个叶子至多一行策略；kp_id 同时是主键与外键。
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True
    )
    # 有效确认数下限：窗口内真实确认数 + 基础确认数。
    min_confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # 不同真实题目数下限：整体自评的基础确认不能替代它。
    min_real_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # 题型配额，例如 {"single_choice": 1, "fill_blank": 1, "calculation": 2}。
    # 键是 question_type；值为该题型至少需要几道不同真实题。
    required_question_types: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    # 该知识点不使用的题型；推荐与组卷都不会选它们。
    excluded_question_types: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    # 必考考法标签；从考过题目的标签并集里至少覆盖这么多个。
    required_skill_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    required_variant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    min_day_span: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    manual_mastered_credit: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    review_intervals_days: Mapped[list[int]] = mapped_column(
        JSON, nullable=False, default=lambda: [7, 15, 30]
    )
    max_evidence_window: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    # 仅用于展示与将来扩展：说明这个策略为什么这样配置。
    note: Mapped[str | None] = mapped_column(Text)


class DailyPlan(Base, TimestampMixin):
    """某个上海学习日的一份练习卷；同一天只保留一份活动计划。"""

    __tablename__ = "daily_plans"
    __table_args__ = (UniqueConstraint("study_date", name="daily_plan_date"),)

    id: Mapped[UUID] = uuid_pk()
    # 上海日期字符串 YYYY-MM-DD；用 String 让跨天比较与索引都稳定。
    study_date: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    items: Mapped[list["PracticeItem"]] = relationship(
        back_populates="plan", order_by="PracticeItem.ordinal"
    )


class PracticeItem(Base, TimestampMixin):
    """今日练习卷里的一道题及顺序；追加只写 max(ordinal)+1，做完不删除。"""

    __tablename__ = "practice_items"
    __table_args__ = (
        UniqueConstraint("plan_id", "question_id", name="practice_item_plan_question"),
        UniqueConstraint("plan_id", "ordinal", name="practice_item_plan_ordinal"),
    )

    id: Mapped[UUID] = uuid_pk()
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("daily_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id"), nullable=False
    )
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_self_grade: Mapped[str | None] = mapped_column(String(30))

    question: Mapped[Question] = relationship()
    plan: Mapped[DailyPlan] = relationship(back_populates="items")


class QuestionAttempt(Base):
    """用户每次练习与自评的永久历史；不继承 TimestampMixin（提交时间即事实时间）。"""

    __tablename__ = "question_attempts"

    id: Mapped[UUID] = uuid_pk()
    practice_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("practice_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id"), nullable=False, index=True
    )
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    raw_answer: Mapped[str | None] = mapped_column(Text)
    # 机器判分只是复盘参考，绝不覆盖 self_grade。
    objective_result: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown"
    )
    self_grade: Mapped[str] = mapped_column(String(30), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 客户端重复提交同一动作时不再产生第二条历史。
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # 本次自评之后该叶子的状态与原因，供回看与排错。
    result_state: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningEvent(Base):
    """状态变化的不可变事实；只追加，不修改。"""

    __tablename__ = "learning_events"

    id: Mapped[UUID] = uuid_pk()
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 无外键：事件可能引用题目、计划或节点自评，来源类型随 event_type 变化。
    source_id: Mapped[UUID | None] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence_level: Mapped[str | None] = mapped_column(String(30))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)