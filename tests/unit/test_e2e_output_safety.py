"""Invalid destinations must be rejected before resetting any test data."""
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows runner safety contract")
@pytest.mark.parametrize("target", ["workspace", "outside"])
def test_invalid_output_rejected_before_test_database_activity(target, tmp_path):
    destination = ROOT if target == "workspace" else tmp_path
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(ROOT / "scripts/run-e2e.ps1"), "-OutputDir", str(destination)],
        cwd=ROOT, capture_output=True, timeout=20)
    assert result.returncode != 0
    assert b"OutputDir" in result.stderr
    assert b"1/4" not in result.stdout


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows runner safety contract")
def test_existing_report_directory_is_not_cleared():
    folder = ROOT / "eval" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="runner-safety-", dir=folder) as destination:
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(ROOT / "scripts/run-e2e.ps1"), "-OutputDir", destination],
            cwd=ROOT, capture_output=True, timeout=20)
        assert result.returncode != 0 and b"already exists" in result.stderr
        assert b"1/4" not in result.stdout


def test_deployment_checker_root_is_checkout_relative():
    import scripts.check_deploy_config as checker
    assert checker.ROOT == ROOT


def test_runner_uses_new_resource_directory_and_retains_startup_logs():
    source = (ROOT / "scripts/run-e2e.ps1").read_text(encoding="utf-8-sig")
    assert 'storage/e2e-test/' in source
    assert "[guid]::NewGuid().ToString('N')" in source
    assert "$env:CHROMA_DIR = Join-Path $runStorage 'chroma'" in source
    assert "$env:UPLOAD_DIR = Join-Path $runStorage 'uploads'" in source
    assert "-RedirectStandardError" in source
    assert "backend.stderr.log" in source
    assert source.index("OutputDir already exists") < source.index("New-Item -ItemType Directory")


def test_preparation_does_not_delete_corrupt_vector_directory():
    source = (ROOT / "scripts/prepare_e2e_data.py").read_text(encoding="utf-8")
    assert "shutil.rmtree" not in source
    assert "原目录保留供诊断" in source
