"""Real fresh cluster, never kaoyan/kaoyan_test. Explicit local binaries required."""
import os
from pathlib import Path
import socket

import pytest
from fastapi.testclient import TestClient
from psycopg import errors, sql

from backend.app import create_app
from backend.config import get_settings
from desktop.bootstrap import prepare_schema
from desktop.postgres import ManagedPostgres, APP_USER, DATABASE, _run
from desktop.runtime_paths import RuntimePaths
from desktop.server import attach_frontend, configure_environment


def test_owned_pg_first_boot_restart_preservation_and_backup(tmp_path, monkeypatch):
    binary_dir = os.environ.get("KAOYAN_MANAGED_PG_TEST_BIN")
    if os.name != "nt" or not binary_dir:
        pytest.skip("explicit Windows PG18 binaries required for isolated-cluster test")
    root = Path(__file__).resolve().parents[2]
    paths = RuntimePaths.windows(resources=root, local_app_data=tmp_path / "managed-user")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert port >= 18000
    monkeypatch.setattr("desktop.server.os.environ", dict(os.environ))
    monkeypatch.delenv("PGSERVICE", raising=False)
    monkeypatch.setattr("backend.app._try_build_retrieval_stack", lambda *_args: False)
    identity = None
    try:
        with ManagedPostgres(paths, Path(binary_dir), port=port) as manager:
            configure_environment(paths, manager.database_url, 18751)
            result = prepare_schema(manager)
            assert result["seeded"] is True and result["backup_created"] is False
            assert not list((paths.data / "config").glob("pg-init-*.tmp"))
            assert manager.credentials.read_bytes().startswith(b"PGDPAPI1\n")
            assert manager._passwords[APP_USER].encode() not in manager.credentials.read_bytes()
            identity = manager.owner["cluster_id"]
            # A duplicate must neither acquire the data lock nor stop the original.
            with pytest.raises(ValueError, match="data_in_use"):
                ManagedPostgres(paths, Path(binary_dir), port=port).start()
            with manager._connect(APP_USER, DATABASE) as connection:
                assert connection.execute("SELECT count(*) FROM knowledge_points").fetchone()[0] >= 300
                assert connection.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0] is False
                with pytest.raises(errors.InsufficientPrivilege):
                    connection.execute("CREATE ROLE desktop_forbidden_probe")
                connection.execute("CREATE TABLE desktop_preservation_probe (value text)")
                connection.execute("INSERT INTO desktop_preservation_probe VALUES ('synthetic-retained')")
            dump = manager.backup()
            assert dump.exists() and dump.stat().st_size > 1024
            # Check archive restoration into a new DB inside this owned cluster,
            # not by replacing the original DB or any development/test database.
            restore_db = "desktop_restore_probe"
            with manager._connect() as connection:
                connection.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(restore_db), sql.Identifier(APP_USER)))
            restored = _run([manager.binary("pg_restore"), "--no-password", "--host=127.0.0.1",
                             "--port=" + str(port), "--username=" + APP_USER,
                             "--dbname=" + restore_db, str(dump)], timeout=60,
                            extra_env={"PGPASSWORD": manager._passwords[APP_USER]})
            assert restored.returncode == 0
            with manager._connect(APP_USER, restore_db) as connection:
                assert connection.execute("SELECT value FROM desktop_preservation_probe").fetchone()[0] == "synthetic-retained"
            with manager._connect() as connection:
                connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(restore_db)))
            app = attach_frontend(create_app(), root / "frontend/dist", port=18751)
            with TestClient(app, base_url="http://127.0.0.1:18751", client=("127.0.0.1", 12345)) as client:
                assert client.get("/api/health").json()["database"] == "connected"
                assert client.get("/api/settings/model").json()["key_configured"] is False
                assert client.get("/api/materials").status_code == 200
                for route in ("/study", "/chat", "/knowledge", "/materials", "/settings"):
                    assert client.get(route).status_code == 200
        assert not (manager.cluster / "postmaster.pid").exists()
        with ManagedPostgres(paths, Path(binary_dir), port=port) as restarted:
            configure_environment(paths, restarted.database_url, 18751)
            assert prepare_schema(restarted)["seeded"] is False
            assert restarted.owner["cluster_id"] == identity
            with restarted._connect(APP_USER, DATABASE) as connection:
                assert connection.execute("SELECT value FROM desktop_preservation_probe").fetchone()[0] == "synthetic-retained"
        assert not (restarted.cluster / "postmaster.pid").exists()
        with socket.socket() as probe:
            probe.settimeout(0.2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        get_settings.cache_clear()
