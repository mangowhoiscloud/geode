"""Memory Ports — abstract interfaces for memory stores.

SessionStorePort is the structural type for the explicit session-store
dependency-injection seam. InMemorySessionStore is the only shipped
implementation.

ProjectMemoryPort, OrganizationMemoryPort, UserProfilePort were single-impl
Protocols with no such injection seam and have been removed — use concrete types
directly instead.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionStorePort(Protocol):
    """Port for ephemeral session storage (L2 Session tier).

    Implemented by InMemorySessionStore; typed here so tool services can
    accept any injected conforming store.
    """

    def get(self, session_id: str) -> dict[str, Any] | None: ...

    def set(self, session_id: str, data: dict[str, Any]) -> None: ...

    def delete(self, session_id: str) -> bool: ...

    def exists(self, session_id: str) -> bool: ...

    def list_sessions(self) -> list[str]: ...
