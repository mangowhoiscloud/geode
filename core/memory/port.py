"""Memory Ports — abstract interfaces for memory stores with multiple implementations.

SessionStorePort is kept because HybridSessionStore combines two different
concrete stores (l1/l2), requiring a structural type for the parameter.

ProjectMemoryPort, OrganizationMemoryPort, UserProfilePort were single-impl
Protocols and have been removed — use concrete types directly instead.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionStorePort(Protocol):
    """Port for ephemeral session storage (L2 Session tier).

    Multiple implementations: InMemorySessionStore, _RedisLikeStore,
    _FileStore, HybridSessionStore (combines l1+l2).
    """

    def get(self, session_id: str) -> dict[str, Any] | None: ...

    def set(self, session_id: str, data: dict[str, Any]) -> None: ...

    def delete(self, session_id: str) -> bool: ...

    def exists(self, session_id: str) -> bool: ...

    def list_sessions(self) -> list[str]: ...

    def save_checkpoint(self, session_id: str, checkpoint_data: dict[str, Any]) -> None: ...

    def load_checkpoint(self, session_id: str) -> dict[str, Any] | None: ...
