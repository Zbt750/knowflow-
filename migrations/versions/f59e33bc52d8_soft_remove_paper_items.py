"""Keep removed paper items and their permanent learning history."""
from alembic import op
import sqlalchemy as sa

revision = 'f59e33bc52d8'
down_revision = 'f58d22ab41c7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('practice_items', sa.Column('removed_at', sa.DateTime(timezone=True)))
    foreign_keys = sa.inspect(op.get_bind()).get_foreign_keys('question_attempts')
    for fk in foreign_keys:
        if fk['constrained_columns'] == ['practice_item_id']:
            op.drop_constraint(fk['name'], 'question_attempts', type_='foreignkey')
            op.create_foreign_key(fk['name'], 'question_attempts', 'practice_items',
                                  ['practice_item_id'], ['id'], ondelete='RESTRICT')


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text('SELECT count(*) FROM practice_items WHERE removed_at IS NOT NULL')):
        raise RuntimeError('Cannot discard persisted paper removal history')
    op.drop_column('practice_items', 'removed_at')
    # Keep the stronger permanent-history FK even when reverting the UI column.
