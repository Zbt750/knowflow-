from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session as OrmSession

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
    # 自引用父节点；根节点为 NULL。父节点不绑定练习题。
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_points.id"))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 只有 True 的叶子才能绑定题目、记录练习、自评和毕业。
    is_assessable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 历年考点索引叶子只持有原卷来源引用，不含题干；完成原卷后可自评并计入该节点毕业。
    is_reference_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    assessment_basis: Mapped[str] = mapped_column(String(30), nullable=False, default="legacy_self_reported")
    pending_review_question_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # evidence_window 只存去重后的真实题目/历年原卷引用的 mastered 确认 + 上海日期。
    evidence_window: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    review_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mastered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 叶子整体自评结果；不伪造 QuestionAttempt。
    node_self_grade: Mapped[str | None] = mapped_column(String(30))
    # 透明基础确认数：节点整体自评「我已掌握」时写 2。
    manual_credit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 用户首次开始该知识点时固定的 v3 题集版本。None 表示尚未开始，跟随当前发布版。
    graduation_set_version: Mapped[int | None] = mapped_column(Integer)
    # Legacy activity without a trustworthy frozen set remains visible, but
    # cannot count toward v3 until the learner explicitly starts that set.
    graduation_set_binding_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unstarted", server_default="unstarted"
    )
    graduation_set_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Question(Base, TimestampMixin):
    """一道题只属于一个叶子知识点；题干不复制进练习记录。"""

    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint("bank_scope IN ('public','personal')", name="question_bank_scope_valid"),
        Index("ix_questions_bank_node_visible", "bank_scope", "kp_id", "is_hidden"),
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["question_versions.question_id", "question_versions.id"],
            name="fk_question_current_version_pair",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_type: Mapped[str] = mapped_column(String(30), nullable=False)
    grading_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="self_assessed"
    )
    grading_config: Mapped[dict[str, Any] | None] = mapped_column(JSON)
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
    # Ownership is not provenance or certification. Existing rows remain public.
    bank_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="public", server_default="public")
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    generation_batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("personal_generation_batches.id", ondelete="RESTRICT"), index=True)
    # Trust is deliberately separate from grading_config.provenance, which is a
    # legacy import snapshot and must not silently certify old questions.
    question_provenance: Mapped[str] = mapped_column(String(40), nullable=False, default="legacy_unknown")
    content_trust: Mapped[str] = mapped_column(String(30), nullable=False, default="unreviewed")
    source_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    answer_provenance: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    answer_reliability: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    content_reviewed_by: Mapped[str | None] = mapped_column(String(100))
    content_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_reviewed_by: Mapped[str | None] = mapped_column(String(100))
    answer_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # This pointer is the only active answer-verification stamp. Eligibility
    # also checks its content hash, so edits cannot inherit stale trust.
    answer_verification_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_answer_verification_events.id", ondelete="RESTRICT",
                   use_alter=True, name="fk_question_current_answer_verification"),
        nullable=True,
    )
    current_answer_verification: Mapped["QuestionAnswerVerificationEvent | None"] = relationship(
        foreign_keys=[answer_verification_event_id], post_update=True,
    )
    auto_review_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_auto_review_events.id", ondelete="RESTRICT",
                   use_alter=True, name="fk_question_current_auto_review"),
        nullable=True,
    )
    current_auto_review: Mapped["QuestionAutoReviewEvent | None"] = relationship(
        foreign_keys=[auto_review_event_id], post_update=True,
    )
    # Machine/source attestation is separate from human review and binds only
    # the imported question stem/options/type/mapping, not its answer key.
    source_attestation_key: Mapped[str | None] = mapped_column(String(64))
    source_attestation_sha256: Mapped[str | None] = mapped_column(String(64))
    answer_attestation_key: Mapped[str | None] = mapped_column(String(64))
    answer_attestation_sha256: Mapped[str | None] = mapped_column(String(64))
    current_version: Mapped["QuestionVersion | None"] = relationship(
        "QuestionVersion",
        primaryjoin="and_(Question.id == QuestionVersion.question_id, "
                    "Question.current_version_id == QuestionVersion.id)",
        foreign_keys="[Question.id, Question.current_version_id]",
        post_update=True,
    )
    versions: Mapped[list["QuestionVersion"]] = relationship(
        foreign_keys="QuestionVersion.question_id", back_populates="question",
        order_by="QuestionVersion.version_number", cascade="save-update, merge",
    )


