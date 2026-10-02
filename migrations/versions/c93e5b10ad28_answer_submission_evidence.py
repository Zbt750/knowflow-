"""Add verified grading configuration and append-only answer evidence.

Revision ID: c93e5b10ad28
Revises: b82d4a90ce17
"""
from alembic import op
import sqlalchemy as sa

revision = "c93e5b10ad28"
down_revision = "b82d4a90ce17"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("questions", sa.Column("grading_config", sa.JSON(), nullable=True))
    op.add_column("practice_items", sa.Column("answer_revealed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("question_attempts", sa.Column("grading_evidence", sa.JSON(), nullable=True))
    op.alter_column("question_attempts", "self_grade", existing_type=sa.String(30), nullable=True)


def downgrade():
    # 自动作答无自评，不能伪造自评来满足旧表结构；存在新证据时拒绝降级。
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM question_attempts WHERE self_grade IS NULL")).scalar()
    if count:
        raise RuntimeError("Answer evidence exists; restore a pre-upgrade backup instead of discarding history")
    op.alter_column("question_attempts", "self_grade", existing_type=sa.String(30), nullable=False)
    op.drop_column("question_attempts", "grading_evidence")
    op.drop_column("practice_items", "answer_revealed_at")
    op.drop_column("questions", "grading_config")
