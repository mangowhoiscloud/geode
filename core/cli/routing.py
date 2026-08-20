"""Compatibility re-exports for the neutral slash-routing contract."""

from core.slash_routing import (
    COMMAND_REGISTRY,
    CommandSpec,
    RunLocation,
    compose_command_registry,
    is_thin,
    lookup,
)

__all__ = [
    "COMMAND_REGISTRY",
    "CommandSpec",
    "RunLocation",
    "compose_command_registry",
    "is_thin",
    "lookup",
]
