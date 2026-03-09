"""Tests for L1 Memory Ports (Protocol interfaces)."""

from geode.infrastructure.ports.memory_port import (
    OrganizationMemoryPort,
    ProjectMemoryPort,
    SessionStorePort,
)
from geode.memory.session import InMemorySessionStore


class TestSessionStorePort:
    def test_inmemory_is_session_store_port(self):
        store = InMemorySessionStore()
        assert isinstance(store, SessionStorePort)

    def test_port_has_required_methods(self):
        assert hasattr(SessionStorePort, "get")
        assert hasattr(SessionStorePort, "set")
        assert hasattr(SessionStorePort, "delete")
        assert hasattr(SessionStorePort, "exists")
        assert hasattr(SessionStorePort, "save_checkpoint")
        assert hasattr(SessionStorePort, "load_checkpoint")


class TestProjectMemoryPort:
    def test_port_has_required_methods(self):
        assert hasattr(ProjectMemoryPort, "load_memory")
        assert hasattr(ProjectMemoryPort, "load_rules")
        assert hasattr(ProjectMemoryPort, "add_insight")
        assert hasattr(ProjectMemoryPort, "get_context_for_ip")


class TestOrganizationMemoryPort:
    def test_port_has_required_methods(self):
        assert hasattr(OrganizationMemoryPort, "get_ip_context")
        assert hasattr(OrganizationMemoryPort, "get_common_rubric")
        assert hasattr(OrganizationMemoryPort, "get_soul")
        assert hasattr(OrganizationMemoryPort, "save_analysis_result")

    def test_port_is_runtime_checkable(self):
        class MockOrg:
            def get_ip_context(self, ip_name: str) -> dict:
                return {}

            def get_common_rubric(self) -> dict:
                return {}

            def get_soul(self) -> str:
                return ""

            def save_analysis_result(self, ip_name: str, result: dict) -> bool:
                return True

        assert isinstance(MockOrg(), OrganizationMemoryPort)
