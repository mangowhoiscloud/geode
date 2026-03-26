"""Tool System Ports — Protocol interfaces for tool registry and policy.

Defines abstract contracts for ToolRegistry and PolicyChain,
enabling Clean Architecture dependency inversion.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
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
    def to_anthropic_tools_with_defer(
        self,
        *,
        policy: PolicyChainPort | None = None,
        mode: str = "full_pipeline",
        defer_threshold: int = 10,
        mcp_tools: list[dict[str, Any]] | None = None,
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


# ---------------------------------------------------------------------------
# Tool executor contextvar (NOT in state — functions are not serializable)
# ---------------------------------------------------------------------------

ToolExecutorCallable = Callable[..., dict[str, Any]]

_tool_executor_ctx: ContextVar[ToolExecutorCallable | None] = ContextVar(
    "tool_executor", default=None
)


def set_tool_executor(executor: ToolExecutorCallable | None) -> None:
    """Inject tool executor callable (called by GeodeRuntime.create())."""
    _tool_executor_ctx.set(executor)


def get_tool_executor() -> ToolExecutorCallable | None:
    """Get injected tool executor. Returns None if not injected."""
    return _tool_executor_ctx.get()
