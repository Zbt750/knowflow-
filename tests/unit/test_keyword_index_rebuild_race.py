from __future__ import annotations

from threading import Event, Thread
from uuid import UUID, uuid4

import rank_bm25

from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.protocols import VectorRecord


def _record(text: str) -> VectorRecord:
    return VectorRecord(
        chunk_id=uuid4(),
        material_id=UUID("00000000-0000-0000-0000-000000000001"),
        index_version="v1",
        ordinal=0,
        content=text,
        heading_path=(),
        source_type="builtin",
    )


def test_readers_keep_a_consistent_snapshot_during_rebuild(monkeypatch) -> None:
    old_records = [_record("苹果"), _record("橘子"), _record("葡萄")]
    new_records = [_record("香蕉"), _record("梨"), _record("西瓜")]
    index = KeywordIndex()
    index.rebuild(old_records)

    building = Event()
    release = Event()
    original_bm25 = rank_bm25.BM25Okapi

    def blocked_bm25(*args, **kwargs):
        building.set()
        assert release.wait(timeout=5)
        return original_bm25(*args, **kwargs)

    monkeypatch.setattr(rank_bm25, "BM25Okapi", blocked_bm25)
    failures: list[BaseException] = []

    def rebuild() -> None:
        try:
            index.rebuild(new_records)
        except BaseException as error:  # captured so the worker failure fails this test
            failures.append(error)

    worker = Thread(target=rebuild)
    worker.start()
    try:
        assert building.wait(timeout=5)
        # The published index must remain wholly old until the replacement is ready.
        assert [chunk_id for chunk_id, _ in index.search("苹果", top_k=3)] == [old_records[0].chunk_id]
        assert index.record(old_records[0].chunk_id) == old_records[0]
        assert index.record(new_records[0].chunk_id) is None
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert failures == []
    assert [chunk_id for chunk_id, _ in index.search("香蕉", top_k=3)] == [new_records[0].chunk_id]
