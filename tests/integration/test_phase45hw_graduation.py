"""Phase H-W: fixed-question graduation and per-question trusted completion.

Every row in this file is synthetic TEST_FIXTURE data in the owned test DB.
"""
from datetime import timedelta

from sqlalchemy import select
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import get_settings
from backend.models.learning import (
    DailyPlan,
    KpGraduationQuestionSetVersion,
    KpMasteryPolicy,
    KpState,
    PracticeItem,
    Question,
)
from backend.services.answer_submission_service import submit_answer
from backend.services.graduation_question_set import (
    freeze_graduation_question_set,
    question_set_sha256,
)
from tests.integration.test_learning_loop import clean_database, session_factory
from tests.integration.test_learning_loop import mark_isolated_question_trusted
from tests.integration.test_policy_origin_semantics import DAY, attempt, make_origin_slice
from backend.services.practice_service import create_initial_plan
from backend.mastery.storage import policy_for_node, policy_from_storage, snapshot_from_storage
from backend.mastery.origin_evidence import compatible_confirmation
from backend.services.policy_evidence_service import current_policy_snapshot
from backend.services.capability_service import read_capability_profile
from backend.services.answer_submission_service import question_content_snapshot


def make_questions_distinct(db, questions):
    stems = (
        "TEST_FIXTURE A: Select the derivative of x squared at x=3.",
        "TEST_FIXTURE B: Select the derivative of sine x at x=0.",
        "TEST_FIXTURE C: Select the determinant of the identity matrix.",
    )
    for question, stem in zip(questions, stems):
        question.stem = stem
        mark_isolated_question_trusted(question, db=db)
    db.flush()


def wrong_attempt(db, node, question, day):
    # Match the production first-plan contract: v3 membership is pinned before
    # the learner begins answering an item from that plan.
    policy_for_node(db, node.id, bind_if_unset=True, now=day)
    plan = DailyPlan(study_date=day.date().isoformat(), status="active")
    db.add(plan)
    db.flush()
    item = PracticeItem(plan_id=plan.id, kp_id=node.id, question_id=question.id, ordinal=1)
    db.add(item)
    db.flush()
    return submit_answer(db, item_id=item.id, raw_answer=None, selected_option="B",
        idempotency_key="phase45hw-wrong-test", now=day)


def test_freeze_validates_set_and_prevents_silent_replacement(session_factory, clean_database):
    with session_factory() as db:
        node, old_policy, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        old_origins = dict(old_policy.required_question_origins)
        ids = [q.id for q in questions]
        policy = freeze_graduation_question_set(db, kp_id=node.id, question_ids=ids,
            reason="TEST_FIXTURE: validate explicit isolated graduation set")
        row = db.get(KpGraduationQuestionSetVersion, (node.id, 1))
        assert policy.policy_version == 3
        assert policy.required_question_origins == {}
        assert policy.graduation_question_ids == [str(value) for value in ids]
        assert row.question_ids_sha256 == question_set_sha256(policy.graduation_question_ids)
        assert old_origins == {"real_exam": 3}
        try:
            freeze_graduation_question_set(db, kp_id=node.id, question_ids=ids[:2],
                reason="TEST_FIXTURE: must not replace set")
        except ValueError as exc:
            assert str(exc) == "graduation_question_set_already_frozen"
        else:
            raise AssertionError("existing frozen set was silently replaced")
        db.rollback()


def test_reference_only_flag_alone_does_not_bypass_question_eligibility(
    session_factory, clean_database
):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        question = questions[0]
        node.is_reference_only = True
        # No current source binding or auto-review: reference-only mapping is
        # not eligible merely because the question is otherwise trusted.
        try:
            freeze_graduation_question_set(db, kp_id=node.id, question_ids=[question.id],
                reason="TEST_FIXTURE: reject unbound reference-only question")
        except ValueError as exc:
            assert str(exc) == "graduation_question_not_trusted_objective"
        else:
            raise AssertionError("unbound reference-only question was accepted")
        db.rollback()


def test_exactly_auto_qualified_reference_topic_can_freeze_v3_set(
    session_factory, clean_database, monkeypatch
):
    """A reference-topic leaf is admitted only after its current exact mapping passes review."""
    from backend.services.auto_question_review import qualify_public_question, question_snapshot_sha256
    from backend.services.question_eligibility import question_eligibility
    from tests.integration.test_auto_question_review import _candidate

    with session_factory() as db:
        question, node = _candidate(db, family="determinant_2x2")
        node.is_reference_only = True
        db.add(question)
        db.flush()
        event, result = qualify_public_question(db, question_id=question.id, node_id=node.id,
            expected_snapshot_sha256=question_snapshot_sha256(question),
            idempotency_key=f"freeze-ref-topic:{question.id}")
        assert event is not None and result["status"] == "AUTO_VERIFIED"
        eligible = question_eligibility(question, node)
        assert eligible.mapping_status == "auto_reviewed_reference_topic"
        assert eligible.evidence_capability == "verified_objective"
        policy = freeze_graduation_question_set(db, kp_id=node.id,
            question_ids=[question.id],
            reason="TEST_FIXTURE: exact-bound auto-qualified public question")
        assert policy.policy_version == 3
        assert policy.graduation_question_ids == [str(question.id)]
        # A source-index import flag must not erase a concrete frozen set when
        # the user confirms the daily plan. Exercise the real selector with v3.
        from backend.services import practice_service
        real_selector = practice_service.select_questions
        seen_versions = []

        def record_policy(selected_policy, *args, **kwargs):
            seen_versions.append(selected_policy.policy_version)
            return real_selector(selected_policy, *args, **kwargs)

        monkeypatch.setattr(practice_service, "select_questions", record_policy)
        if db.get(KpState, node.id) is None:
            db.add(KpState(kp_id=node.id))
            db.flush()
        plan = create_initial_plan(db, study_date=DAY.date(), selected_kp_ids=[node.id], now=DAY)
        db.flush()
        picked = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan.id)))
        assert seen_versions == [3]
        assert [item.question_id for item in picked] == [question.id]
        db.rollback()


