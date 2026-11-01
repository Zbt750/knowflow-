"""Personal local bank; no provenance or historical evidence conversion."""
from alembic import op
import sqlalchemy as sa

revision = "f47c10a2b903"
down_revision = "f46b2c8d901a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("personal_generation_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_key", sa.String(36), nullable=False, unique=True),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("study_date", sa.String(10), nullable=False),
        sa.Column("reserved_calls", sa.Integer(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_personal_generation_batches_study_date", "personal_generation_batches", ["study_date"])
    op.add_column("questions", sa.Column("bank_scope", sa.String(20), nullable=False, server_default="public"))
    op.add_column("questions", sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("questions", sa.Column("generation_batch_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_question_generation_batch", "questions", "personal_generation_batches", ["generation_batch_id"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("question_bank_scope_valid", "questions", "bank_scope IN ('public','personal')")
    op.create_index("ix_questions_generation_batch_id", "questions", ["generation_batch_id"])
    op.create_index("ix_questions_bank_node_visible", "questions", ["bank_scope", "kp_id", "is_hidden"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM personal_generation_batches")).scalar_one():
        raise RuntimeError("Personal generation history exists; refusing destructive downgrade")
    op.drop_index("ix_questions_bank_node_visible", table_name="questions")
    op.drop_index("ix_questions_generation_batch_id", table_name="questions")
    op.drop_constraint("question_bank_scope_valid", "questions")
    op.drop_constraint("fk_question_generation_batch", "questions", type_="foreignkey")
    for column in ("generation_batch_id", "is_hidden", "bank_scope"):
        op.drop_column("questions", column)
    op.drop_table("personal_generation_batches")
