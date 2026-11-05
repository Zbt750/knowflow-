import json
import sys
from types import SimpleNamespace

import pytest

from desktop.postgres import (
    DataDirectoryLock, ManagedPostgres, PostgresCommandFailure,
    _diagnostic_text, _process_alive, _run, _terminate_process_tree,
)
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


@pytest.mark.parametrize("encoding", ["utf-8", "cp936"])
def test_identity_supports_exact_chinese_path_in_windows_pid_file(tmp_path, monkeypatch, encoding):
    paths = RuntimePaths.windows(resources=tmp_path / "resources", local_app_data=tmp_path / "学习资料")
    managed = ManagedPostgres(paths, tmp_path / "postgres/bin", port=18761)
    managed.cluster.mkdir(parents=True)
    content = f"123\n{managed.cluster}\n100\n18761\n\n127.0.0.1\n\nready\n"
    (managed.cluster / "postmaster.pid").write_bytes(content.encode(encoding))
    monkeypatch.setattr("desktop.postgres.locale.getencoding", lambda: "cp936")
    assert managed._identity() == (123, 100)


@pytest.mark.parametrize("bad_field", ["path", "port", "invalid_bytes"])
def test_identity_encoding_fallback_preserves_owner_checks(tmp_path, monkeypatch, bad_field):
    paths = RuntimePaths.windows(resources=tmp_path / "resources", local_app_data=tmp_path / "学习资料")
    managed = ManagedPostgres(paths, tmp_path / "postgres/bin", port=18761)
    managed.cluster.mkdir(parents=True)
    directory = tmp_path / "other" if bad_field == "path" else managed.cluster
    port = 18762 if bad_field == "port" else 18761
    content = f"123\n{directory}\n100\n{port}\n".encode("cp936")
    if bad_field == "invalid_bytes":
        content = b"123\n\x81\n100\n18761\n"
    (managed.cluster / "postmaster.pid").write_bytes(content)
    monkeypatch.setattr("desktop.postgres.locale.getencoding", lambda: "cp936")
    assert managed._identity() is None


@pytest.mark.parametrize("status,expected",[(False,False),(True,True),(None,None)])
def test_cluster_process_status_checks_only_pid_bound_to_exact_cluster(tmp_path,monkeypatch,status,expected):
    paths=RuntimePaths.windows(resources=tmp_path/"resources",local_app_data=tmp_path/"user")
    managed=ManagedPostgres(paths,tmp_path/"postgres/bin",port=18761)
    managed.cluster.mkdir(parents=True)
    (managed.cluster/"postmaster.pid").write_text(f"-32256\n{managed.cluster}\n1\n5432\n")
    calls=[]
    monkeypatch.setattr("desktop.postgres._process_alive",lambda pid:calls.append(pid) or status)
    assert managed.cluster_process_status() is expected
    assert calls==[32256]


def test_diagnostics_decode_windows_local_code_page_without_replacement(monkeypatch):
    monkeypatch.setattr("desktop.postgres._subprocess_encodings", lambda:("utf-8","cp936"))
    message="错误：测试权限".encode("cp936")
    assert _diagnostic_text(message)=="错误：测试权限"


def test_windows_timeout_cleanup_targets_only_the_spawned_pid_tree(monkeypatch):
    calls=[]
    monkeypatch.setattr("desktop.postgres.subprocess.run",lambda command,**kwargs:
        calls.append((command,kwargs)) or SimpleNamespace(returncode=0,stderr=b""))
    process=SimpleNamespace(pid=24680,wait=lambda timeout:0,kill=lambda:pytest.fail("root was already stopped"))
    result=_terminate_process_tree(process,windows=True)
    command=calls[0][0]
    assert command[-4:]==["/PID","24680","/T","/F"]
    assert result=={"root_process_id":24680,"tree_kill_exit_code":0}


def test_real_local_timeout_is_counted_and_owned_process_is_stopped(tmp_path):
    with pytest.raises(PostgresCommandFailure) as caught:
        _run([sys.executable,"-c","import time; time.sleep(10)"],timeout=0.2,
            stage="local_timeout_probe",cwd=tmp_path)
    diagnostic=caught.value.diagnostic
    assert diagnostic["stage"]=="local_timeout_probe" and diagnostic["timed_out"] is True
    assert diagnostic["process_id"]==diagnostic["descendant_cleanup"]["root_process_id"]
    assert _process_alive(diagnostic["process_id"]) is False


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
    assert all(kwargs["capture"] is True for _args, kwargs in calls)
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
    monkeypatch.setenv("PGSERVICE", "untrusted")
    monkeypatch.setenv("PGHOST", "remote.example")
    captured = {}
    def fake_popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        kwargs["stdout"].write(b"stdout fixture")
        kwargs["stderr"].write(b"stderr fixture")
        return SimpleNamespace(pid=123, wait=lambda timeout: 0)
    monkeypatch.setattr("desktop.postgres.subprocess.Popen", fake_popen)
    result = _run(["pg_dump", "--no-password"], extra_env={"PGPASSWORD": "synthetic-fixture-password"})
    assert "synthetic-fixture-password" not in str(captured["command"])
    assert {k: v for k, v in captured["env"].items() if k.startswith("PG")} == {"PGPASSWORD": "synthetic-fixture-password"}
    assert result.stdout == b"stdout fixture" and result.stderr == b"stderr fixture"
    assert captured["stdout"] != __import__("subprocess").PIPE


