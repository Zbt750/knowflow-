from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.models.learning import (
    DailyPlan, KnowledgePoint, LearningEvent, PracticeItem, Question,
    QuestionAttempt, QuestionVersion,
)
from backend.services.question_versions import (
    question_for_attempt, question_for_practice_item,
)
from backend.services.answer_verification import (
    answer_version_sha256, current_answer_verification, revoke_answer_verification,
    verify_answer,
)


def _question(session):
    node = KnowledgePoint(code=f"version-test-{uuid4().hex[:12]}", name="版本测试节点",
                          subject="数学二", is_assessable=True, is_active=True)
    session.add(node)
    session.flush()
    question = Question(kp_id=node.id, question_type="fill_blank", grading_mode="exact_numeric",
        stem="设函数 f(x)=x²，求 f'(2)。", correct_answer="4", explanation="使用导数定义或幂函数求导。",
        grading_config={"grading": {"method": "exact_numeric_v1"}}, question_provenance="legacy_unknown",
        content_trust="unreviewed", source_status="unknown", answer_provenance="unknown",
        answer_reliability="unknown")
    session.add(question)
    session.flush()
    return node, question


def test_practice_attempt_and_event_keep_the_bound_question_version(test_database_url):
    engine = create_engine(test_database_url)
    try:
        with Session(engine, expire_on_commit=False) as session:
            with session.begin():
                node, question = _question(session)
                v1 = question.current_version_id
                old_snapshot = question_for_practice_item(session, PracticeItem(
                    question_id=question.id, question_version_id=v1))
                plan = DailyPlan(study_date=f"2099-01-{uuid4().int % 27 + 1:02d}", status="active")
                session.add(plan)
                session.flush()
                item = PracticeItem(plan_id=plan.id, question_id=question.id,
                    question_version_id=v1, kp_id=node.id, ordinal=1)
                session.add(item)
                session.flush()
                attempt = QuestionAttempt(practice_item_id=item.id, question_id=question.id,
                    question_version_id=item.question_version_id, kp_id=node.id, raw_answer="4",
                    objective_result="right", self_grade=None, grading_evidence={"version": 1},
                    submitted_at=datetime.now(timezone.utc), idempotency_key=f"version-test-{uuid4()}",
                    result_state="unseen", reason_code="version_test", next_review_at=None)
                session.add(attempt)
                session.flush()
                event = LearningEvent(kp_id=node.id, source_id=attempt.id,
                    event_type="answer_submitted", evidence_level="weak", payload={},
                    occurred_at=datetime.now(timezone.utc), idempotency_key=f"version-event-{uuid4()}")
                session.add(event)
                self_assessment = LearningEvent(kp_id=node.id, source_id=attempt.id,
                    event_type="question_self_assessed", evidence_level="weak", payload={},
                    occurred_at=datetime.now(timezone.utc), idempotency_key=f"self-assessment-{uuid4()}")
                session.add(self_assessment)
                session.flush()
                assert item.question_version_id == v1
                assert attempt.question_version_id == v1
                assert event.question_version_id == v1
                assert self_assessment.question_version_id == v1

                question.stem = "设函数 f(x)=x²+1，求 f'(2)。"
                session.flush()
                assert question.current_version_id != v1
                assert session.scalar(select(QuestionVersion.version_number).where(
                    QuestionVersion.id == question.current_version_id)) == 2
                old_item_snapshot = question_for_practice_item(session, item)
                old_attempt_snapshot = question_for_attempt(session, attempt)
                assert old_item_snapshot.stem == "设函数 f(x)=x²，求 f'(2)。"
                assert old_attempt_snapshot.stem == old_item_snapshot.stem
                assert question_for_practice_item(session, PracticeItem(
                    question_id=question.id, question_version_id=question.current_version_id)).stem == question.stem
    finally:
        engine.dispose()


