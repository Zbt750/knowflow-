"""All data are isolated TEST_FIXTURE rows; no real review is manufactured."""
from datetime import date, datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
import pytest
from backend.models.learning import KpGraduationQuestionSetVersion,KpState,Question,PracticeItem,DailyPlan
from backend.services.graduation_question_set import (freeze_graduation_question_set,
    publish_all_public_question_set_version,question_set_sha256)
from backend.mastery.storage import policy_for_node
from backend.api.deps import get_time_provider
from backend.services.practice_service import create_initial_plan
from tests.integration.test_learning_loop import clean_database, session_factory
from tests.integration.test_policy_origin_semantics import make_origin_slice,DAY
from tests.integration.test_phase45hw_graduation import make_questions_distinct


@pytest.fixture
def legacy_client(app):
    app.dependency_overrides[get_time_provider] = lambda: (lambda: datetime.now(timezone.utc))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()

def test_publish_appends_complete_set_preserves_version_history_and_replays_noop(session_factory,clean_database):
    with session_factory() as db:
        node,_,questions=make_origin_slice(db)
        make_questions_distinct(db,questions)
        freeze_graduation_question_set(db,kp_id=node.id,question_ids=[questions[0].id],reason='TEST_FIXTURE initial')
        old=db.get(KpGraduationQuestionSetVersion,(node.id,1))
        before=(list(old.question_ids),old.question_ids_sha256,old.reason,old.created_at)
        state=db.get(KpState,node.id)
        state_before={c.name:getattr(state,c.name) for c in state.__table__.columns}
        args=dict(kp_id=node.id,question_ids=[q.id for q in questions],expected_set_version=1,
            expected_set_sha256=old.question_ids_sha256,publication_key='TEST_FIXTURE-hx2',reason='all formal items')
        policy,result=publish_all_public_question_set_version(db,**args)
        assert result['status']=='PUBLISHED' and policy.graduation_set_version==2
        assert policy.graduation_question_ids==[str(q.id) for q in questions]
        assert (list(old.question_ids),old.question_ids_sha256,old.reason,old.created_at)==before
        assert {c.name:getattr(state,c.name) for c in state.__table__.columns}==state_before
        _,replay=publish_all_public_question_set_version(db,**args)
        assert replay['status']=='NOOP'
        assert len(list(db.scalars(select(KpGraduationQuestionSetVersion).where(
            KpGraduationQuestionSetVersion.kp_id==node.id))))==2
        db.rollback()

def test_publication_rejects_partial_pool_personal_question_and_stale_hash(session_factory,clean_database):
    with session_factory() as db:
        node,_,questions=make_origin_slice(db);make_questions_distinct(db,questions)
        freeze_graduation_question_set(db,kp_id=node.id,question_ids=[questions[0].id],reason='TEST_FIXTURE initial')
        before_sha=question_set_sha256([str(questions[0].id)])
        common=dict(kp_id=node.id,expected_set_version=1,expected_set_sha256=before_sha,
            publication_key='TEST_FIXTURE-invalid',reason='test guards')
        with pytest.raises(ValueError,match='include_all_formal'):
            publish_all_public_question_set_version(db,question_ids=[questions[0].id],**common)
        with pytest.raises(ValueError,match='previous_hash'):
            publish_all_public_question_set_version(db,question_ids=[q.id for q in questions],
                **{**common,'expected_set_sha256':'0'*64})
        personal=Question(id=__import__('uuid').uuid4(),kp_id=node.id,bank_scope='personal',
            question_type='single_choice',stem='TEST_FIXTURE personal not a public set item',
            options={'A':'one','B':'two'},correct_answer='A',explanation='TEST_FIXTURE only',is_active=True)
        db.add(personal);db.flush()
        with pytest.raises(ValueError,match='include_all_formal'):
            publish_all_public_question_set_version(db,question_ids=[q.id for q in questions]+[personal.id],**common)
        assert db.get(KpGraduationQuestionSetVersion,(node.id,2)) is None
        db.rollback()


def test_started_learner_stays_on_pinned_set_after_publication(session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id,
            question_ids=[questions[0].id], reason="TEST_FIXTURE initial v1")
        state = db.get(KpState, node.id)
        # The migration backfills existing activity to the version current at
        # deployment time; simulate that established learner before publishing.
        state.graduation_set_version = 1
        state.state = "practicing"
        old = policy_for_node(db, node.id)
        assert old.graduation_set_version == 1
        old_ids = old.graduation_question_ids
        publish_all_public_question_set_version(db, kp_id=node.id,
            question_ids=[q.id for q in questions], expected_set_version=1,
            expected_set_sha256=question_set_sha256(list(old_ids)),
            publication_key="TEST_FIXTURE learner-pinned-v1",
            reason="TEST_FIXTURE publish complete pool as v2")
        effective = policy_for_node(db, node.id)
        assert effective.graduation_set_version == 1
        assert effective.graduation_question_ids == old_ids
        assert db.get(KpState, node.id).graduation_set_version == 1
        db.rollback()


