import pytest

from scripts.upgrade_reviewed_transcriptions import ROOT, local_output, read_json


def test_upgrade_report_cannot_write_public_source():
    with pytest.raises(ValueError, match="ignored local"):
        local_output(ROOT / "docs/upgrade-private.json")
    assert local_output(ROOT / "eval/reports/upgrade-preview-unit-test-never-written.json").is_relative_to(ROOT)


def test_previous_artifact_preserved_and_input_bounded(tmp_path, monkeypatch):
    import scripts.upgrade_reviewed_transcriptions as cli
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    previous = tmp_path / "storage/question-intake/fixture.json"
    previous.parent.mkdir(parents=True)
    previous.write_text("SYNTHETIC test artifact", encoding="utf-8")
    with pytest.raises(ValueError, match="overwrite"):
        local_output(previous)
    path = tmp_path / "too-large.json"
    with path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="16 MiB"):
        read_json(path)
