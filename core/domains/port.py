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
        """Domain identifier, e.g. 'game_ip', 'research'."""
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
