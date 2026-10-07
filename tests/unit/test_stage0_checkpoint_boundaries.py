"""Stage 0 does not read original exams or mutate learning data."""
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_math_preparation_requires_explicit_local_inputs():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/prepare_local_math_completion.py"), "--help"], capture_output=True)
    assert result.returncode == 0
    assert b"--source-pdf" in result.stdout and b"--intake-dir" in result.stdout
    text = (ROOT / "scripts/prepare_local_math_completion.py").read_text(encoding="utf-8")
    assert "C:/Users/" not in text


def test_backup_cannot_target_workspace_or_existing_data():
    from scripts.create_development_checkpoint_backup import safe_output
    for path in [ROOT, ROOT / "storage", ROOT / "storage/backups", ROOT / "seed"]:
        with pytest.raises(ValueError):
            safe_output(path)


def test_docker_excludes_all_project_venvs():
    rules = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for name in (".venv", ".venv-ragas", ".venv-desktop-build"):
        assert name in rules
