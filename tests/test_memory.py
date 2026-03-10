"""Tests for L2 InMemorySessionStore."""

from unittest.mock import patch

from core.memory.session import InMemorySessionStore, SessionEntry


class TestInMemorySessionStore:
    def test_set_and_get(self):
        store = InMemorySessionStore()
        store.set("s1", {"ip_name": "Berserk", "mode": "full_pipeline"})
        data = store.get("s1")
        assert data is not None
        assert data["ip_name"] == "Berserk"

    def test_get_missing_returns_none(self):
        store = InMemorySessionStore()
        assert store.get("nonexistent") is None

    def test_overwrite(self):
        store = InMemorySessionStore()
        store.set("s1", {"v": 1})
        store.set("s1", {"v": 2})
        assert store.get("s1") == {"v": 2}

    def test_delete(self):
        store = InMemorySessionStore()
        store.set("s1", {"x": 1})
        assert store.delete("s1") is True
        assert store.get("s1") is None

    def test_delete_missing(self):
        store = InMemorySessionStore()
        assert store.delete("nope") is False

    def test_exists(self):
        store = InMemorySessionStore()
        store.set("s1", {"x": 1})
        assert store.exists("s1") is True
        assert store.exists("s2") is False

    def test_clear(self):
        store = InMemorySessionStore()
        store.set("s1", {"a": 1})
        store.set("s2", {"b": 2})
        store.clear()
        assert store.list_sessions() == []

    def test_list_sessions(self):
        store = InMemorySessionStore()
        store.set("a", {})
        store.set("b", {})
        store.set("c", {})
        sessions = store.list_sessions()
        assert sorted(sessions) == ["a", "b", "c"]

    def test_ttl_expiry(self):
        store = InMemorySessionStore(ttl=10.0)
        store.set("s1", {"x": 1})
        # Manually backdate the entry
        entry = store._store["s1"]
        with patch("time.time", return_value=entry.created_at + 11):
            assert store.get("s1") is None

    def test_ttl_not_expired(self):
        store = InMemorySessionStore(ttl=100.0)
        store.set("s1", {"x": 1})
        assert store.get("s1") is not None

    def test_list_sessions_evicts_expired(self):
        store = InMemorySessionStore(ttl=5.0)
        store.set("fresh", {})
        store.set("stale", {})
        # Backdate "stale"
        store._store["stale"].created_at -= 10
        sessions = store.list_sessions()
        assert "stale" not in sessions
        assert "fresh" in sessions

    def test_ttl_property(self):
        store = InMemorySessionStore(ttl=42.0)
        assert store.ttl == 42.0


class TestSessionEntry:
    def test_default_created_at(self):
        entry = SessionEntry(data={"key": "value"})
        assert entry.created_at > 0
        assert entry.data == {"key": "value"}
