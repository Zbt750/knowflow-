"""Bind trusted answer claims to immutable verification events and exact content.

Revision ID: f45a9b7e2c10
Revises: e42c7a10b9f3
"""
from alembic import op
import sqlalchemy as sa


revision = "f45a9b7e2c10"
down_revision = "e42c7a10b9f3"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("question_answer_provenance_valid", "questions", type_="check")
    op.create_check_constraint(
        "question_answer_provenance_valid",
        "questions",
        "answer_provenance IN ('verified_reference','human_verified','ai_generated','legacy_transcription','unknown')",
    )
    op.add_column("questions", sa.Column("answer_verification_event_id", sa.UUID(), nullable=True))
    op.create_table(
        "question_answer_verification_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("verification_type", sa.String(30), nullable=False),
        sa.Column("answer_sha256", sa.String(64), nullable=False),
        sa.Column("verification_method", sa.String(120), nullable=False),
        sa.Column("verifier", sa.String(100), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("previous_state", sa.JSON(), nullable=True),
        sa.Column("related_event_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("event_type IN ('verified','revoked')", name="answer_verification_event_type_valid"),
        sa.CheckConstraint("verification_type IN ('human_verified','verified_reference')", name="answer_verification_type_valid"),
        sa.CheckConstraint("length(answer_sha256) = 64", name="answer_verification_hash_length"),
        sa.CheckConstraint("length(idempotency_key) BETWEEN 1 AND 160", name="answer_verification_idempotency_length"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["related_event_id"], ["question_answer_verification_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_answer_verification_idempotency"),
    )
    op.create_index("ix_question_answer_verification_events_question_id", "question_answer_verification_events", ["question_id"])
    op.create_index("ix_answer_verification_question_created", "question_answer_verification_events", ["question_id", "created_at"])
    op.create_foreign_key(
        "fk_question_current_answer_verification", "questions", "question_answer_verification_events",
        ["answer_verification_event_id"], ["id"], ondelete="RESTRICT",
    )
    # The audit trail is append-only even if a future maintenance script bypasses
    # the service layer. PostgreSQL row triggers do not interfere with TRUNCATE
    # in isolated test schemas.
    op.execute("""
        CREATE FUNCTION reject_answer_verification_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'question answer verification events are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER question_answer_verification_events_immutable
        BEFORE UPDATE OR DELETE ON question_answer_verification_events
        FOR EACH ROW EXECUTE FUNCTION reject_answer_verification_mutation()
    """)


def downgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text("""
        SELECT count(*) FROM question_answer_verification_events
    """)).scalar_one()
    upgraded = bind.execute(sa.text("""
        SELECT count(*) FROM questions WHERE answer_provenance = 'human_verified'
           OR answer_verification_event_id IS NOT NULL
    """)).scalar_one()
    if rows or upgraded:
        raise RuntimeError("Answer verification history exists; back it up before downgrade")
    op.execute("DROP TRIGGER IF EXISTS question_answer_verification_events_immutable ON question_answer_verification_events")
    op.execute("DROP FUNCTION IF EXISTS reject_answer_verification_mutation()")
    op.drop_constraint("fk_question_current_answer_verification", "questions", type_="foreignkey")
    op.drop_index("ix_answer_verification_question_created", table_name="question_answer_verification_events")
    op.drop_index("ix_question_answer_verification_events_question_id", table_name="question_answer_verification_events")
    op.drop_table("question_answer_verification_events")
    op.drop_column("questions", "answer_verification_event_id")
    op.drop_constraint("question_answer_provenance_valid", "questions", type_="check")
    op.create_check_constraint(
        "question_answer_provenance_valid", "questions",
        "answer_provenance IN ('verified_reference','ai_generated','legacy_transcription','unknown')",
    )
