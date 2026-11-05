"""Strictly verify the runner-owned test database before enabling provider HTTP.

Transport tests mock the final network boundary, but still use the production
HTTP client policy. This helper proves the active test database and its owned
cluster identity instead of relaxing the production database safety guard.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.chat import http_clients


def configure_owned_test_provider_http() -> None:
    test_url = os.environ.get("TEST_DATABASE_URL", "")
    admin_url = os.environ.get("NAIWA_ADMIN_TEST_DATABASE_URL", "")
    owner_marker = os.environ.get("NAIWA_OWNER_MARKER", "")
    expected_cluster = os.environ.get("NAIWA_EXPECTED_CLUSTER_ID", "")
    expected_system = os.environ.get("NAIWA_EXPECTED_SYSTEM_IDENTIFIER", "")
    expected_database = os.environ.get("NAIWA_ISOLATED_DATABASE", "")
    try:
        expected_port = int(os.environ.get("NAIWA_ISOLATED_PG_PORT", "0"))
    except ValueError:
        expected_port = 0

    url = make_url(test_url)
    if (os.environ.get("APP_ENV") != "test"
            or os.environ.get("NAIWA_FRESH_TEST_DATABASE") != "1"
            or not admin_url or not owner_marker or not expected_cluster or not expected_system
            or url.get_backend_name() != "postgresql"
            or url.host != "127.0.0.1" or url.port != expected_port
            or url.database != expected_database or url.username != "kaoyan_app"
            or expected_port <= 18000 or expected_port in {5433, 63044}
            or expected_database == "naiwa_experience_test"
            or not expected_database.endswith("_test")):
        raise RuntimeError("provider transport tests require a verified owned _test database")

    marker = json.loads(Path(owner_marker).read_text(encoding="utf-8"))
    if marker.get("cluster_id") != expected_cluster:
        raise RuntimeError("provider transport test cluster marker mismatch")

    app_engine = create_engine(test_url, pool_pre_ping=True)
    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    try:
        with app_engine.connect() as connection:
            observed = connection.execute(text(
                "SELECT current_database(), current_user, host(inet_server_addr()), inet_server_port()"
            )).one()
        if tuple(observed) != (expected_database, "kaoyan_app", "127.0.0.1", expected_port):
            raise RuntimeError("provider transport test database identity mismatch")
        with admin_engine.connect() as connection:
            system_identifier = str(connection.execute(text(
                "SELECT system_identifier FROM pg_control_system()"
            )).scalar_one())
        if system_identifier != expected_system:
            raise RuntimeError("provider transport test system identifier mismatch")
    finally:
        app_engine.dispose()
        admin_engine.dispose()

    identity = {
        "cluster_id": expected_cluster,
        "database": expected_database,
        "role": "kaoyan_app",
        "host": "127.0.0.1",
        "port": expected_port,
    }
    http_clients.configure_isolated_provider_http(
        SimpleNamespace(app_env="test", active_database_url=test_url),
        verified_fresh_identity=identity,
    )
