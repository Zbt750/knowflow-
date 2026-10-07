"""Version mastery basis without rewriting existing learning history.

Revision ID: d04f6c21be39
Revises: c93e5b10ad28
"""
from alembic import op
import sqlalchemy as sa

revision = "d04f6c21be39"
down_revision = "c93e5b10ad28"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("kp_states", sa.Column("assessment_basis", sa.String(30), nullable=False,
                                        server_default="legacy_self_reported"))
    op.alter_column("kp_states", "assessment_basis", server_default=None)
    op.add_column("kp_states", sa.Column("pending_review_question_ids", sa.JSON(), nullable=False,
                                        server_default=sa.text("'[]'")))
    op.alter_column("kp_states", "pending_review_question_ids", server_default=None)


def downgrade():
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM kp_states WHERE assessment_basis = 'objective_v1'")).scalar()
    if count:
        raise RuntimeError("Objective mastery exists; restore a pre-upgrade backup rather than relabeling it as self-report")
    op.drop_column("kp_states", "pending_review_question_ids")
    op.drop_column("kp_states", "assessment_basis")
