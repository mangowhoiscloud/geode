"""Tests for L2 Hybrid Session Store (Redis + PostgreSQL simulation)."""

from pathlib import Path
from unittest.mock import patch

from geode.memory.hybrid_session import (
    HybridSessionStore,
    PostgreSQLSessionStore,
    RedisSessionStore,
)


class TestRedisSessionStore:
    def test_set_and_get(self):
        store = RedisSessionStore()
        store.set("s1", {"ip": "Berserk"})
        assert store.get("s1") == {"ip": "Berserk"}

    def test_get_missing(self):
        store = RedisSessionStore()
        assert store.get("nope") is None

    def test_delete(self):
        store = RedisSessionStore()
        store.set("s1", {"a": 1})
        assert store.delete("s1") is True
        assert store.get("s1") is None

    def test_delete_missing(self):
        store = RedisSessionStore()
        assert store.delete("nope") is False

    def test_exists(self):
        store = RedisSessionStore()
        store.set("s1", {})
        assert store.exists("s1") is True
        assert store.exists("s2") is False

    def test_ttl_expiry(self):
        store = RedisSessionStore(ttl_hours=1.0)
        store.set("s1", {"x": 1})
        entry = store._store["s1"]
        with patch("time.time", return_value=entry.created_at + 3601):
            assert store.get("s1") is None

    def test_save_load_checkpoint(self):
        store = RedisSessionStore()
        store.save_checkpoint("s1", {"state": "checkpoint"})
        cp = store.load_checkpoint("s1")
        assert cp == {"state": "checkpoint"}

    def test_load_checkpoint_missing(self):
        store = RedisSessionStore()
        assert store.load_checkpoint("s1") is None


class TestPostgreSQLSessionStore:
    def test_set_and_get(self, tmp_path: Path):
        store = PostgreSQLSessionStore(tmp_path / "pg")
        store.set("s1", {"ip": "Berserk"})
        assert store.get("s1") == {"ip": "Berserk"}

    def test_get_missing(self, tmp_path: Path):
        store = PostgreSQLSessionStore(tmp_path / "pg")
        assert store.get("nope") is None

    def test_delete(self, tmp_path: Path):
        store = PostgreSQLSessionStore(tmp_path / "pg")
        store.set("s1", {"a": 1})
        assert store.delete("s1") is True
        assert store.get("s1") is None

    def test_delete_missing(self, tmp_path: Path):
        store = PostgreSQLSessionStore(tmp_path / "pg")
        assert store.delete("nope") is False

    def test_exists(self, tmp_path: Path):
        store = PostgreSQLSessionStore(tmp_path / "pg")
        store.set("s1", {})
        assert store.exists("s1") is True
        assert store.exists("s2") is False

    def test_save_load_checkpoint(self, tmp_path: Path):
        store = PostgreSQLSessionStore(tmp_path / "pg")
        store.save_checkpoint("s1", {"pipeline": "state"})
        cp = store.load_checkpoint("s1")
        assert cp == {"pipeline": "state"}

    def test_load_checkpoint_missing(self, tmp_path: Path):
        store = PostgreSQLSessionStore(tmp_path / "pg")
        assert store.load_checkpoint("s1") is None


class TestHybridSessionStore:
    def _make_hybrid(self, tmp_path: Path) -> HybridSessionStore:
        l1 = RedisSessionStore(ttl_hours=4.0)
        l2 = PostgreSQLSessionStore(tmp_path / "pg")
        return HybridSessionStore(l1, l2)

    def test_write_through(self, tmp_path: Path):
        hybrid = self._make_hybrid(tmp_path)
        hybrid.set("s1", {"ip": "Berserk"})
        assert hybrid.l1.get("s1") == {"ip": "Berserk"}
        assert hybrid.l2.get("s1") == {"ip": "Berserk"}

    def test_read_l1_hit(self, tmp_path: Path):
        hybrid = self._make_hybrid(tmp_path)
        hybrid.set("s1", {"x": 1})
        assert hybrid.get("s1") == {"x": 1}

    def test_read_l2_fallback(self, tmp_path: Path):
        hybrid = self._make_hybrid(tmp_path)
        # Write directly to L2 only
        hybrid.l2.set("s1", {"from_l2": True})
        data = hybrid.get("s1")
        assert data == {"from_l2": True}
        # Should backfill L1
        assert hybrid.l1.get("s1") == {"from_l2": True}

    def test_read_both_miss(self, tmp_path: Path):
        hybrid = self._make_hybrid(tmp_path)
        assert hybrid.get("nope") is None

    def test_delete_both(self, tmp_path: Path):
        hybrid = self._make_hybrid(tmp_path)
        hybrid.set("s1", {"a": 1})
        assert hybrid.delete("s1") is True
        assert hybrid.l1.get("s1") is None
        assert hybrid.l2.get("s1") is None

    def test_exists(self, tmp_path: Path):
        hybrid = self._make_hybrid(tmp_path)
        hybrid.set("s1", {})
        assert hybrid.exists("s1") is True
        assert hybrid.exists("nope") is False

    def test_checkpoint_write_through(self, tmp_path: Path):
        hybrid = self._make_hybrid(tmp_path)
        hybrid.save_checkpoint("s1", {"state": "saved"})
        assert hybrid.l1.load_checkpoint("s1") == {"state": "saved"}
        assert hybrid.l2.load_checkpoint("s1") == {"state": "saved"}

    def test_checkpoint_l2_fallback(self, tmp_path: Path):
        hybrid = self._make_hybrid(tmp_path)
        hybrid.l2.save_checkpoint("s1", {"from_l2": True})
        cp = hybrid.load_checkpoint("s1")
        assert cp == {"from_l2": True}
