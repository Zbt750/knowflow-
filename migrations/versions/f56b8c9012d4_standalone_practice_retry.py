"""Standalone retries preserve original receipts and do not enlarge daily papers."""
from alembic import op
import sqlalchemy as sa
revision = 'f56b8c9012d4'
down_revision = 'f55a7b9012c3'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('practice_items', sa.Column('retry_source_id', sa.Uuid(), nullable=True))
    op.add_column('practice_items', sa.Column('retry_key', sa.String(100), nullable=True))
    op.create_foreign_key('fk_practice_retry_source', 'practice_items', 'practice_items', ['retry_source_id'], ['id'])
    op.create_index('ix_practice_items_retry_source_id', 'practice_items', ['retry_source_id'])
    op.create_unique_constraint('uq_practice_retry_key', 'practice_items', ['retry_key'])
    op.alter_column('practice_items', 'plan_id', nullable=True)
    op.create_check_constraint('practice_item_plan_or_retry', 'practice_items',
        '(plan_id IS NOT NULL AND retry_source_id IS NULL AND retry_key IS NULL) OR '
        '(plan_id IS NULL AND retry_source_id IS NOT NULL AND retry_key IS NOT NULL)')
    op.create_table('practice_retry_requests',
        sa.Column('idempotency_key',sa.String(100),primary_key=True),
        sa.Column('source_id',sa.Uuid(),sa.ForeignKey('practice_items.id',ondelete='CASCADE'),nullable=False),
        sa.Column('retry_id',sa.Uuid(),sa.ForeignKey('practice_items.id',ondelete='CASCADE'),nullable=False))

def downgrade():
    # Refuse destructive downgrade when standalone learning evidence exists.
    if op.get_bind().execute(sa.text('SELECT 1 FROM practice_items WHERE plan_id IS NULL LIMIT 1')).first():
        raise RuntimeError('Preserve standalone retry evidence before downgrade')
    op.drop_table('practice_retry_requests')
    op.drop_constraint('practice_item_plan_or_retry', 'practice_items', type_='check')
    op.alter_column('practice_items', 'plan_id', nullable=False)
    op.drop_constraint('uq_practice_retry_key', 'practice_items', type_='unique')
    op.drop_index('ix_practice_items_retry_source_id', table_name='practice_items')
    op.drop_constraint('fk_practice_retry_source', 'practice_items', type_='foreignkey')
    op.drop_column('practice_items', 'retry_key')
    op.drop_column('practice_items', 'retry_source_id')
