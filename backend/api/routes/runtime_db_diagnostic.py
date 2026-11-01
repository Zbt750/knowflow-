from __future__ import annotations

import logging
import secrets
from typing import Literal

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.errors import AppError
from backend.services.model_settings_service import authorize_local

logger = logging.getLogger(__name__)

QueryStatus = Literal[
    "available",
    "missing_or_not_visible",
    "permission_denied",
    "query_unavailable",
]

NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "not_found", "message": "not found"}},
        headers=NO_STORE_HEADERS,
    )

# These statements are intentionally fixed. The endpoint accepts no SQL,
# schema, table, or connection parameters from the caller.
IDENTITY_SQL = text(
    """SELECT current_database() AS database_name,
              current_user AS database_user,
              inet_server_addr() AS server_address,
              inet_server_port() AS server_port,
              current_schema() AS current_schema,
              current_setting('search_path') AS search_path"""
)
ALEMBIC_SCHEMAS_SQL = text(
    """SELECT table_schema
       FROM information_schema.tables
       WHERE table_name = 'alembic_version' AND table_type = 'BASE TABLE'
       ORDER BY table_schema"""
)
ALEMBIC_REVISIONS_SQL = text("SELECT version_num FROM alembic_version")
TRAINING_TABLES_SQL = text(
    """SELECT table_schema, table_name
       FROM information_schema.tables
       WHERE table_name IN (
           'personal_trainings', 'personal_training_items',
           'personal_training_attempts', 'personal_training_actions'
       ) AND table_type = 'BASE TABLE'
       ORDER BY table_schema, table_name"""
)
DRAFT_COLUMNS_SQL = text(
    """SELECT table_schema, table_name, column_name
       FROM information_schema.columns
       WHERE table_name = 'personal_training_items'
         AND column_name IN (
             'draft_answer', 'draft_selected_option', 'draft_revision', 'draft_saved_at'
         )
       ORDER BY table_schema, column_name"""
)

TRAINING_TABLE_NAMES = (
    "personal_trainings",
    "personal_training_items",
    "personal_training_attempts",
    "personal_training_actions",
)
DRAFT_COLUMN_NAMES = (
    "draft_answer",
    "draft_selected_option",
    "draft_revision",
    "draft_saved_at",
)

router = APIRouter(tags=["internal-diagnostics"])


class DatabaseIdentity(BaseModel):
    database_name: str
    database_user: str
    server_address: str | None
    server_port: int | None
    current_schema: str | None
    search_path: str


class ObjectPresence(BaseModel):
    name: str
    present: bool
    schemas: list[str]


class AlembicDiagnostic(BaseModel):
    status: QueryStatus
    version_table_schemas: list[str]
    revisions: list[str]


class DiagnosticQueryStatuses(BaseModel):
    identity: QueryStatus
    alembic_version_schemas: QueryStatus
    alembic_revisions: QueryStatus
    training_tables: QueryStatus
    draft_columns: QueryStatus


class DiagnosticStatus(BaseModel):
    overall: QueryStatus
    queries: DiagnosticQueryStatuses


class RuntimeDatabaseDiagnostic(BaseModel):
    database_identity: DatabaseIdentity | None
    alembic: AlembicDiagnostic
    tables: list[ObjectPresence]
    draft_columns: list[ObjectPresence]
    diagnostic_status: DiagnosticStatus


def _sqlstate(error: BaseException) -> str | None:
    original = getattr(error, "orig", error)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _failure_status(error: BaseException) -> QueryStatus:
    state = _sqlstate(error)
    if state == "42P01":
        return "missing_or_not_visible"
    if state == "42501":
        return "permission_denied"
    return "query_unavailable"


def _run_fixed_query(session_factory, stage: str, statement) -> tuple[list[dict], QueryStatus]:
    """Run one fixed SELECT in its own Session so failures cannot poison peers."""
    session = None
    rows: list[dict] = []
    status: QueryStatus = "available"
    try:
        session = session_factory()
        rows = [dict(row) for row in session.execute(statement).mappings().all()]
    except Exception as error:  # SQLAlchemy/driver errors must not leak to callers.
        status = _failure_status(error)
        logger.warning(
            "runtime DB diagnostic stage=%s exception_type=%s status=%s",
            stage,
            type(error).__name__,
            status,
        )
    finally:
        if session is not None:
            try:
                # Session.close() rolls back any open read transaction; no commit is used.
                session.close()
            except Exception as error:  # Do not emit exception text or parameters.
                logger.warning(
                    "runtime DB diagnostic stage=%s exception_type=%s status=query_unavailable",
                    f"{stage}_session_close",
                    type(error).__name__,
                )
                if status == "available":
                    status = "query_unavailable"
    return rows, status


