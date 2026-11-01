"""Hash-bound answer verification integration tests; only the isolated test DB is written."""
from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from backend.models.learning import (
    DailyPlan,
    KnowledgePoint,
    PracticeItem,
    Question,
    QuestionAnswerVerificationEvent,
)
from backend.services.answer_verification import (
    answer_version_sha256,
    current_answer_verification,
    revoke_answer_verification,
    verify_answer,
)
from backend.services.question_eligibility import question_eligibility
from tests.integration.test_learning_loop import clean_database, client, clock, session_factory


def make_untrusted_ai_choice(db):
    question = db.scalar(select(Question).where(
        Question.is_active.is_(True), Question.question_type == "single_choice"
    ).order_by(Question.id).limit(1))
    assert question is not None
    question.answer_provenance = "ai_generated"
    question.answer_reliability = "ai_generated_consistent"
    question.answer_reviewed_by = None
    question.answer_reviewed_at = None
    question.answer_verification_event_id = None
    question.current_answer_verification = None
    question.grading_config = {"verified": True, "method": "single_choice"}
    db.flush()
    return question


def test_human_verification_is_hash_bound_idempotent_and_enables_only_supported_objective_grading(
        session_factory, clean_database):
    with session_factory() as db:
        question = make_untrusted_ai_choice(db)
        expected_hash = answer_version_sha256(question)
        before_events = db.scalar(select(func.count()).select_from(QuestionAnswerVerificationEvent))
        event = verify_answer(db, question_id=question.id, verification_type="human_verified",
            verifier="synthetic-test-reviewer", method="manual answer comparison",
            note="Synthetic isolated test confirmation only.", idempotency_key="test:human-verify-1",
            expected_answer_sha256=expected_hash, now=datetime(2026, 1, 2, tzinfo=timezone.utc))
        db.flush()
        assert verify_answer(db, question_id=question.id, verification_type="human_verified",
            verifier="synthetic-test-reviewer", method="manual answer comparison",
            note="Synthetic isolated test confirmation only.", idempotency_key="test:human-verify-1",
            expected_answer_sha256=expected_hash).id == event.id
        eligibility = question_eligibility(question, db.get(KnowledgePoint, question.kp_id))
        assert current_answer_verification(question).id == event.id
        assert eligibility.answer_verification_type == "human_verified"
        assert eligibility.evidence_capability == "verified_objective"
        assert eligibility.grading_capability == "deterministic"
        assert db.scalar(select(func.count()).select_from(QuestionAnswerVerificationEvent)) == before_events + 1
        db.rollback()


def test_reference_claim_requires_allowlisted_source_and_ai_generated_practice_cannot_claim_it(
        session_factory, clean_database):
    with session_factory() as db:
        question = make_untrusted_ai_choice(db)
        sha = answer_version_sha256(question)
        with pytest.raises(ValueError, match="authoritative_answer_source_required"):
            verify_answer(db, question_id=question.id, verification_type="verified_reference",
                verifier="reviewer", method="source comparison", note="Missing reference source metadata.",
                idempotency_key="test:missing-reference", expected_answer_sha256=sha)
        question.question_provenance = "ai_generated_practice"
        with pytest.raises(ValueError, match="generated_practice"):
            verify_answer(db, question_id=question.id, verification_type="verified_reference",
                verifier="reviewer", method="source comparison", note="Fake source must be refused.",
                idempotency_key="test:generated-reference", expected_answer_sha256=sha,
                source_metadata={"kind": "official_answer_key", "identifier": "x",
                    "title": "Synthetic", "locator": "test-only"})
        assert question.answer_provenance == "ai_generated"
        assert question.answer_verification_event_id is None
        db.rollback()


