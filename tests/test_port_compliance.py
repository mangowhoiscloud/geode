"""Tests that all concrete implementations satisfy their Port protocols.

Verifies Clean Architecture compliance: every concrete class used in
GeodeRuntime is isinstance-checkable against its corresponding Port.

Note: Only ports with multiple implementations (or kept for DI extensibility)
are tested here. Single-implementation ports have been removed per the
ports-migrate refactor.
"""

from __future__ import annotations

from core.llm.router import LLMClientPort
from core.memory.port import (
    OrganizationMemoryPort,
    ProjectMemoryPort,
    SessionStorePort,
)


class TestExistingPortCompliance:
    """Verify retained ports still pass."""

    def test_in_memory_session_store_satisfies_port(self):
        from core.memory.session import InMemorySessionStore

        assert isinstance(InMemorySessionStore(), SessionStorePort)

    def test_project_memory_satisfies_port(self):
        from core.memory.project import ProjectMemory

        assert isinstance(ProjectMemory(), ProjectMemoryPort)

    def test_organization_memory_satisfies_port(self):
        from core.memory.organization import MonoLakeOrganizationMemory

        assert isinstance(MonoLakeOrganizationMemory(), OrganizationMemoryPort)

    def test_claude_adapter_satisfies_port(self):
        from core.llm.router import ClaudeAdapter

        assert isinstance(ClaudeAdapter(), LLMClientPort)
