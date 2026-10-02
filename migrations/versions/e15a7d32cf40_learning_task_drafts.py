"""Persist read-only learning task drafts, not daily plans.
Revision ID: e15a7d32cf40
Revises: d04f6c21be39
"""
from alembic import op
import sqlalchemy as sa
revision = "e15a7d32cf40"
down_revision = "d04f6c21be39"
branch_labels = depends_on = None


def upgrade():
    op.create_table("learning_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("chat_sessions.id", ondelete="SET NULL")),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("budget_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("run_token", sa.String(36)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("draft", sa.JSON()), sa.Column("context", sa.JSON()),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(60)), sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('created','running','ready','needs_info','failed','cancelled')", name="learning_task_status_valid"),
        sa.CheckConstraint("budget_minutes >= 5 AND budget_minutes <= 240", name="learning_task_budget_valid"))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM learning_tasks")).scalar():
        raise RuntimeError("Learning drafts exist; back them up before removing the task table")
    op.drop_table("learning_tasks")