def test_changed_answer_invalidates_stamp_and_revoke_preserves_both_events(session_factory, clean_database):
    with session_factory() as db:
        question = make_untrusted_ai_choice(db)
        original_provenance = question.answer_provenance
        first_hash = answer_version_sha256(question)
        verification = verify_answer(db, question_id=question.id, verification_type="human_verified",
            verifier="synthetic-test-reviewer", method="manual review",
            note="Synthetic test review before content change.", idempotency_key="test:verify-then-change",
            expected_answer_sha256=first_hash)
        question.correct_answer = "B" if question.correct_answer != "B" else "A"
        assert current_answer_verification(question) is None
        stale = question_eligibility(question, db.get(KnowledgePoint, question.kp_id))
        assert not stale.answer_verification_current
        assert stale.evidence_capability != "verified_objective"
        revoked = revoke_answer_verification(db, question_id=question.id,
            expected_event_id=verification.id, verifier="synthetic-test-reviewer",
            method="manual correction", note="Synthetic test revocation after answer edit.",
            idempotency_key="test:revoke-after-change", expected_answer_sha256=answer_version_sha256(question))
        db.flush()
        assert revoked.event_type == "revoked"
        assert question.answer_provenance == original_provenance
        assert question.answer_verification_event_id is None
        assert db.scalar(select(func.count()).select_from(QuestionAnswerVerificationEvent)
            .where(QuestionAnswerVerificationEvent.question_id == question.id)) == 3
        db.rollback()


def test_revoke_disables_verified_grader_and_downgrades_trust(session_factory, clean_database):
    with session_factory() as db:
        question = make_untrusted_ai_choice(db)
        verification = verify_answer(db, question_id=question.id, verification_type="human_verified",
            verifier="synthetic-test-reviewer", method="manual review",
            note="Synthetic test review to exercise revocation.", idempotency_key="test:verify-revoke-current",
            expected_answer_sha256=answer_version_sha256(question))
        assert question_eligibility(question, db.get(KnowledgePoint, question.kp_id)).verified_grading_method == "single_choice"
        revoke_answer_verification(db, question_id=question.id, expected_event_id=verification.id,
            verifier="synthetic-test-reviewer", method="review correction",
            note="Synthetic test revocation; source review was withdrawn.",
            idempotency_key="test:revoke-current", expected_answer_sha256=answer_version_sha256(question))
        downgraded = question_eligibility(question, db.get(KnowledgePoint, question.kp_id))
        assert question.answer_verification_event_id is None
        assert question.grading_mode == "self_assessed"
        assert question.grading_config["verified"] is False and question.grading_config["method"] is None
        assert downgraded.verified_grading_method is None
        assert not downgraded.answer_verification_current
        assert downgraded.evidence_capability != "verified_objective"
        db.rollback()


def test_verified_objective_first_independent_answer_enters_existing_evidence_policy(
        session_factory, clean_database, client, clock):
    with session_factory.begin() as db:
        question = make_untrusted_ai_choice(db)
        node_id, question_id, answer = question.kp_id, question.id, question.correct_answer
        verify_answer(db, question_id=question_id, verification_type="human_verified",
            verifier="synthetic-test-reviewer", method="manual answer comparison",
            note="Synthetic integration test only, not production approval.",
            idempotency_key="test:objective-submission", expected_answer_sha256=answer_version_sha256(question))
        plan = DailyPlan(study_date="2026-01-01", status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=question_id, kp_id=node_id, ordinal=1)
        db.add(item)
        db.flush()
        item_id = item.id
    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json={
        "selected_option": answer, "idempotency_key": "verified-answer-first-independent"})
    assert response.status_code == 200
    result = response.json()
    assert result["result"] == "right"
    assert result["assessment_basis"] == "objective_v1"
    assert result["effective_confirmation_count"] == 1
    assert result["sequence_category"] == "first_independent_correct"


def test_verification_event_rows_are_immutable_in_database(session_factory, clean_database):
    with session_factory() as db:
        question = make_untrusted_ai_choice(db)
        event = verify_answer(db, question_id=question.id, verification_type="human_verified",
            verifier="synthetic-test-reviewer", method="manual review",
            note="Immutable event integration fixture.", idempotency_key="test:immutable-event",
            expected_answer_sha256=answer_version_sha256(question))
        db.flush()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text("UPDATE question_answer_verification_events SET note='tampered' WHERE id=:id"),
                {"id": str(event.id)})
        db.rollback()
