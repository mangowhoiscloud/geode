"""GatewayPort — Protocol interface for inbound message gateway.

Defines the contract for receiving and routing external messages
to GEODE processing.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GatewayPort(Protocol):
    """Port for inbound message gateway operations."""

    def start(self) -> None:
        """Start all configured pollers."""
        ...

    def stop(self) -> None:
        """Stop all pollers."""
        ...

    def add_binding(self, binding: Any) -> None:
        """Add a channel binding rule (ChannelBinding dataclass)."""
        ...

    def get_stats(self) -> dict[str, Any]:
        """Return gateway routing statistics."""
        ...


# ---------------------------------------------------------------------------
# contextvars injection
# ---------------------------------------------------------------------------

_gateway_ctx: ContextVar[GatewayPort | None] = ContextVar(
    "gateway_port", default=None
)


def set_gateway(gateway: GatewayPort | None) -> None:
    """Set the active gateway for the current context."""
    _gateway_ctx.set(gateway)


def get_gateway() -> GatewayPort | None:
    """Get the active gateway, or None if not set."""
    return _gateway_ctx.get()
