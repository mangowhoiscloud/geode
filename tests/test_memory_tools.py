"""Tests for Memory Interaction Tools."""

from __future__ import annotations

from pathlib import Path

from geode.memory.session import InMemorySessionStore
from geode.tools.base import Tool
from geode.tools.memory_tools import (
    MemoryGetTool,
    MemorySaveTool,
    MemorySearchTool,
    RuleDeleteTool,
    RuleUpdateTool,
    set_project_memory,
)


def _make_store_with_data() -> InMemorySessionStore:
    """Create a session store pre-populated with test data."""
    store = InMemorySessionStore(ttl=3600)
    store.set("session-1", {"ip_name": "Berserk", "mode": "full_pipeline", "score": 82.2})
    store.set("session-2", {"ip_name": "Cowboy Bebop", "mode": "dry_run", "score": 76.2})
    return store


class TestMemorySearchTool:
    def test_satisfies_protocol(self):
        assert isinstance(MemorySearchTool(), Tool)

    def test_name(self):
        assert MemorySearchTool().name == "memory_search"

    def test_search_finds_matching_session(self):
        store = _make_store_with_data()
        tool = MemorySearchTool(session_store=store)
        result = tool.execute(query="Berserk")
        matches = result["result"]["matches"]
        assert len(matches) >= 1
        assert matches[0]["session_id"] == "session-1"

    def test_search_no_matches(self):
        store = _make_store_with_data()
        tool = MemorySearchTool(session_store=store)
        result = tool.execute(query="nonexistent_ip_xyz")
        assert result["result"]["total_found"] == 0

    def test_search_respects_limit(self):
        store = _make_store_with_data()
        tool = MemorySearchTool(session_store=store)
        # Both sessions contain "pipeline"
        result = tool.execute(query="pipeline", limit=1)
        assert result["result"]["total_found"] == 1

    def test_search_empty_store(self):
        store = InMemorySessionStore()
        tool = MemorySearchTool(session_store=store)
        result = tool.execute(query="anything")
        assert result["result"]["total_found"] == 0


class TestMemoryGetTool:
    def test_satisfies_protocol(self):
        assert isinstance(MemoryGetTool(), Tool)

    def test_name(self):
        assert MemoryGetTool().name == "memory_get"

    def test_get_existing_session(self):
        store = _make_store_with_data()
        tool = MemoryGetTool(session_store=store)
        result = tool.execute(session_id="session-1")
        assert result["result"]["found"] is True
        assert result["result"]["data"]["ip_name"] == "Berserk"

    def test_get_nonexistent_session(self):
        store = _make_store_with_data()
        tool = MemoryGetTool(session_store=store)
        result = tool.execute(session_id="session-99")
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
        result = tool.execute(session_id="new-session", data={"ip_name": "Test"})
        assert result["result"]["saved"] is True
        # Verify stored
        assert store.get("new-session") == {"ip_name": "Test"}

    def test_save_merge_mode(self):
        store = InMemorySessionStore()
        store.set("session-x", {"ip_name": "Berserk", "score": 80})
        tool = MemorySaveTool(session_store=store)
        result = tool.execute(session_id="session-x", data={"tier": "S"}, merge=True)
        assert result["result"]["merged"] is True
        data = store.get("session-x")
        assert data is not None
        assert data["ip_name"] == "Berserk"  # preserved
        assert data["tier"] == "S"  # added

    def test_save_replace_mode(self):
        store = InMemorySessionStore()
        store.set("session-x", {"ip_name": "Berserk", "score": 80})
        tool = MemorySaveTool(session_store=store)
        result = tool.execute(session_id="session-x", data={"tier": "S"}, merge=False)
        assert result["result"]["merged"] is False
        data = store.get("session-x")
        assert data is not None
        assert "ip_name" not in data  # replaced, not merged
        assert data["tier"] == "S"

    def test_save_persistent_no_project_memory(self):
        """persistent=True with no ProjectMemory still saves to session."""
        set_project_memory(None)
        store = InMemorySessionStore()
        tool = MemorySaveTool(session_store=store)
        result = tool.execute(
            session_id="no-proj",
            data={"content": "test"},
            persistent=True,
        )
        assert result["result"]["saved"] is True
        assert result["result"]["persistent"] is True
        assert store.get("no-proj") == {"content": "test"}

    def test_save_persistent_writes_to_memory(self, tmp_path: Path):
        from geode.memory.project import ProjectMemory

        mem = ProjectMemory(project_root=tmp_path)
        mem.ensure_structure()
        set_project_memory(mem)
        try:
            store = InMemorySessionStore()
            tool = MemorySaveTool(session_store=store)
            result = tool.execute(
                session_id="persist-test",
                data={"content": "persistent insight test"},
                persistent=True,
            )
            assert result["result"]["saved"] is True
            assert result["result"]["persistent"] is True
            # Verify written to MEMORY.md
            content = mem.memory_file.read_text()
            assert "persistent insight test" in content
        finally:
            set_project_memory(None)


def _make_project_with_rule(tmp_path: Path):
    """Create a ProjectMemory with a test rule."""
    from geode.memory.project import ProjectMemory

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
        set_project_memory(None)
        tool = RuleUpdateTool()
        result = tool.execute(name="x", content="y")
        assert result["result"]["updated"] is False
        assert "not available" in result["result"]["error"]

    def test_update_existing_rule(self, tmp_path: Path):
        mem = _make_project_with_rule(tmp_path)
        set_project_memory(mem)
        try:
            tool = RuleUpdateTool()
            result = tool.execute(name="test-rule", content="# Updated Content")
            assert result["result"]["updated"] is True
            # Verify content updated
            rules = mem.load_rules("*")
            matched = [r for r in rules if r["name"] == "test-rule"]
            assert len(matched) == 1
            assert "Updated Content" in matched[0]["content"]
        finally:
            set_project_memory(None)

    def test_update_nonexistent_rule(self, tmp_path: Path):
        from geode.memory.project import ProjectMemory

        mem = ProjectMemory(project_root=tmp_path)
        mem.ensure_structure()
        set_project_memory(mem)
        try:
            tool = RuleUpdateTool()
            result = tool.execute(name="no-such-rule", content="x")
            assert result["result"]["updated"] is False
        finally:
            set_project_memory(None)


class TestRuleDeleteTool:
    def test_satisfies_protocol(self):
        assert isinstance(RuleDeleteTool(), Tool)

    def test_name(self):
        assert RuleDeleteTool().name == "rule_delete"

    def test_no_project_memory(self):
        set_project_memory(None)
        tool = RuleDeleteTool()
        result = tool.execute(name="x")
        assert result["result"]["deleted"] is False
        assert "not available" in result["result"]["error"]

    def test_delete_existing_rule(self, tmp_path: Path):
        mem = _make_project_with_rule(tmp_path)
        set_project_memory(mem)
        try:
            tool = RuleDeleteTool()
            result = tool.execute(name="test-rule")
            assert result["result"]["deleted"] is True
            # Verify deleted
            rules = mem.list_rules()
            names = [r["name"] for r in rules]
            assert "test-rule" not in names
        finally:
            set_project_memory(None)

    def test_delete_nonexistent_rule(self, tmp_path: Path):
        from geode.memory.project import ProjectMemory

        mem = ProjectMemory(project_root=tmp_path)
        mem.ensure_structure()
        set_project_memory(mem)
        try:
            tool = RuleDeleteTool()
            result = tool.execute(name="no-such-rule")
            assert result["result"]["deleted"] is False
        finally:
            set_project_memory(None)
