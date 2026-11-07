from pathlib import Path
from types import SimpleNamespace
import builtins
import importlib.machinery
import threading

import pytest

from backend.retrieval import stack
from backend.retrieval.protocols import VectorStoreError
from backend.retrieval.embedding import SentenceTransformerEmbedder


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


def test_embedder_probe_checks_installation_without_importing_heavy_package(monkeypatch):
    import backend.retrieval.embedding as embedding

    monkeypatch.setattr(
        embedding.importlib.util,
        "find_spec",
        lambda name: importlib.machinery.ModuleSpec(name, loader=None),
    )
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise AssertionError("startup probe must not import sentence_transformers")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    embedder = SentenceTransformerEmbedder("test-model")

    assert embedder.probe() is None
    assert embedder.loaded_dimension is None


def test_embedder_probe_reports_missing_optional_package_without_import(monkeypatch):
    import backend.retrieval.embedding as embedding

    monkeypatch.setattr(embedding.importlib.util, "find_spec", lambda _name: None)
    embedder = SentenceTransformerEmbedder("test-model")

    assert embedder.probe() == "missing_dependency:ModuleNotFoundError"
    assert embedder.loaded_dimension is None


def test_runtime_import_probe_is_async_and_reports_import_failure(monkeypatch):
    import backend.retrieval.embedding as embedding

    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    result = []

    def slow_broken_import(name):
        assert name == "sentence_transformers"
        entered.set()
        assert release.wait(timeout=2)
        raise RuntimeError("native dependency load failed")

    monkeypatch.setattr(embedding.importlib, "import_module", slow_broken_import)
    embedder = SentenceTransformerEmbedder("test-model")
    thread = embedder.probe_runtime_async(lambda reason: (result.append(reason), completed.set()))

    assert thread.daemon is True
    assert entered.wait(timeout=1)
    assert completed.is_set() is False
    release.set()
    assert completed.wait(timeout=1)
    thread.join(timeout=1)
    assert result == ["dependency_import_failed:RuntimeError"]


def test_stack_remains_not_ready_until_async_runtime_probe_completes(monkeypatch):
    class AsyncEmbedder:
        loaded_dimension = None

        def __init__(self, *args, **kwargs):
            self.callback = None

        @property
        def dimension(self):
            raise AssertionError("cold stack initialization must not load model weights")

        def probe(self):
            return None

        def probe_runtime_async(self, callback):
            self.callback = callback

    class Store:
        def __init__(self, **kwargs):
            pass

        def assert_model_matches(self):
            pass

        def embedding_dimension(self):
            return None

    monkeypatch.setattr(stack, "SentenceTransformerEmbedder", AsyncEmbedder)
    monkeypatch.setattr(stack, "ChromaVectorStore", Store)
    result = stack.build_retrieval_stack(
        embedding_model="test", reranker_model=None,
        chroma_dir=Path("unused"), model_cache_dir=None,
    )

    assert result.availability_snapshot() == (False, "dependency_probe_pending")
    result.embedder.callback("dependency_import_failed:RuntimeError")
    assert result.availability_snapshot() == (False, "dependency_import_failed:RuntimeError")
    result.embedder.callback(None)
    assert result.availability_snapshot() == (True, None)