def test_unstarted_learner_binds_latest_set_on_first_plan_action(session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id,
            question_ids=[questions[0].id], reason="TEST_FIXTURE initial v1")
        # The fixture creates an unseen projection; an unstarted learner has no binding.
        state = db.get(KpState, node.id)
        db.delete(state)
        db.flush()
        publish_all_public_question_set_version(db, kp_id=node.id,
            question_ids=[q.id for q in questions], expected_set_version=1,
            expected_set_sha256=question_set_sha256([str(questions[0].id)]),
            publication_key="TEST_FIXTURE unstarted-latest-v2",
            reason="TEST_FIXTURE publish complete pool as v2")
        read_policy = policy_for_node(db, node.id)
        assert read_policy.graduation_set_version == 2
        assert db.get(KpState, node.id) is None
        bound = policy_for_node(db, node.id, bind_if_unset=True)
        assert bound.graduation_set_version == 2
        assert db.get(KpState, node.id).graduation_set_version == 2
        db.rollback()


def test_started_unbound_learner_fails_closed_instead_of_using_latest(session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id,
            question_ids=[questions[0].id], reason="TEST_FIXTURE frozen v1")
        state = db.get(KpState, node.id)
        state.state = "practicing"
        with pytest.raises(ValueError, match="graduation_set_binding_missing_for_started_learner"):
            policy_for_node(db, node.id)
        db.rollback()


def test_legacy_history_requires_explicit_transition_before_current_set_binding(session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id,
            question_ids=[q.id for q in questions], reason="TEST_FIXTURE current formal set")
        old_day = date(2026, 1, 1)
        old_plan = DailyPlan(study_date=old_day.isoformat(), status="completed")
        db.add(old_plan); db.flush()
        old_item = PracticeItem(plan_id=old_plan.id, kp_id=node.id,
            question_id=questions[0].id, ordinal=1)
        db.add(old_item)
        state = db.get(KpState, node.id)
        state.graduation_set_binding_status = "legacy_history_unbound"
        state.graduation_set_version = None
        db.flush()

        read_policy = policy_for_node(db, node.id)
        assert read_policy.graduation_binding_pending is True
        assert read_policy.policy_version == 2
        assert read_policy.graduation_question_ids == ()
        with pytest.raises(ValueError, match="graduation_set_transition_confirmation_required"):
            create_initial_plan(db, study_date=old_day + timedelta(days=1),
                selected_kp_ids=[node.id], now=DAY)
        assert state.graduation_set_version is None
        assert state.graduation_set_binding_status == "legacy_history_unbound"
        assert db.get(PracticeItem, old_item.id) is old_item

        create_initial_plan(db, study_date=old_day + timedelta(days=2),
            selected_kp_ids=[node.id], now=DAY,
            confirm_legacy_set_transition_ids=[node.id])
        assert state.graduation_set_version == 1
        assert state.graduation_set_binding_status == "bound"
        assert state.graduation_set_started_at == DAY
        assert db.get(PracticeItem, old_item.id) is old_item
        db.rollback()


def test_legacy_v3_transition_is_a_named_api_conflict_without_mutation(legacy_client, session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id,
            question_ids=[q.id for q in questions], reason="TEST_FIXTURE current formal set")
        state = db.get(KpState, node.id)
        state.graduation_set_binding_status = "legacy_history_unbound"
        state.graduation_set_version = None
        db.commit()
        node_id = node.id

    response = legacy_client.post("/api/plans/today/generate", json={
        "selected_kp_ids": [str(node_id)], "budget": "light",
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "graduation_set_transition_confirmation_required"
    with session_factory() as db:
        state = db.get(KpState, node_id)
        assert state.graduation_set_binding_status == "legacy_history_unbound"
        assert state.graduation_set_version is None
        assert db.scalar(select(DailyPlan).where(DailyPlan.study_date == "2026-01-01")) is None


def test_legacy_v2_history_is_not_given_a_synthetic_v3_set(session_factory, clean_database):
    with session_factory() as db:
        node, policy, questions = make_origin_slice(db)
        plan = DailyPlan(study_date="2026-01-01", status="completed")
        db.add(plan); db.flush()
        db.add(PracticeItem(plan_id=plan.id, kp_id=node.id, question_id=questions[0].id, ordinal=1))
        state = db.get(KpState, node.id)
        state.graduation_set_binding_status = "legacy_history_unbound"
        state.graduation_set_version = None
        assert policy.policy_version == 2 and policy.graduation_set_version == 0
        resolved = policy_for_node(db, node.id, bind_if_unset=True)
        assert resolved.policy_version == 2
        assert resolved.graduation_set_version == 0
        assert state.graduation_set_binding_status == "legacy_history_unbound"
        assert state.graduation_set_version is None
        assert db.scalar(select(KpGraduationQuestionSetVersion).where(
            KpGraduationQuestionSetVersion.kp_id == node.id
        )) is None
        db.rollback()


def test_pinned_set_hash_is_verified_before_use(session_factory, clean_database):
    with session_factory() as db:
        node, _, questions = make_origin_slice(db)
        make_questions_distinct(db, questions)
        freeze_graduation_question_set(db, kp_id=node.id,
            question_ids=[questions[0].id], reason="TEST_FIXTURE frozen v1")
        state = db.get(KpState, node.id)
        state.graduation_set_version = 1
        version = db.get(KpGraduationQuestionSetVersion, (node.id, 1))
        version.question_ids_sha256 = "0" * 64
        with pytest.raises(ValueError, match="graduation_set_binding_integrity_error"):
            policy_for_node(db, node.id)
        db.rollback()
