"""Policy Chain — mode/context-based tool access control.

Inspired by OpenClaw's 6-layer Policy Resolution Chain:
Profile → Global → Agent → Group → Sandbox → Subagent.

GEODE adapts this to pipeline modes: full_pipeline, evaluation, scoring, dry_run.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class PolicyAuditResult:
    """Result of a policy audit check with full evaluation trace."""

    tool_name: str
    mode: str
    allowed: bool
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    user: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def blocking_policies(self) -> list[str]:
        return [e["policy"] for e in self.evaluations if not e["allowed"]]


@dataclass
class ToolPolicy:
    """A single policy rule for tool access control.

    If allowed_tools is set, only those tools are permitted.
    If denied_tools is set, those tools are blocked.
    allowed_tools takes precedence (whitelist mode).
    """

    name: str
    mode: str  # e.g. "dry_run", "evaluation", "scoring", "*" for all modes
    priority: int = 100  # Lower = higher priority
    allowed_tools: set[str] = field(default_factory=set)
    denied_tools: set[str] = field(default_factory=set)

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed by this policy."""
        if self.allowed_tools:
            return tool_name in self.allowed_tools
        if self.denied_tools:
            return tool_name not in self.denied_tools
        return True  # No restrictions


class PolicyChain:
    """Chain of policies applied in priority order.

    Most specific policy (lowest priority number) wins.
    A tool must pass ALL applicable policies to be allowed.

    Usage:
        chain = PolicyChain()
        chain.add_policy(ToolPolicy(
            name="dry_run_block_llm",
            mode="dry_run",
            denied_tools={"run_analyst", "run_evaluator"},
        ))
        allowed = chain.filter_tools(["run_analyst", "psm_calculate"], mode="dry_run")
        # → ["psm_calculate"]
    """

    def __init__(self) -> None:
        self._policies: list[ToolPolicy] = []

    def add_policy(self, policy: ToolPolicy) -> None:
        """Add a policy to the chain."""
        self._policies.append(policy)
        self._policies.sort(key=lambda p: p.priority)

    def remove_policy(self, name: str) -> bool:
        """Remove a named policy. Returns True if found."""
        before = len(self._policies)
        self._policies = [p for p in self._policies if p.name != name]
        return len(self._policies) < before

    def filter_tools(self, tool_names: list[str], *, mode: str = "full_pipeline") -> list[str]:
        """Filter tool names through all applicable policies.

        A tool is allowed only if it passes every matching policy.
        """
        applicable = [p for p in self._policies if p.mode in (mode, "*")]

        if not applicable:
            return tool_names

        result = []
        for name in tool_names:
            if all(p.is_allowed(name) for p in applicable):
                result.append(name)
            else:
                blocking = [p.name for p in applicable if not p.is_allowed(name)]
                log.debug("Tool '%s' blocked by policies: %s", name, blocking)

        return result

    def is_allowed(self, tool_name: str, *, mode: str = "full_pipeline") -> bool:
        """Check if a single tool is allowed under current mode."""
        applicable = [p for p in self._policies if p.mode in (mode, "*")]
        return all(p.is_allowed(tool_name) for p in applicable)

    def list_policies(self) -> list[str]:
        """List all policy names in priority order."""
        return [p.name for p in self._policies]

    def clear(self) -> None:
        """Remove all policies."""
        self._policies.clear()

    def audit_check(
        self, tool_name: str, *, mode: str = "full_pipeline", user: str = ""
    ) -> PolicyAuditResult:
        """Check tool permission with full audit trail.

        Returns a PolicyAuditResult with allowed/denied status and
        the chain of policies that were evaluated.
        """
        applicable = [p for p in self._policies if p.mode in (mode, "*")]
        evaluations: list[dict[str, Any]] = []
        allowed = True

        for p in applicable:
            result = p.is_allowed(tool_name)
            evaluations.append(
                {
                    "policy": p.name,
                    "mode": p.mode,
                    "priority": p.priority,
                    "allowed": result,
                }
            )
            if not result:
                allowed = False

        return PolicyAuditResult(
            tool_name=tool_name,
            mode=mode,
            allowed=allowed,
            evaluations=evaluations,
            user=user,
        )


# ---------------------------------------------------------------------------
# Node-scoped tool allowlists (Phase 2-D)
# ---------------------------------------------------------------------------

# Default per-node tool allowlists.
NODE_TOOL_ALLOWLISTS: dict[str, list[str]] = {
    "analyst": ["memory_search", "memory_get", "query_monolake"],
    "evaluator": ["memory_search", "memory_get", "steam_info", "reddit_sentiment", "web_search"],
    "scoring": ["memory_search", "psm_calculate"],
    "synthesizer": ["memory_search", "memory_get", "explain_score"],
    "verification": ["memory_search", "memory_get"],
}


class NodeScopePolicy:
    """Filter available tools based on the executing node.

    Each node type has a whitelist of tools it may invoke.
    Tools not in the whitelist are silently excluded.
    If the node has no explicit allowlist, all tools pass through.
    """

    def __init__(
        self,
        node_allowlists: dict[str, list[str]] | None = None,
    ) -> None:
        self._allowlists: dict[str, set[str]] = {
            k: set(v) for k, v in (node_allowlists or NODE_TOOL_ALLOWLISTS).items()
        }

    def filter(
        self,
        tool_names: list[str],
        *,
        node: str | None = None,
    ) -> list[str]:
        """Return only tools allowed for *node*.

        Analyst subtypes like ``analyst_game_mechanics`` match the
        ``analyst`` prefix.  If *node* is ``None`` or has no allowlist
        entry, all tools pass through unchanged.
        """
        if node is None:
            return tool_names
        # Match exact key first, then prefix (e.g. "analyst_*" → "analyst")
        allowlist = self._allowlists.get(node)
        if allowlist is None:
            for prefix, allowed in self._allowlists.items():
                if node.startswith(prefix):
                    allowlist = allowed
                    break
        if allowlist is None:
            return tool_names
        filtered = [t for t in tool_names if t in allowlist]
        if len(filtered) < len(tool_names):
            blocked = set(tool_names) - set(filtered)
            log.debug("NodeScopePolicy[%s] blocked: %s", node, blocked)
        return filtered

    def is_allowed(self, tool_name: str, *, node: str | None = None) -> bool:
        """Check if a single tool is allowed for *node*."""
        return tool_name in self.filter([tool_name], node=node)

    def get_allowlist(self, node: str) -> set[str]:
        """Return the allowlist for *node* (or empty set if unrestricted)."""
        result = self._allowlists.get(node)
        if result is not None:
            return result
        for prefix, allowed in self._allowlists.items():
            if node.startswith(prefix):
                return allowed
        return set()
