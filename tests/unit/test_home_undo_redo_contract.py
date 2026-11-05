from types import SimpleNamespace
from uuid import uuid4

from backend.services import home_recommendation_service as home


def test_home_history_links_only_uncommitted_home_task_and_checks_owner():
    session_id = uuid4()
    paper = {"selected_kp_ids": [str(uuid4())], "questions": [{"question_id": str(uuid4())}]}
    task = SimpleNamespace(
        id=uuid4(), session_id=session_id, draft=paper,
        metrics={}, context={"home_recommendation": True},
    )
    entry = home._history_entry(task, paper)
    assert entry == {"task_id": str(task.id)}

    db = SimpleNamespace(get=lambda model, identifier: task if identifier == task.id else None)
    restored = home._history_paper(db, session_id, entry)
    assert restored == paper
    assert restored is not paper

    assert home._history_paper(db, uuid4(), entry) is None
    task.context = {"home_recommendation": False}
    assert home._history_paper(db, session_id, entry) is None
    task.context = {"home_recommendation": True}
    task.metrics = {"commit": {"plan_id": str(uuid4())}}
    assert home._history_entry(task, paper) == {"snapshot": paper}
    assert home._history_paper(db, session_id, {"task_id": str(task.id)}) is None


def test_home_history_snapshot_is_detached_and_rejects_malformed_entries():
    paper = {"selected_kp_ids": [str(uuid4())], "questions": [{"question_id": str(uuid4())}]}
    snapshot = home._history_entry(None, paper)
    assert snapshot == {"snapshot": paper}
    assert snapshot["snapshot"] is not paper
    snapshot["snapshot"]["questions"].clear()
    assert paper["questions"]

    db = SimpleNamespace(get=lambda *_: None)
    assert home._history_paper(db, uuid4(), {"snapshot": {"selected_kp_ids": [], "questions": []}}) is None
    assert home._history_paper(db, uuid4(), None) is None
    assert home._history_paper(db, uuid4(), {"task_id": "not-a-uuid"}) is None


def test_home_preview_exposes_history_availability_but_not_history_payload(monkeypatch):
    session_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(), session_id=session_id, goal="编辑方案", status="ready", message="ready",
        error_code=None, draft={"questions": []}, budget_minutes=90,
        metrics={}, context={
            "home_recommendation": True,
            "home_undo_stack": [{"snapshot": {"private": "history payload"}}],
            "home_redo_stack": [],
        },
    )
    monkeypatch.setattr(home, "_draft_version", lambda _: "a" * 64)
    result = home.view(row)
    assert result["undo_available"] is True
    assert result["redo_available"] is False
    assert "home_undo_stack" not in result["context"]
    assert "home_redo_stack" not in result["context"]
    assert result["context"] == {"home_recommendation": True}
