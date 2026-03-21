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

    def list_sessions(self) -> list[str]: ...

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

    def get_soul(self) -> str: ...

    def save_analysis_result(self, ip_name: str, result: dict[str, Any]) -> bool: ...


@runtime_checkable
class UserProfilePort(Protocol):
    """Port for persistent user profile (Tier 0.5 — between SOUL and Organization).

    Stores user identity, preferences, and auto-learned patterns across sessions.
    Global (~/.geode/user_profile/) with project-local override (.geode/user_profile/).
    """

    def load_profile(self) -> dict[str, Any]: ...

    def save_profile(self, data: dict[str, Any]) -> bool: ...

    def get_preference(self, key: str, default: Any = None) -> Any: ...

    def set_preference(self, key: str, value: Any) -> bool: ...

    def add_learned_pattern(self, pattern: str, category: str = "general") -> bool: ...

    def get_learned_patterns(self, category: str | None = None) -> list[str]: ...

    def get_context_summary(self) -> str: ...

    def load_career(self) -> dict[str, Any]: ...

    def exists(self) -> bool: ...
