from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from backend.errors import AppError
from backend.services import process_review_service as service


def test_duplicate_item_or_key_is_rejected_without_entering_work():
    item = uuid4()
    with service._review_admission(item, "same-key"):
        for duplicate_item, duplicate_key in [(item, "other-key"), (uuid4(), "same-key")]:
            with pytest.raises(AppError) as caught:
                with service._review_admission(duplicate_item, duplicate_key):
                    pytest.fail("duplicate was admitted")
            assert caught.value.code == "process_review_busy"
            assert caught.value.status_code == 503


def test_capacity_rejects_immediately_and_recovers_after_release():
    with service._review_admission(uuid4(), "first"):
        with service._review_admission(uuid4(), "second"):
            with pytest.raises(AppError):
                with service._review_admission(uuid4(), "third"):
                    pytest.fail("capacity exceeded")
    with service._review_admission(uuid4(), "third"):
        pass


def test_exception_releases_item_and_key():
    item = uuid4()
    with pytest.raises(RuntimeError):
        with service._review_admission(item, "failed"):
            raise RuntimeError("synthetic failure")
    with service._review_admission(item, "failed"):
        pass


def test_parallel_duplicate_never_reaches_model_and_first_result_is_preserved(monkeypatch):
    started, release = Event(), Event()
    item = uuid4()
    calls = []
    saved = object()

    def fake_work(*args, **kwargs):
        calls.append(kwargs["idempotency_key"])
        started.set()
        assert release.wait(5)
        return saved

    monkeypatch.setattr(service, "_review_text_process", fake_work)
    kwargs = dict(item_id=item, work_text="synthetic text", subjective_kind=None,
                  idempotency_key="parallel", now=None, provider=None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(service.review_text_process, None, **kwargs)
        try:
            assert started.wait(5)
            with pytest.raises(AppError):
                service.review_text_process(None, **kwargs)
            assert calls == ["parallel"]
        finally:
            release.set()
        assert first.result(5) is saved
    assert not service._ACTIVE_ITEMS and not service._ACTIVE_KEYS
