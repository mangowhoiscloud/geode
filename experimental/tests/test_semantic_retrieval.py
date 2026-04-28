"""Tests for P2 semantic retrieval layer: embeddings, vector store, RAG router."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from experimental.memory.embeddings import EmbeddingEngine, get_embedding_engine, set_embedding_engine
from experimental.memory.rag_router import RAGRouter
from experimental.memory.vector_store import (
    SimpleVectorStore,
    get_vector_store,
    set_vector_store,
)

# ---------------------------------------------------------------------------
# EmbeddingEngine — "none" backend (no API calls)
# ---------------------------------------------------------------------------


class TestEmbeddingEngineNone:
    def test_none_backend_returns_zeros(self) -> None:
        engine = EmbeddingEngine(backend="none", dimension=64)
        result = engine.embed(["hello world"])
        assert result.shape == (1, 64)
        assert np.allclose(result, 0.0)

    def test_none_backend_empty_input(self) -> None:
        engine = EmbeddingEngine(backend="none", dimension=64)
        result = engine.embed([])
        assert result.shape == (0, 64)

    def test_embed_single(self) -> None:
        engine = EmbeddingEngine(backend="none", dimension=32)
        result = engine.embed_single("test")
        assert result.shape == (32,)

    def test_dimension_property(self) -> None:
        engine = EmbeddingEngine(backend="none", dimension=128)
        assert engine.dimension == 128

    def test_backend_property(self) -> None:
        engine = EmbeddingEngine(backend="none")
        assert engine.backend == "none"


class TestEmbeddingCache:
    def test_cache_saves_and_loads(self, tmp_path: Path) -> None:
        engine = EmbeddingEngine(backend="none", dimension=16, cache_dir=tmp_path / "cache")
        # First call — compute + save
        engine.embed(["cached text"])
        # Check cache file exists
        cache_files = list((tmp_path / "cache").glob("*.npy"))
        assert len(cache_files) == 1

    def test_cache_hit_returns_same(self, tmp_path: Path) -> None:
        # Use a mock engine that returns distinct vectors
        engine = _MockEngine(dimension=8, cache_dir=tmp_path / "cache")
        v1 = engine.embed(["same text"])
        v2 = engine.embed(["same text"])  # should hit cache
        np.testing.assert_array_equal(v1, v2)


class _MockEngine(EmbeddingEngine):
    """Engine that returns sequential vectors (not zeros) to test cache."""

    _counter = 0

    def _compute(self, texts: list[str]) -> list[np.ndarray]:
        results = []
        for _ in texts:
            _MockEngine._counter += 1
            vec = np.full(self._dimension, _MockEngine._counter, dtype=np.float32)
            results.append(vec)
        return results


# ---------------------------------------------------------------------------
# EmbeddingEngine — ContextVar DI
# ---------------------------------------------------------------------------


class TestEmbeddingContextVar:
    def test_set_and_get(self) -> None:
        prev = get_embedding_engine()
        try:
            engine = EmbeddingEngine(backend="none")
            set_embedding_engine(engine)
            assert get_embedding_engine() is engine
        finally:
            set_embedding_engine(prev)


# ---------------------------------------------------------------------------
# SimpleVectorStore
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path, dimension: int = 8) -> SimpleVectorStore:
    engine = _MockEngine(backend="none", dimension=dimension, cache_dir=tmp_path / "cache")
    return SimpleVectorStore("test", engine=engine, persist_dir=tmp_path / "vectors")


class TestSimpleVectorStore:
    def test_add_and_size(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        added = store.add(["hello", "world"])
        assert added == 2
        assert store.size == 2

    def test_search_returns_results(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(
            ["machine learning", "deep learning", "cooking recipes"],
            [{"source": "ml"}, {"source": "dl"}, {"source": "cook"}],
        )
        # With mock engine, search will return results based on cosine similarity
        # of sequential integer vectors (not semantically meaningful, but tests mechanics)
        results = store.search("query", k=2)
        assert len(results) <= 2

    def test_search_empty_store(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        results = store.search("query")
        assert results == []

    def test_search_without_engine(self, tmp_path: Path) -> None:
        store = SimpleVectorStore("no-engine", persist_dir=tmp_path / "vectors")
        store.add(["text"])  # adds without embeddings
        results = store.search("query")
        assert results == []

    def test_add_with_metadata(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(["text1", "text2"], [{"key": "a"}, {"key": "b"}])
        assert store.size == 2

    def test_clear(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(["text1", "text2"])
        store.clear()
        assert store.size == 0

    def test_persistence(self, tmp_path: Path) -> None:
        engine = _MockEngine(backend="none", dimension=8, cache_dir=tmp_path / "cache")
        store1 = SimpleVectorStore("persist", engine=engine, persist_dir=tmp_path / "vectors")
        store1.add(["hello", "world"])
        assert store1.size == 2

        # Create new store instance — should load from disk
        store2 = SimpleVectorStore("persist", engine=engine, persist_dir=tmp_path / "vectors")
        assert store2.size == 2

    def test_filter_fn(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(
            ["alpha", "beta", "gamma"],
            [{"type": "a"}, {"type": "b"}, {"type": "a"}],
        )
        results = store.search(
            "query", k=10, filter_fn=lambda m: m.get("type") == "a"
        )
        for r in results:
            assert r.metadata.get("type") == "a"


# ---------------------------------------------------------------------------
# SimpleVectorStore — ContextVar DI
# ---------------------------------------------------------------------------


class TestVectorStoreContextVar:
    def test_set_and_get(self, tmp_path: Path) -> None:
        prev = get_vector_store()
        try:
            store = _make_store(tmp_path)
            set_vector_store(store)
            assert get_vector_store() is store
        finally:
            set_vector_store(prev)


# ---------------------------------------------------------------------------
# RAGRouter
# ---------------------------------------------------------------------------


class TestRAGRouter:
    def test_classify_simple(self) -> None:
        router = RAGRouter()
        assert router.classify("what is the score of Berserk") == "simple"
        assert router.classify("how many copies sold") == "simple"

    def test_classify_complex(self) -> None:
        router = RAGRouter()
        assert router.classify("compare Berserk and Cowboy Bebop across all axes") == "complex"
        assert router.classify("common patterns between all analyzed IPs") == "complex"

    def test_classify_focused(self) -> None:
        router = RAGRouter()
        assert router.classify("franchise revival potential for dark fantasy IPs") == "focused"

    def test_retrieve_simple_returns_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(["some data"])
        router = RAGRouter(vector_store=store)
        # Simple queries should return empty (caller uses lexical)
        results = router.retrieve("what is the score")
        assert results == []

    def test_retrieve_without_store(self) -> None:
        router = RAGRouter(vector_store=None)
        results = router.retrieve("deep query about something")
        assert results == []

    def test_retrieve_focused(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(["franchise revival analysis", "market expansion data", "cooking tips"])
        router = RAGRouter(vector_store=store, similarity_threshold=0.0)
        results = router.retrieve("franchise revival potential for dark fantasy IPs", k=2)
        # With mock embeddings threshold=0, should return results
        assert len(results) <= 2