def test_subprocess_oserror_keeps_stage_and_windows_code_without_raw_exception(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise PermissionError(13, "access denied", str(tmp_path / "initdb.exe"))
    monkeypatch.setattr("desktop.postgres.subprocess.Popen", fail)
    with pytest.raises(PostgresCommandFailure) as caught:
        _run([str(tmp_path / "initdb.exe"), "--pwfile=private.tmp"], stage="initdb", cwd=tmp_path)
    assert caught.value.code == "desktop_postgres_command_failed"
    assert caught.value.diagnostic["stage"] == "initdb"
    assert caught.value.diagnostic["failure_phase"] == "process_launch"
    assert caught.value.diagnostic["os_error_type"] == "PermissionError"
    assert caught.value.diagnostic["errno"] == 13
    assert caught.value.diagnostic["filename"] == "initdb.exe"
    assert "private.tmp" not in str(caught.value.diagnostic)


def test_subprocess_timeout_keeps_captured_stderr_and_marks_unknown_completion(monkeypatch, tmp_path):
    def fail(*_args, **kwargs):
        kwargs["stdout"].write(b"partial stdout")
        kwargs["stderr"].write(b"FATAL: timeout")
        process = SimpleNamespace(pid=987, wait=lambda **_kwargs: (_ for _ in ()).throw(
            __import__("subprocess").TimeoutExpired("initdb", 90)), kill=lambda: None)
        monkeypatch.setattr("desktop.postgres._terminate_process_tree", lambda _process:
            {"root_process_id": 987, "tree_kill_exit_code": 0})
        return process
    monkeypatch.setattr("desktop.postgres.subprocess.Popen", fail)
    with pytest.raises(PostgresCommandFailure) as caught:
        _run(["initdb.exe"], timeout=90, stage="initdb", cwd=tmp_path)
    assert caught.value.diagnostic["timed_out"] is True
    assert caught.value.diagnostic["timeout_seconds"] == 90
    assert caught.value.diagnostic["stdout_tail"] == "partial stdout"
    assert caught.value.diagnostic["stderr_tail"] == "FATAL: timeout"
    assert caught.value.diagnostic["descendant_cleanup"]["root_process_id"] == 987


def test_initdb_nonzero_preserves_redacted_stderr_and_removes_private_password_file(manager, monkeypatch):
    manager.paths.ensure_data_dirs()
    manager._passwords = {"kaoyan_admin": "never-log-this-password", "kaoyan_app": "unused"}
    monkeypatch.setattr("desktop.postgres._private_file", lambda _path: None)
    monkeypatch.setattr("desktop.postgres._run", lambda *_args, **_kwargs:
        SimpleNamespace(returncode=1, stdout=b"", stderr=b"FATAL: password=never-log-this-password"))
    with pytest.raises(PostgresCommandFailure) as caught:
        manager._initialize()
    assert caught.value.code == "desktop_postgres_initialization_failed"
    assert caught.value.diagnostic["stage"] == "initdb"
    assert caught.value.diagnostic["returncode"] == 1
    assert "[REDACTED]" in caught.value.diagnostic["stderr_tail"]
    assert "never-log-this-password" not in str(caught.value.diagnostic)
    assert not list((manager.paths.data / "config").glob("pg-init-*.tmp"))


def test_output_capture_permission_error_is_distinct_from_process_launch(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise PermissionError(13,"access denied",str(tmp_path/"capture.tmp"))
    monkeypatch.setattr("desktop.postgres.tempfile.TemporaryFile",fail)
    with pytest.raises(PostgresCommandFailure) as caught:
        _run(["initdb.exe"],stage="initdb",cwd=tmp_path)
    assert caught.value.diagnostic["failure_phase"]=="capture_file_setup"
    assert caught.value.diagnostic["os_error_type"]=="PermissionError"
    assert caught.value.diagnostic["errno"]==13
