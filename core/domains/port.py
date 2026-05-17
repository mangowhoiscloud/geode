"""DomainPort — Protocol interface for pluggable domain adapters.

Defines the contract that domain plugins must implement to provide
domain-specific configuration (analyst types, evaluator axes, scoring
weights, classification rules, prompts, fixtures) to the generic
GEODE pipeline engine.

Injection via contextvars follows the same pattern as LLMClientPort.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DomainPort(Protocol):
    """Contract for domain plugin adapters.

    A domain adapter encapsulates all domain-specific logic and
    configuration, allowing the pipeline nodes to remain generic.
    """

    # --- Identity ---

    @property
    def name(self) -> str:
        """Domain identifier, e.g. 'research'."""
        ...

    @property
    def version(self) -> str:
        """Domain adapter version string."""
        ...

    @property
    def description(self) -> str:
        """Human-readable domain description."""
        ...

    # --- Analyst Configuration ---

    def get_analyst_types(self) -> list[str]:
        """Return ordered list of analyst type names for this domain."""
        ...

    def get_analyst_specific(self) -> dict[str, str]:
        """Return analyst_type → specific prompt fragment mapping."""
        ...

    # --- Evaluator Configuration ---

    def get_evaluator_types(self) -> list[str]:
        """Return evaluator type names for this domain."""
        ...

    def get_evaluator_axes(self) -> dict[str, dict[str, Any]]:
        """Return evaluator_type → axes config (with descriptions, ranges)."""
        ...

    def get_prospect_evaluator_axes(self) -> dict[str, dict[str, Any]]:
        """Return prospect_evaluator_type → axes config.

        Domains without a prospect-evaluation track may return an empty dict.
        """
        ...

    def get_valid_axes_map(self) -> dict[str, set[str]]:
        """Return evaluator_type → set of valid axis key names."""
        ...

    # --- Scoring ---

    def get_scoring_weights(self) -> dict[str, float]:
        """Return subscore_name → weight mapping for final score."""
        ...

    def get_confidence_multiplier_params(self) -> tuple[float, float]:
        """Return (base, scale) for confidence multiplier: base + scale * conf/100."""
        ...

    def get_tier_thresholds(self) -> list[tuple[float, str]]:
        """Return sorted (threshold, tier_name) pairs, highest first.

        Example: [(80, 'S'), (60, 'A'), (40, 'B')]
        Scores below all thresholds map to the fallback tier.
        """
        ...

    def get_tier_fallback(self) -> str:
        """Return tier name for scores below all thresholds."""
        ...

    # --- Classification ---

    def get_cause_values(self) -> list[str]:
        """Return valid cause type strings for this domain."""
        ...

    def get_action_values(self) -> list[str]:
        """Return valid action type strings for this domain."""
        ...

    def get_cause_to_action(self) -> dict[str, str]:
        """Return cause → recommended action mapping."""
        ...

    def get_cause_descriptions(self) -> dict[str, str]:
        """Return cause → human-readable description mapping."""
        ...

    def get_action_descriptions(self) -> dict[str, str]:
        """Return action → human-readable description mapping."""
        ...

    # --- Fixtures ---

    def list_fixtures(self) -> list[str]:
        """Return available fixture names for this domain."""
        ...

    def get_fixture_path(self) -> str | None:
        """Return path to fixtures directory, or None if no fixtures."""
        ...

    # --- Lifecycle hooks (v2, optional) ---
    #
    # The four methods below were introduced in step 3 of the
    # domain-free-core refactor to remove the last direct
    # plugin imports inside runtime wiring. They are *optional*: domains
    # that have no signal layer or no system-prompt customization may
    # leave the methods unimplemented, in which case call sites in
    # ``core/`` fall back to a no-op via ``getattr(domain, '<name>',
    # None)``.  The Protocol declares them with ``...`` bodies so type
    # checkers still enforce the signature when an implementation is
    # provided.
    #
    # Convention for callers in core/:
    #     fn = getattr(domain, "wire_context_assembler", None)
    #     if callable(fn):
    #         fn(assembler)

    def wire_context_assembler(self, assembler: Any) -> None:
        """Inject a ContextAssembler into the domain's pipeline nodes.

        Optional: domains whose nodes don't bridge to L2 memory may omit.
        Default behavior at call sites: skip silently.
        """
        ...

    def build_task_graph(self, memory: Any, subject_id: str) -> Any:
        """Build the domain's TaskGraph for the given subject.

        Optional: domains without a task-graph topology may omit.
        Default behavior at call sites: skip and return None.
        """
        ...

    def build_signal_adapter(self) -> Any:
        """Build and inject the domain's signal adapter.

        Optional: domains without external signal sources may omit.
        Default behavior at call sites: skip silently.
        """
        ...

    def compose_static_prefix(self, model: str) -> str:
        """Return the domain-specific static prefix for the system prompt.

        Optional: domains without prompt customization may omit. Default
        behavior at call sites: emit a generic GEODE prefix without
        domain-specific substitutions.
        """
        ...

    # --- CLI extension hooks (v2, optional, step 4) ---
    #
    # The three methods below were introduced in step 4 of the
    # domain-free-core refactor to remove domain-specific command logic
    # from ``core/cli/commands.py`` and ``core/cli/tool_handlers.py``. Like
    # the step-3 hooks they are *optional* — domains that do not extend
    # the slash-command surface or contribute pipeline-shaped tools may
    # leave them unimplemented and call sites in ``core/`` fall back to
    # safe defaults via ``getattr(domain, '<name>', None)``.

    def get_rerunnable_nodes(self) -> set[str]:
        """Return pipeline node names that ``/rerun_node`` will accept.

        Default: empty set (no rerunnable nodes for non-pipeline domains).
        """
        ...

    def register_slash_commands(self, command_map: dict[str, str]) -> None:
        """Merge domain-specific slash command entries into ``command_map``.

        Default: no-op. Implementations should call
        ``command_map.update({...})`` with their own ``"/cmd" -> "action"``
        entries; the generic ``COMMAND_MAP`` is mutated in place.
        """
        ...

    def register_tool_handlers(self, handlers: dict[str, Any]) -> None:
        """Merge domain-specific tool handler entries into ``handlers``.

        Default: no-op. Implementations should call
        ``handlers.update({...})`` with their own ``"tool_name" -> callable``
        entries; the generic dispatcher dict is mutated in place.
        """
        ...

    # --- MCP server extension hook (v2, optional, step 6) ---
    #
    # Introduced in step 6 to keep domain-specific MCP tools out of
    # ``core/mcp_server.py``.  Like the other v2 hooks it is *optional* —
    # domains without an MCP surface (or whose surface is exposed
    # differently) may leave it unimplemented, and the call site in
    # ``core/mcp_server.py:create_mcp_server`` falls back to a no-op via
    # ``getattr(domain, 'register_mcp_tools', None)``.

    def register_mcp_tools(self, server: Any) -> None:
        """Register domain-specific MCP tools and resources on ``server``.

        The plugin uses FastMCP decorators (``@server.tool()``,
        ``@server.resource()``) to attach its tools/resources at
        server-creation time. ``server`` is a
        ``mcp.server.fastmcp.FastMCP`` instance.

        Default: no-op. Implementations should call
        ``@server.tool(...)`` / ``@server.resource(...)`` to attach
        their MCP surface; the generic core tools (``query_memory``,
        ``get_health``, ``geode://soul``) are already registered by the
        time this method runs.
        """
        ...


# ---------------------------------------------------------------------------
# contextvars injection (same pattern as LLMClientPort)
# ---------------------------------------------------------------------------

_domain_ctx: ContextVar[DomainPort] = ContextVar("domain_port")


def set_domain(domain: DomainPort) -> None:
    """Set the active domain adapter for the current context."""
    _domain_ctx.set(domain)


def get_domain() -> DomainPort:
    """Get the active domain adapter. Raises LookupError if not set."""
    return _domain_ctx.get()


def get_domain_or_none() -> DomainPort | None:
    """Get the active domain adapter, or None if not set."""
    return _domain_ctx.get(None)
