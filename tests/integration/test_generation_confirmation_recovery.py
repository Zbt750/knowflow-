"""Real isolated PostgreSQL; synthetic content and providers, no paid calls."""
from contextlib import contextmanager
import asyncio
import os
from threading import Event, Timer
from types import SimpleNamespace
from uuid import UUID, uuid4
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, create_engine
from sqlalchemy.exc import ProgrammingError

from backend.api.routes.chat import router
from backend.db import create_session_factory
from backend.errors import AppError, register_error_handlers
from backend.models.chat import ChatMessage, ChatSession
from backend.models.learning import KnowledgePoint, KpState, Question, QuestionVersion, DailyPlan, PracticeItem, QuestionAttempt, PersonalAnswerVerificationEvent
from backend.models.personal_generation import PersonalGenerationBatch
from scripts.run_question_repair_pilot import isolated_factory
from tests.integration.test_personal_general_generation import GeneralModel


@pytest.fixture
def generation_fixture(test_database_url):
    with isolated_factory(test_database_url) as (factory, schema):
        with factory.begin() as db:
            node = KnowledgePoint(code="TEST_FIXTURE.confirmation.geometric", name="等比级数的敛散性与求和",
                subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
            session = ChatSession(title="TEST_FIXTURE confirmation", mode="builtin", purpose="qa")
            db.add_all([node, session]); db.flush()
            db.add(KpState(kp_id=node.id))
            kp, sid = node.id, session.id
        model = GeneralModel()
        yield factory, schema, kp, sid, model


def application(factory, model=None):
    app = FastAPI(); app.include_router(router, prefix="/api"); register_error_handlers(app)
    app.state.session_factory = factory
    app.state.settings = SimpleNamespace(app_env="test", capture_test_evidence=False)
    if model is not None: app.state.personal_generation_provider = model
    return app


def events(response):
    assert response.status_code == 200, response.text
    result = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.splitlines()
        name = next((line[7:] for line in lines if line.startswith("event: ")), None)
        raw = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if name and raw: result.append((name, json.loads(raw)))
    return result


def setup_confirmation(client, sid, kp):
    payload = {"question": "帮我生成一道等比级数的敛散性与求和的题", "request_key": str(uuid4()),
        "study_context": {"surface": "study", "knowledge_node_ids": [str(kp)]}}
    first = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload))
    assert any(name == "personal_generation_confirmation" for name, _ in first)
    mid = next(data["message_id"] for name, data in first if name == "meta")
    payload.update(request_key=str(uuid4()), personal_generation_confirmed_kp_id=str(kp),
        personal_generation_confirmation_message_id=mid)
    return payload, mid


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


@pytest.mark.parametrize("legacy_client", [False, True])
def test_confirmation_reuses_user_and_duplicate_confirmation_is_idempotent(generation_fixture, legacy_client):
    factory, _, kp, sid, model = generation_fixture
    with TestClient(application(factory, model)) as client:
        payload, _ = setup_confirmation(client, sid, kp)
        assert model.calls == 0
        if legacy_client: payload.pop("personal_generation_confirmation_message_id")
        generated = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload))
        assert any(name == "personal_generation" for name, _ in generated), generated
        assert not any(name == "error" for name, _ in generated), generated
        for key in (payload["request_key"], str(uuid4())):
            replay = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json={**payload, "request_key": key}))
            assert any(name == "meta" and data.get("replayed") for name, data in replay)
        assert model.calls == 1
        history = client.get(f"/api/chat/sessions/{sid}/messages").json()
        assert sum(row["role"] == "user" for row in history) == 1
    with factory() as db:
        assert count(db, Question) == count(db, QuestionVersion) == count(db, PersonalGenerationBatch) == 1
        assert count(db, DailyPlan) == count(db, PracticeItem) == 0
        q = db.scalar(select(Question))
        assert q.bank_scope == "personal" and q.auto_review_event_id is None
        assert db.get(KpState, kp).mastered_at is None


