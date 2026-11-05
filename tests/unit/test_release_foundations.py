from pathlib import Path
import pytest
from desktop.runtime_paths import RuntimePaths
from desktop.resource_manifest import build_manifest
from backend.services.program_sandbox_policy import SandboxPolicy


def test_desktop_data_is_separate_and_resource_is_not_created(tmp_path):
    resources = tmp_path / "Program Files" / "考研"
    paths = RuntimePaths.windows(resources=resources, local_app_data=tmp_path / "用户")
    paths.ensure_data_dirs()
    assert not resources.exists()
    assert paths.settings_overrides()["upload_dir"].is_relative_to(paths.data)
    assert (paths.data / "backups").is_dir()


def test_desktop_rejects_relative_and_overlapping_paths(tmp_path):
    with pytest.raises(ValueError):
        RuntimePaths.windows(resources=Path("relative"), local_app_data=tmp_path)
    with pytest.raises(ValueError):
        RuntimePaths.windows(resources=tmp_path, local_app_data=tmp_path)


def test_resource_manifest_ignores_private_and_dependencies(tmp_path):
    for name in ("backend/app.py", "backend/.env.py", "backend/__pycache__/x.py", "seed/readme.md",
                 "storage/user.md", ".env", ".pgdata/database.py", "frontend/dist/index.html"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic", encoding="utf-8")
    manifest = build_manifest(tmp_path)
    assert {entry["path"] for entry in manifest["files"]} == {"backend/app.py", "seed/readme.md", "frontend/dist/index.html"}
    assert manifest["installer_ready"] is False


def test_manifest_includes_only_reviewed_bootstrap_scripts(tmp_path):
    for name in ("alembic.ini", "scripts/seed.py", "scripts/private_eval.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic", encoding="utf-8")
    assert {entry["path"] for entry in build_manifest(tmp_path)["files"]} == {"alembic.ini", "scripts/seed.py"}


@pytest.mark.parametrize("policy", [SandboxPolicy(), SandboxPolicy(enabled=True, image_digest="python:latest"),
                                    SandboxPolicy(enabled=True, image_digest="x@sha256:" + "a" * 64, timeout_seconds=60)])
def test_sandbox_refuses_unsafe_defaults(policy):
    with pytest.raises(ValueError): policy.container_create_args(name="kaoyan-test-" + "a" * 32)


def test_sandbox_command_has_limits_and_no_host_mount():
    args = SandboxPolicy(enabled=True, image_digest="local/reviewed@sha256:" + "a" * 64).container_create_args(name="kaoyan-test-" + "b" * 32)
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" in args and "--privileged" not in args and "--volume" not in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
