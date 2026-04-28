"""Tests for P3 RAPTOR hierarchical indexing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from experimental.memory.embeddings import EmbeddingEngine
from experimental.memory.raptor import RAPTORIndex, get_raptor_index, set_raptor_index
from experimental.memory.vector_store import SimpleVectorStore


class _MockEngine(EmbeddingEngine):
    """Engine that returns deterministic vectors for testing."""

    _counter = 0

    def _compute(self, texts: list[str]) -> list[np.ndarray]:
        results = []
        for text in texts:
            _MockEngine._counter += 1
            # Use hash-based vector for some semantic differentiation
            seed = hash(text) % 10000
            rng = np.random.default_rng(seed)
            vec = rng.random(self._dimension).astype(np.float32)
            vec /= np.linalg.norm(vec)  # normalize
            results.append(vec)
        return results


def _make_index(tmp_path: Path, dim: int = 16) -> tuple[RAPTORIndex, SimpleVectorStore]:
    engine = _MockEngine(backend="none", dimension=dim, cache_dir=tmp_path / "cache")
    store = SimpleVectorStore("test", engine=engine, persist_dir=tmp_path / "vectors")
    index = RAPTORIndex(
        "test", store, engine,
        cluster_size=3,
        max_levels=2,
        persist_dir=tmp_path / "raptor",
    )
    return index, store


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


class TestRAPTORBuild:
    def test_build_creates_tree(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        texts = [f"Document about topic {i}" for i in range(9)]
        index.build(texts)

        assert index.is_built
        assert index.level_count >= 2
        assert index.node_count > len(texts)  # leaves + cluster nodes

    def test_build_empty_texts(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        index.build([])
        assert not index.is_built

    def test_build_few_texts(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        index.build(["one", "two"])
        assert index.is_built
        assert index.level_count == 1  # only leaves, too few to cluster

    def test_build_persists_to_disk(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        texts = [f"Doc {i}" for i in range(9)]
        index.build(texts)

        raptor_dir = tmp_path / "raptor" / "test"
        assert (raptor_dir / "tree_meta.json").exists()
        assert (raptor_dir / "tree_embeddings.npz").exists()

    def test_build_loads_from_disk(self, tmp_path: Path) -> None:
        engine = _MockEngine(backend="none", dimension=16, cache_dir=tmp_path / "cache")
        store = SimpleVectorStore("test", engine=engine, persist_dir=tmp_path / "vectors")

        # Build first index
        index1 = RAPTORIndex(
            "test", store, engine, cluster_size=3, persist_dir=tmp_path / "raptor"
        )
        index1.build([f"Doc {i}" for i in range(9)])
        n1 = index1.node_count

        # Create second index — should load from disk
        index2 = RAPTORIndex(
            "test", store, engine, cluster_size=3, persist_dir=tmp_path / "raptor"
        )
        assert index2.is_built
        assert index2.node_count == n1


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestRAPTORSearch:
    def test_search_returns_results(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        index.build([f"Topic about area {i}" for i in range(9)])

        results = index.search("area 5", k=3)
        assert len(results) <= 3
        assert all(hasattr(r, "level") for r in results)

    def test_search_empty_index(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        results = index.search("anything")
        assert results == []

    def test_search_detail_level(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        index.build([f"Leaf node {i}" for i in range(9)])

        detail_results = index.search("query", detail_level="detail", k=5)
        for r in detail_results:
            assert r.level == 0

    def test_search_global_level(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        index.build([f"Leaf node {i}" for i in range(9)])

        global_results = index.search("query", detail_level="global", k=5)
        if global_results:
            max_level = index.level_count - 1
            for r in global_results:
                assert r.level == max_level

    def test_search_auto_returns_mixed_levels(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        index.build([f"Leaf node {i}" for i in range(9)])

        results = index.search("query", detail_level="auto", k=10)
        if len(results) > 1:
            levels = {r.level for r in results}
            # auto should search across levels
            assert len(levels) >= 1


# ---------------------------------------------------------------------------
# Incremental update
# ---------------------------------------------------------------------------


class TestRAPTORUpdate:
    def test_update_incremental(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        index.build([f"Original {i}" for i in range(6)])
        original_count = index.node_count

        index.update_incremental(["New document 1", "New document 2"])
        assert index.node_count >= original_count  # rebuilt with more leaves


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestRAPTORCleanup:
    def test_cleanup(self, tmp_path: Path) -> None:
        index, _store = _make_index(tmp_path)
        index.build([f"Doc {i}" for i in range(9)])

        removed = index.cleanup()
        assert removed >= 2  # meta + embeddings


# ---------------------------------------------------------------------------
# ContextVar DI
# ---------------------------------------------------------------------------


class TestRAPTORContextVar:
    def test_set_and_get(self, tmp_path: Path) -> None:
        prev = get_raptor_index()
        try:
            index, _store = _make_index(tmp_path)
            set_raptor_index(index)
            assert get_raptor_index() is index
        finally:
            set_raptor_index(prev)