def test_cancel_is_persistent_idempotent_and_invalidates_card(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    with TestClient(application(factory, model)) as client:
        payload, mid = setup_confirmation(client, sid, kp)
        endpoint = f"/api/chat/sessions/{sid}/generation-confirmations/{mid}/cancel"
        assert client.post(endpoint).json()["status"] == "cancelled"
        assert client.post(endpoint).status_code == 200
        history = client.get(f"/api/chat/sessions/{sid}/messages").json()
        assert history[-1]["personal_generation_confirmation"] is None
        assert history[-1]["personal_generation_confirmation_status"] == "cancelled"
        rejected = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload))
        assert rejected[-1][1]["code"] == "personal_generation_confirmation_invalid"
    with factory() as db:
        assert count(db, ChatMessage) == 2 and count(db, Question) == 0
        assert count(db, PersonalGenerationBatch) == 0
    assert model.calls == 0


def test_cross_session_or_changed_node_cannot_reuse_confirmation(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    with factory.begin() as db:
        other = ChatSession(title="TEST_FIXTURE other", mode="builtin", purpose="qa")
        db.add(other); db.flush(); other_id = other.id
    with TestClient(application(factory, model)) as client:
        payload, _ = setup_confirmation(client, sid, kp)
        rejected = events(client.post(f"/api/chat/sessions/{other_id}/assistant:stream", json=payload))
        assert rejected[-1][1]["code"] == "personal_generation_confirmation_invalid"
        rejected = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json={
            **payload, "personal_generation_confirmed_kp_id": str(uuid4())}))
        assert rejected[-1][1]["code"] == "personal_generation_confirmation_invalid"
    assert model.calls == 0


def test_provider_setup_error_is_safe_and_can_retry_without_another_user(generation_fixture, monkeypatch):
    factory, _, kp, sid, model = generation_fixture
    app = application(factory)
    secret = "TEST_FIXTURE secret prompt that must never be logged"
    # Capture at the service logger boundary: other integration tests and
    # TestClient lifespan setup can reconfigure root handlers, which makes
    # caplog order-dependent without testing the actual diagnostic payload.
    logged = []
    monkeypatch.setattr("backend.services.learning_assistant_service.logger.error",
        lambda message, *args: logged.append((message, args)))
    def configuration_error(*args, **kwargs): raise RuntimeError(secret)
    monkeypatch.setattr("backend.services.question_generation.configured_provider", configuration_error)
    with TestClient(app) as client:
        payload, _ = setup_confirmation(client, sid, kp)
        failed = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload))
        error = next(data for name, data in failed if name == "error")
        assert error["code"] == "internal_error" and error["message_id"]
        rendered_log = " ".join([logged[0][0], *(str(value) for value in logged[0][1])])
        assert secret not in rendered_log
        assert "generation_provider_setup" in rendered_log and "RuntimeError" in rendered_log
        history = client.get(f"/api/chat/sessions/{sid}/messages").json()
        assert history[-1]["assistant_error_code"] == "internal_error"
        assert history[-1]["personal_generation_confirmed_kp_id"] == str(kp)
        app.state.personal_generation_provider = model
        retry = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json={
            **payload, "retry_of_message_id": error["message_id"]}))
        assert any(name == "personal_generation" for name, _ in retry), retry
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.role == "user")) == 1
        failed_row = db.get(ChatMessage, UUID(error["message_id"]))
        # The retry reuses the visible assistant row. Keep the prior safe
        # diagnostic in its bounded retry history instead of exposing a stale
        # error as the status of the now-successful answer.
        assert failed_row.status == "completed"
        assert failed_row.metadata_["retry_history"][-1]["failure_stage"] == "generation_provider_setup"
        assert failed_row.metadata_["retry_history"][-1]["failure_type"] == "RuntimeError"
    assert model.calls == 1


