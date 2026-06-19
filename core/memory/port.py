"""Memory Ports — abstract interfaces for memory stores.

SessionStorePort is kept as the structural type for the session-store
dependency-injection seam: `core.tools.memory_tools` holds the active store in a
ContextVar and lets callers inject any conforming store via
`set_default_session_store`, so the tools layer types against the Protocol rather
than a concrete class. InMemorySessionStore is the only shipped implementation.

ProjectMemoryPort, OrganizationMemoryPort, UserProfilePort were single-impl
Protocols with no such injection seam and have been removed — use concrete types
directly instead.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionStorePort(Protocol):
    """Port for ephemeral session storage (L2 Session tier).

    Implemented by InMemorySessionStore; typed here as a Protocol so the
    session-store ContextVar in `core.tools.memory_tools` can accept any
    injected conforming store.
    """

    def get(self, session_id: str) -> dict[str, Any] | None: ...

    def set(self, session_id: str, data: dict[str, Any]) -> None: ...

    def delete(self, session_id: str) -> bool: ...

    def exists(self, session_id: str) -> bool: ...

    def list_sessions(self) -> list[str]: ...

    def save_checkpoint(self, session_id: str, checkpoint_data: dict[str, Any]) -> None: ...

    def load_checkpoint(self, session_id: str) -> dict[str, Any] | None: ...
