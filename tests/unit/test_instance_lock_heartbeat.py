from __future__ import annotations

import time
from threading import Event, Lock, Thread
from types import SimpleNamespace

from backend import app as app_module


def test_failed_instance_lock_heartbeat_marks_process_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "INSTANCE_LOCK_HEARTBEAT_SECONDS", 0.005)

    class BrokenConnection:
        def execute(self, _statement):
            raise OSError("connection lost")

    app = SimpleNamespace(state=SimpleNamespace(job_runner=None, instance_lock_lost=False))
    stop = Event()
    worker = Thread(
        target=app_module._watch_instance_lock,
        args=(app, BrokenConnection(), stop, Lock()),
    )
    worker.start()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert app.state.instance_lock_lost is True
