"""allow annual exam references to be scheduled and assessed

Revision ID: b82d4a90ce17
Revises: f17c6a1d4b20
Create Date: 2026-09-28 00:00:00

Practice rows can now point to either a bank question or a source-linked
annual exam reference. Existing rows retain their question_id unchanged.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b82d4a90ce17"
down_revision: str | None = "f17c6a1d4b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("practice_items", "question_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("practice_items", sa.Column("exam_reference_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_practice_items_exam_reference_id_exam_question_references"),
        "practice_items",
        "exam_question_references",
        ["exam_reference_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "practice_item_plan_exam_reference",
        "practice_items",
        ["plan_id", "exam_reference_id"],
    )
    op.create_check_constraint(
        op.f("ck_practice_items_practice_item_exactly_one_source"),
        "practice_items",
        "(question_id IS NOT NULL AND exam_reference_id IS NULL) OR "
        "(question_id IS NULL AND exam_reference_id IS NOT NULL)",
    )

    op.alter_column("question_attempts", "question_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("question_attempts", sa.Column("exam_reference_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_question_attempts_exam_reference_id_exam_question_references"),
        "question_attempts",
        "exam_question_references",
        ["exam_reference_id"],
        ["id"],
    )
    op.create_index(
        "ix_question_attempts_exam_reference_id",
        "question_attempts",
        ["exam_reference_id"],
        unique=False,
    )
    op.create_check_constraint(
        op.f("ck_question_attempts_question_attempt_exactly_one_source"),
        "question_attempts",
        "(question_id IS NOT NULL AND exam_reference_id IS NULL) OR "
        "(question_id IS NULL AND exam_reference_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_question_attempts_question_attempt_exactly_one_source"),
        "question_attempts",
        type_="check",
    )
    op.drop_index("ix_question_attempts_exam_reference_id", table_name="question_attempts")
    op.drop_constraint(
        op.f("fk_question_attempts_exam_reference_id_exam_question_references"),
        "question_attempts",
        type_="foreignkey",
    )
    op.drop_column("question_attempts", "exam_reference_id")
    op.alter_column("question_attempts", "question_id", existing_type=sa.Uuid(), nullable=False)

    op.drop_constraint(
        op.f("ck_practice_items_practice_item_exactly_one_source"),
        "practice_items",
        type_="check",
    )
    op.drop_constraint("practice_item_plan_exam_reference", "practice_items", type_="unique")
    op.drop_constraint(
        op.f("fk_practice_items_exam_reference_id_exam_question_references"),
        "practice_items",
        type_="foreignkey",
    )
    op.drop_column("practice_items", "exam_reference_id")
    op.alter_column("practice_items", "question_id", existing_type=sa.Uuid(), nullable=False)
