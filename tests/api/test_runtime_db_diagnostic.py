from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from backend.api.routes.runtime_db_diagnostic import (
    ALEMBIC_REVISIONS_SQL,
    ALEMBIC_SCHEMAS_SQL,
    DRAFT_COLUMNS_SQL,
    IDENTITY_SQL,
    TRAINING_TABLES_SQL,
    router,
)

TOKEN = "unit-test-local-token"
SECRET = "postgresql://private-user:private-password@private-host/private-db"


class FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> FakeMappings:
        return FakeMappings(self._rows)


class FakePostgresError(SQLAlchemyError):
    def __init__(self, sqlstate: str) -> None:
        self.orig = SimpleNamespace(sqlstate=sqlstate)
        super().__init__(SECRET)


class FakeSession:
    def __init__(self, factory: "FakeSessionFactory") -> None:
        self.factory = factory
        self.closed = False
        self.commits = 0
        self.statements: list[str] = []

    def execute(self, statement, *_args, **_kwargs) -> FakeResult:
        rendered = str(statement)
        self.statements.append(rendered)
        self.factory.all_statements.append(rendered)
        if rendered in self.factory.failures:
            raise self.factory.failures[rendered]
        return FakeResult(self.factory.rows.get(rendered, []))

    def close(self) -> None:
        self.closed = True

    def commit(self) -> None:
        self.commits += 1


class FakeSessionFactory:
    def __init__(self, rows: dict[str, list[dict[str, Any]]] | None = None,
                 failures: dict[str, Exception] | None = None) -> None:
        self.engine = object()
        self.kw = {"bind": self.engine}
        self.rows = rows or {}
        self.failures = failures or {}
        self.sessions: list[FakeSession] = []
        self.all_statements: list[str] = []

    def __call__(self) -> FakeSession:
        session = FakeSession(self)
        self.sessions.append(session)
        return session


def default_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        str(IDENTITY_SQL): [{
            "database_name": "diagnostic_test",
            "database_user": "diagnostic_role",
            "server_address": "127.0.0.1",
            "server_port": 18761,
            "current_schema": "public",
            "search_path": '"$user", public',
        }],
        str(ALEMBIC_SCHEMAS_SQL): [{"table_schema": "public"}],
        str(ALEMBIC_REVISIONS_SQL): [
            {"version_num": "f57c9a21d340"},
            {"version_num": "f58d22ab41c7"},
        ],
        str(TRAINING_TABLES_SQL): [
            {"table_schema": "public", "table_name": "personal_trainings"},
            {"table_schema": "study", "table_name": "personal_training_items"},
        ],
        str(DRAFT_COLUMNS_SQL): [
            {"table_schema": "study", "table_name": "personal_training_items", "column_name": "draft_answer"},
            {"table_schema": "study", "table_name": "personal_training_items", "column_name": "draft_revision"},
        ],
    }


def make_client(
    factory: FakeSessionFactory,
    *,
    enabled: bool = True,
    app_env: str = "dev",
    client_host: str = "127.0.0.1",
    host_header: str = "127.0.0.1",
) -> TestClient:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        app_env=app_env,
        runtime_db_diagnostics_enabled=enabled,
    )
    app.state.settings_csrf_token = TOKEN
    app.state.engine = factory.engine
    app.state.session_factory = factory
    app.include_router(router, prefix="/api")
    return TestClient(
        app,
        base_url="http://127.0.0.1",
        client=(client_host, 12345),
        raise_server_exceptions=False,
        headers={"Host": host_header},
    )


def test_default_disabled_returns_not_found_without_opening_session() -> None:
    factory = FakeSessionFactory()
    with make_client(factory, enabled=False) as client:
        response = client.get("/api/internal/runtime-db-diagnostic")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert factory.sessions == []


@pytest.mark.parametrize("app_env", ["test", "prod"])
def test_non_dev_environment_is_hidden_and_does_not_query(app_env: str) -> None:
    factory = FakeSessionFactory()
    with make_client(factory, app_env=app_env) as client:
        response = client.get("/api/internal/runtime-db-diagnostic", headers={"X-Settings-Token": TOKEN})

    assert response.status_code == 404
    assert factory.sessions == []


@pytest.mark.parametrize(
    "client_host,host_header,extra_headers",
    [
        ("192.0.2.20", "127.0.0.1", {}),
        ("127.0.0.1", "example.invalid", {}),
        ("127.0.0.1", "127.0.0.1", {"Forwarded": "for=127.0.0.1"}),
        ("127.0.0.1", "127.0.0.1", {"X-Forwarded-Host": "127.0.0.1"}),
        ("127.0.0.1", "127.0.0.1", {"Origin": "https://attacker.invalid"}),
    ],
)
def test_non_local_or_forwarded_requests_are_rejected(
    client_host: str, host_header: str, extra_headers: dict[str, str]
) -> None:
    factory = FakeSessionFactory()
    with make_client(factory, client_host=client_host, host_header=host_header) as client:
        response = client.get(
            "/api/internal/runtime-db-diagnostic",
            headers={"X-Settings-Token": TOKEN, **extra_headers},
        )

    assert response.status_code == 404
    assert factory.sessions == []


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_missing_or_wrong_settings_token_is_rejected(token: str | None) -> None:
    factory = FakeSessionFactory()
    headers = {} if token is None else {"X-Settings-Token": token}
    with make_client(factory) as client:
        response = client.get("/api/internal/runtime-db-diagnostic", headers=headers)

    assert response.status_code == 404
    assert TOKEN not in response.text
    assert factory.sessions == []


