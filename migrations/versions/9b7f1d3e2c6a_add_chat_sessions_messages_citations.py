from alembic import op
import sqlalchemy as sa
revision = "9b7f1d3e2c6a"
down_revision = "4e69a0e83a3b"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table("chat_sessions", sa.Column("id", sa.Uuid(), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("mode", sa.String(20), nullable=False), sa.Column("archived_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.CheckConstraint("mode IN ('builtin', 'user')", name="chat_session_mode_valid"), sa.PrimaryKeyConstraint("id"))
    op.create_table("chat_messages", sa.Column("id", sa.Uuid(), nullable=False), sa.Column("session_id", sa.Uuid(), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("matched_kp_id", sa.Uuid()), sa.Column("metadata", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["matched_kp_id"], ["knowledge_points.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_table("message_citations", sa.Column("id", sa.Uuid(), nullable=False), sa.Column("message_id", sa.Uuid(), nullable=False), sa.Column("chunk_id", sa.Uuid(), nullable=False), sa.Column("label", sa.String(20), nullable=False), sa.Column("ordinal", sa.Integer(), nullable=False), sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("message_id", "label", name="citation_label_once"), sa.UniqueConstraint("message_id", "chunk_id", name="citation_chunk_once"))
    op.create_index("ix_message_citations_message_id", "message_citations", ["message_id"])
    op.create_index("ix_message_citations_chunk_id", "message_citations", ["chunk_id"])
def downgrade() -> None:
    op.drop_table("message_citations")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
