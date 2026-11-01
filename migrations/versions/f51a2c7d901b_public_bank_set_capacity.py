"""Increase bounded public graduation set capacity; preserve all versions.

Revision ID: f51a2c7d901b
Revises: f50c7e2a1b64
"""
from alembic import op
import sqlalchemy as sa
revision='f51a2c7d901b'
down_revision='f50c7e2a1b64'
branch_labels=None
depends_on=None

def policy_constraint(limit):
    return ("(policy_version IN (1,2) AND graduation_set_version = 0 "
        "AND graduation_question_ids::jsonb = '[]'::jsonb) OR "
        "(policy_version = 3 AND ((graduation_set_version = 0 AND graduation_question_ids::jsonb = '[]'::jsonb) OR "
        "(graduation_set_version >= 1 AND jsonb_typeof(graduation_question_ids::jsonb) = 'array' "
        f"AND jsonb_array_length(graduation_question_ids::jsonb) BETWEEN 1 AND {limit})))")

def replace_constraints(limit):
    op.drop_constraint('kp_policy_graduation_set_semantics','kp_mastery_policies',type_='check')
    op.create_check_constraint('kp_policy_graduation_set_semantics','kp_mastery_policies',policy_constraint(limit))
    op.drop_constraint('ck_kp_graduation_set_question_ids_bounded','kp_graduation_question_set_versions',type_='check')
    op.create_check_constraint('ck_kp_graduation_set_question_ids_bounded','kp_graduation_question_set_versions',
        f'jsonb_array_length(question_ids::jsonb) BETWEEN 1 AND {limit}')

def upgrade():replace_constraints(200)

def downgrade():
    bind=op.get_bind()
    if bind.execute(sa.text('SELECT count(*) FROM kp_graduation_question_set_versions WHERE jsonb_array_length(question_ids::jsonb)>20')).scalar_one():
        raise RuntimeError('Published large sets exist; refusing destructive capacity downgrade')
    replace_constraints(20)
