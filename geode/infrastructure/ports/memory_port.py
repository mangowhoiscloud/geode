"""Memory Ports — abstract interfaces for 3-tier memory architecture.

Layer 1 infrastructure ports for Session, Project, and Organization memory.
Defines contracts that concrete adapters implement.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionStorePort(Protocol):
    """Port for ephemeral session storage (L2 Session tier)."""

    def get(self, session_id: str) -> dict[str, Any] | None: ...

    def set(self, session_id: str, data: dict[str, Any]) -> None: ...

    def delete(self, session_id: str) -> bool: ...

    def exists(self, session_id: str) -> bool: ...

    def save_checkpoint(self, session_id: str, checkpoint_data: dict[str, Any]) -> None: ...

    def load_checkpoint(self, session_id: str) -> dict[str, Any] | None: ...


@runtime_checkable
class ProjectMemoryPort(Protocol):
    """Port for project-level persistent memory (L2 Project tier)."""

    def load_memory(self, max_lines: int = 200) -> str: ...

    def load_rules(self, context: str = "*") -> list[dict[str, Any]]: ...

    def add_insight(self, insight: str) -> bool: ...

    def get_context_for_ip(self, ip_name: str) -> dict[str, Any]: ...


@runtime_checkable
class OrganizationMemoryPort(Protocol):
    """Port for organization-level shared memory (L2 Organization tier)."""

    def get_ip_context(self, ip_name: str) -> dict[str, Any]: ...

    def get_common_rubric(self) -> dict[str, Any]: ...

    def save_analysis_result(self, ip_name: str, result: dict[str, Any]) -> bool: ...