def test_saved_question_is_reconciled_after_lost_worker_result_without_regeneration(generation_fixture, monkeypatch):
    factory, _, kp, sid, model = generation_fixture
    from backend.services import personal_question_service
    original = personal_question_service.run_generation
    times = 0
    def lost_response(*args, **kwargs):
        nonlocal times
        times += 1
        result = original(*args, **kwargs)
        if times == 1: raise RuntimeError("TEST_FIXTURE response lost after committed generation")
        return result
    monkeypatch.setattr(personal_question_service, "run_generation", lost_response)
    with TestClient(application(factory, model)) as client:
        payload, _ = setup_confirmation(client, sid, kp)
        recovered = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload))
        saved = next(data for name, data in recovered if name == "personal_generation")
        assert saved["reconciled_after_worker_error"] and len(saved["question_ids"]) == 1
        assert not any(name == "error" for name, _ in recovered)
        assert any(name == "done" and data["status"] == "completed" for name, data in recovered)
    with factory() as db:
        assert count(db, Question) == count(db, QuestionVersion) == count(db, PersonalGenerationBatch) == 1
        assert db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.role == "user")) == 1
        assert count(db, PracticeItem) == count(db, DailyPlan) == 0
    assert model.calls == 1


def test_failed_generation_is_not_a_completed_answer_and_replay_never_charges_again(generation_fixture):
    factory, _, kp, sid, _ = generation_fixture
    class FailOnceModel:
        simulation = True
        model = "TEST_FIXTURE_fail_once_then_succeed"
        def __init__(self):
            self.calls = 0
            self.recovery = GeneralModel()
        def complete(self, messages, *, attempt=1):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("TEST_FIXTURE first attempt timed out")
            return self.recovery.complete(messages, attempt=attempt)
    model = FailOnceModel()
    with TestClient(application(factory, model)) as client:
        payload, _ = setup_confirmation(client, sid, kp)
        failed = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload))
        result = next(data for name, data in failed if name == "personal_generation")
        error = next(data for name, data in failed if name == "error")
        assert result["status"] == "failed" and not result["question_ids"]
        assert error["code"] == "personal_generation_failed" and error["retryable"] is True
        assert not any(name == "done" for name, _ in failed)
        history = client.get(f"/api/chat/sessions/{sid}/messages").json()
        assert history[-1]["status"] == "failed" and history[-1]["retryable"] is True
        retried = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json={
            **payload, "retry_of_message_id": error["message_id"]}))
        recovered = next(data for name, data in retried if name == "personal_generation")
        assert recovered["status"] == "completed" and len(recovered["question_ids"]) == 1
        assert not any(name == "error" for name, _ in retried)
        with factory() as db:
            same_turn=db.get(ChatMessage,UUID(error["message_id"]))
            retry_record=same_turn.metadata_["retry_history"][-1]
            assert retry_record["failure_reason_codes"] == ["PROVIDER_TIMEOUT"]
        replay = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json={
            **payload, "retry_of_message_id": error["message_id"]}))
        assert any(name == "meta" and data.get("replayed") for name, data in replay)
    with factory() as db:
        assert count(db, Question) == count(db, QuestionVersion) == 1
        assert db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.role == "user")) == 1
        assert count(db, PersonalGenerationBatch) == 2
    assert model.calls == 2


