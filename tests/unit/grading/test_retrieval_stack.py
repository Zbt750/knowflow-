from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.retrieval import stack
from backend.retrieval.protocols import VectorStoreError


def test_dimension_mismatch_raises_typed_error(monkeypatch):
    class LoadedEmbedder:
        loaded_dimension = 512

        def __init__(self, *args, **kwargs):
            pass

        @property
        def dimension(self):
            return self.loaded_dimension

    monkeypatch.setattr(stack, "SentenceTransformerEmbedder", LoadedEmbedder)
    monkeypatch.setattr(stack, "ChromaVectorStore", lambda **kw: SimpleNamespace(
        assert_model_matches=lambda: None, embedding_dimension=lambda: 384,
    ))
    with pytest.raises(VectorStoreError, match="384.*512"):
        stack.build_retrieval_stack(
            embedding_model="test", reranker_model=None,
            chroma_dir=Path("unused"), model_cache_dir=None,
        )


def test_stack_build_does_not_read_dimension_from_uninitialized_model(monkeypatch):
    class LazyEmbedder:
        loaded_dimension = None

        def __init__(self, *args, **kwargs):
            pass

        @property
        def dimension(self):
            raise AssertionError("cold stack initialization must not load model weights")

        def probe(self):
            return "missing_dependency:ImportError"

    class Store:
        def __init__(self, **kwargs):
            pass

        def assert_model_matches(self):
            pass

        def embedding_dimension(self):
            return 384

    monkeypatch.setattr(stack, "SentenceTransformerEmbedder", LazyEmbedder)
    monkeypatch.setattr(stack, "ChromaVectorStore", Store)

    result = stack.build_retrieval_stack(
        embedding_model="test", reranker_model=None,
        chroma_dir=Path("unused"), model_cache_dir=None,
    )

    assert result.available is False
    assert result.unavailable_reason == "missing_dependency:ImportError"
