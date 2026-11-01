from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )


def test_new_round_ledger_starts_empty_and_closed_without_importing_history():
    code = r'''
import json, tempfile
from pathlib import Path
from scripts import naiwa_v33_paid_continuation_20261023 as runtime
with tempfile.TemporaryDirectory(prefix="naiwa-round-ledger-") as temp:
    root = Path(temp)
    ledger = root / "round" / "provider-ledger.json"
    control = root / "round" / "control.json"
    runtime.create_round_ledger(ledger, control)
    doc = json.loads(ledger.read_text(encoding="utf-8"))
    state = json.loads(control.read_text(encoding="utf-8"))
    assert doc["limits"]["max_requests"] == 40
    assert doc["requests"] == [] and doc["stop_reason"] is None
    assert sum(doc["scene_limits"].values()) == 40
    assert state["paid_enabled"] is False and state["authorization_received"] is False
    print("empty_independent_ledger_closed")
'''
    result = run_isolated(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "empty_independent_ledger_closed" in result.stdout


def test_new_round_ledger_refuses_existing_path_without_overwriting_it():
    code = r'''
import tempfile
from pathlib import Path
from scripts import naiwa_v33_paid_continuation_20261023 as runtime
with tempfile.TemporaryDirectory(prefix="naiwa-round-ledger-existing-") as temp:
    ledger = Path(temp) / "round" / "provider-ledger.json"
    control = ledger.with_name("control.json")
    ledger.parent.mkdir()
    ledger.write_text("prior-ledger-evidence", encoding="utf-8")
    try:
        runtime.create_round_ledger(ledger, control)
    except RuntimeError as exc:
        assert str(exc) == "new_round_ledger_path_already_exists"
    else:
        raise AssertionError("existing ledger was accepted")
    assert ledger.read_text(encoding="utf-8") == "prior-ledger-evidence"
    assert not control.exists()
    print("existing_ledger_preserved")
'''
    result = run_isolated(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "existing_ledger_preserved" in result.stdout


def test_parent_canonical_ledger_hash_is_pinned_for_the_new_round():
    code = r'''
import json, tempfile
from pathlib import Path
from scripts import naiwa_v33_paid_continuation_20261023 as runtime
with tempfile.TemporaryDirectory(prefix="naiwa-parent-ledger-") as temp:
    runtime.OUT = Path(temp)
    runtime.OUT.mkdir(exist_ok=True)
    runtime.save_new(runtime.OUT / "continuation-preflight.json", {
        "parent_ledger_sha256": runtime.legacy.sha(runtime.PARENT_LEDGER),
        "parent_control_sha256": runtime.legacy.sha(runtime.PARENT_LEDGER_DIR / "control.json"),
    })
    runtime.validate_parent_ledger()
    print("parent_ledger_and_control_hashes_pinned")
'''
    result = run_isolated(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "parent_ledger_and_control_hashes_pinned" in result.stdout


def test_differentiated_round_caps_leave_at_least_fourteen_of_original_forty_unused():
    from scripts import naiwa_v33_paid_continuation_20261023 as runtime

    assert runtime.ROUND_CATEGORY_TO_GATE_SCENE == {
        "A": "A", "B": "C", "C": "E", "D": "D",
        "E": "B", "F": "F", "G": "H", "H": "R",
    }
    # Two historical reservations already occupy scene A. The old V3 A cap of
    # three is retained, so this run can use at most 21 more slots overall.
    assert runtime.ROUND_GATE_SCENE_CAPS == {
        "A": 3, "C": 4, "E": 4, "D": 3,
        "B": 2, "F": 3, "H": 2, "R": 2,
    }
    assert sum(runtime.ROUND_GATE_SCENE_CAPS.values()) == 23
    assert 40 - sum(runtime.ROUND_GATE_SCENE_CAPS.values()) >= 14
    assert not runtime.DifferentiatedRoundGate.round_cap_reached(
        [{"case_id": "A"}, {"case_id": "A"}], "A"
    )
    assert runtime.DifferentiatedRoundGate.round_cap_reached(
        [{"case_id": "A"}, {"case_id": "A"}, {"case_id": "A"}], "A"
    )


def test_isolated_startup_preflight_does_not_require_daily_ports_to_be_free(monkeypatch):
    from scripts import naiwa_v33_paid_continuation_20261023 as runtime

    bound = []

    class Probe:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def bind(self, address):
            bound.append(address)

    monkeypatch.setattr(runtime.socket, "socket", Probe)
    runtime.assert_isolated_ports_free()
    assert bound == [("127.0.0.1", port) for port in runtime.ISOLATED_PORTS]
    assert 5433 not in {port for _, port in bound}
    assert 8000 not in {port for _, port in bound}
    assert 5173 not in {port for _, port in bound}