def test_sse_disconnect_during_provider_call_reconciles_saved_question(generation_fixture, monkeypatch):
    factory, _, kp, sid, _ = generation_fixture
    started = Event()
    release = Event()

    class SlowModel(GeneralModel):
        def complete(self, messages, *, attempt=1):
            self.calls += 1
            self.requests.append(json.loads(messages[-1]["content"]))
            started.set()
            release_timer = Timer(0.5, release.set)
            release_timer.daemon = True
            release_timer.start()
            if not release.wait(timeout=10):
                raise TimeoutError("TEST_FIXTURE provider release timed out")
            return GeneralModel().complete(messages, attempt=attempt)

    model = SlowModel()
    with TestClient(application(factory, model)) as client:
        payload, _ = setup_confirmation(client, sid, kp)
        # Drive the production SSE generator and cancel its consumer while the
        # provider is outstanding, matching Starlette's disconnect task cancel.
        from backend.schemas.learning_assistant import AssistantRequest
        from backend.services.learning_assistant_service import assistant_stream
        body = AssistantRequest.model_validate(payload)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            personal_generation_provider=model)))
        stream = assistant_stream(factory, request=request, session_id=sid, body=body,
            stack=None, provider=None)
        frames = []

        async def consume_until_cancelled():
            async for frame in stream:
                frames.append(frame)

        async def disconnect():
            async def cancel_while_worker_runs(_pending, timeout=None):
                await asyncio.to_thread(started.wait, 5)
                assert started.is_set(), "provider worker did not start before simulated SSE disconnect"
                raise asyncio.CancelledError()

            monkeypatch.setattr("backend.services.learning_assistant_service.asyncio.wait", cancel_while_worker_runs)
            task = asyncio.create_task(consume_until_cancelled())
            try:
                await task
            except asyncio.CancelledError:
                return

        asyncio.run(disconnect())
        assert any("event: meta" in frame.decode("utf-8") for frame in frames)
        endpoint = f"/api/chat/sessions/{sid}/assistant:stream"
        history = client.get(f"/api/chat/sessions/{sid}/messages").json()
        assert sum(row["role"] == "user" for row in history) == 1
        assistant = history[-1]
        assert assistant["status"] == "completed", assistant
        assert assistant["personal_generation"]["question_ids"]
        assert assistant["retryable"] is False
        replay = events(client.post(endpoint, json=payload))
        assert any(name == "meta" and data.get("replayed") for name, data in replay)

    with factory() as db:
        assert count(db, Question) == count(db, QuestionVersion) == count(db, PersonalGenerationBatch) == 1
        assert count(db, PracticeItem) == count(db, DailyPlan) == count(db, QuestionAttempt) == 0
        question = db.scalar(select(Question))
        assert question.bank_scope == "personal" and question.auto_review_event_id is None
        assistant_row = db.get(ChatMessage, UUID(assistant["message_id"]))
        assert assistant_row.status == "completed"
        assert assistant_row.metadata_["transport_disconnected"] is True
    assert model.calls == 1


