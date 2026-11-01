"""Add immutable question content versions and bind existing learning rows.

This migration is intended to run on a restored/isolated database first. It
copies existing Question state to version 1 without changing historical facts.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json
from uuid import UUID, uuid4

from alembic import op
import sqlalchemy as sa


revision = "f53b7e2a901c"
down_revision = "f52a6c8d301e"
branch_labels = None
depends_on = None


VERSION_FIELDS = (
    "kp_id", "question_type", "grading_mode", "grading_config", "stem", "options",
    "correct_answer", "explanation", "question_role", "skill_tags", "estimated_minutes",
    "is_variant", "variant_group", "difficulty", "is_active", "bank_scope", "is_hidden",
    "generation_batch_id", "question_provenance", "content_trust", "source_status",
    "answer_provenance", "answer_reliability", "content_reviewed_by", "content_reviewed_at",
    "answer_reviewed_by", "answer_reviewed_at", "answer_verification_event_id",
    "auto_review_event_id", "source_attestation_key", "source_attestation_sha256",
    "answer_attestation_key", "answer_attestation_sha256",
)


def _json(value):
    if isinstance(value, (UUID, date, datetime)):
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _digest(payload):
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def upgrade():
    bind = op.get_bind()
    op.create_table(
        "question_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("question_id", sa.Uuid(as_uuid=True), sa.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("kp_id", sa.Uuid(as_uuid=True), sa.ForeignKey("knowledge_points.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("question_type", sa.String(30), nullable=False),
        sa.Column("grading_mode", sa.String(30), nullable=False),
        sa.Column("grading_config", sa.JSON()),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON()),
        sa.Column("correct_answer", sa.Text()),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("question_role", sa.String(30), nullable=False),
        sa.Column("skill_tags", sa.JSON(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("is_variant", sa.Boolean(), nullable=False),
        sa.Column("variant_group", sa.String(120)),
        sa.Column("difficulty", sa.String(30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("bank_scope", sa.String(20), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), nullable=False),
        sa.Column("generation_batch_id", sa.Uuid(as_uuid=True)),
        sa.Column("question_provenance", sa.String(40), nullable=False),
        sa.Column("content_trust", sa.String(30), nullable=False),
        sa.Column("source_status", sa.String(30), nullable=False),
        sa.Column("answer_provenance", sa.String(40), nullable=False),
        sa.Column("answer_reliability", sa.String(40), nullable=False),
        sa.Column("content_reviewed_by", sa.String(100)),
        sa.Column("content_reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("answer_reviewed_by", sa.String(100)),
        sa.Column("answer_reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("answer_verification_event_id", sa.Uuid(as_uuid=True)),
        sa.Column("auto_review_event_id", sa.Uuid(as_uuid=True)),
        sa.Column("source_attestation_key", sa.String(64)),
        sa.Column("source_attestation_sha256", sa.String(64)),
        sa.Column("answer_attestation_key", sa.String(64)),
        sa.Column("answer_attestation_sha256", sa.String(64)),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("review_status", sa.String(40), nullable=False, server_default="snapshot_only"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("question_id", "version_number", name="uq_question_version_number"),
        sa.UniqueConstraint("question_id", "id", name="uq_question_version_question_id_id"),
        sa.CheckConstraint("version_number >= 1", name="question_version_number_positive"),
        sa.CheckConstraint("length(content_hash) = 64", name="question_version_hash_length"),
    )
    op.create_index("ix_question_versions_question_id", "question_versions", ["question_id"])

    op.add_column("questions", sa.Column("current_version_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("practice_items", sa.Column("question_version_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("question_attempts", sa.Column("question_version_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("learning_events", sa.Column("question_version_id", sa.Uuid(as_uuid=True), nullable=True))
    for table, name in (("practice_items", "fk_practice_item_question_version"),
                        ("question_attempts", "fk_attempt_question_version"),
                        ("learning_events", "fk_learning_event_question_version")):
        op.create_foreign_key(name, table, "question_versions", ["question_version_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_practice_items_question_version_id", "practice_items", ["question_version_id"])
    op.create_index("ix_question_attempts_question_version_id", "question_attempts", ["question_version_id"])
    op.create_index("ix_learning_events_question_version_id", "learning_events", ["question_version_id"])
    op.add_column("kp_graduation_question_set_versions", sa.Column("question_version_ids", sa.JSON(), nullable=True))
    op.add_column("kp_graduation_question_set_versions", sa.Column("question_version_ids_sha256", sa.String(64), nullable=True))

    questions = sa.Table("questions", sa.MetaData(), autoload_with=bind)
    versions = sa.Table("question_versions", sa.MetaData(), autoload_with=bind)
    id_to_version: dict[UUID, UUID] = {}
    for row in bind.execute(sa.select(questions)).mappings():
        snapshot = {name: _json(row[name]) for name in VERSION_FIELDS}
        version_id = uuid4()
        values = {name: row[name] for name in VERSION_FIELDS}
        values.update(id=version_id, question_id=row["id"], version_number=1,
                      snapshot_json=snapshot, content_hash=_digest(snapshot),
                      review_status="legacy_snapshot_unverified")
        bind.execute(versions.insert().values(**values))
        bind.execute(questions.update().where(questions.c.id == row["id"])
                     .values(current_version_id=version_id))
        id_to_version[row["id"]] = version_id

    if len(id_to_version) != bind.execute(sa.select(sa.func.count()).select_from(questions)).scalar_one():
        raise RuntimeError("question_version_backfill_incomplete")

    pi = sa.Table("practice_items", sa.MetaData(), autoload_with=bind)
    bind.execute(sa.text("""
        UPDATE practice_items pi SET question_version_id = q.current_version_id
          FROM questions q WHERE pi.question_id = q.id AND pi.question_id IS NOT NULL
    """))
    mismatch = bind.execute(sa.text("""
        SELECT count(*) FROM practice_items pi
         WHERE pi.question_id IS NOT NULL AND pi.question_version_id IS NULL
    """)).scalar_one()
    if mismatch:
        raise RuntimeError(f"practice_item_version_backfill_incomplete:{mismatch}")

    bind.execute(sa.text("""
        UPDATE question_attempts a SET question_version_id = pi.question_version_id
          FROM practice_items pi
         WHERE a.practice_item_id = pi.id AND a.question_id IS NOT NULL
    """))
    mismatch = bind.execute(sa.text("""
        SELECT count(*) FROM question_attempts a
          LEFT JOIN practice_items pi ON pi.id = a.practice_item_id
         WHERE a.question_id IS NOT NULL
           AND (a.question_version_id IS NULL OR pi.question_id IS DISTINCT FROM a.question_id
                OR pi.question_version_id IS DISTINCT FROM a.question_version_id)
    """)).scalar_one()
    if mismatch:
        raise RuntimeError(f"attempt_version_backfill_mismatch:{mismatch}")

    op.create_check_constraint("practice_item_question_requires_version", "practice_items",
        "question_id IS NULL OR question_version_id IS NOT NULL")
    op.create_check_constraint("question_attempt_question_requires_version", "question_attempts",
        "question_id IS NULL OR question_version_id IS NOT NULL")

    # Only source types with an unambiguous question-version relation are bound.
    bind.execute(sa.text("""
        UPDATE learning_events le SET question_version_id = a.question_version_id
          FROM question_attempts a
         WHERE le.source_id = a.id
           AND le.event_type IN ('answer_submitted','practice_self_reported','question_self_assessed')
    """))
    bind.execute(sa.text("""
        UPDATE learning_events le SET question_version_id = pi.question_version_id
          FROM practice_items pi
         WHERE le.source_id = pi.id AND le.event_type IN ('qa_assistance_used','ai_process_reviewed')
    """))
    bind.execute(sa.text("""
        UPDATE learning_events le SET question_version_id = q.current_version_id
          FROM questions q
         WHERE le.source_id = q.id AND le.event_type = 'qa_assistance_used'
           AND le.question_version_id IS NULL
    """))

    sets = sa.Table("kp_graduation_question_set_versions", sa.MetaData(), autoload_with=bind)
    for row in bind.execute(sa.select(sets)).mappings():
        question_ids = list(row["question_ids"] or [])
        version_ids = []
        for qid in question_ids:
            qid_uuid = UUID(str(qid))
            version_id = id_to_version.get(qid_uuid)
            if version_id is None:
                raise RuntimeError(f"graduation_set_unknown_question:{qid}")
            version_ids.append(str(version_id))
        sets_id = (sets.c.kp_id == row["kp_id"]) & (sets.c.set_version == row["set_version"])
        bind.execute(sets.update().where(sets_id).values(
            question_version_ids=version_ids, question_version_ids_sha256=_digest(version_ids)))

    op.create_foreign_key("fk_question_current_version_pair", "questions", "question_versions",
        ["id", "current_version_id"], ["question_id", "id"], deferrable=True,
        initially="DEFERRED")
    op.create_foreign_key("fk_practice_item_question_version_pair", "practice_items", "question_versions",
        ["question_id", "question_version_id"], ["question_id", "id"])
    op.create_foreign_key("fk_attempt_question_version_pair", "question_attempts", "question_versions",
        ["question_id", "question_version_id"], ["question_id", "id"])

    op.execute("""
    CREATE FUNCTION prevent_question_version_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'question_versions_are_append_only'; END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER question_versions_immutable BEFORE UPDATE OR DELETE ON question_versions
      FOR EACH ROW EXECUTE FUNCTION prevent_question_version_mutation();
    """)
    op.execute("""
    CREATE FUNCTION guard_question_version_pointer() RETURNS trigger AS $$
    DECLARE current_question questions%ROWTYPE;
            mismatch_keys text;
    BEGIN
      SELECT * INTO current_question FROM questions WHERE id = NEW.id;
      IF current_question.current_version_id IS NULL OR NOT EXISTS (
          SELECT 1 FROM question_versions v
           WHERE v.id = current_question.current_version_id AND v.question_id = current_question.id
      ) THEN RAISE EXCEPTION 'question_current_version_required'; END IF;
      IF NOT EXISTS (
          SELECT 1 FROM question_versions v
           WHERE v.id = current_question.current_version_id AND v.question_id = current_question.id
             AND (v.snapshot_json::jsonb - ARRAY['content_reviewed_at','answer_reviewed_at']) =
                 ((to_jsonb(current_question) - ARRAY['id','current_version_id','created_at','updated_at'])
                   - ARRAY['content_reviewed_at','answer_reviewed_at'])
             AND v.content_reviewed_at IS NOT DISTINCT FROM current_question.content_reviewed_at
             AND v.answer_reviewed_at IS NOT DISTINCT FROM current_question.answer_reviewed_at
      ) THEN
        SELECT string_agg(COALESCE(expected.key, actual.key), ',' ORDER BY COALESCE(expected.key, actual.key))
          INTO mismatch_keys
          FROM jsonb_each((SELECT v.snapshot_json::jsonb FROM question_versions v
                            WHERE v.id = current_question.current_version_id
                              AND v.question_id = current_question.id)) AS expected
          FULL OUTER JOIN jsonb_each(to_jsonb(current_question) - ARRAY['id','current_version_id','created_at','updated_at']) AS actual
            USING (key)
         WHERE expected.value IS DISTINCT FROM actual.value;
        RAISE EXCEPTION 'question_current_version_content_mismatch'
          USING DETAIL = COALESCE(mismatch_keys, 'no matching version snapshot');
      END IF;
      IF TG_OP = 'UPDATE' AND NEW.current_version_id IS NOT DISTINCT FROM OLD.current_version_id
         AND (to_jsonb(NEW) - 'current_version_id' - 'updated_at')
             IS DISTINCT FROM (to_jsonb(OLD) - 'current_version_id' - 'updated_at')
      THEN RAISE EXCEPTION 'question_content_change_requires_new_version'; END IF;
      RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER questions_require_current_version
      AFTER INSERT OR UPDATE ON questions DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION guard_question_version_pointer();
    """)


def downgrade():
    raise RuntimeError("question_versions_are_historical_facts; destructive downgrade is refused")
