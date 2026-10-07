"""Persist bounded independent AI answer-consistency runs.

Revision ID: c5a8f2d10e73
Revises: f26a91c7d840
"""
from alembic import op
import sqlalchemy as sa


revision = "c5a8f2d10e73"
down_revision = "f26a91c7d840"
branch_labels = depends_on = None


def upgrade():
    op.drop_constraint("question_answer_reliability_valid", "questions", type_="check")
    op.create_check_constraint("question_answer_reliability_valid", "questions",
        "answer_reliability IN ('verified','ai_generated_consistent','ai_disagreement','model_generated','unverified','unknown')")
    op.create_table(
        "question_answer_consistency_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("check_key", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("question_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("configured_model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("normalizer_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("normalized_final_answer", sa.Text(), nullable=True),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("run_number >= 1 AND run_number <= 4", name="answer_consistency_run_bound"),
        sa.CheckConstraint("status IN ('completed','failed','unsupported')", name="answer_consistency_status_valid"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("check_key", "run_number", name="uq_answer_consistency_check_run"),
    )
    op.create_index("ix_question_answer_consistency_runs_check_key",
                    "question_answer_consistency_runs", ["check_key"], unique=False)
    op.create_index("ix_answer_consistency_question_hash", "question_answer_consistency_runs",
                    ["question_id", "question_content_sha256"], unique=False)


def downgrade():
    bind = op.get_bind()
    disagreements = bind.execute(sa.text(
        "SELECT count(*) FROM questions WHERE answer_reliability='ai_disagreement'"
    )).scalar_one()
    if disagreements:
        raise RuntimeError("AI disagreement reliability exists; preserve it before downgrade")
    runs = bind.execute(sa.text("SELECT count(*) FROM question_answer_consistency_runs")).scalar_one()
    if runs:
        raise RuntimeError("Consistency run history exists; preserve it before downgrade")
    op.drop_index("ix_answer_consistency_question_hash", table_name="question_answer_consistency_runs")
    op.drop_index("ix_question_answer_consistency_runs_check_key", table_name="question_answer_consistency_runs")
    op.drop_table("question_answer_consistency_runs")
    op.drop_constraint("question_answer_reliability_valid", "questions", type_="check")
    op.create_check_constraint("question_answer_reliability_valid", "questions",
        "answer_reliability IN ('verified','ai_generated_consistent','model_generated','unverified','unknown')")
