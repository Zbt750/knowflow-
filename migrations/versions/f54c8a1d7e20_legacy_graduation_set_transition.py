"""Represent legacy activity without a recoverable frozen graduation set.

The marker is compatibility metadata only. It preserves old plans/evidence and
prevents them from silently adopting the current v3 set until an explicit
learner-confirmed transition.
"""
from alembic import op
import sqlalchemy as sa


revision = "f54c8a1d7e20"
down_revision = "f53b7e2a901c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("kp_states", sa.Column(
        "graduation_set_binding_status", sa.String(length=32), nullable=False,
        server_default="unstarted",
    ))
    op.add_column("kp_states", sa.Column(
        "graduation_set_started_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.create_check_constraint(
        "kp_state_graduation_set_binding_status_valid", "kp_states",
        "graduation_set_binding_status IN ('unstarted','legacy_history_unbound','bound')",
    )
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE kp_states
           SET graduation_set_binding_status = 'bound'
         WHERE graduation_set_version IS NOT NULL
    """))
    bind.execute(sa.text("""
        UPDATE kp_states s
           SET graduation_set_binding_status = 'legacy_history_unbound'
         WHERE s.graduation_set_version IS NULL
           AND (
                s.state <> 'unseen' OR s.mastered_at IS NOT NULL
                OR COALESCE(s.evidence_window::jsonb, '[]'::jsonb) <> '[]'::jsonb
                OR EXISTS (SELECT 1 FROM practice_items pi WHERE pi.kp_id = s.kp_id)
                OR EXISTS (SELECT 1 FROM question_attempts qa WHERE qa.kp_id = s.kp_id)
                OR EXISTS (SELECT 1 FROM learning_events le WHERE le.kp_id = s.kp_id)
           )
    """))


def downgrade():
    bind = op.get_bind()
    legacy = bind.execute(sa.text("""
        SELECT count(*) FROM kp_states
         WHERE graduation_set_binding_status = 'legacy_history_unbound'
            OR graduation_set_started_at IS NOT NULL
    """)).scalar_one()
    if legacy:
        raise RuntimeError("legacy_graduation_set_history_exists; refusing destructive downgrade")
    op.drop_constraint("kp_state_graduation_set_binding_status_valid", "kp_states", type_="check")
    op.drop_column("kp_states", "graduation_set_started_at")
    op.drop_column("kp_states", "graduation_set_binding_status")