def test_question_versions_are_append_only_and_raw_content_updates_are_guarded(test_database_url):
    engine = create_engine(test_database_url)
    try:
        with Session(engine) as session:
            with session.begin():
                _, question = _question(session)
                version_id = question.current_version_id
                version = session.get(QuestionVersion, version_id)
                version.explanation = "尝试篡改历史版本"
                try:
                    session.flush()
                except ValueError as exc:
                    assert str(exc) == "question_version_is_immutable"
                    session.rollback()
                else:
                    raise AssertionError("ORM mutation of an existing question version must be rejected")
    finally:
        engine.dispose()


def test_answer_verification_revocation_invalidates_trust_on_old_bound_version(test_database_url):
    engine = create_engine(test_database_url)
    try:
        with Session(engine, expire_on_commit=False) as session:
            with session.begin():
                node, question = _question(session)
                verified = verify_answer(session, question_id=question.id,
                    verification_type="human_verified", verifier="isolated-test-reviewer",
                    method="synthetic isolated verification", note="TEST_FIXTURE only, not a human review.",
                    idempotency_key=f"version-revoke-verify-{uuid4()}",
                    expected_answer_sha256=answer_version_sha256(question),
                    now=datetime(2026, 1, 1, tzinfo=timezone.utc))
                plan = DailyPlan(study_date=f"2099-02-{uuid4().int % 27 + 1:02d}", status="active")
                session.add(plan)
                session.flush()
                item = PracticeItem(plan_id=plan.id, question_id=question.id,
                    question_version_id=question.current_version_id, kp_id=node.id, ordinal=1)
                session.add(item)
                session.flush()
                bound_version_id = item.question_version_id
                before = question_for_practice_item(session, item)
                assert current_answer_verification(before) is not None

                revoke_answer_verification(session, question_id=question.id,
                    expected_event_id=verified.id, verifier="isolated-test-reviewer",
                    method="synthetic isolated withdrawal", note="TEST_FIXTURE revocation only.",
                    idempotency_key=f"version-revoke-{uuid4()}",
                    expected_answer_sha256=answer_version_sha256(question),
                    now=datetime(2026, 1, 2, tzinfo=timezone.utc))

                # The old content is still available to explain the historical
                # item; its explicitly revoked answer stamp is no longer active.
                after = question_for_practice_item(session, item)
                assert item.question_version_id == bound_version_id
                assert after.stem == before.stem
                assert current_answer_verification(after) is None
                assert question.current_version_id != bound_version_id
    finally:
        engine.dispose()


def test_database_trigger_rejects_direct_version_row_update(test_database_url):
    engine = create_engine(test_database_url)
    try:
        with Session(engine) as session:
            with session.begin():
                _, question = _question(session)
                question_id, version_id = question.id, question.current_version_id
                question.stem = "设函数 f(x)=x²+2，求 f'(2)。"
                session.flush()
                current_version_id = question.current_version_id
                assert current_version_id != version_id
        with engine.connect() as connection:
            transaction = connection.begin()
            savepoint = connection.begin_nested()
            try:
                connection.execute(text("UPDATE question_versions SET explanation='tamper' WHERE id=:id"),
                                   {"id": version_id})
            except DBAPIError:
                savepoint.rollback()
            else:
                savepoint.rollback()
                raise AssertionError("Database append-only trigger did not reject a direct update")
            transaction.rollback()

            transaction = connection.begin()
            savepoint = connection.begin_nested()
            connection.execute(text("UPDATE questions SET stem='mismatched body', current_version_id=:old WHERE id=:id"),
                               {"id": question_id, "old": version_id})
            try:
                transaction.commit()  # A pointer to an older snapshot cannot authorize newer live content.
            except DBAPIError:
                transaction.rollback()
            else:
                raise AssertionError("Database trigger accepted Question content that mismatched its current version")

            transaction = connection.begin()
            savepoint = connection.begin_nested()
            connection.execute(text("UPDATE questions SET stem='direct unversioned edit' WHERE id=:id"),
                               {"id": question_id})
            try:
                transaction.commit()  # Deferred pointer guard is checked at commit.
            except DBAPIError:
                transaction.rollback()
            else:
                raise AssertionError("Database pointer trigger did not reject an unversioned content edit")
    finally:
        engine.dispose()
