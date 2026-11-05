from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.services.answer_submission_service import (
    _question_content_digest,
    _question_content_snapshot,
    question_content_hash,
    question_content_hash_matches,
)


def _question(review_time):
    return SimpleNamespace(
        stem="TEST_FIXTURE: select the unique answer",
        question_type="single_choice",
        options={"A": "one", "B": "two"},
        correct_answer="A",
        grading_config={"verified": True, "method": "single_choice"},
        explanation="Synthetic unit-test explanation",
        skill_tags=["test-skill"],
        is_variant=False,
        kp_id=uuid4(),
        bank_scope="public",
        generation_batch_id=None,
        question_provenance="trusted_practice",
        content_trust="verified",
        source_status="not_applicable",
        answer_provenance="human_verified",
        answer_reliability="verified",
        answer_verification_event_id=uuid4(),
        content_reviewed_by="isolated-test-fixture",
        content_reviewed_at=review_time,
        answer_reviewed_by="isolated-test-fixture",
        answer_reviewed_at=review_time,
    )


def test_question_hash_is_stable_across_timestamptz_offsets_and_accepts_legacy_digest():
    instant = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    question = _question(instant)
    legacy_digest = _question_content_digest(_question_content_snapshot(
        question, normalize_trust_timestamps=False))
    canonical_digest = question_content_hash(question)

    question.content_reviewed_at = instant.astimezone(ZoneInfo("Asia/Shanghai"))
    question.answer_reviewed_at = instant.astimezone(ZoneInfo("Asia/Shanghai"))

    assert question_content_hash(question) == canonical_digest
    assert question_content_hash_matches(canonical_digest, question)
    assert question_content_hash_matches(legacy_digest, question)

    question.stem += " (changed content)"
    assert not question_content_hash_matches(legacy_digest, question)


def test_question_hash_changes_when_answer_or_grading_content_changes():
    question = _question(datetime(2026, 1, 1, tzinfo=timezone.utc))
    saved = question_content_hash(question)
    question.correct_answer = "B"
    assert not question_content_hash_matches(saved, question)
    question.correct_answer = "A"
    question.grading_config = {"verified": True, "method": "unsupported"}
    assert not question_content_hash_matches(saved, question)
