"""Add versioned frozen graduation question sets for adaptive mastery v3.

Revision ID: f50c7e2a1b64
Revises: f49d10c2a703
"""
from alembic import op
import sqlalchemy as sa


revision = "f50c7e2a1b64"
down_revision = "f49d10c2a703"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("kp_mastery_policies", sa.Column(
        "graduation_question_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("kp_mastery_policies", sa.Column(
        "graduation_set_version", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("kp_mastery_policies", "graduation_question_ids", server_default=None)
    op.alter_column("kp_mastery_policies", "graduation_set_version", server_default=None)
    op.drop_constraint("kp_policy_version", "kp_mastery_policies", type_="check")
    op.drop_constraint("kp_policy_origin_semantics", "kp_mastery_policies", type_="check")
    op.create_check_constraint("kp_policy_version", "kp_mastery_policies", "policy_version IN (1,2,3)")
    op.create_check_constraint("kp_policy_origin_semantics", "kp_mastery_policies",
        "(policy_version = 1 AND required_question_origins::jsonb = '{}'::jsonb) OR "
        "(policy_version = 2 AND NOT (required_question_types::jsonb ? 'external_exam')) OR "
        "(policy_version = 3 AND required_question_origins::jsonb = '{}'::jsonb "
        "AND NOT (required_question_types::jsonb ? 'external_exam'))")
    op.create_check_constraint("kp_policy_graduation_set_semantics", "kp_mastery_policies",
        "(policy_version IN (1,2) AND graduation_set_version = 0 "
        "AND graduation_question_ids::jsonb = '[]'::jsonb) OR "
        "(policy_version = 3 AND ((graduation_set_version = 0 AND graduation_question_ids::jsonb = '[]'::jsonb) OR "
        "(graduation_set_version >= 1 AND jsonb_typeof(graduation_question_ids::jsonb) = 'array' "
        "AND jsonb_array_length(graduation_question_ids::jsonb) BETWEEN 1 AND 20)))")
    op.create_table(
        "kp_graduation_question_set_versions",
        sa.Column("kp_id", sa.Uuid(), nullable=False),
        sa.Column("set_version", sa.Integer(), nullable=False),
        sa.Column("question_ids", sa.JSON(), nullable=False),
        sa.Column("question_ids_sha256", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["kp_id"], ["knowledge_points.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("kp_id", "set_version", name=op.f("pk_kp_graduation_question_set_versions")),
        sa.CheckConstraint("set_version >= 1", name="ck_kp_graduation_set_version_positive"),
        sa.CheckConstraint("jsonb_typeof(question_ids::jsonb) = 'array'", name="ck_kp_graduation_set_question_ids_array"),
        sa.CheckConstraint("jsonb_array_length(question_ids::jsonb) BETWEEN 1 AND 20", name="ck_kp_graduation_set_question_ids_bounded"),
        sa.CheckConstraint("length(question_ids_sha256) = 64", name="ck_kp_graduation_set_hash_length"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_kp_graduation_set_reason_nonempty"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM kp_mastery_policies WHERE policy_version = 3 "
                            "OR graduation_set_version > 0 OR graduation_question_ids::jsonb <> '[]'::jsonb")).scalar_one():
        raise RuntimeError("Frozen graduation sets exist; refusing destructive downgrade")
    if bind.execute(sa.text("SELECT count(*) FROM kp_graduation_question_set_versions")).scalar_one():
        raise RuntimeError("Graduation set history exists; refusing destructive downgrade")
    op.drop_table("kp_graduation_question_set_versions")
    op.drop_constraint("kp_policy_graduation_set_semantics", "kp_mastery_policies", type_="check")
    op.drop_constraint("kp_policy_origin_semantics", "kp_mastery_policies", type_="check")
    op.drop_constraint("kp_policy_version", "kp_mastery_policies", type_="check")
    op.create_check_constraint("kp_policy_version", "kp_mastery_policies", "policy_version IN (1,2)")
    op.create_check_constraint("kp_policy_origin_semantics", "kp_mastery_policies",
        "(policy_version = 1 AND required_question_origins::jsonb = '{}'::jsonb) OR "
        "(policy_version = 2 AND NOT (required_question_types::jsonb ? 'external_exam'))")
    op.drop_column("kp_mastery_policies", "graduation_set_version")
    op.drop_column("kp_mastery_policies", "graduation_question_ids")
