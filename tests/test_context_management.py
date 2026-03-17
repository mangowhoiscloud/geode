"""Tests for context management improvements.

Covers:
1. Snapshot auto-GC (threshold-based pruning)
2. Session file persistence (survive restart)
3. Multi-IP LRU result cache
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.automation.snapshot import SnapshotManager
from core.memory.session import InMemorySessionStore

# ---------------------------------------------------------------------------
# 1. Snapshot auto-GC
# ---------------------------------------------------------------------------


class TestSnapshotAutoGC:
    def test_auto_gc_on_capture(self, tmp_path: Path):
        """Snapshot count is pruned when it exceeds auto_gc_threshold."""
        mgr = SnapshotManager(
            storage_dir=tmp_path,
            max_recent=5,
            auto_gc_threshold=10,
        )
        # Capture 12 snapshots → should trigger GC after threshold
        for i in range(12):
            mgr.capture(f"sess-{i}", pipeline_state={"i": i})

        # After GC, count should be <= max_recent (5) + weekly keepers
        remaining = len(mgr.list_snapshots())
        assert remaining <= 10, f"Expected <= 10 after GC, got {remaining}"

    def test_no_gc_under_threshold(self, tmp_path: Path):
        """No pruning when count stays under threshold."""
        mgr = SnapshotManager(
            storage_dir=tmp_path,
            max_recent=5,
            auto_gc_threshold=20,
        )
        for i in range(10):
            mgr.capture(f"sess-{i}", pipeline_state={"i": i})

        assert len(mgr.list_snapshots()) == 10

    def test_gc_disabled_when_zero(self, tmp_path: Path):
        """auto_gc_threshold=0 disables auto-GC."""
        mgr = SnapshotManager(
            storage_dir=tmp_path,
            max_recent=3,
            auto_gc_threshold=0,
        )
        for i in range(10):
            mgr.capture(f"sess-{i}", pipeline_state={"i": i})

        # No auto-GC, all 10 should remain
        assert len(mgr.list_snapshots()) == 10

    def test_startup_gc(self, tmp_path: Path):
        """GC runs on startup if existing files exceed threshold."""
        # Create initial manager with many snapshots
        mgr1 = SnapshotManager(storage_dir=tmp_path, max_recent=5, auto_gc_threshold=0)
        for i in range(15):
            mgr1.capture(f"sess-{i}", pipeline_state={"i": i})

        # New manager with threshold should GC on load
        mgr2 = SnapshotManager(
            storage_dir=tmp_path,
            max_recent=5,
            auto_gc_threshold=10,
        )
        remaining = len(mgr2.list_snapshots())
        assert remaining <= 10


# ---------------------------------------------------------------------------
# 2. Session file persistence
# ---------------------------------------------------------------------------


class TestSessionFilePersistence:
    def test_persist_and_restore(self, tmp_path: Path):
        """Sessions persisted to disk are restored on new store creation."""
        store1 = InMemorySessionStore(ttl=3600, storage_dir=tmp_path)
        store1.set("ip:berserk:analysis", {"tier": "S", "score": 81.3})
        store1.set("ip:cowboy-bebop:analysis", {"tier": "A", "score": 68.4})

        # Simulate restart: new store same dir
        store2 = InMemorySessionStore(ttl=3600, storage_dir=tmp_path)
        data = store2.get("ip:berserk:analysis")
        assert data is not None
        assert data["tier"] == "S"
        assert store2.get("ip:cowboy-bebop:analysis") is not None

    def test_expired_not_restored(self, tmp_path: Path):
        """Expired sessions on disk are cleaned up, not restored."""
        store1 = InMemorySessionStore(ttl=1, storage_dir=tmp_path)
        store1.set("old-session", {"data": "stale"})

        # Manually age the file
        for f in tmp_path.glob("sess-*.json"):
            raw = json.loads(f.read_text())
            raw["created_at"] = 0.0  # very old
            f.write_text(json.dumps(raw))

        store2 = InMemorySessionStore(ttl=1, storage_dir=tmp_path)
        assert store2.get("old-session") is None

    def test_delete_removes_file(self, tmp_path: Path):
        """delete() removes the backing file."""
        store = InMemorySessionStore(ttl=3600, storage_dir=tmp_path)
        store.set("test-sess", {"x": 1})
        assert len(list(tmp_path.glob("sess-*.json"))) == 1

        store.delete("test-sess")
        assert len(list(tmp_path.glob("sess-*.json"))) == 0

    def test_clear_removes_all_files(self, tmp_path: Path):
        """clear() removes all backing files."""
        store = InMemorySessionStore(ttl=3600, storage_dir=tmp_path)
        store.set("a", {"x": 1})
        store.set("b", {"x": 2})
        assert len(list(tmp_path.glob("sess-*.json"))) == 2

        store.clear()
        assert len(list(tmp_path.glob("sess-*.json"))) == 0
        assert store.list_sessions() == []

    def test_no_storage_dir_is_pure_memory(self):
        """Without storage_dir, behaves exactly as before."""
        store = InMemorySessionStore(ttl=3600)
        store.set("s1", {"a": 1})
        assert store.get("s1") == {"a": 1}
        store.delete("s1")
        assert store.get("s1") is None

    def test_checkpoint_persisted(self, tmp_path: Path):
        """Checkpoints are also file-backed."""
        store1 = InMemorySessionStore(ttl=3600, storage_dir=tmp_path)
        store1.save_checkpoint("sess-1", {"step": 3})

        store2 = InMemorySessionStore(ttl=3600, storage_dir=tmp_path)
        cp = store2.load_checkpoint("sess-1")
        assert cp is not None
        assert cp["step"] == 3


# ---------------------------------------------------------------------------
# 3. Multi-IP LRU result cache
# ---------------------------------------------------------------------------


class TestResultCache:
    def test_lru_eviction(self):
        """Cache evicts oldest entry when max_size exceeded."""
        from core.cli import _ResultCache

        cache = _ResultCache(max_size=3)
        cache._cache.clear()  # isolate from disk

        cache.put({"ip_name": "A", "score": 1})
        cache.put({"ip_name": "B", "score": 2})
        cache.put({"ip_name": "C", "score": 3})
        cache.put({"ip_name": "D", "score": 4})

        # A should be evicted
        assert cache.get("A") is None
        assert cache.get("B") is not None
        assert cache.get("D") is not None

    def test_get_moves_to_end(self):
        """Accessing an entry makes it most-recently-used."""
        from core.cli import _ResultCache

        cache = _ResultCache(max_size=3)
        cache._cache.clear()

        cache.put({"ip_name": "X", "score": 1})
        cache.put({"ip_name": "Y", "score": 2})
        cache.put({"ip_name": "Z", "score": 3})

        # Access X → makes it MRU
        cache.get("X")
        # Add new item → Y should be evicted (oldest)
        cache.put({"ip_name": "W", "score": 4})

        assert cache.get("Y") is None
        assert cache.get("X") is not None

    def test_case_insensitive_key(self):
        """Keys are case-insensitive."""
        from core.cli import _ResultCache

        cache = _ResultCache(max_size=5)
        cache._cache.clear()

        cache.put({"ip_name": "Berserk", "score": 81.3})
        assert cache.get("berserk") is not None
        assert cache.get("BERSERK") is not None

    def test_disk_persistence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Cache persists to and loads from disk."""
        from core.cli import _ResultCache

        monkeypatch.setattr("core.cli.result_cache._RESULT_CACHE_DIR", tmp_path)

        cache1 = _ResultCache(max_size=5)
        cache1._cache.clear()
        cache1.put({"ip_name": "TestIP", "score": 99})

        # Verify file exists
        files = list(tmp_path.glob("*.json"))
        assert len(files) >= 1

        # New cache loads from disk
        cache2 = _ResultCache(max_size=5)
        result = cache2.get("testip")
        assert result is not None
        assert result["score"] == 99
