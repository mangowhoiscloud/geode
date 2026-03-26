"""Tests that concrete implementations satisfy their Port protocols.

Only ports with multiple implementations are tested here.
Single-implementation Protocols (ProjectMemoryPort, OrganizationMemoryPort,
UserProfilePort) have been removed — use concrete types directly.
"""

from __future__ import annotations

from core.llm.router import LLMClientPort
from core.memory.port import SessionStorePort


class TestExistingPortCompliance:
    """Verify retained ports still pass."""

    def test_in_memory_session_store_satisfies_port(self):
        from core.memory.session import InMemorySessionStore

        assert isinstance(InMemorySessionStore(), SessionStorePort)

    def test_claude_adapter_satisfies_port(self):
        from core.llm.router import ClaudeAdapter

        assert isinstance(ClaudeAdapter(), LLMClientPort)
