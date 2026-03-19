"""Tests for GAP 6: AgentMemoryStore (sub-agent isolated memory)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from core.memory.agent_memory import AgentMemoryStore


class TestAgentMemoryStoreCRUD:
    """Basic save/get/list/clear operations."""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> AgentMemoryStore:
        return AgentMemoryStore("task-1", base_dir=tmp_path / "agent-memory")

    def test_save_and_get(self, store: AgentMemoryStore) -> None:
        store.save("findings", "Berserk is S-tier")
        assert store.get("findings") == "Berserk is S-tier"

    def test_get_nonexistent_returns_none(self, store: AgentMemoryStore) -> None:
        assert store.get("nonexistent") is None

    def test_overwrite(self, store: AgentMemoryStore) -> None:
        store.save("key", "v1")
        store.save("key", "v2")
        assert store.get("key") == "v2"

    def test_list_keys(self, store: AgentMemoryStore) -> None:
        store.save("alpha", "a")
        store.save("beta", "b")
        keys = store.list_keys()
        assert keys == ["alpha", "beta"]

    def test_list_keys_empty(self, store: AgentMemoryStore) -> None:
        assert store.list_keys() == []

    def test_clear(self, store: AgentMemoryStore) -> None:
        store.save("key", "value")
        store.clear()
        assert store.get("key") is None
        assert store.list_keys() == []

    def test_task_id_property(self, store: AgentMemoryStore) -> None:
        assert store.task_id == "task-1"

    def test_task_dir_isolation(self, tmp_path: Path) -> None:
        """Different task IDs use different directories."""
        base = tmp_path / "mem"
        s1 = AgentMemoryStore("t1", base_dir=base)
        s2 = AgentMemoryStore("t2", base_dir=base)
        s1.save("k", "from t1")
        s2.save("k", "from t2")
        assert s1.get("k") == "from t1"
        assert s2.get("k") == "from t2"


class TestAgentMemoryTTL:
    """TTL expiry behavior."""

    def test_expired_returns_none(self, tmp_path: Path) -> None:
        store = AgentMemoryStore("task-ttl", base_dir=tmp_path, ttl_hours=0.001)
        # Write a file with old timestamp
        task_dir = tmp_path / "task-ttl"
        task_dir.mkdir(parents=True)
        entry = {"value": "old data", "created_at": time.time() - 3600, "task_id": "task-ttl"}
        (task_dir / "old.json").write_text(json.dumps(entry), encoding="utf-8")
        assert store.get("old") is None

    def test_non_expired_returns_value(self, tmp_path: Path) -> None:
        store = AgentMemoryStore("task-ttl", base_dir=tmp_path, ttl_hours=24.0)
        store.save("fresh", "new data")
        assert store.get("fresh") == "new data"


class TestAgentMemoryCleanup:
    """Class-level cleanup of expired task directories."""

    def test_cleanup_removes_old(self, tmp_path: Path) -> None:
        base = tmp_path / "agent-memory"
        # Create an old task
        old_task = base / "old-task"
        old_task.mkdir(parents=True)
        entry = {"value": "x", "created_at": time.time() - (100 * 3600), "task_id": "old-task"}
        (old_task / "k.json").write_text(json.dumps(entry), encoding="utf-8")

        # Create a recent task
        new_store = AgentMemoryStore("new-task", base_dir=base)
        new_store.save("k", "fresh")

        removed = AgentMemoryStore.cleanup_expired(base_dir=base, ttl_hours=72)
        assert removed == 1
        assert not old_task.exists()
        assert new_store.get("k") == "fresh"

    def test_cleanup_no_dir(self, tmp_path: Path) -> None:
        removed = AgentMemoryStore.cleanup_expired(
            base_dir=tmp_path / "nonexistent",
            ttl_hours=24,
        )
        assert removed == 0
