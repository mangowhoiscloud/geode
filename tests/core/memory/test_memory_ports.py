"""Tests for L1 Memory Ports (SessionStorePort — multi-impl Protocol)."""

from core.memory.port import SessionStorePort
from core.memory.session import InMemorySessionStore


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
