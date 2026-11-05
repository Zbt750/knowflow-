"""add annual exam question references to knowledge points

Revision ID: f17c6a1d4b20
Revises: e54f60dca851
Create Date: 2026-09-27 00:00:00

The new reference table stores year/question/source metadata only. It deliberately
does not copy exam stems or answer explanations into the practice question bank.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f17c6a1d4b20"
down_revision: str | None = "e54f60dca851"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_points",
        sa.Column(
            "is_reference_only",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_table(
        "exam_question_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=80), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("question_number", sa.Integer(), nullable=False),
        sa.Column("knowledge_point_id", sa.Uuid(), nullable=False),
        sa.Column("topic_label", sa.Text(), nullable=False),
        sa.Column("source_topic_label", sa.Text(), nullable=False),
        sa.Column("question_source_url", sa.Text(), nullable=True),
        sa.Column("topic_source_url", sa.Text(), nullable=True),
        sa.Column("local_folder", sa.String(length=100), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"],
            ["knowledge_points.id"],
            name="fk_exam_question_references_knowledge_point_id_knowledge_points",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exam_question_references"),
        sa.UniqueConstraint(
            "subject",
            "year",
            "question_number",
            "knowledge_point_id",
            name="exam_ref_question_kp",
        ),
    )
    op.create_index(
        "ix_exam_ref_kp_year_q",
        "exam_question_references",
        ["knowledge_point_id", "year", "question_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_exam_ref_kp_year_q", table_name="exam_question_references")
    op.drop_table("exam_question_references")
    op.drop_column("knowledge_points", "is_reference_only")
