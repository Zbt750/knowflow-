"""Execute the Windows startup helpers without stopping real processes."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]
PS = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(PS is None, reason="Windows development launcher")

def quote(value):
    return "'" + str(value).replace("'", "''") + "'"

def evaluate(expression):
    script = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
              + ". " + quote(ROOT / "scripts/dev-service-health.ps1") + "; " + expression)
    result = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.lstrip("\ufeff"))

@pytest.mark.parametrize("payload,expected", [
    ({"status": "ok", "database": "connected", "environment": "dev"}, True),
    ({"error": {"code": "instance_lock_lost"}}, False),
    ({"status": "ok", "database": "disconnected", "environment": "dev"}, False),
    ({"status": "ok", "database": "connected", "environment": "test"}, False),
    ({}, False),
])
def test_listening_backend_only_reused_after_valid_dev_health(payload, expected):
    body = quote(json.dumps(payload))
    assert evaluate(f"$body={body}|ConvertFrom-Json; Test-DevBackendHealth $body|ConvertTo-Json -Compress") is expected

def test_http_503_preserves_lock_loss_code_for_recovery():
    result = evaluate('''
function Invoke-RestMethod {
    $e=New-Object System.Exception('HTTP 503');
    $record=New-Object System.Management.Automation.ErrorRecord($e,'probe',[System.Management.Automation.ErrorCategory]::ResourceUnavailable,$null);
    $record.ErrorDetails=New-Object System.Management.Automation.ErrorDetails('{"error":{"code":"instance_lock_lost","message":"lost"}}');
    throw $record
}
Get-DevBackendProbe|ConvertTo-Json -Compress
''')
    assert result["Ok"] is False and result["ErrorCode"] == "instance_lock_lost"

@pytest.mark.parametrize("change,expected", [("valid", True), ("pid", False), ("workspace", False), ("stale", False), ("outside", False)])
def test_restart_requires_matching_local_manifest_not_only_an_open_port(tmp_path, change, expected):
    manifest = tmp_path / "tmp/runtime.json"
    manifest.parent.mkdir()
    created = datetime(2026, 10, 7, 1, tzinfo=timezone.utc)
    data = {"pid": 4567, "workspace": str(tmp_path), "module": "backend.main:app",
            "bind": "127.0.0.1:8000", "started_at": (created + timedelta(seconds=2)).isoformat()}
    if change == "pid": data["pid"] = 9999
    if change == "workspace": data["workspace"] = str(tmp_path.parent)
    if change == "stale": data["started_at"] = (created - timedelta(hours=1)).isoformat()
    manifest.write_text(json.dumps(data), encoding="utf-8")
    arg = "../foreign.json" if change == "outside" else "tmp/runtime.json"
    expression = ("$process=[pscustomobject]@{ProcessId=4567;ExecutablePath='C:\\Python\\python.exe';"
                  + "CommandLine=" + quote(f"python -u scripts/run_phase4_backend.py --manifest {arg}")
                  + ";CreationDate=[datetime]" + quote(created.isoformat()) + "}; "
                  + "Test-DevBackendOwner " + quote(tmp_path) + " $process|ConvertTo-Json -Compress")
    assert evaluate(expression) is expected

def test_start_script_is_valid_windows_powershell():
    path = quote(ROOT / "scripts/start-dev.ps1")
    assert evaluate(f"$tokens=$null;$errors=$null;[void][System.Management.Automation.Language.Parser]::ParseFile({path},[ref]$tokens,[ref]$errors);@($errors).Count|ConvertTo-Json -Compress") == 0
