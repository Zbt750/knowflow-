from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from backend.services.practice_request_service import view

NOW = datetime.now(timezone.utc)


def _row(status="draft", expires_in=timedelta(hours=1)):
    return SimpleNamespace(
        id=uuid4(), status=status, expires_at=NOW + expires_in,
        source_conversation_id=None, source_message_id=None,
        user_request="在等比级数再加两道", request={"target_knowledge_node_ids": []},
        planner_task_id=None, daily_plan_id=None, error_code=None,
        created_at=NOW - timedelta(minutes=5), handled_at=None,
    )


def test_failed_task_derives_failed():
    assert view(_row("pending"), NOW, task_status="failed")["status"] == "failed"


def test_cancelled_task_derives_cancelled():
    assert view(_row("pending"), NOW, task_status="cancelled")["status"] == "cancelled"


def test_running_task_derives_planning():
    assert view(_row("pending"), NOW, task_status="running")["status"] == "planning"


def test_ready_task_with_draft_derives_proposed():
    assert view(_row("pending"), NOW, task_status="ready")["status"] == "proposed"


def test_unknown_task_status_keeps_stored_status():
    assert view(_row("pending"), NOW, task_status=None)["status"] == "pending"


def test_expired_wins_over_task_derivation():
    assert view(_row("pending", timedelta(hours=-1)), NOW, task_status="running")["status"] == "expired"


def test_accepted_status_is_not_overwritten_by_task():
    assert view(_row("accepted"), NOW, task_status="failed")["status"] == "accepted"
