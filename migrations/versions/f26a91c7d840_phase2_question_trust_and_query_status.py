"""Separate question/answer trust and support read-only task completion.

Revision ID: f26a91c7d840
Revises: e15a7d32cf40
"""
from alembic import op
import sqlalchemy as sa

revision = "f26a91c7d840"
down_revision = "e15a7d32cf40"
branch_labels = depends_on = None


def upgrade():
    # Defaults are intentionally conservative. No legacy row is inferred as
    # reviewed from its old JSON import metadata.
    columns = (
        ("question_provenance", sa.String(40), "legacy_unknown"),
        ("content_trust", sa.String(30), "unreviewed"),
        ("source_status", sa.String(30), "unknown"),
        ("answer_provenance", sa.String(40), "unknown"),
        ("answer_reliability", sa.String(40), "unknown"),
    )
    for name, kind, default in columns:
        op.add_column("questions", sa.Column(name, kind, nullable=False, server_default=default))
        op.alter_column("questions", name, server_default=None)
    op.add_column("questions", sa.Column("content_reviewed_by", sa.String(100)))
    op.add_column("questions", sa.Column("content_reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("questions", sa.Column("answer_reviewed_by", sa.String(100)))
    op.add_column("questions", sa.Column("answer_reviewed_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("question_provenance_valid", "questions",
        "question_provenance IN ('real_exam','trusted_practice','ai_generated_practice','legacy_unknown')")
    op.create_check_constraint("question_content_trust_valid", "questions",
        "content_trust IN ('unreviewed','needs_review','verified')")
    op.create_check_constraint("question_source_status_valid", "questions",
        "source_status IN ('verified','traceable','needs_review','unknown','not_applicable')")
    op.create_check_constraint("question_answer_provenance_valid", "questions",
        "answer_provenance IN ('verified_reference','ai_generated','legacy_transcription','unknown')")
    op.create_check_constraint("question_answer_reliability_valid", "questions",
        "answer_reliability IN ('verified','ai_generated_consistent','model_generated','unverified','unknown')")

    op.drop_constraint("learning_task_status_valid", "learning_tasks", type_="check")
    op.create_check_constraint("learning_task_status_valid", "learning_tasks",
        "status IN ('created','running','ready','needs_info','answered','failed','cancelled')")


def downgrade():
    bind = op.get_bind()
    # Never discard metadata that may have been explicitly reviewed after this
    # migration. Default-only legacy rows can safely return to the old schema.
    reviewed = bind.execute(sa.text("""
        SELECT count(*) FROM questions WHERE
          question_provenance <> 'legacy_unknown' OR content_trust <> 'unreviewed' OR
          source_status <> 'unknown' OR answer_provenance <> 'unknown' OR
          answer_reliability <> 'unknown' OR content_reviewed_by IS NOT NULL OR
          content_reviewed_at IS NOT NULL OR answer_reviewed_by IS NOT NULL OR
          answer_reviewed_at IS NOT NULL
    """)).scalar_one()
    if reviewed:
        raise RuntimeError("Question trust metadata exists; back it up before downgrade")
    answered = bind.execute(sa.text("SELECT count(*) FROM learning_tasks WHERE status='answered'")).scalar_one()
    if answered:
        op.execute("UPDATE learning_tasks SET status='needs_info' WHERE status='answered'")
    op.drop_constraint("learning_task_status_valid", "learning_tasks", type_="check")
    op.create_check_constraint("learning_task_status_valid", "learning_tasks",
        "status IN ('created','running','ready','needs_info','failed','cancelled')")
    for name in ("question_answer_reliability_valid", "question_answer_provenance_valid",
                 "question_source_status_valid", "question_content_trust_valid", "question_provenance_valid"):
        op.drop_constraint(name, "questions", type_="check")
    for name in ("answer_reviewed_at", "answer_reviewed_by", "content_reviewed_at", "content_reviewed_by",
                 "answer_reliability", "answer_provenance", "source_status", "content_trust", "question_provenance"):
        op.drop_column("questions", name)
