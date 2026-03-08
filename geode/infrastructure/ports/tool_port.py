"""Tool System Ports — Protocol interfaces for tool registry and policy.

Defines abstract contracts for ToolRegistry and PolicyChain,
enabling Clean Architecture dependency inversion.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PolicyChainPort(Protocol):
    """Protocol for tool access policy chain."""

    def add_policy(self, policy: Any) -> None: ...
    def remove_policy(self, name: str) -> bool: ...
    def filter_tools(self, tool_names: list[str], *, mode: str = "full_pipeline") -> list[str]: ...
    def is_allowed(self, tool_name: str, *, mode: str = "full_pipeline") -> bool: ...
    def list_policies(self) -> list[str]: ...
    def clear(self) -> None: ...


@runtime_checkable
class ToolRegistryPort(Protocol):
    """Protocol for tool registry.

    Implementations: ToolRegistry.
    """

    def register(self, tool: Any) -> None: ...
    def get(self, name: str) -> Any | None: ...
    def list_tools(
        self,
        *,
        policy: PolicyChainPort | None = None,
        mode: str = "full_pipeline",
    ) -> list[str]: ...
    def to_anthropic_tools(
        self,
        *,
        policy: PolicyChainPort | None = None,
        mode: str = "full_pipeline",
    ) -> list[dict[str, Any]]: ...
    def to_openai_tools(
        self,
        *,
        policy: PolicyChainPort | None = None,
        mode: str = "full_pipeline",
    ) -> list[dict[str, Any]]: ...
    def execute(
        self,
        name: str,
        *,
        policy: PolicyChainPort | None = None,
        mode: str = "full_pipeline",
        **kwargs: Any,
    ) -> dict[str, Any]: ...
    def __len__(self) -> int: ...
    def __contains__(self, name: str) -> bool: ...
