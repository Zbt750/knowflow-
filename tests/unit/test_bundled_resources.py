from pathlib import Path
import sys

import pytest

from backend.resources import bundled_path, resource_root


def test_web_ignores_desktop_resource_override(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_RUNTIME_PROFILE", "web")
    monkeypatch.setenv("DESKTOP_RESOURCE_ROOT", str(tmp_path))
    assert resource_root() == Path(__file__).resolve().parents[2]


def test_desktop_resources_are_independent_of_cwd(monkeypatch, tmp_path):
    resource = tmp_path / "只读资源"
    (resource / "seed/lessons").mkdir(parents=True)
    (resource / "seed/lessons/synthetic.lesson.md").write_text("# 隔离讲解", encoding="utf-8")
    monkeypatch.setenv("APP_RUNTIME_PROFILE", "desktop")
    monkeypatch.setenv("DESKTOP_RESOURCE_ROOT", str(resource))
    monkeypatch.chdir(tmp_path)
    from backend.services.lesson_service import read_lesson
    assert read_lesson("synthetic.lesson") == "# 隔离讲解"
    assert read_lesson("../private") is None


def test_frozen_default_is_bundle_root_not_executable_or_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("DESKTOP_RESOURCE_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    assert resource_root() == (tmp_path / "_internal").resolve()


@pytest.mark.parametrize("name", ["../private", "seed/../../private"])
def test_resource_traversal_refused(monkeypatch, tmp_path, name):
    monkeypatch.setenv("APP_RUNTIME_PROFILE", "desktop")
    monkeypatch.setenv("DESKTOP_RESOURCE_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="path_escape"):
        bundled_path(name)


def test_seed_loader_reads_explicit_bundle(monkeypatch, tmp_path):
    (tmp_path / "seed").mkdir()
    (tmp_path / "seed/synthetic.json").write_text('{"bundle": true}', encoding="utf-8")
    monkeypatch.setenv("APP_RUNTIME_PROFILE", "desktop")
    monkeypatch.setenv("DESKTOP_RESOURCE_ROOT", str(tmp_path))
    from scripts.seed import load_json
    assert load_json("synthetic.json") == {"bundle": True}


def test_non_absolute_desktop_root_is_not_accepted(monkeypatch):
    monkeypatch.setenv("APP_RUNTIME_PROFILE", "desktop")
    monkeypatch.setenv("DESKTOP_RESOURCE_ROOT", "relative")
    with pytest.raises(ValueError, match="root_invalid"):
        resource_root()
