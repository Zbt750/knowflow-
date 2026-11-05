"""Add database timestamp defaults to personal generation batches.

Revision ID: f49d10c2a703
Revises: f48c2e7d901a
"""
from alembic import op
import sqlalchemy as sa


revision = "f49d10c2a703"
down_revision = "f48c2e7d901a"
branch_labels = None
depends_on = None


def upgrade():
    # The ORM's TimestampMixin declares these server defaults, but the original
    # personal-question migration omitted them. New batch inserts otherwise
    # fail before the first generation request reaches its Provider.
    op.alter_column(
        "personal_generation_batches", "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
    op.alter_column(
        "personal_generation_batches", "updated_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )


def downgrade():
    op.alter_column(
        "personal_generation_batches", "updated_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
    )
    op.alter_column(
        "personal_generation_batches", "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
    )