def test_valid_request_uses_current_app_factory_and_returns_all_fixed_select_results(monkeypatch) -> None:
    factory = FakeSessionFactory(default_rows())
    import backend.db

    def forbidden_engine(*_args, **_kwargs):
        raise AssertionError("diagnostic route must use the app session factory")

    monkeypatch.setattr(backend.db, "create_db_engine", forbidden_engine)
    with make_client(factory) as client:
        response = client.get(
            "/api/internal/runtime-db-diagnostic",
            headers={"X-Settings-Token": TOKEN},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    body = response.json()
    assert body["database_identity"] == {
        "database_name": "diagnostic_test",
        "database_user": "diagnostic_role",
        "server_address": "127.0.0.1",
        "server_port": 18761,
        "current_schema": "public",
        "search_path": '"$user", public',
    }
    assert body["alembic"]["revisions"] == ["f57c9a21d340", "f58d22ab41c7"]
    assert body["tables"][0] == {
        "name": "personal_trainings", "present": True, "schemas": ["public"]
    }
    assert body["tables"][1] == {
        "name": "personal_training_items", "present": True, "schemas": ["study"]
    }
    assert body["draft_columns"][0] == {
        "name": "draft_answer", "present": True, "schemas": ["study"]
    }
    assert body["draft_columns"][1]["present"] is False
    assert body["diagnostic_status"]["overall"] == "available"
    assert SECRET not in response.text
    assert TOKEN not in response.text
    assert len(factory.sessions) == 5
    assert all(session.closed for session in factory.sessions)
    assert all(session.commits == 0 for session in factory.sessions)
    assert factory.all_statements == [
        str(IDENTITY_SQL),
        str(ALEMBIC_SCHEMAS_SQL),
        str(ALEMBIC_REVISIONS_SQL),
        str(TRAINING_TABLES_SQL),
        str(DRAFT_COLUMNS_SQL),
    ]
    assert all(statement.lstrip().lower().startswith("select ") for statement in factory.all_statements)
    assert "runtime-db-diagnostic" not in client.get("/openapi.json").text


def test_configuration_defaults_runtime_diagnostics_to_disabled_and_supports_opt_in(monkeypatch) -> None:
    from backend.config import Settings

    database_url = "postgresql+psycopg://test-user:test-password@127.0.0.1:18761/diagnostic_test"
    default = Settings(_env_file=None, database_url=database_url)
    assert Settings.model_fields["runtime_db_diagnostics_enabled"].default is False
    assert default.runtime_db_diagnostics_enabled is False
    monkeypatch.setenv("RUNTIME_DB_DIAGNOSTICS_ENABLED", "true")
    enabled = Settings(_env_file=None, database_url=database_url)
    assert enabled.runtime_db_diagnostics_enabled is True


def test_application_registers_hidden_runtime_diagnostic_route(monkeypatch) -> None:
    import backend.app as app_module

    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: SimpleNamespace(allowed_web_origins=[], app_env="dev"),
    )
    app = app_module.create_app()
    # Do not enter TestClient as a context manager: that would start app lifespan
    # and open the configured database. With the default-disabled switch, this
    # request proves router registration while remaining entirely in memory.
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345))
    response = client.get("/api/internal/runtime-db-diagnostic")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "not found"}}
    assert "runtime-db-diagnostic" not in app.openapi()["paths"]


def test_arbitrary_query_parameters_are_rejected_before_database_access() -> None:
    factory = FakeSessionFactory()
    with make_client(factory) as client:
        response = client.get(
            "/api/internal/runtime-db-diagnostic?sql=select%201",
            headers={"X-Settings-Token": TOKEN},
        )

    assert response.status_code == 404
    assert factory.sessions == []


def test_missing_alembic_table_is_reported_without_losing_other_query_results() -> None:
    rows = default_rows()
    failures = {str(ALEMBIC_REVISIONS_SQL): FakePostgresError("42P01")}
    factory = FakeSessionFactory(rows=rows, failures=failures)
    with make_client(factory) as client:
        response = client.get(
            "/api/internal/runtime-db-diagnostic",
            headers={"X-Settings-Token": TOKEN},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["alembic"]["status"] == "missing_or_not_visible"
    assert body["alembic"]["version_table_schemas"] == ["public"]
    assert body["alembic"]["revisions"] == []
    assert body["database_identity"]["database_name"] == "diagnostic_test"
    assert body["tables"][0]["present"] is True
    assert body["diagnostic_status"]["queries"]["training_tables"] == "available"
    assert all(session.closed for session in factory.sessions)


@pytest.mark.parametrize(
    "sqlstate,expected",
    [("42501", "permission_denied"), ("08006", "query_unavailable")],
)
def test_query_failure_categories_are_safe_and_do_not_stop_other_stages(
    sqlstate: str, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    factory = FakeSessionFactory(
        rows=default_rows(),
        failures={str(DRAFT_COLUMNS_SQL): FakePostgresError(sqlstate)},
    )
    with make_client(factory) as client:
        response = client.get(
            "/api/internal/runtime-db-diagnostic",
            headers={"X-Settings-Token": TOKEN},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["diagnostic_status"]["queries"]["draft_columns"] == expected
    assert body["database_identity"]["database_name"] == "diagnostic_test"
    assert body["alembic"]["revisions"] == ["f57c9a21d340", "f58d22ab41c7"]
    assert SECRET not in response.text
    assert TOKEN not in response.text
    assert SECRET not in caplog.text
    assert TOKEN not in caplog.text
    assert all(session.closed for session in factory.sessions)
    assert all(session.commits == 0 for session in factory.sessions)


def test_engine_binding_mismatch_fails_closed_without_query() -> None:
    factory = FakeSessionFactory(default_rows())
    factory.kw["bind"] = object()
    with make_client(factory) as client:
        response = client.get(
            "/api/internal/runtime-db-diagnostic",
            headers={"X-Settings-Token": TOKEN},
        )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text
    assert factory.sessions == []