class QuestionVersion(Base):
    """Append-only, hash-bound snapshot of the question content and trust state."""

    __tablename__ = "question_versions"
    __table_args__ = (
        UniqueConstraint("question_id", "version_number", name="uq_question_version_number"),
        UniqueConstraint("question_id", "id", name="uq_question_version_question_id_id"),
        CheckConstraint("version_number >= 1", name="question_version_number_positive"),
        CheckConstraint("length(content_hash) = 64", name="question_version_hash_length"),
    )

    id: Mapped[UUID] = uuid_pk()
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kp_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="RESTRICT"), nullable=False)
    question_type: Mapped[str] = mapped_column(String(30), nullable=False)
    grading_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    grading_config: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(JSON)
    correct_answer: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    question_role: Mapped[str] = mapped_column(String(30), nullable=False)
    skill_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_variant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    variant_group: Mapped[str | None] = mapped_column(String(120))
    difficulty: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    bank_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False)
    generation_batch_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    question_provenance: Mapped[str] = mapped_column(String(40), nullable=False)
    content_trust: Mapped[str] = mapped_column(String(30), nullable=False)
    source_status: Mapped[str] = mapped_column(String(30), nullable=False)
    answer_provenance: Mapped[str] = mapped_column(String(40), nullable=False)
    answer_reliability: Mapped[str] = mapped_column(String(40), nullable=False)
    content_reviewed_by: Mapped[str | None] = mapped_column(String(100))
    content_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_reviewed_by: Mapped[str | None] = mapped_column(String(100))
    answer_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_verification_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    auto_review_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    source_attestation_key: Mapped[str | None] = mapped_column(String(64))
    source_attestation_sha256: Mapped[str | None] = mapped_column(String(64))
    answer_attestation_key: Mapped[str | None] = mapped_column(String(64))
    answer_attestation_sha256: Mapped[str | None] = mapped_column(String(64))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    review_status: Mapped[str] = mapped_column(String(40), nullable=False, default="snapshot_only")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    question: Mapped[Question] = relationship(
        foreign_keys=[question_id], back_populates="versions"
    )


