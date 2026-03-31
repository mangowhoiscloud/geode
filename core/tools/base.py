"""Tool Protocol — defines the interface for all GEODE tools.

Layer 5 component that enables LLM-driven tool use via Anthropic's
tool_use API or autonomous agent patterns.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

# Valid values for tool metadata fields.
VALID_CATEGORIES = frozenset(
    {
        "discovery",
        "analysis",
        "memory",
        "planning",
        "external",
        "model",
        "data",
        "scheduling",
        "profile",
        "notification",
        "calendar",
        "task",
    }
)

VALID_COST_TIERS = frozenset({"free", "cheap", "expensive"})


@runtime_checkable
class Tool(Protocol):
    """Protocol for GEODE tools.

    Any class implementing these 4 attributes/methods is a valid Tool.
    Uses @runtime_checkable for isinstance() checks.

    Optional metadata:
        category  — functional group (discovery, analysis, memory, ...).
        cost_tier — resource cost indicator (free, cheap, expensive).
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


# ---------------------------------------------------------------------------
# Standardized tool error helper
# ---------------------------------------------------------------------------

# Error types that tools can return
ToolErrorType = Literal[
    "validation",   # bad input / missing required params
    "not_found",    # resource not found
    "permission",   # access denied / policy blocked
    "connection",   # network / external service failure
    "timeout",      # operation timed out
    "dependency",   # missing library / unconfigured service
    "internal",     # unexpected internal error
]


def tool_error(
    message: str,
    *,
    error_type: ToolErrorType = "internal",
    recoverable: bool = True,
    hint: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a standardized tool error dict for LLM consumption.

    Returns a dict with ``error`` (message string for backward-compat)
    plus structured metadata that helps the LLM classify and recover.

    Args:
        message: Human-readable error description.
        error_type: Machine-readable category (validation, not_found, ...).
        recoverable: Whether the LLM should retry or try alternatives.
        hint: Actionable suggestion for the LLM (e.g. "use list_ips first").
        context: Extra key-value pairs (parameter name, value, etc.).
    """
    result: dict[str, Any] = {
        "error": message,
        "error_type": error_type,
        "recoverable": recoverable,
    }
    if hint:
        result["hint"] = hint
    if context:
        result["context"] = context
    return result


def classify_tool_exception(exc: Exception, tool_name: str = "") -> dict[str, Any]:
    """Classify an unhandled tool exception into a standardized error dict.

    Called at the executor level to wrap unexpected exceptions before
    they reach the LLM as raw stack traces.
    """
    msg = str(exc)
    exc_type = type(exc).__name__

    # Order matters: check specific OSError subclasses before generic OSError
    if isinstance(exc, TimeoutError):
        return tool_error(
            f"Operation timed out: {msg}",
            error_type="timeout",
            hint="Retry or try a simpler query.",
        )
    if isinstance(exc, PermissionError):
        return tool_error(
            f"Permission denied: {msg}",
            error_type="permission",
            recoverable=False,
        )
    if isinstance(exc, FileNotFoundError):
        return tool_error(
            f"File not found: {msg}",
            error_type="not_found",
            hint="Verify the file path exists.",
        )
    if isinstance(exc, (ConnectionError, OSError)):
        return tool_error(
            f"Connection failed: {msg}",
            error_type="connection",
            hint="Check network connectivity or retry.",
        )
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return tool_error(
            f"Invalid input: {msg}",
            error_type="validation",
            hint="Check parameter types and values.",
        )
    if isinstance(exc, ImportError):
        return tool_error(
            f"Missing dependency: {msg}",
            error_type="dependency",
            recoverable=False,
            hint="Required library is not installed.",
        )
    # Generic fallback
    return tool_error(
        f"{exc_type}: {msg}" if tool_name else msg,
        error_type="internal",
        hint=f"Unexpected error in {tool_name}." if tool_name else "",
    )
