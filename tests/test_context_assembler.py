"""Tests for L2 Context Assembler (3-tier memory merge)."""

from unittest.mock import patch

from geode.memory.context import ContextAssembler
from geode.memory.organization import MonoLakeOrganizationMemory
from geode.memory.project import ProjectMemory
from geode.memory.session import InMemorySessionStore


class TestContextAssembler:
    def test_assemble_empty(self):
        assembler = ContextAssembler()
        ctx = assembler.assemble("sess-1", "Berserk")
        assert ctx["_session_id"] == "sess-1"
        assert ctx["_ip_name"] == "Berserk"

    def test_assemble_with_org(self):
        org = MonoLakeOrganizationMemory()
        assembler = ContextAssembler(organization_memory=org)
        ctx = assembler.assemble("sess-1", "Berserk")
        assert ctx.get("_org_loaded") is True
        assert "ip_info" in ctx

    def test_assemble_with_session(self):
        store = InMemorySessionStore()
        store.set("sess-1", {"custom_key": "value"})
        assembler = ContextAssembler(session_store=store)
        ctx = assembler.assemble("sess-1", "Berserk")
        assert ctx.get("_session_loaded") is True
        assert ctx["custom_key"] == "value"

    def test_session_overrides_org(self):
        org = MonoLakeOrganizationMemory()
        store = InMemorySessionStore()
        store.set("sess-1", {"ip_info": {"ip_name": "Custom"}})
        assembler = ContextAssembler(
            organization_memory=org,
            session_store=store,
        )
        ctx = assembler.assemble("sess-1", "Berserk")
        # Session should override org
        assert ctx["ip_info"]["ip_name"] == "Custom"

    def test_assemble_with_project(self, tmp_path):
        pm = ProjectMemory(tmp_path)
        pm.ensure_structure()
        assembler = ContextAssembler(project_memory=pm)
        ctx = assembler.assemble("sess-1", "Berserk")
        assert ctx.get("_project_loaded") is True
        assert "memory" in ctx

    def test_is_data_fresh_before_assembly(self):
        assembler = ContextAssembler()
        assert assembler.is_data_fresh() is False

    def test_is_data_fresh_after_assembly(self):
        assembler = ContextAssembler(freshness_threshold_s=3600.0)
        ctx = assembler.assemble("s1", "Berserk")
        assembler.mark_assembled(ctx.get("_assembled_at"))
        assert assembler.is_data_fresh() is True

    def test_mark_assembled_separate_from_query(self):
        """Verify assemble() is a pure query; mark_assembled() is the command."""
        assembler = ContextAssembler(freshness_threshold_s=3600.0)
        assembler.assemble("s1", "Berserk")
        # assemble() alone should NOT update freshness (CQRS separation)
        assert assembler.is_data_fresh() is False
        # mark_assembled() is the explicit command
        assembler.mark_assembled()
        assert assembler.is_data_fresh() is True

    def test_is_data_stale(self):
        assembler = ContextAssembler(freshness_threshold_s=10.0)
        ctx = assembler.assemble("s1", "Berserk")
        assembler.mark_assembled(ctx.get("_assembled_at"))
        with patch("time.time", return_value=assembler._last_assembly_time + 20):
            assert assembler.is_data_fresh() is False
