"""Phase 4C conversation purposes and two-confirmation practice requests.

Revision ID: e42c7a10b9f3
Revises: d31b8c9e2a74
"""
from alembic import op
import sqlalchemy as sa
revision="e42c7a10b9f3"
down_revision="d31b8c9e2a74"
branch_labels=None
depends_on=None
def upgrade():
    op.add_column("chat_sessions",sa.Column("purpose",sa.String(20),nullable=False,server_default="qa"))
    op.add_column("chat_sessions",sa.Column("study_date",sa.String(10)))
    op.add_column("chat_sessions",sa.Column("material_scope_ids",sa.JSON(),nullable=False,server_default=sa.text("'[]'::json")))
    op.create_table("practice_requests",
        sa.Column("id",sa.UUID(),primary_key=True),sa.Column("status",sa.String(20),nullable=False),
        sa.Column("source_conversation_id",sa.UUID(),sa.ForeignKey("chat_sessions.id",ondelete="SET NULL")),
        sa.Column("source_message_id",sa.UUID(),sa.ForeignKey("chat_messages.id",ondelete="SET NULL")),
        sa.Column("request",sa.JSON(),nullable=False),sa.Column("user_request",sa.Text(),nullable=False),
        sa.Column("handled_at",sa.DateTime(timezone=True)),
        sa.Column("planner_task_id",sa.UUID(),sa.ForeignKey("learning_tasks.id",ondelete="SET NULL")),
        sa.Column("daily_plan_id",sa.UUID(),sa.ForeignKey("daily_plans.id",ondelete="SET NULL")),
        sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("error_code",sa.String(80)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft','pending','planning','proposed','accepted','declined','expired','failed')",name="practice_request_status_valid"),
        sa.UniqueConstraint("source_message_id",name="practice_request_source_once"))
def downgrade():
    op.drop_table("practice_requests")
    op.drop_column("chat_sessions","material_scope_ids")
    op.drop_column("chat_sessions","study_date")
    op.drop_column("chat_sessions","purpose")
