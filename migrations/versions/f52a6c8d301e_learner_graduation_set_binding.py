"""Pin each started learner/node to its existing frozen graduation set."""
from alembic import op
import sqlalchemy as sa

revision = "f52a6c8d301e"
down_revision = "f51a2c7d901b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("kp_states", sa.Column("graduation_set_version", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "kp_state_graduation_set_version_positive",
        "kp_states",
        "graduation_set_version IS NULL OR graduation_set_version >= 1",
    )
    unresolved = op.get_bind().execute(sa.text("""
        WITH started AS (
            SELECT kp_id FROM kp_states
             WHERE state <> 'unseen' OR mastered_at IS NOT NULL
                OR COALESCE(evidence_window::jsonb, '[]'::jsonb) <> '[]'::jsonb
            UNION SELECT kp_id FROM question_attempts WHERE kp_id IS NOT NULL
            UNION SELECT kp_id FROM learning_events WHERE kp_id IS NOT NULL
            UNION SELECT kp_id FROM practice_items WHERE kp_id IS NOT NULL
        )
        SELECT count(*)
          FROM started s
          LEFT JOIN kp_states st ON st.kp_id = s.kp_id
          LEFT JOIN kp_mastery_policies p ON p.kp_id = s.kp_id
         WHERE p.policy_version = 3
           AND (st.kp_id IS NULL
            OR p.graduation_set_version < 1
            OR NOT EXISTS (
                SELECT 1 FROM kp_graduation_question_set_versions v
                 WHERE v.kp_id = p.kp_id AND v.set_version = p.graduation_set_version
            ))
    """)).scalar_one()
    if unresolved:
        raise RuntimeError(
            f"Refusing graduation-set binding migration: {unresolved} started nodes lack a valid frozen set"
        )
    op.execute(sa.text("""
        UPDATE kp_states AS s
        SET graduation_set_version = p.graduation_set_version
        FROM kp_mastery_policies AS p
        WHERE p.kp_id = s.kp_id
          AND p.policy_version = 3
          AND p.graduation_set_version >= 1
          AND (
              s.state <> 'unseen'
              OR s.mastered_at IS NOT NULL
              OR COALESCE(s.evidence_window::jsonb, '[]'::jsonb) <> '[]'::jsonb
              OR EXISTS (SELECT 1 FROM question_attempts qa WHERE qa.kp_id = s.kp_id)
              OR EXISTS (SELECT 1 FROM learning_events le WHERE le.kp_id = s.kp_id)
              OR EXISTS (SELECT 1 FROM practice_items pi WHERE pi.kp_id = s.kp_id)
          )
    """))


def downgrade():
    bind = op.get_bind()
    pinned = bind.execute(sa.text(
        "SELECT count(*) FROM kp_states WHERE graduation_set_version IS NOT NULL"
    )).scalar_one()
    if pinned:
        raise RuntimeError("Learner set bindings exist; refusing destructive downgrade")
    op.drop_constraint("kp_state_graduation_set_version_positive", "kp_states", type_="check")
    op.drop_column("kp_states", "graduation_set_version")
