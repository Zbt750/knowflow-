import json
from types import SimpleNamespace

import pytest

from desktop.postgres import DataDirectoryLock, ManagedPostgres
from desktop.runtime_paths import RuntimePaths


@pytest.fixture
def manager(tmp_path):
    paths = RuntimePaths.windows(resources=tmp_path / "resources", local_app_data=tmp_path / "user")
    return ManagedPostgres(paths, tmp_path / "postgres/bin", port=18761)


def test_os_lock_rejects_second_owner_and_releases(tmp_path):
    first, second = DataDirectoryLock(tmp_path), DataDirectoryLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(ValueError, match="data_in_use"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_unowned_cluster_is_never_initialized_or_marked(manager):
    manager.paths.ensure_data_dirs()
    manager.cluster.mkdir()
    (manager.cluster / "PG_VERSION").write_text("18")
    with pytest.raises(ValueError, match="unowned_cluster"):
        manager._load_owner()
    assert not manager.marker.exists()
    assert (manager.cluster / "PG_VERSION").read_text() == "18"


def test_owner_marker_is_stable_and_bound_to_root(manager):
    manager.paths.ensure_data_dirs()
    manager._load_owner()
    original = manager.owner.copy()
    manager._load_owner()
    assert manager.owner == original
    modified = {**original, "root_hash": "0" * 64}
    manager.marker.write_text(json.dumps(modified))
    with pytest.raises(ValueError, match="owner_invalid"):
        manager._load_owner()


def test_partial_cluster_not_reinitialized(manager, monkeypatch):
    manager.paths.ensure_data_dirs()
    manager.cluster.mkdir()
    (manager.cluster / "important-user-data").write_text("preserve")
    monkeypatch.setattr("desktop.postgres._run", lambda *_args, **_kwargs: pytest.fail("must not invoke initdb"))
    with pytest.raises(ValueError, match="partial_cluster"):
        manager._initialize()
    assert (manager.cluster / "important-user-data").read_text() == "preserve"


def test_major_version_mismatch_preserves_cluster(manager):
    manager.cluster.mkdir(parents=True)
    (manager.cluster / "PG_VERSION").write_text("17")
    with pytest.raises(ValueError, match="version_mismatch"):
        manager._initialize()


def test_shutdown_without_ownership_never_runs_pg_ctl(manager, monkeypatch):
    monkeypatch.setattr("desktop.postgres._run", lambda *_args, **_kwargs: pytest.fail("must not stop another PG"))
    manager.stop()


def test_shutdown_identity_changed_does_not_stop_replacement(manager, monkeypatch):
    manager._owned_identity = (123, 100)
    monkeypatch.setattr(manager, "_identity", lambda: (456, 200))
    monkeypatch.setattr("desktop.postgres._run", lambda *_args, **_kwargs: pytest.fail("must not stop replacement"))
    with pytest.raises(ValueError, match="identity_changed"):
        manager.stop()


def test_safe_shutdown_targets_only_owned_directory(manager, monkeypatch):
    manager._owned_identity = (123, 100)
    monkeypatch.setattr(manager, "_identity", lambda: (123, 100))
    calls = []
    monkeypatch.setattr("desktop.postgres._run", lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0))
    manager.stop()
    assert len(calls) == 1 and calls[0][calls[0].index("-D") + 1] == str(manager.cluster)
    assert calls[0][calls[0].index("-m") + 1] == "fast"
    assert manager._owned_identity is None


def test_preflight_port_invalid_is_readonly(manager):
    manager.port = 5433
    with pytest.raises(ValueError, match="port_invalid"):
        manager.preflight()
    assert not manager.paths.data.exists()


def test_backup_without_ownership_refused(manager):
    with pytest.raises(ValueError, match="requires_owned_instance"):
        manager.backup()


def test_inherited_libpq_service_is_not_consulted(manager, monkeypatch):
    monkeypatch.setenv("PGSERVICE", "untrusted-development-service")
    monkeypatch.setattr("psycopg.connect", lambda **_kwargs: pytest.fail("must not read service file"))
    with pytest.raises(ValueError, match="inherited_service_forbidden"):
        manager._connect()


def test_database_failure_stops_only_this_new_process(manager, monkeypatch):
    monkeypatch.setattr(manager, "preflight", lambda: None)
    monkeypatch.setattr(manager, "_load_owner", lambda: None)
    monkeypatch.setattr(manager, "_load_passwords", lambda: None)
    monkeypatch.setattr(manager, "_initialize", lambda: None)
    monkeypatch.setattr("desktop.postgres.time.time", lambda: 100)
    monkeypatch.setattr(manager, "_identity", lambda: (123, 100))
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("desktop.postgres._run", run)
    def unavailable():
        raise ValueError("desktop_postgres_database_unavailable")
    monkeypatch.setattr(manager, "_ensure_database", unavailable)
    with pytest.raises(ValueError, match="database_unavailable"):
        manager.start()
    assert [args[-1] for args, _kwargs in calls] == ["start", "stop"]
    assert all(kwargs["capture"] is False for _args, kwargs in calls)
    assert manager.lock.handle is None and manager._owned_identity is None


def test_port_collision_does_not_initialize_or_stop_existing_pg(manager, monkeypatch):
    import socket
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        manager.port = occupied.getsockname()[1]
        monkeypatch.setattr(manager, "preflight", lambda: None)
        monkeypatch.setattr(manager, "_load_owner", lambda: pytest.fail("must not initialize"))
        monkeypatch.setattr("desktop.postgres._run", lambda *_args, **_kwargs: pytest.fail("must not stop existing PG"))
        with pytest.raises(ValueError, match="port_in_use"):
            manager.start()
        assert manager.lock.handle is None


def test_argv_does_not_hold_password_and_pg_environment_filtered(monkeypatch):
    from desktop.postgres import _run
    monkeypatch.setenv("PGSERVICE", "untrusted")
    monkeypatch.setenv("PGHOST", "remote.example")
    captured = {}
    def fake_run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("desktop.postgres.subprocess.run", fake_run)
    _run(["pg_dump", "--no-password"], extra_env={"PGPASSWORD": "synthetic-fixture-password"})
    assert "synthetic-fixture-password" not in str(captured["command"])
    assert {k: v for k, v in captured["env"].items() if k.startswith("PG")} == {"PGPASSWORD": "synthetic-fixture-password"}
