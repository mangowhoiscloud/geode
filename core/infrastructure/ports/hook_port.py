"""Hook System Port — abstract interface for event-driven hook system.

Defines the contract that HookSystem implements, allowing automation
components to depend on the abstraction rather than the concrete class.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HookSystemPort(Protocol):
    """Port for the event-driven hook system."""

    def trigger(self, event: Enum, data: dict[str, Any]) -> None: ...

    def register(
        self,
        event: Enum,
        handler: Callable[..., Any],
        *,
        name: str = "",
        priority: int = 50,
    ) -> None: ...

    def unregister(self, event: Enum, name: str) -> bool: ...
