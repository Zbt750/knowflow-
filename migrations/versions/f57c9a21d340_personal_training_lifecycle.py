"""Add independent personal training lifecycle tables."""
from alembic import op
import sqlalchemy as sa

revision = "f57c9a21d340"
down_revision = "f56b8c9012d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_trainings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_session_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(length=100), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("selected_kp_ids", sa.JSON(), nullable=False),
        sa.Column("selection_basis", sa.String(length=32), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=True),
        sa.Column("target_minutes", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=False),
        sa.Column("question_type", sa.String(length=30), nullable=True),
        sa.Column("adapted_from_training_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active','paused','completed','cancelled')", name=op.f("ck_personal_trainings_personal_training_status_valid")),
        sa.CheckConstraint("target_minutes BETWEEN 5 AND 240", name=op.f("ck_personal_trainings_personal_training_target_minutes_valid")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_personal_trainings_personal_training_version_positive")),
        sa.ForeignKeyConstraint(["owner_session_id"], ["chat_sessions.id"], name=op.f("fk_personal_trainings_owner_session_id_chat_sessions"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["adapted_from_training_id"], ["personal_trainings.id"], name=op.f("fk_personal_trainings_adapted_from_training_id_personal_trainings"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personal_trainings")),
        sa.UniqueConstraint("request_key", name=op.f("uq_personal_trainings_request_key")),
    )
    op.create_index("ix_personal_trainings_owner_session_id", "personal_trainings", ["owner_session_id"])
    op.create_index("ix_personal_trainings_owner_status_updated", "personal_trainings", ["owner_session_id", "status", "updated_at"])

    op.create_table(
        "personal_training_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("training_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("question_version_id", sa.Uuid(), nullable=False),
        sa.Column("kp_id", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["training_id"], ["personal_trainings.id"], name=op.f("fk_personal_training_items_training_id_personal_trainings"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], name=op.f("fk_personal_training_items_question_id_questions"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_version_id"], ["question_versions.id"], name=op.f("fk_personal_training_items_question_version_id_question_versions"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["kp_id"], ["knowledge_points.id"], name=op.f("fk_personal_training_items_kp_id_knowledge_points"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_id", "question_version_id"], ["question_versions.question_id", "question_versions.id"], name=op.f("fk_personal_training_question_version_pair")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personal_training_items")),
        sa.UniqueConstraint("training_id", "question_id", name=op.f("personal_training_question_once")),
        sa.UniqueConstraint("training_id", "ordinal", name=op.f("personal_training_ordinal_once")),
    )
    op.create_index("ix_personal_training_items_training_completed", "personal_training_items", ["training_id", "completed_at"])

    op.create_table(
        "personal_training_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("training_item_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("question_version_id", sa.Uuid(), nullable=False),
        sa.Column("kp_id", sa.Uuid(), nullable=False),
        sa.Column("raw_answer", sa.Text(), nullable=True),
        sa.Column("selected_option", sa.String(length=20), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("method", sa.String(length=80), nullable=False),
        sa.Column("grading_evidence", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["training_item_id"], ["personal_training_items.id"], name=op.f("fk_personal_training_attempts_training_item_id_personal_training_items"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], name=op.f("fk_personal_training_attempts_question_id_questions"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_version_id"], ["question_versions.id"], name=op.f("fk_personal_training_attempts_question_version_id_question_versions"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["kp_id"], ["knowledge_points.id"], name=op.f("fk_personal_training_attempts_kp_id_knowledge_points"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_id", "question_version_id"], ["question_versions.question_id", "question_versions.id"], name=op.f("fk_personal_training_attempt_question_version_pair")),
        sa.CheckConstraint("result IN ('right','wrong','unknown')", name=op.f("ck_personal_training_attempts_personal_training_attempt_result_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personal_training_attempts")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_personal_training_attempts_idempotency_key")),
    )
    op.create_index("ix_personal_training_attempts_training_item_id", "personal_training_attempts", ["training_item_id"])
    op.create_index("ix_personal_training_attempts_item_submitted", "personal_training_attempts", ["training_item_id", "submitted_at"])

    op.create_table(
        "personal_training_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("training_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["training_id"], ["personal_trainings.id"], name=op.f("fk_personal_training_actions_training_id_personal_trainings"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personal_training_actions")),
        sa.UniqueConstraint("request_key", name=op.f("uq_personal_training_actions_request_key")),
    )
    op.create_index("ix_personal_training_actions_training", "personal_training_actions", ["training_id", "created_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM personal_training_attempts LIMIT 1")).first():
        raise RuntimeError("Preserve personal training attempts before downgrade")
    if op.get_bind().execute(sa.text("SELECT 1 FROM personal_trainings LIMIT 1")).first():
        raise RuntimeError("Preserve personal training records before downgrade")
    op.drop_index("ix_personal_training_actions_training", table_name=op.f("personal_training_actions"))
    op.drop_table("personal_training_actions")
    op.drop_index("ix_personal_training_attempts_item_submitted", table_name=op.f("personal_training_attempts"))
    op.drop_index("ix_personal_training_attempts_training_item_id", table_name=op.f("personal_training_attempts"))
    op.drop_table("personal_training_attempts")
    op.drop_index("ix_personal_training_items_training_completed", table_name=op.f("personal_training_items"))
    op.drop_table("personal_training_items")
    op.drop_index("ix_personal_trainings_owner_status_updated", table_name=op.f("personal_trainings"))
    op.drop_index("ix_personal_trainings_owner_session_id", table_name=op.f("personal_trainings"))
    op.drop_table("personal_trainings")

