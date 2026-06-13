"""Tool Protocol — defines the interface for all GEODE tools.

Layer 5 component that enables LLM-driven tool use via Anthropic's
tool_use API or autonomous agent patterns.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast, runtime_checkable

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
        # Petri × GEODE alignment audit (`petri_audit` tool). Distinct
        # from `analysis` because the audit harness evaluates GEODE
        # itself (auditor → target → judge) rather than an external
        # domain subject.
        "evaluation",
        # P4 own-evaluator preparation (B+C): OTel-based LLM/agent
        # tracing surface (``obs_otel_export``) + audit log
        # visualization (``eval_inspect_viz``). Distinct from
        # ``evaluation`` because these tools wire instrumentation /
        # rendering rather than score-producing audits themselves.
        "observability",
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

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool asynchronously with given parameters.

        Returns:
            Result dict with at minimum a "result" key.
        """
        ...


@dataclass(slots=True)
class ToolContext:
    """Runtime context passed to async-capable tools.

    The four LLM-identity fields (``provider`` / ``source`` / ``model`` /
    ``adapter_name``) carry the AgenticLoop's currently-resolved adapter
    routing forward into tool execution — PR-TOOL-EXEC-CONTEXT (2026-05-28),
    paperclip ``AdapterExecutionContext.agent`` analogue
    (``packages/adapter-utils/src/types.ts``).

    Without this propagation an LLM-touching tool (web_search, future
    web_extract / web_crawl / summarise) re-runs the adapter resolution
    chain from scratch via ``infer_source(provider)`` — drawing solely
    from operator settings + ProfileStore — so the tool may land on a
    different (provider, source) pair than the orchestration loop's main
    LLM call. That is fine when the operator has one credential per
    provider, but breaks the moment a session is intentionally driven by
    Claude OAuth subscription while PAYG keys also sit in the environment.
    Tools that read these fields can pass ``prefer_provider`` /
    ``prefer_source`` to ``core.llm.adapters.dispatch`` helpers so the
    candidate ordering matches the loop's choice.

    Most tools do not consume these fields — they are injected as a single
    ``_tool_context=`` kwarg that the tool's ``**kwargs`` splat absorbs
    silently. Only LLM-touching tools opt in by reading
    ``kwargs.get("_tool_context")``.
    """

    session_id: str = ""
    cwd: Path = field(default_factory=Path.cwd)
    permission_mode: str = ""
    is_subagent: bool = False
    cancellation: asyncio.Event | None = None
    progress: Any | None = None
    # LLM-identity propagation (PR-TOOL-EXEC-CONTEXT) — empty string when
    # the loop has not resolved an adapter yet, or when a tool is invoked
    # outside an AgenticLoop (CLI utility / test harness). Consumers must
    # treat empty as "no preference".
    provider: str = ""
    source: str = ""
    model: str = ""
    adapter_name: str = ""


@runtime_checkable
class AsyncTool(Tool, Protocol):
    """Backward-compatible alias for the async-native GEODE tool protocol."""


# ---------------------------------------------------------------------------
# Standardized tool error helper
# ---------------------------------------------------------------------------

# Error types that tools can return
ToolErrorType = Literal[
    "validation",  # bad input / missing required params
    "not_found",  # resource not found
    "permission",  # access denied / policy blocked
    "connection",  # network / external service failure
    "timeout",  # operation timed out
    "dependency",  # missing library / unconfigured service
    "internal",  # unexpected internal error
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
        hint: Actionable suggestion for the LLM (e.g. "use memory_search first").
        context: Extra key-value pairs (parameter name, value, etc.).
    """
    from core.auth.scrub import scrub_credentials

    result: dict[str, Any] = {
        "error": scrub_credentials(message),
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


# ---------------------------------------------------------------------------
# Shared tool definition loader (was duplicated in sub_agent.py + bash_tool.py)
# ---------------------------------------------------------------------------

_TOOLS_JSON_PATH = Path(__file__).resolve().parent / "definitions.json"

# Two-layer tool model (intentional, not redundancy — PR-LOWRISK-SLOP C):
#   1. ``definitions.json`` — the DECLARATIVE layer: name / description /
#      input_schema / category / cost_tier. Single SoT for the metadata the LLM
#      sees (prompt-injectable + git-diffable). No behaviour here.
#   2. the ``Tool`` protocol + ``ToolRegistry`` — the BEHAVIOUR layer: each tool
#      class implements ``aexecute()``. The registry filters/dispatches instances.
# The split is deliberate: metadata that ships to the model must be a static,
# reviewable artifact, while execution is polymorphic Python. The registry's
# schema is validated against this JSON so the two layers cannot silently drift.


def load_all_tool_definitions() -> list[dict[str, Any]]:
    """Load all tool definitions from definitions.json (single source of truth).

    Other modules should import this instead of independently reading
    the JSON file to avoid path duplication.
    """
    return cast(list[dict[str, Any]], json.loads(_TOOLS_JSON_PATH.read_text(encoding="utf-8")))


def load_tool_definition(name: str) -> dict[str, Any]:
    """Load a single tool definition by name from definitions.json."""
    all_tools = load_all_tool_definitions()
    for t in all_tools:
        if t["name"] == name:
            return t
    raise KeyError(f"Tool '{name}' not found in {_TOOLS_JSON_PATH}")