def test_assisted_correct_is_not_complete_but_later_independent_question_attempt_graduates(
    session_factory, clean_database
):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id,
            question_ids=[q.id for q in questions],
            reason="TEST_FIXTURE: verify assisted versus independent completion")
        failed = wrong_attempt(db, node, questions[0], DAY)
        state = db.get(KpState, node.id)
        assert failed.result == "wrong"
        assert str(questions[0].id) in state.pending_review_question_ids
        assert state.evidence_window == []
        assisted = attempt(db, node, questions[0], DAY + timedelta(days=1), assisted=True)
        state = db.get(KpState, node.id)
        assert assisted.result == "right"
        assert str(questions[0].id) not in {entry.get("question_id") for entry in state.evidence_window}
        independent = attempt(db, node, questions[0], DAY + timedelta(days=2))
        assert independent.result == "right"
        assert independent.sequence_category == "repeat_correct"
        assert independent.effective_confirmation_count == 1
        state = db.get(KpState, node.id)
        assert str(questions[0].id) in {entry.get("question_id") for entry in state.evidence_window}
        result = None
        for index in (1, 2):
            result = attempt(db, node, questions[index], DAY + timedelta(days=index + 2))
        assert result and result.state == "mastered"
        state = db.get(KpState, node.id)
        assert len(state.evidence_window) == 3
        assert state.mastered_at is not None
        policy = policy_from_storage(db.get(KpMasteryPolicy, node.id))
        saved_snapshot = snapshot_from_storage(state)
        assert all(compatible_confirmation(item, policy) for item in saved_snapshot.evidence_window)
        projected = current_policy_snapshot(db, state, policy)
        assert len(projected.evidence_window) == 3
        service_profile = read_capability_profile(db, node)
        assert service_profile.graduation_progress.completed_question_count == 3
        visible_questions = [q for q in questions if q.is_active and not q.is_hidden]
        route_profile = read_capability_profile(db, node, questions=visible_questions)
        assert route_profile.graduation_progress.completed_question_count == 3
        question_snapshots_before_commit = {
            q.id: question_content_snapshot(q) for q in questions
        }
        db.commit()
        kp_id = node.id

    with session_factory() as db:
        persisted_node = db.get(type(node), kp_id)
        for question_id, before_content in question_snapshots_before_commit.items():
            current_question = db.get(Question, question_id)
            assert question_content_snapshot(current_question) == before_content
        persisted_state = db.get(KpState, kp_id)
        persisted_policy = policy_from_storage(db.get(KpMasteryPolicy, kp_id))
        live_projection = current_policy_snapshot(db, persisted_state, persisted_policy)
        assert len(live_projection.evidence_window) == 3
        persisted_profile = read_capability_profile(db, persisted_node)
        assert persisted_profile.graduation_progress.completed_question_count == 3

    app = create_app()
    app.state.session_factory = session_factory
    app.state.settings = get_settings()
    client = TestClient(app, base_url="http://127.0.0.1:8004")
    response = client.get(f"/api/knowledge/{kp_id}")
    assert response.status_code == 200, response.text
    progress = response.json()["capability_profile"]["graduation_progress"]
    assert progress["configured"] is True
    assert progress["completed_question_count"] == progress["required_question_count"] == 3, progress
    assert progress["graduated"] is True
    assert all(item["status"] == "COMPLETED" for item in progress["questions"])


def test_frozen_set_drives_plan_without_legacy_type_or_day_quotas(session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id,
            question_ids=[q.id for q in questions],
            reason="TEST_FIXTURE: frozen set ignores stale legacy graduation gates")
        policy_row = db.get(KpMasteryPolicy, node.id)
        # These old fields intentionally describe impossible extra quotas and
        # exclusions. They must not block or alter the explicit v3 set.
        policy_row.required_question_types = {"program": 50}
        policy_row.required_variant_count = 12
        policy_row.required_skill_tags = ["never-a-graduation-gate"]
        policy_row.min_day_span = 99
        policy_row.excluded_question_types = ["single_choice"]
        plan = create_initial_plan(db, study_date=DAY.date(), selected_kp_ids=[node.id], now=DAY)
        db.flush()
        items = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan.id)))
        assert {item.question_id for item in items} == {q.id for q in questions}
        assert len(items) == 3
        assert db.scalar(select(DailyPlan.id).where(DailyPlan.id == plan.id)) == plan.id
        db.rollback()
