import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from scripts import verify_checkpoint_restore as drill


@pytest.mark.parametrize("name", ["kaoyan", "kaoyan_test", "postgres", "kaoyan_restore_x", 'x";DROP DATABASE kaoyan'])
def test_existing_or_injected_database_name_rejected(name):
    with pytest.raises(ValueError):
        drill.validate_database_name(name)


def test_restore_name_has_exact_generated_scope():
    name = "kaoyan_restore_" + "a" * 32
    assert drill.validate_database_name(name) == name


def fixture_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(drill, "ROOT", tmp_path)
    folder = tmp_path / "storage/backups/one"
    folder.mkdir(parents=True)
    dump, asset = b"synthetic dump", b"synthetic asset"
    (folder / "database.dump").write_bytes(dump)
    with zipfile.ZipFile(folder / "private-assets.zip", "w") as archive:
        archive.writestr("storage/uploads/synthetic.md", asset)
    (folder / "manifest.json").write_text(json.dumps({
        "format": "development-checkpoint-backup-v1", "database_sha256": hashlib.sha256(dump).hexdigest(),
        "assets": [{"path": "storage/uploads/synthetic.md", "bytes": len(asset),
                    "sha256": hashlib.sha256(asset).hexdigest()}]}), encoding="utf-8")
    return folder


def test_asset_and_dump_hashes_verified_without_extracting(tmp_path, monkeypatch):
    folder = fixture_backup(tmp_path, monkeypatch)
    _, facts = drill.check_backup(folder)
    assert facts["asset_files_verified"] == 1
    assert not (tmp_path / "storage/uploads").exists()
    (folder / "database.dump").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        drill.check_backup(folder)


@pytest.mark.parametrize("environment,host", [("prod", "127.0.0.1"), ("dev", "remote.example")])
def test_nonlocal_or_production_rejected_before_backup_read(environment, host, monkeypatch):
    monkeypatch.setattr(drill, "get_settings", lambda: SimpleNamespace(
        app_env=environment, active_database_url=f"postgresql+psycopg://u:p@{host}/kaoyan"))
    monkeypatch.setattr(drill, "check_backup", lambda _: pytest.fail("backup should not be read"))
    with pytest.raises(ValueError, match="local development"):
        drill.drill(Path("irrelevant"), Path("irrelevant"), admin_user="postgres")


def test_restore_failure_cleans_only_newly_created_database(tmp_path, monkeypatch):
    folder = fixture_backup(tmp_path, monkeypatch)
    binary = tmp_path / ("pg_restore.exe" if drill.os.name == "nt" else "pg_restore")
    binary.touch()
    monkeypatch.setattr(drill, "get_settings", lambda: SimpleNamespace(
        app_env="dev", active_database_url="postgresql+psycopg://u:private@127.0.0.1:5433/kaoyan"))
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=None):
            calls.append(str(sql))
            return SimpleNamespace(scalar=lambda: False)

    engine = SimpleNamespace(connect=Connection, dispose=lambda: None)
    monkeypatch.setattr(drill, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(drill.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    facts = drill.drill(folder, tmp_path, admin_user="postgres")
    assert not facts["restore_passed"] and facts["cleanup_passed"]
    assert calls[-1] == f'DROP DATABASE "{facts["temporary_database"]}"'
    assert facts["development_database_modified"] is False
    assert "private" not in json.dumps(facts)


@pytest.mark.parametrize("name", ["../secret", "/absolute", "C:/secret", "C:secret", "a\\b", "a/../b", "a//b", "a:b", ""])
def test_nonportable_or_escaping_asset_paths_rejected(name):
    with pytest.raises(ValueError, match="Unsafe asset path"):
        drill.safe_asset_name(name)


def test_material_coverage_checks_archive_not_live_files():
    materials = [{"stored_path": "one.md", "raw_hash": "hash", "file_size": 7}]
    assets = [{"path": "storage/uploads/one.md", "sha256": "hash", "bytes": 7}]
    facts = drill.material_asset_coverage(materials, assets, "storage/uploads")
    assert facts["passed"] and facts["matched"] == 1


@pytest.mark.parametrize("field,value,counter", [
    ("stored_path", "missing.md", "missing"),
    ("stored_path", "../one.md", "unsafe_paths"),
    ("raw_hash", "different", "hash_mismatches"),
    ("raw_hash", None, "unknown_hashes"),
    ("file_size", 8, "size_mismatches"),
])
def test_material_coverage_does_not_mask_incomplete_backup(field, value, counter):
    row = {"stored_path": "one.md", "raw_hash": "hash", "file_size": 7}
    row[field] = value
    facts = drill.material_asset_coverage([row], [{"path": "storage/uploads/one.md", "sha256": "hash", "bytes": 7}], "storage/uploads")
    assert not facts["passed"] and facts[counter] == 1
