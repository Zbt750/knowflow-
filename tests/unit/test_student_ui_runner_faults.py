from pathlib import Path
from uuid import uuid4
import json

from scripts.naiwa_student_ui_acceptance_20261024 import _active_isolated_get_fault


def marker(path: Path, payload: dict):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_sessions_fault_is_short_lived_station_owned_and_get_only(tmp_path):
    now = 1_800_000_000.0
    marker(tmp_path / "fault-chat-sessions-500.json", {
        "station_id": "uihandoff2", "route": "sessions", "expires_at": now + 300,
    })
    assert _active_isolated_get_fault(method="GET", path="/api/chat/sessions",
        marker_dir=tmp_path, station_id="uihandoff2", now=now) == {
            "route": "sessions", "session_id": None}
    assert _active_isolated_get_fault(method="POST", path="/api/chat/sessions",
        marker_dir=tmp_path, station_id="uihandoff2", now=now) is None
    assert _active_isolated_get_fault(method="GET", path="/api/chat/sessions/",
        marker_dir=tmp_path, station_id="uihandoff2", now=now) is None
    assert _active_isolated_get_fault(method="GET", path="/api/chat/sessions",
        marker_dir=tmp_path, station_id="another-station", now=now) is None


def test_messages_fault_must_match_one_exact_session_and_expiry(tmp_path):
    now = 1_800_000_000.0
    session_id = str(uuid4())
    marker(tmp_path / "fault-chat-messages-500.json", {
        "station_id": "uihandoff2", "route": "messages", "session_id": session_id,
        "expires_at": now + 300,
    })
    path = f"/api/chat/sessions/{session_id}/messages"
    assert _active_isolated_get_fault(method="GET", path=path, marker_dir=tmp_path,
        station_id="uihandoff2", now=now) == {"route": "messages", "session_id": session_id}
    assert _active_isolated_get_fault(method="GET", path=f"/api/chat/sessions/{uuid4()}/messages",
        marker_dir=tmp_path, station_id="uihandoff2", now=now) is None
    assert _active_isolated_get_fault(method="GET", path=path, marker_dir=tmp_path,
        station_id="uihandoff2", now=now + 301) is None


def test_fault_marker_rejects_expired_or_unbounded_lifetime(tmp_path):
    now = 1_800_000_000.0
    fault_path = tmp_path / "fault-chat-sessions-500.json"
    for expiry in (now, now + 3601):
        marker(fault_path, {"station_id": "uihandoff2", "route": "sessions", "expires_at": expiry})
        assert _active_isolated_get_fault(method="GET", path="/api/chat/sessions",
            marker_dir=tmp_path, station_id="uihandoff2", now=now) is None