@contextmanager
def runtime_select_role(factory, schema):
    """Reproduce runtime ACLs using only the disposable cluster admin account."""
    owner = factory.kw["bind"]
    role = "generation_runtime_" + uuid4().hex[:12]
    admin_url = os.environ.get("KAOYAN_TEST_ADMIN_DATABASE_URL")
    if not admin_url:
        raise RuntimeError("isolated_test_admin_url_required_for_acl_test")
    admin_engine = create_engine(admin_url)
    role_engine = None
    role_created = False
    try:
        with admin_engine.begin() as connection:
            assert connection.scalar(text("SELECT current_database()")).endswith("_test")
            assert connection.scalar(text("SELECT inet_server_port()")) != 5433
            from sqlalchemy.engine import make_url
            assert connection.scalar(text("SELECT current_user")) == make_url(admin_url).username
            assert connection.scalar(text("SELECT current_database()")) == owner.url.database
            assert connection.scalar(text("SELECT inet_server_port()")) == owner.url.port
            assert connection.scalar(text("SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"))
            # A NOLOGIN role avoids creating credentials. The test connection
            # authenticates as the normal test app role, then SET ROLE below.
            connection.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN')
            role_created = True
            connection.exec_driver_sql(f'GRANT "{role}" TO "{owner.url.username}"')
            connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
            connection.exec_driver_sql(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"')
            for table in ("chat_sessions", "chat_messages", "questions"):
                connection.exec_driver_sql(f'GRANT INSERT, UPDATE ON "{schema}"."{table}" TO "{role}"')
            connection.exec_driver_sql(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"')
        role_engine = create_engine(owner.url,
            connect_args={"options": f"-csearch_path={schema}"})
        from sqlalchemy import event
        @event.listens_for(role_engine, "connect")
        def _assume_runtime_role(dbapi_connection, _record):
            # `role` is generated from a fixed prefix plus UUID hex digits.
            with dbapi_connection.cursor() as cursor:
                cursor.execute(f'SET ROLE "{role}"')
            # Keep the session-level role change across SQLAlchemy pool
            # rollbacks, which otherwise undo the setup transaction.
            dbapi_connection.commit()
        yield create_session_factory(role_engine), role
    finally:
        if role_engine is not None: role_engine.dispose()
        try:
            if role_created:
                with admin_engine.begin() as connection:
                    # This fresh role owns no objects and only received grants
                    # on the synthetic schema above.
                    connection.exec_driver_sql(f'REVOKE "{role}" FROM "{owner.url.username}"')
                    connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
                    connection.exec_driver_sql(f'DROP ROLE "{role}"')
        finally:
            admin_engine.dispose()


def test_select_only_runtime_role_is_blocked_before_charge_then_minimal_grants_work(generation_fixture):
    owner_factory, schema, kp, sid, model = generation_fixture
    with runtime_select_role(owner_factory, schema) as (factory, role):
        # This is the original failure stage: an actual PostgreSQL INSERT is
        # denied with SQLSTATE 42501 on the SELECT-only runtime role.
        with pytest.raises(ProgrammingError) as original_error:
            with factory.begin() as db:
                db.add(PersonalGenerationBatch(request_key=str(uuid4()), input_sha256="0" * 64,
                    status="running", study_date="2026-10-18", reserved_calls=1,
                    request={"synthetic": True}, result={}))
                db.flush()
        assert original_error.value.orig.sqlstate == "42501"
        from backend.services.personal_question_service import generation_storage_permissions
        with factory() as db:
            assert db.scalar(text("SELECT current_user")) == role
            assert generation_storage_permissions(db) == [
                {"table": "personal_generation_batches", "privilege": "INSERT"},
                {"table": "personal_generation_batches", "privilege": "UPDATE"},
                {"table": "question_versions", "privilege": "INSERT"},
                {"table": "personal_answer_verification_events", "privilege": "INSERT"},
            ]
        with TestClient(application(factory, model)) as client:
            payload, _ = setup_confirmation(client, sid, kp)
            failed = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload))
            errors = [data for name, data in failed if name == "error"]
            assert errors, failed
            error = errors[-1]
            assert error["code"] == "personal_generation_storage_forbidden" and error["retryable"] is True, failed
            assert model.calls == 0
            with owner_factory() as db: assert count(db, PersonalGenerationBatch) == 0
            with owner_factory.kw["bind"].begin() as connection:
                for table, privileges in (("personal_generation_batches", "INSERT, UPDATE"),
                        ("question_versions", "INSERT"),
                        ("personal_answer_verification_events", "INSERT")):
                    connection.exec_driver_sql(f'GRANT {privileges} ON "{schema}"."{table}" TO "{role}"')
            saved = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json={
                **payload, "retry_of_message_id": error["message_id"]}))
            assert any(name == "personal_generation" for name, _ in saved), saved
            assert not any(name == "error" for name, _ in saved), saved
            with factory() as db:
                assert not db.scalar(text("SELECT has_table_privilege(current_user, 'question_versions', 'UPDATE')"))
                assert not db.scalar(text("SELECT has_table_privilege(current_user, 'question_versions', 'DELETE')"))
                assert db.scalar(select(func.count()).select_from(PersonalAnswerVerificationEvent)) == 1
                assert not db.scalar(text("SELECT has_table_privilege(current_user, 'personal_answer_verification_events', 'UPDATE')"))
                assert not db.scalar(text("SELECT has_table_privilege(current_user, 'personal_answer_verification_events', 'DELETE')"))
                assert not db.scalar(text("SELECT has_table_privilege(current_user, 'question_auto_review_events', 'INSERT')"))
        assert model.calls == 1
    with owner_factory() as db:
        assert count(db, Question) == count(db, QuestionVersion) == 1
        assert db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.role == "user")) == 1
        assert count(db, DailyPlan) == count(db, PracticeItem) == 0
