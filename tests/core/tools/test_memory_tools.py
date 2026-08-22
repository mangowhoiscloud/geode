"""Tests for Memory Interaction Tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.memory.session import InMemorySessionStore
from core.tools.base import Tool
from core.tools.memory_tools import (
    MemoryGetTool,
    MemorySaveTool,
    MemorySearchTool,
    MemoryToolServices,
    RuleDeleteTool,
    RuleUpdateTool,
)


def _make_store_with_data() -> InMemorySessionStore:
    """Create a session store pre-populated with test data."""
    store = InMemorySessionStore(ttl=3600)
    store.set("session-1", {"subject_id": "Project Atlas", "mode": "full_pipeline", "score": 82.2})
    store.set("session-2", {"subject_id": "Project Orion", "mode": "dry_run", "score": 76.2})
    return store


class TestMemorySearchTool:
    def test_satisfies_protocol(self):
        assert isinstance(MemorySearchTool(), Tool)

    def test_name(self):
        assert MemorySearchTool().name == "memory_search"

    def test_search_finds_matching_session(self):
        store = _make_store_with_data()
        tool = MemorySearchTool(session_store=store)
        result = asyncio.run(tool.aexecute(query="Project Atlas"))
        matches = result["result"]["matches"]
        assert len(matches) >= 1
        assert matches[0]["session_id"] == "session-1"

    def test_search_no_matches(self):
        store = _make_store_with_data()
        tool = MemorySearchTool(session_store=store)
        result = asyncio.run(tool.aexecute(query="nonexistent_ip_xyz"))
        assert result["result"]["total_found"] == 0

    def test_search_respects_limit(self):
        store = _make_store_with_data()
        tool = MemorySearchTool(session_store=store)
        # Both sessions contain "pipeline"
        result = asyncio.run(tool.aexecute(query="pipeline", limit=1))
        assert result["result"]["total_found"] == 1

    def test_search_empty_store(self):
        store = InMemorySessionStore()
        tool = MemorySearchTool(session_store=store)
        result = asyncio.run(tool.aexecute(query="anything"))
        assert result["result"]["total_found"] == 0


class TestMemoryGetTool:
    def test_satisfies_protocol(self):
        assert isinstance(MemoryGetTool(), Tool)

    def test_name(self):
        assert MemoryGetTool().name == "memory_get"

    def test_get_existing_session(self):
        store = _make_store_with_data()
        tool = MemoryGetTool(session_store=store)
        result = asyncio.run(tool.aexecute(session_id="session-1"))
        assert result["result"]["found"] is True
        assert result["result"]["data"]["subject_id"] == "Project Atlas"

    def test_get_nonexistent_session(self):
        store = _make_store_with_data()
        tool = MemoryGetTool(session_store=store)
        result = asyncio.run(tool.aexecute(session_id="session-99"))
        assert result["result"]["found"] is False
        assert result["result"]["data"] is None


class TestMemorySaveTool:
    def test_satisfies_protocol(self):
        assert isinstance(MemorySaveTool(), Tool)

    def test_name(self):
        assert MemorySaveTool().name == "memory_save"

    def test_save_new_session(self):
        store = InMemorySessionStore()
        tool = MemorySaveTool(session_store=store)
        result = asyncio.run(tool.aexecute(session_id="new-session", data={"subject_id": "Test"}))
        assert result["result"]["saved"] is True
        # Verify stored
        assert store.get("new-session") == {"subject_id": "Test"}

    def test_save_merge_mode(self):
        store = InMemorySessionStore()
        store.set("session-x", {"subject_id": "Project Atlas", "score": 80})
        tool = MemorySaveTool(session_store=store)
        result = asyncio.run(tool.aexecute(session_id="session-x", data={"tier": "S"}, merge=True))
        assert result["result"]["merged"] is True
        data = store.get("session-x")
        assert data is not None
        assert data["subject_id"] == "Project Atlas"  # preserved
        assert data["tier"] == "S"  # added

    def test_save_replace_mode(self):
        store = InMemorySessionStore()
        store.set("session-x", {"subject_id": "Project Atlas", "score": 80})
        tool = MemorySaveTool(session_store=store)
        result = asyncio.run(tool.aexecute(session_id="session-x", data={"tier": "S"}, merge=False))
        assert result["result"]["merged"] is False
        data = store.get("session-x")
        assert data is not None
        assert "subject_id" not in data  # replaced, not merged
        assert data["tier"] == "S"

    def test_save_persistent_no_project_memory(self):
        """persistent=True with no ProjectMemory still saves to session."""
        store = InMemorySessionStore()
        tool = MemorySaveTool(session_store=store)
        result = asyncio.run(
            tool.aexecute(
                session_id="no-proj",
                data={"content": "test"},
                persistent=True,
            )
        )
        assert result["result"]["saved"] is True
        assert result["result"]["persistent"] is True
        assert store.get("no-proj") == {"content": "test"}

    def test_save_persistent_writes_to_memory(self, tmp_path: Path):
        from core.memory.project import ProjectMemory

        mem = ProjectMemory(project_root=tmp_path)
        mem.ensure_structure()
        store = InMemorySessionStore()
        tool = MemorySaveTool(services=MemoryToolServices(session_store=store, project_memory=mem))
        result = asyncio.run(
            tool.aexecute(
                session_id="persist-test",
                data={"content": "persistent insight test"},
                persistent=True,
            )
        )
        assert result["result"]["saved"] is True
        assert result["result"]["persistent"] is True
        assert "persistent insight test" in mem.memory_file.read_text()


def _make_project_with_rule(tmp_path: Path):
    """Create a ProjectMemory with a test rule."""
    from core.memory.project import ProjectMemory

    mem = ProjectMemory(project_root=tmp_path)
    mem.ensure_structure()
    mem.create_rule("test-rule", ["*test*"], "# Test Rule\nSome content.")
    return mem


class TestRuleUpdateTool:
    def test_satisfies_protocol(self):
        assert isinstance(RuleUpdateTool(), Tool)

    def test_name(self):
        assert RuleUpdateTool().name == "rule_update"

    def test_no_project_memory(self):
        tool = RuleUpdateTool()
        result = asyncio.run(tool.aexecute(name="x", content="y"))
        assert result["result"]["updated"] is False
        assert "not available" in result["result"]["error"]

    def test_update_existing_rule(self, tmp_path: Path):
        mem = _make_project_with_rule(tmp_path)
        tool = RuleUpdateTool(MemoryToolServices(project_memory=mem))
        result = asyncio.run(tool.aexecute(name="test-rule", content="# Updated Content"))
        assert result["result"]["updated"] is True
        rules = mem.load_rules("*")
        matched = [r for r in rules if r["name"] == "test-rule"]
        assert len(matched) == 1
        assert "Updated Content" in matched[0]["content"]

    def test_update_nonexistent_rule(self, tmp_path: Path):
        from core.memory.project import ProjectMemory

        mem = ProjectMemory(project_root=tmp_path)
        mem.ensure_structure()
        tool = RuleUpdateTool(MemoryToolServices(project_memory=mem))
        result = asyncio.run(tool.aexecute(name="no-such-rule", content="x"))
        assert result["result"]["updated"] is False


class TestRuleDeleteTool:
    def test_satisfies_protocol(self):
        assert isinstance(RuleDeleteTool(), Tool)

    def test_name(self):
        assert RuleDeleteTool().name == "rule_delete"

    def test_no_project_memory(self):
        tool = RuleDeleteTool()
        result = asyncio.run(tool.aexecute(name="x"))
        assert result["result"]["deleted"] is False
        assert "not available" in result["result"]["error"]

    def test_delete_existing_rule(self, tmp_path: Path):
        mem = _make_project_with_rule(tmp_path)
        tool = RuleDeleteTool(MemoryToolServices(project_memory=mem))
        result = asyncio.run(tool.aexecute(name="test-rule"))
        assert result["result"]["deleted"] is True
        names = [r["name"] for r in mem.list_rules()]
        assert "test-rule" not in names

    def test_delete_nonexistent_rule(self, tmp_path: Path):
        from core.memory.project import ProjectMemory

        mem = ProjectMemory(project_root=tmp_path)
        mem.ensure_structure()
        tool = RuleDeleteTool(MemoryToolServices(project_memory=mem))
        result = asyncio.run(tool.aexecute(name="no-such-rule"))
        assert result["result"]["deleted"] is False


class TestSessionStoreContract:
    """Fake-success guards for explicit session-store wiring."""

    def test_save_then_get_roundtrip_via_injected_services(self):
        store = InMemorySessionStore(ttl=3600)
        services = MemoryToolServices(session_store=store)
        save = asyncio.run(
            MemorySaveTool(services=services).aexecute(session_id="rt-1", data={"k": "v"})
        )
        assert save["result"]["saved"] is True
        assert save["result"]["ephemeral"] is False

        got = asyncio.run(MemoryGetTool(services=services).aexecute(session_id="rt-1"))
        assert got["result"]["found"] is True
        assert got["result"]["data"] == {"k": "v"}

    def test_unwired_store_reports_ephemeral_not_saved(self):
        """No injected store must report the per-call fallback honestly."""
        save = asyncio.run(MemorySaveTool().aexecute(session_id="eph-1", data={"k": "v"}))
        assert save["result"]["ephemeral"] is True
        assert save["result"]["saved"] is False

        got = asyncio.run(MemoryGetTool().aexecute(session_id="eph-1"))
        assert got["result"]["found"] is False
        assert got["result"]["ephemeral"] is True

    def test_bootstrap_build_memory_preserves_store_identity(self, tmp_path: Path):
        from unittest.mock import patch

        store = InMemorySessionStore(ttl=3600)
        with patch("core.paths.ensure_directories"):
            from core.wiring.bootstrap import build_memory

            _, _, assembler, _ = build_memory(session_store=store, hooks=None)
        assert assembler._session_store is store