def _overall_status(statuses: DiagnosticQueryStatuses) -> QueryStatus:
    values = (
        statuses.identity,
        statuses.alembic_version_schemas,
        statuses.alembic_revisions,
        statuses.training_tables,
        statuses.draft_columns,
    )
    for candidate in ("query_unavailable", "permission_denied", "missing_or_not_visible"):
        if candidate in values:
            return candidate  # type: ignore[return-value]
    return "available"


@router.get(
    "/internal/runtime-db-diagnostic",
    include_in_schema=False,
    response_model=RuntimeDatabaseDiagnostic,
)
def runtime_db_diagnostic(
    request: Request,
    response: Response,
    x_settings_token: str | None = Header(default=None, alias="X-Settings-Token"),
) -> RuntimeDatabaseDiagnostic | JSONResponse:
    response.headers.update(NO_STORE_HEADERS)
    settings = getattr(request.app.state, "settings", None)
    if (
        not bool(getattr(settings, "runtime_db_diagnostics_enabled", False))
        or getattr(settings, "app_env", None) != "dev"
    ):
        return _not_found()

    try:
        local_token = authorize_local(request)
    except AppError:
        return _not_found()

    supplied_token = x_settings_token or ""
    if (
        len(supplied_token) > 256
        or not secrets.compare_digest(supplied_token.encode("utf-8"), local_token.encode("utf-8"))
        or request.query_params
    ):
        return _not_found()

    session_factory = getattr(request.app.state, "session_factory", None)
    engine = getattr(request.app.state, "engine", None)
    bound_engine = getattr(session_factory, "kw", {}).get("bind") if session_factory is not None else None
    if session_factory is None or engine is None or bound_engine is not engine:
        logger.warning("runtime DB diagnostic stage=engine_binding status=query_unavailable")
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "diagnostic_unavailable", "message": "diagnostic unavailable"}},
            headers=NO_STORE_HEADERS,
        )

    identity_rows, identity_status = _run_fixed_query(session_factory, "identity", IDENTITY_SQL)
    version_schema_rows, version_schema_status = _run_fixed_query(
        session_factory, "alembic_version_schemas", ALEMBIC_SCHEMAS_SQL
    )
    revision_rows, revision_status = _run_fixed_query(
        session_factory, "alembic_revisions", ALEMBIC_REVISIONS_SQL
    )
    table_rows, tables_status = _run_fixed_query(session_factory, "training_tables", TRAINING_TABLES_SQL)
    column_rows, columns_status = _run_fixed_query(session_factory, "draft_columns", DRAFT_COLUMNS_SQL)

    identity = None
    if identity_status == "available" and identity_rows:
        row = identity_rows[0]
        server_address = row["server_address"]
        identity = DatabaseIdentity(
            database_name=str(row["database_name"]),
            database_user=str(row["database_user"]),
            server_address=str(server_address) if server_address is not None else None,
            server_port=int(row["server_port"]) if row["server_port"] is not None else None,
            current_schema=row["current_schema"],
            search_path=str(row["search_path"]),
        )

    version_table_schemas = [str(row["table_schema"]) for row in version_schema_rows]
    revisions = [str(row["version_num"]) for row in revision_rows]
    table_schema_map = {name: [] for name in TRAINING_TABLE_NAMES}
    for row in table_rows:
        name = str(row["table_name"])
        if name in table_schema_map:
            table_schema_map[name].append(str(row["table_schema"]))
    column_schema_map = {name: [] for name in DRAFT_COLUMN_NAMES}
    for row in column_rows:
        name = str(row["column_name"])
        if name in column_schema_map:
            column_schema_map[name].append(str(row["table_schema"]))

    statuses = DiagnosticQueryStatuses(
        identity=identity_status,
        alembic_version_schemas=version_schema_status,
        alembic_revisions=revision_status,
        training_tables=tables_status,
        draft_columns=columns_status,
    )
    return RuntimeDatabaseDiagnostic(
        database_identity=identity,
        alembic=AlembicDiagnostic(
            status=revision_status,
            version_table_schemas=version_table_schemas,
            revisions=revisions,
        ),
        tables=[
            ObjectPresence(name=name, present=bool(table_schema_map[name]), schemas=table_schema_map[name])
            for name in TRAINING_TABLE_NAMES
        ],
        draft_columns=[
            ObjectPresence(name=name, present=bool(column_schema_map[name]), schemas=column_schema_map[name])
            for name in DRAFT_COLUMN_NAMES
        ],
        diagnostic_status=DiagnosticStatus(overall=_overall_status(statuses), queries=statuses),
    )
