"""Append-only automatic question quality qualification.

Revision ID: f48c2e7d901a
Revises: f47c10a2b903
"""
from alembic import op
import sqlalchemy as sa


revision = "f48c2e7d901a"
down_revision = "f47c10a2b903"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("question_content_trust_valid", "questions", type_="check")
    op.create_check_constraint(
        "question_content_trust_valid", "questions",
        "content_trust IN ('unreviewed','needs_review','source_attested','verified','auto_verified')",
    )
    op.drop_constraint("question_answer_provenance_valid", "questions", type_="check")
    op.create_check_constraint(
        "question_answer_provenance_valid", "questions",
        "answer_provenance IN ('verified_reference','human_verified','ai_generated','legacy_transcription','unknown','auto_verified')",
    )
    op.create_table(
        "question_auto_review_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("qualification_class", sa.String(30), nullable=False),
        sa.Column("review_version", sa.String(80), nullable=False),
        sa.Column("question_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("answer_sha256", sa.String(64), nullable=False),
        sa.Column("audit_sha256", sa.String(64), nullable=False),
        sa.Column("audit_snapshot", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("related_event_id", sa.Uuid(), nullable=True),
        sa.Column("previous_state", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("event_type IN ('qualified','revoked')", name="question_auto_review_event_type_valid"),
        sa.CheckConstraint("qualification_class IN ('exam_curated','exam_variant','development_original')",
                           name="question_auto_review_class_valid"),
        sa.CheckConstraint("length(question_snapshot_sha256) = 64", name="question_auto_review_snapshot_hash_length"),
        sa.CheckConstraint("length(answer_sha256) = 64", name="question_auto_review_answer_hash_length"),
        sa.CheckConstraint("length(audit_sha256) = 64", name="question_auto_review_audit_hash_length"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["related_event_id"], ["question_auto_review_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_question_auto_review_idempotency"),
    )
    op.create_index("ix_question_auto_review_events_question_id", "question_auto_review_events", ["question_id"])
    op.create_index("ix_question_auto_review_question_created", "question_auto_review_events", ["question_id", "created_at"])
    op.add_column("questions", sa.Column("auto_review_event_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_question_current_auto_review", "questions", "question_auto_review_events",
                           ["auto_review_event_id"], ["id"], ondelete="RESTRICT")
    op.execute("""
        CREATE FUNCTION reject_question_auto_review_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'question auto review events are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER question_auto_review_events_immutable
        BEFORE UPDATE OR DELETE ON question_auto_review_events
        FOR EACH ROW EXECUTE FUNCTION reject_question_auto_review_mutation()
    """)


def downgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT count(*) FROM question_auto_review_events")).scalar_one()
    upgraded = bind.execute(sa.text("SELECT count(*) FROM questions WHERE auto_review_event_id IS NOT NULL OR content_trust='auto_verified' OR answer_provenance='auto_verified'")).scalar_one()
    if rows or upgraded:
        raise RuntimeError("Automatic question review history exists; preserve it before downgrade")
    op.execute("DROP TRIGGER IF EXISTS question_auto_review_events_immutable ON question_auto_review_events")
    op.execute("DROP FUNCTION IF EXISTS reject_question_auto_review_mutation()")
    op.drop_constraint("fk_question_current_auto_review", "questions", type_="foreignkey")
    op.drop_column("questions", "auto_review_event_id")
    op.drop_index("ix_question_auto_review_question_created", table_name="question_auto_review_events")
    op.drop_index("ix_question_auto_review_events_question_id", table_name="question_auto_review_events")
    op.drop_table("question_auto_review_events")
    op.drop_constraint("question_answer_provenance_valid", "questions", type_="check")
    op.create_check_constraint(
        "question_answer_provenance_valid", "questions",
        "answer_provenance IN ('verified_reference','human_verified','ai_generated','legacy_transcription','unknown')",
    )
    op.drop_constraint("question_content_trust_valid", "questions", type_="check")
    op.create_check_constraint("question_content_trust_valid", "questions",
        "content_trust IN ('unreviewed','needs_review','source_attested','verified')")