class QuestionSourceAttestation(Base):
    """Append-only deterministic record; never a human-review certificate."""

    __tablename__ = "question_source_attestations"
    __table_args__ = (
        UniqueConstraint("attestation_key", name="uq_question_source_attestation_key"),
        UniqueConstraint("question_id", "source_content_sha256", "pack_id", "pack_version",
                         name="uq_question_source_attestation_snapshot"),
        CheckConstraint("status IN ('source_attested','needs_review','conflict')",
                        name="question_source_attestation_status_valid"),
    )

    id: Mapped[UUID] = uuid_pk()
    attestation_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    candidate_id: Mapped[str] = mapped_column(String(160), nullable=False)
    pack_id: Mapped[str] = mapped_column(String(100), nullable=False)
    pack_version: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_archive_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    question_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str] = mapped_column(String(500), nullable=False)
    mapping_type: Mapped[str] = mapped_column(String(80), nullable=False)
    attestation_method: Mapped[str] = mapped_column(String(100), nullable=False)
    attestation_source: Mapped[str] = mapped_column(String(160), nullable=False)
    source_identity: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    detected_issues: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class QuestionAnswerConsistencyRun(Base):
    """One independent, content-hash-bound AI answer solve; never an official key."""

    __tablename__ = "question_answer_consistency_runs"
    __table_args__ = (
        UniqueConstraint("check_key", "run_number", name="uq_answer_consistency_check_run"),
        CheckConstraint("run_number >= 1 AND run_number <= 6", name="answer_consistency_run_bound"),
        CheckConstraint("status IN ('completed','failed','unsupported')", name="answer_consistency_status_valid"),
        CheckConstraint("run_role IN ('solve_a','solve_b','verify_c','legacy_solve')", name="answer_consistency_role_valid"),
        Index("ix_answer_consistency_question_hash", "question_id", "question_content_sha256"),
    )

    id: Mapped[UUID] = uuid_pk()
    check_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    question_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    run_role: Mapped[str | None] = mapped_column(String(20))
    configured_model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_final_answer: Mapped[str | None] = mapped_column(Text)
    # Only the requested final answer, never chain-of-thought or solver reasoning.
    final_answer: Mapped[str | None] = mapped_column(Text)
    verification_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    verification_note: Mapped[str | None] = mapped_column(String(500))
    candidate_answers_sha256: Mapped[str | None] = mapped_column(String(64))
    source_answer_sha256: Mapped[str | None] = mapped_column(String(64))
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(80))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class QuestionAnswerVerificationEvent(Base):
    """Append-only human/reference answer verification audit record.

    AI consistency runs deliberately remain a separate table and can never
    create one of these records.
    """

    __tablename__ = "question_answer_verification_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_answer_verification_idempotency"),
        CheckConstraint("event_type IN ('verified','revoked')", name="answer_verification_event_type_valid"),
        CheckConstraint("verification_type IN ('human_verified','verified_reference')",
                        name="answer_verification_type_valid"),
        CheckConstraint("length(answer_sha256) = 64", name="answer_verification_hash_length"),
        CheckConstraint("length(idempotency_key) BETWEEN 1 AND 160",
                        name="answer_verification_idempotency_length"),
        Index("ix_answer_verification_question_created", "question_id", "created_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    verification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    answer_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(120), nullable=False)
    verifier: Mapped[str] = mapped_column(String(100), nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    related_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_answer_verification_events.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    question: Mapped[Question] = relationship(
        foreign_keys=[question_id], backref="answer_verification_events"
    )
    related_event: Mapped["QuestionAnswerVerificationEvent | None"] = relationship(
        remote_side="QuestionAnswerVerificationEvent.id", foreign_keys=[related_event_id]
    )


class QuestionAutoReviewEvent(Base):
    """Append-only machine quality decision bound to one full question snapshot.

    This is intentionally distinct from human answer verification. A passing
    event can qualify a public question for bounded objective evidence, but it
    never records a human reviewer or changes learner graduation rules.
    """

    __tablename__ = "question_auto_review_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_question_auto_review_idempotency"),
        CheckConstraint("event_type IN ('qualified','revoked')",
                        name="question_auto_review_event_type_valid"),
        CheckConstraint("qualification_class IN ('exam_curated','exam_variant','development_original')",
                        name="question_auto_review_class_valid"),
        CheckConstraint("length(question_snapshot_sha256) = 64",
                        name="question_auto_review_snapshot_hash_length"),
        CheckConstraint("length(answer_sha256) = 64",
                        name="question_auto_review_answer_hash_length"),
        CheckConstraint("length(audit_sha256) = 64",
                        name="question_auto_review_audit_hash_length"),
        Index("ix_question_auto_review_question_created", "question_id", "created_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    qualification_class: Mapped[str] = mapped_column(String(30), nullable=False)
    review_version: Mapped[str] = mapped_column(String(80), nullable=False)
    question_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    related_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_auto_review_events.id", ondelete="RESTRICT")
    )
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    question: Mapped[Question] = relationship(foreign_keys=[question_id], backref="auto_review_events")
    related_event: Mapped["QuestionAutoReviewEvent | None"] = relationship(
        remote_side="QuestionAutoReviewEvent.id", foreign_keys=[related_event_id]
    )


class ExamQuestionReference(Base, TimestampMixin):
    """历年试题的题号引用；不包含题干，不是可作答的 Question。"""

    __tablename__ = "exam_question_references"
    __table_args__ = (
        UniqueConstraint(
            "subject",
            "year",
            "question_number",
            "knowledge_point_id",
            name="exam_ref_question_kp",
        ),
        Index("ix_exam_ref_kp_year_q", "knowledge_point_id", "year", "question_number"),
    )

    id: Mapped[UUID] = uuid_pk()
    subject: Mapped[str] = mapped_column(String(80), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    knowledge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False
    )
    # topic_label 是拆分后绑定到节点的标签；source_topic_label 保留索引原始整行标签。
    topic_label: Mapped[str] = mapped_column(Text, nullable=False)
    source_topic_label: Mapped[str] = mapped_column(Text, nullable=False)
    question_source_url: Mapped[str | None] = mapped_column(Text)
    topic_source_url: Mapped[str | None] = mapped_column(Text)
    # 项目不打包原卷；该字段指向用户桌面年度文件夹中的相对目录。
    local_folder: Mapped[str] = mapped_column(String(100), nullable=False)
    source_note: Mapped[str] = mapped_column(Text, nullable=False)


class KpMasteryPolicy(Base, TimestampMixin):
    """每个可考核叶子的版本化毕业策略；v3 指向一个冻结题目集合。"""

    __tablename__ = "kp_mastery_policies"
    __table_args__ = (
        CheckConstraint("min_confirmations >= 1", name="kp_policy_min_confirmations"),
        CheckConstraint("min_real_questions >= 1", name="kp_policy_min_real_questions"),
        CheckConstraint("required_variant_count >= 0", name="kp_policy_variant_count"),
        CheckConstraint("min_day_span >= 0", name="kp_policy_day_span"),
        CheckConstraint("manual_mastered_credit >= 0", name="kp_policy_manual_credit"),
        CheckConstraint("policy_version IN (1,2,3)", name="kp_policy_version"),
        CheckConstraint("jsonb_typeof(required_question_origins::jsonb) = 'object'", name="kp_policy_origins_object"),
        CheckConstraint("(policy_version = 1 AND required_question_origins::jsonb = '{}'::jsonb) OR "
            "(policy_version = 2 AND NOT (required_question_types::jsonb ? 'external_exam')) OR "
            "(policy_version = 3 AND required_question_origins::jsonb = '{}'::jsonb "
            "AND NOT (required_question_types::jsonb ? 'external_exam'))",
            name="kp_policy_origin_semantics"),
        CheckConstraint("(policy_version IN (1,2) AND graduation_set_version = 0 "
            "AND graduation_question_ids::jsonb = '[]'::jsonb) OR "
            "(policy_version = 3 AND ((graduation_set_version = 0 AND graduation_question_ids::jsonb = '[]'::jsonb) OR "
            "(graduation_set_version >= 1 AND jsonb_typeof(graduation_question_ids::jsonb) = 'array' "
            "AND jsonb_array_length(graduation_question_ids::jsonb) BETWEEN 1 AND 200)))",
            name="kp_policy_graduation_set_semantics"),
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
    # Version 1 reads historical type quotas; version 2 separates provenance.
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    required_question_origins: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    graduation_question_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    graduation_set_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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


class KpGraduationQuestionSetVersion(Base):
    """只追加的毕业题目集合版本记录；题库新增不会自动修改既有集合。"""

    __tablename__ = "kp_graduation_question_set_versions"
    __table_args__ = (
        CheckConstraint("set_version >= 1", name="kp_graduation_set_version_positive"),
        CheckConstraint("jsonb_typeof(question_ids::jsonb) = 'array'",
            name="kp_graduation_set_question_ids_array"),
        CheckConstraint("jsonb_array_length(question_ids::jsonb) BETWEEN 1 AND 200",
            name="kp_graduation_set_question_ids_bounded"),
        CheckConstraint("length(question_ids_sha256) = 64", name="kp_graduation_set_hash_length"),
        CheckConstraint("length(trim(reason)) > 0", name="kp_graduation_set_reason_nonempty"),
    )

    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True
    )
    set_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    question_ids_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Ordered immutable content-version bindings parallel to question_ids.
    question_version_ids: Mapped[list[str] | None] = mapped_column(JSON)
    question_version_ids_sha256: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
    """今日卷中的一道题或一道原卷任务；两种来源恰有一种。"""

    __tablename__ = "practice_items"
    __table_args__ = (
        UniqueConstraint("plan_id", "question_id", name="practice_item_plan_question"),
        UniqueConstraint("plan_id", "exam_reference_id", name="practice_item_plan_exam_reference"),
        UniqueConstraint("plan_id", "ordinal", name="practice_item_plan_ordinal"),
        UniqueConstraint("retry_key", name="uq_practice_retry_key"),
        CheckConstraint("(plan_id IS NOT NULL AND retry_source_id IS NULL AND retry_key IS NULL) OR "
            "(plan_id IS NULL AND retry_source_id IS NOT NULL AND retry_key IS NOT NULL)", name="practice_item_plan_or_retry"),
        CheckConstraint(
            "(question_id IS NOT NULL AND exam_reference_id IS NULL) OR "
            "(question_id IS NULL AND exam_reference_id IS NOT NULL)",
            name="practice_item_exactly_one_source",
        ),
        CheckConstraint("question_id IS NULL OR question_version_id IS NOT NULL",
                        name="practice_item_question_requires_version"),
        ForeignKeyConstraint(
            ["question_id", "question_version_id"],
            ["question_versions.question_id", "question_versions.id"],
            name="fk_practice_item_question_version_pair",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("daily_plans.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Explicitly requested retries are standalone instances, never extra paper items.
    retry_source_id: Mapped[UUID | None] = mapped_column(ForeignKey("practice_items.id"), nullable=True, index=True)
    retry_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    question_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("questions.id"), nullable=True
    )
    question_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    exam_reference_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("exam_question_references.id"), nullable=True
    )
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_self_grade: Mapped[str | None] = mapped_column(String(30))
    answer_revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    question: Mapped[Question | None] = relationship()
    question_version: Mapped[QuestionVersion | None] = relationship(foreign_keys=[question_version_id])
    exam_reference: Mapped[ExamQuestionReference | None] = relationship()
    plan: Mapped[DailyPlan] = relationship(back_populates="items")
    attempts: Mapped[list["QuestionAttempt"]] = relationship(back_populates="practice_item")


class PracticeRetryRequest(Base):
    """Durable aliases when two tabs resume the same pending retry."""
    __tablename__ = 'practice_retry_requests'
    idempotency_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey('practice_items.id', ondelete='CASCADE'), nullable=False)
    retry_id: Mapped[UUID] = mapped_column(ForeignKey('practice_items.id', ondelete='CASCADE'), nullable=False)


class QuestionAttempt(Base):
    """用户每次练习与自评的永久历史；不继承 TimestampMixin（提交时间即事实时间）。"""

    __tablename__ = "question_attempts"

    id: Mapped[UUID] = uuid_pk()
    practice_item: Mapped[PracticeItem] = relationship(
        back_populates="attempts", foreign_keys="QuestionAttempt.practice_item_id"
    )
    question_version: Mapped[QuestionVersion | None] = relationship(foreign_keys="QuestionAttempt.question_version_id")
    practice_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("practice_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    __table_args__ = (
        CheckConstraint(
            "(question_id IS NOT NULL AND exam_reference_id IS NULL) OR "
            "(question_id IS NULL AND exam_reference_id IS NOT NULL)",
            name="question_attempt_exactly_one_source",
        ),
        CheckConstraint("question_id IS NULL OR question_version_id IS NOT NULL",
                        name="question_attempt_question_requires_version"),
        Index("ix_question_attempts_exam_reference_id", "exam_reference_id"),
        ForeignKeyConstraint(
            ["question_id", "question_version_id"],
            ["question_versions.question_id", "question_versions.id"],
            name="fk_attempt_question_version_pair",
        ),
    )

    question_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("questions.id"), nullable=True, index=True
    )
    question_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    exam_reference_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("exam_question_references.id"), nullable=True
    )
    kp_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    raw_answer: Mapped[str | None] = mapped_column(Text)
    # 机器判分只是复盘参考，绝不覆盖 self_grade。
    objective_result: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown"
    )
    self_grade: Mapped[str | None] = mapped_column(String(30), nullable=True)
    grading_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
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
    question_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence_level: Mapped[str | None] = mapped_column(String(30))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)


@event.listens_for(OrmSession, "before_flush")
def _ensure_question_version_bindings(session, _flush_context, _instances):
    # Imported lazily to avoid model/service import cycles during mapper setup.
    from backend.services.question_versions import ensure_question_versions_for_flush
    ensure_question_versions_for_flush(session)
