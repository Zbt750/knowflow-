"""Batch reads preserve the same pinned policies and fail-closed guards."""
from dataclasses import asdict

import pytest
from sqlalchemy import event

from backend.mastery.storage import policy_for_node
from backend.models.learning import DailyPlan, PracticeItem, KpGraduationQuestionSetVersion
from backend.services.study_read_context import load_policy_read_context
from backend.services.graduation_question_set import freeze_graduation_question_set
from tests.integration.test_learning_loop import session_factory, clean_database
from tests.integration.test_policy_origin_semantics import make_origin_slice
from tests.integration.test_phase45hw_graduation import make_questions_distinct


def test_batch_context_matches_existing_policy_and_does_not_query_per_node(session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id, question_ids=[q.id for q in questions],
            reason='TEST_FIXTURE: batch read compatibility')
        db.flush()
        # Persisted rows with no learning activity resolve to the current set.
        expected = policy_for_node(db, node.id)
        context = load_policy_read_context(db, [node.id])
        statements = []
        def count(*args):
            statements.append(args[2])
        event.listen(db.bind, 'before_cursor_execute', count)
        try:
            for _ in range(10):
                assert asdict(policy_for_node(db, node.id, _read_context=context)) == asdict(expected)
            assert statements == []
        finally:
            event.remove(db.bind, 'before_cursor_execute', count)
        with pytest.raises(ValueError, match='read_policy_context_cannot_bind_learner'):
            policy_for_node(db, node.id, bind_if_unset=True, _read_context=context)
        db.rollback()


def test_pinned_version_and_corrupt_set_fail_identically(session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id, question_ids=[q.id for q in questions],
            reason='TEST_FIXTURE: pinned version batch read')
        db.flush()
        policy_for_node(db, node.id, bind_if_unset=True)
        context = load_policy_read_context(db, [node.id])
        assert asdict(policy_for_node(db, node.id, _read_context=context)) == asdict(policy_for_node(db, node.id))
        row = db.get(KpGraduationQuestionSetVersion, (node.id, 1))
        row.question_ids_sha256 = '0' * 64
        for kwargs in ({}, {'_read_context': context}):
            with pytest.raises(ValueError, match='graduation_set_binding_integrity_error'):
                policy_for_node(db, node.id, **kwargs)
        db.rollback()


def test_read_context_is_not_reused_after_a_new_request(session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id, question_ids=[q.id for q in questions],
            reason='TEST_FIXTURE: context lifetime')
        db.flush()
        first = load_policy_read_context(db, [node.id])
        plan = DailyPlan(study_date='2099-01-01', status='active')
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=questions[0].id,
                            kp_id=node.id, ordinal=1)
        db.add(item)
        db.flush()
        second = load_policy_read_context(db, [node.id])
        assert first is not second
        assert first.activity_ids is not second.activity_ids
        assert node.id not in first.activity_ids
        assert node.id not in second.activity_ids
        assert asdict(policy_for_node(db, node.id, _read_context=second)) == asdict(policy_for_node(db, node.id))
        from datetime import datetime, timezone
        item.completed_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        db.flush()
        completed = load_policy_read_context(db, [node.id])
        assert node.id in completed.activity_ids
        # The next read must see newly created history and keep the existing
        # fail-closed missing-binding guard, not reuse yesterday's facts.
        for kwargs in ({}, {'_read_context': completed}):
            with pytest.raises(ValueError, match='graduation_set_binding_missing_for_started_learner'):
                policy_for_node(db, node.id, **kwargs)
        db.rollback()
