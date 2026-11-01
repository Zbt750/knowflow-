"""Persist unsubmitted answers for independent personal training."""
from alembic import op
import sqlalchemy as sa

revision = "f58d22ab41c7"
down_revision = "f57c9a21d340"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("personal_training_items", sa.Column("draft_answer", sa.Text(), nullable=True))
    op.add_column("personal_training_items", sa.Column("draft_selected_option", sa.String(length=20), nullable=True))
    op.add_column("personal_training_items", sa.Column("draft_revision", sa.Integer(), server_default="0", nullable=False))
    op.add_column("personal_training_items", sa.Column("draft_saved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Drafts are disposable input; submitted answers are stored separately.
    op.drop_column("personal_training_items", "draft_saved_at")
    op.drop_column("personal_training_items", "draft_revision")
    op.drop_column("personal_training_items", "draft_selected_option")
    op.drop_column("personal_training_items", "draft_answer")
