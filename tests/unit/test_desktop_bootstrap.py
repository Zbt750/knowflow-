import json
from types import SimpleNamespace

import pytest

from desktop.bootstrap import prepare_schema
from desktop.postgres import APP_USER, DATABASE


@pytest.fixture
def bootstrap(tmp_path, monkeypatch):
    state = SimpleNamespace(tables={"alembic_version"}, revisions=["old"], upgrade=[], disposed=False)
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def execute(self, statement):
            if "current_database" in str(statement):
                return SimpleNamespace(one=lambda: (DATABASE, APP_USER))
            return SimpleNamespace(scalars=lambda: state.revisions)
    class Engine:
        def connect(self): return Connection()
        def dispose(self): state.disposed = True
    engine = Engine()
    monkeypatch.setattr("backend.db.create_db_engine", lambda _url: engine)
    monkeypatch.setattr("desktop.bootstrap.inspect", lambda _connection: SimpleNamespace(get_table_names=lambda: state.tables))
    def get_revision(revision):
        if revision == "foreign": raise ValueError("unknown")
        return revision
    monkeypatch.setattr("desktop.bootstrap.ScriptDirectory.from_config", lambda _config: SimpleNamespace(get_current_head=lambda: "head", get_revision=get_revision))
    monkeypatch.setattr("desktop.bootstrap.command.upgrade", lambda *_args: state.upgrade.append(True))
    data = tmp_path / "user"
    (data / "config").mkdir(parents=True)
    (data / "config/bootstrap.json").write_text(json.dumps({"format": 1, "initialized": True, "cluster_id": "synthetic"}))
    manager = SimpleNamespace(paths=SimpleNamespace(resources=tmp_path / "resources", data=data),
                              owner={"cluster_id": "synthetic"}, database_url="synthetic",
                              backup=lambda: state.upgrade.append("backup"))
    return manager, state


def test_upgrade_backs_up_before_migrating(bootstrap):
    manager, state = bootstrap
    assert prepare_schema(manager)["seeded"] is False
    assert state.upgrade == ["backup", True] and state.disposed


def test_backup_failure_prevents_any_migration(bootstrap):
    manager, state = bootstrap
    def backup_failure(): raise ValueError("desktop_postgres_backup_failed")
    manager.backup = backup_failure
    with pytest.raises(ValueError, match="backup_failed"):
        prepare_schema(manager)
    assert state.upgrade == [] and state.disposed


def test_matching_head_does_not_reseed_or_backup(bootstrap):
    manager, state = bootstrap
    state.revisions = ["head"]
    assert prepare_schema(manager) == {"schema": "head", "seeded": False, "backup_created": False}
    assert state.upgrade == [] and state.disposed


@pytest.mark.parametrize("tables,revisions,error", [
    ({"user_history"}, [], "unknown_schema"),
    ({"alembic_version"}, ["foreign"], "schema_incompatible"),
    ({"alembic_version"}, ["one", "two"], "unknown_schema"),
])
def test_foreign_or_ambiguous_schema_never_migrated(bootstrap, tables, revisions, error):
    manager, state = bootstrap
    state.tables, state.revisions = tables, revisions
    with pytest.raises(ValueError, match=error): prepare_schema(manager)
    assert state.upgrade == [] and state.disposed


def test_invalid_receipt_blocks_initialization(bootstrap):
    manager, state = bootstrap
    (manager.paths.data / "config/bootstrap.json").write_text('{"format": 0}')
    with pytest.raises(ValueError, match="receipt_invalid"): prepare_schema(manager)
    assert state.upgrade == []


def test_initialized_database_with_missing_schema_is_not_silently_recreated(bootstrap):
    manager, state = bootstrap
    state.tables, state.revisions = set(), []
    with pytest.raises(ValueError, match="initialized_schema_missing"):
        prepare_schema(manager)
    assert state.upgrade == [] and state.disposed
