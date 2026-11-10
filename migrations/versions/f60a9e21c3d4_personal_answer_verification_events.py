"""Persist bounded machine answer proofs for personal question versions.

These events are separate from human/reference answer attestations and never
grant public-bank or graduation qualification.
"""
from alembic import op
import sqlalchemy as sa


revision = "f60a9e21c3d4"
down_revision = "f59e33bc52d8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_answer_verification_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("question_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("question_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("question_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("answer_sha256", sa.String(64), nullable=False),
        sa.Column("verifier_version", sa.String(80), nullable=False),
        sa.Column("adapter", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("proof", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('verified','rejected','needs_review')",
                           name="personal_answer_proof_status_valid"),
        sa.CheckConstraint("length(question_snapshot_sha256) = 64",
                           name="personal_answer_proof_snapshot_hash_length"),
        sa.CheckConstraint("length(answer_sha256) = 64",
                           name="personal_answer_proof_answer_hash_length"),
        sa.CheckConstraint("length(idempotency_key) BETWEEN 1 AND 160",
                           name="personal_answer_proof_idempotency_length"),
        sa.ForeignKeyConstraint(
            ["question_id", "question_version_id"],
            ["question_versions.question_id", "question_versions.id"],
            ondelete="RESTRICT", name="fk_personal_answer_proof_question_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_personal_answer_proof_idempotency"),
        sa.UniqueConstraint("question_version_id", "verifier_version", "adapter",
                            name="uq_personal_answer_proof_version_verifier"),
    )
    op.create_index("ix_personal_answer_proof_question_created",
                    "personal_answer_verification_events", ["question_id", "created_at"])
    op.create_index("ix_personal_answer_proof_version",
                    "personal_answer_verification_events", ["question_version_id"])
    op.execute("""
        CREATE FUNCTION reject_personal_answer_proof_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'personal answer verification events are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER personal_answer_verification_events_immutable
        BEFORE UPDATE OR DELETE ON personal_answer_verification_events
        FOR EACH ROW EXECUTE FUNCTION reject_personal_answer_proof_mutation()
    """)


def downgrade():
    bind = op.get_bind()
    count = bind.scalar(sa.text("SELECT count(*) FROM personal_answer_verification_events"))
    if count:
        raise RuntimeError("Personal answer verification history exists; refusing destructive downgrade")
    op.execute("DROP TRIGGER IF EXISTS personal_answer_verification_events_immutable ON personal_answer_verification_events")
    op.execute("DROP FUNCTION IF EXISTS reject_personal_answer_proof_mutation()")
    op.drop_index("ix_personal_answer_proof_version", table_name="personal_answer_verification_events")
    op.drop_index("ix_personal_answer_proof_question_created", table_name="personal_answer_verification_events")
    op.drop_table("personal_answer_verification_events")
