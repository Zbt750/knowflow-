"""Allow the existing local personal-question provenance value.

The application already emits and validates ``server_generated`` for the
deterministic personal-practice path. The database constraint previously
rejected that value, turning a supported zero-provider path into a failed
generation after independent verification.
"""
from alembic import op
import sqlalchemy as sa


revision = "f55a7b9012c3"
down_revision = "f54c8a1d7e20"
branch_labels = None
depends_on = None


_ALLOWED_WITHOUT_SERVER_GENERATED = (
    "'verified_reference','human_verified','ai_generated',"
    "'legacy_transcription','unknown','auto_verified'"
)


def upgrade():
    op.drop_constraint("question_answer_provenance_valid", "questions", type_="check")
    op.create_check_constraint(
        "question_answer_provenance_valid",
        "questions",
        "answer_provenance IN "
        "('verified_reference','human_verified','ai_generated','legacy_transcription',"
        "'unknown','auto_verified','server_generated')",
    )


def downgrade():
    bind = op.get_bind()
    count = bind.execute(sa.text(
        "SELECT count(*) FROM questions WHERE answer_provenance = 'server_generated'"
    )).scalar_one()
    if count:
        raise RuntimeError(
            "cannot_remove_server_generated_while_personal_questions_exist"
        )
    op.drop_constraint("question_answer_provenance_valid", "questions", type_="check")
    op.create_check_constraint(
        "question_answer_provenance_valid",
        "questions",
        f"answer_provenance IN ({_ALLOWED_WITHOUT_SERVER_GENERATED})",
    )
