"""Version graduation policies without rewriting their historical evidence.

Revision ID: f46b2c8d901a
Revises: f45a9b7e2c10
Data conversion is an explicit hash-guarded local maintenance command.
"""
from alembic import op
import sqlalchemy as sa

revision = "f46b2c8d901a"
down_revision = "f45a9b7e2c10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("kp_mastery_policies", sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("kp_mastery_policies", sa.Column("required_question_origins", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.alter_column("kp_mastery_policies", "policy_version", server_default=None)
    op.alter_column("kp_mastery_policies", "required_question_origins", server_default=None)
    op.create_check_constraint("kp_policy_version", "kp_mastery_policies", "policy_version IN (1,2)")
    op.create_check_constraint("kp_policy_origins_object", "kp_mastery_policies", "jsonb_typeof(required_question_origins::jsonb) = 'object'")
    op.create_check_constraint("kp_policy_origin_semantics", "kp_mastery_policies",
        "(policy_version = 1 AND required_question_origins::jsonb = '{}'::jsonb) OR "
        "(policy_version = 2 AND NOT (required_question_types::jsonb ? 'external_exam'))")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM kp_mastery_policies WHERE policy_version <> 1 "
            "OR required_question_origins::jsonb <> '{}'::jsonb")).scalar_one():
        raise RuntimeError("Versioned origin policies exist; use the guarded policy recovery workflow first")
    for name in ("kp_policy_origin_semantics", "kp_policy_origins_object", "kp_policy_version"):
        op.drop_constraint(name, "kp_mastery_policies", type_="check")
    op.drop_column("kp_mastery_policies", "required_question_origins")
    op.drop_column("kp_mastery_policies", "policy_version")
