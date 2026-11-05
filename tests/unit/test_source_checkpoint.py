import hashlib
import zipfile

import pytest
from scripts.create_source_checkpoint import create_checkpoint


def inventory(root):
    return {"issues": [], "missing_workspace_files": [], "manifest": [
        {"path": "src/example.py", "sha256": hashlib.sha256((root / "src/example.py").read_bytes()).hexdigest()}]}


def test_verified_archive_preserves_relative_layout_without_restoring(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/example.py").write_text("synthetic source", encoding="utf-8")
    output = tmp_path / "storage/backups/one"
    result = create_checkpoint(tmp_path, output, auditor=inventory)
    assert result["archive_verified"] and not result["git_modified"]
    assert not result["restore_executed"]
    with zipfile.ZipFile(output / "source-workspace.zip") as archive:
        assert archive.namelist() == ["src/example.py"]
        assert archive.read("src/example.py") == b"synthetic source"


@pytest.mark.parametrize("kind", ["outside", "root", "existing"])
def test_invalid_destination_rejected_before_audit(tmp_path, kind):
    output = tmp_path / "elsewhere" if kind == "outside" else tmp_path / "storage/backups"
    if kind == "existing":
        output = output / "existing"
        output.mkdir(parents=True)
    with pytest.raises(ValueError):
        create_checkpoint(tmp_path, output, auditor=lambda _: pytest.fail("must reject first"))


def test_risky_inventory_cannot_create_archive(tmp_path):
    output = tmp_path / "storage/backups/one"
    with pytest.raises(ValueError, match="inventory risks"):
        create_checkpoint(tmp_path, output, auditor=lambda _: {"issues": [{"kind": "secret"}], "missing_workspace_files": []})
    assert not output.exists()


def test_changed_source_does_not_claim_success(tmp_path):
    (tmp_path / "src").mkdir()
    path = tmp_path / "src/example.py"
    path.write_text("before", encoding="utf-8")
    before = inventory(tmp_path)
    path.write_text("after", encoding="utf-8")
    output = tmp_path / "storage/backups/one"
    with pytest.raises(ValueError, match="Workspace changed"):
        create_checkpoint(tmp_path, output, auditor=lambda _: before)
    assert not (output / "source-manifest.json").exists()
