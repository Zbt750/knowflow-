"""持久化 close 不能变成 reset；用真实 Chroma 但不使用远程模型。"""

import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.retrieval.protocols import VectorRecord
from backend.retrieval.vector_store import ChromaVectorStore


@pytest.mark.parametrize("has_close", [True, False])
def test_close_is_idempotent_and_never_resets(has_close):
    calls = []

    def reset():
        pytest.fail("closing must not reset persistent data")

    client = SimpleNamespace(reset=reset)
    if has_close:
        client.close = lambda: calls.append("close")
    store = ChromaVectorStore.__new__(ChromaVectorStore)
    store._client = client
    store._collection = SimpleNamespace(reset=reset)
    store.close()
    store.close()
    assert calls == (["close"] if has_close else [])
    assert store._client is None and store._collection is None


def test_persistent_index_survives_close_in_fresh_process(tmp_path):
    chunk_id = uuid4()
    store = ChromaVectorStore(persist_directory=tmp_path, embedding_model="lifecycle-test")
    try:
        store.upsert([VectorRecord(
            chunk_id=chunk_id, material_id=uuid4(), index_version="v1", ordinal=0,
            content="persistent evidence", heading_path=("test",), source_type="builtin",
        )], [[1.0, 0.0, 0.0]])
        assert store.count() == 1
    finally:
        store.close()
    # 不能同进程从 Chroma 的缓存读回来，就把它误认为持久化成功。
    script = """
from pathlib import Path
import sys
from backend.retrieval.vector_store import ChromaVectorStore
s = ChromaVectorStore(persist_directory=Path(sys.argv[1]), embedding_model='lifecycle-test')
try:
    assert s.count() == 1
    hits = s.query([1., 0., 0.], top_k=1)
    assert len(hits) == 1 and str(hits[0].chunk_id) == sys.argv[2]
    assert hits[0].document == 'persistent evidence'
finally:
    s.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), str(chunk_id)],
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr


def test_closing_one_client_preserves_other_client(tmp_path):
    first = ChromaVectorStore(persist_directory=tmp_path, embedding_model="lifecycle-test")
    second = ChromaVectorStore(persist_directory=tmp_path, embedding_model="lifecycle-test")
    try:
        record = VectorRecord(
            chunk_id=uuid4(), material_id=uuid4(), index_version="v1", ordinal=0,
            content="shared evidence", heading_path=(), source_type="builtin",
        )
        first.upsert([record], [[1., 0., 0.]])
        first.close()
        assert second.count() == 1
        assert second.query([1., 0., 0.], top_k=1)[0].chunk_id == record.chunk_id
    finally:
        first.close()
        second.close()
