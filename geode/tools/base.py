"""Tool Protocol — defines the interface for all GEODE tools.

Layer 5 component that enables LLM-driven tool use via Anthropic's
tool_use API or autonomous agent patterns.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    """Protocol for GEODE tools.

    Any class implementing these 4 attributes/methods is a valid Tool.
    Uses @runtime_checkable for isinstance() checks.
    """

    @property
    def name(self) -> str:
        """Unique tool name (snake_case)."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description for LLM tool selection."""
        ...

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        ...

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool with given parameters.

        Returns:
            Result dict with at minimum a "result" key.
        """
        ...
