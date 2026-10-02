from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.retrieval import stack
from backend.retrieval.protocols import VectorStoreError


def test_dimension_mismatch_raises_typed_error(monkeypatch):
    monkeypatch.setattr(stack, "SentenceTransformerEmbedder", lambda *a, **kw: SimpleNamespace(dimension=512))
    monkeypatch.setattr(stack, "ChromaVectorStore", lambda **kw: SimpleNamespace(
        assert_model_matches=lambda: None, embedding_dimension=lambda: 384,
    ))
    with pytest.raises(VectorStoreError, match="384.*512"):
        stack.build_retrieval_stack(
            embedding_model="test", reranker_model=None,
            chroma_dir=Path("unused"), model_cache_dir=None,
        )
