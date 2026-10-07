"""Source attestation and three-role answer consistency.

Revision ID: d31b8c9e2a74
Revises: c5a8f2d10e73
"""
from alembic import op
import sqlalchemy as sa


revision = "d31b8c9e2a74"
down_revision = "c5a8f2d10e73"
branch_labels = depends_on = None


def upgrade():
    op.drop_constraint("question_content_trust_valid", "questions", type_="check")
    op.create_check_constraint(
        "question_content_trust_valid", "questions",
        "content_trust IN ('unreviewed','needs_review','source_attested','verified')",
    )
    op.drop_constraint("answer_consistency_run_bound", "question_answer_consistency_runs", type_="check")
    op.create_check_constraint("answer_consistency_run_bound", "question_answer_consistency_runs",
                               "run_number >= 1 AND run_number <= 6")
    op.add_column("questions", sa.Column("source_attestation_key", sa.String(64), nullable=True))
    op.add_column("questions", sa.Column("source_attestation_sha256", sa.String(64), nullable=True))
    op.add_column("questions", sa.Column("answer_attestation_key", sa.String(64), nullable=True))
    op.add_column("questions", sa.Column("answer_attestation_sha256", sa.String(64), nullable=True))
    op.create_table(
        "question_source_attestations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attestation_key", sa.String(64), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.String(160), nullable=False),
        sa.Column("pack_id", sa.String(100), nullable=False),
        sa.Column("pack_version", sa.String(40), nullable=False),
        sa.Column("candidate_archive_sha256", sa.String(64), nullable=False),
        sa.Column("source_content_sha256", sa.String(64), nullable=False),
        sa.Column("question_content_sha256", sa.String(64), nullable=False),
        sa.Column("source_locator", sa.String(500), nullable=False),
        sa.Column("mapping_type", sa.String(80), nullable=False),
        sa.Column("attestation_method", sa.String(100), nullable=False),
        sa.Column("attestation_source", sa.String(160), nullable=False),
        sa.Column("source_identity", sa.JSON(), nullable=False),
        sa.Column("detected_issues", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("pipeline_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('source_attested','needs_review','conflict')",
                           name="question_source_attestation_status_valid"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attestation_key", name="uq_question_source_attestation_key"),
        sa.UniqueConstraint("question_id", "source_content_sha256", "pack_id", "pack_version",
                            name="uq_question_source_attestation_snapshot"),
    )
    op.create_index("ix_question_source_attestations_attestation_key",
                    "question_source_attestations", ["attestation_key"], unique=False)
    op.create_index("ix_question_source_attestations_question_id",
                    "question_source_attestations", ["question_id"], unique=False)

    op.add_column("question_answer_consistency_runs", sa.Column("run_role", sa.String(20), nullable=True))
    op.add_column("question_answer_consistency_runs", sa.Column("final_answer", sa.Text(), nullable=True))
    op.add_column("question_answer_consistency_runs", sa.Column("verification_result", sa.JSON(), nullable=True))
    op.add_column("question_answer_consistency_runs", sa.Column("verification_note", sa.String(500), nullable=True))
    op.add_column("question_answer_consistency_runs", sa.Column("candidate_answers_sha256", sa.String(64), nullable=True))
    op.add_column("question_answer_consistency_runs", sa.Column("source_answer_sha256", sa.String(64), nullable=True))
    op.execute("""
        UPDATE question_answer_consistency_runs
        SET run_role = CASE
          WHEN run_number = 1 THEN 'solve_a'
          WHEN run_number = 2 THEN 'solve_b'
          WHEN run_number = 3 THEN 'verify_c'
          ELSE 'legacy_solve'
        END
        WHERE run_role IS NULL
    """)
    op.create_check_constraint(
        "answer_consistency_role_valid", "question_answer_consistency_runs",
        "run_role IN ('solve_a','solve_b','verify_c','legacy_solve')",
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM question_source_attestations")).scalar_one():
        raise RuntimeError("Source attestation records exist; preserve them before downgrade")
    if bind.execute(sa.text("SELECT count(*) FROM question_answer_consistency_runs WHERE run_role='verify_c'")).scalar_one():
        raise RuntimeError("Three-role consistency records exist; preserve them before downgrade")
    op.drop_constraint("answer_consistency_role_valid", "question_answer_consistency_runs", type_="check")
    op.drop_constraint("answer_consistency_run_bound", "question_answer_consistency_runs", type_="check")
    op.create_check_constraint("answer_consistency_run_bound", "question_answer_consistency_runs",
                               "run_number >= 1 AND run_number <= 4")
    for name in ("source_answer_sha256", "candidate_answers_sha256", "verification_note",
                 "verification_result", "final_answer", "run_role"):
        op.drop_column("question_answer_consistency_runs", name)
    op.drop_index("ix_question_source_attestations_question_id", table_name="question_source_attestations")
    op.drop_index("ix_question_source_attestations_attestation_key", table_name="question_source_attestations")
    op.drop_table("question_source_attestations")
    op.drop_column("questions", "source_attestation_sha256")
    op.drop_column("questions", "source_attestation_key")
    op.drop_column("questions", "answer_attestation_sha256")
    op.drop_column("questions", "answer_attestation_key")
    op.drop_constraint("question_content_trust_valid", "questions", type_="check")
    op.create_check_constraint("question_content_trust_valid", "questions",
        "content_trust IN ('unreviewed','needs_review','verified')")
