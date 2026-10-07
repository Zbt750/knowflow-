from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Event

import pytest

from backend.chat import service as chat_service
from backend.errors import AppError


def test_timed_out_worker_keeps_slot_until_real_thread_exits(monkeypatch) -> None:
    pool = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(chat_service, "_RETRIEVAL_POOL", pool)
    monkeypatch.setattr(chat_service, "_RETRIEVAL_SLOT", BoundedSemaphore(1))
    entered = Event()
    finish = Event()

    def blocked_prepare(*_args, **_kwargs):
        entered.set()
        assert finish.wait(timeout=5)
        return "prepared"

    monkeypatch.setattr(chat_service, "_prepare_from_factory", blocked_prepare)
    try:
        first = chat_service._submit_preparation(object())
        assert entered.wait(timeout=2)
        # A disconnected/timed-out request can cancel its asyncio wrapper, but not
        # the executing Python thread; new requests must be rejected, not queued.
        assert first.cancel() is False
        with pytest.raises(AppError) as captured:
            chat_service._submit_preparation(object())
        assert captured.value.code == "retrieval_busy"

        finish.set()
        assert first.result(timeout=2) == "prepared"
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if chat_service._RETRIEVAL_SLOT.acquire(blocking=False):
                chat_service._RETRIEVAL_SLOT.release()
                break
            time.sleep(0.01)
        else:
            pytest.fail("retrieval slot was not released when its worker exited")

        second = chat_service._submit_preparation(object())
        assert second.result(timeout=2) == "prepared"
    finally:
        finish.set()
        pool.shutdown(wait=True, cancel_futures=True)
