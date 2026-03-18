"""Policy Chain — 6-layer tool access control.

OpenClaw-inspired 6-layer Policy Resolution Chain:
  1. Profile (user preferences)
  2. Organization (team/org overrides)
  3. Mode-based (pipeline mode: full_pipeline, dry_run, etc.)
  4. Agent-level (SAFE/WRITE/DANGEROUS classification)
  5. Node-scope (per-pipeline-node allowlists)
  6. Sub-agent (auto-approval delegation)

Layers 1-2 are new (v0.20.0), layers 3-6 already existed.
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
# Layer 1: Profile Policy — user-level preferences
# ---------------------------------------------------------------------------


@dataclass
class ProfilePolicy:
    """User-level tool preferences loaded from ~/.geode/user_profile/.

    Users can restrict themselves from expensive/write/dangerous tools.
    Profile policies get priority=10 (high) in the PolicyChain.
    """

    user_id: str = ""
    allow_expensive: bool = True
    allow_write: bool = True
    allow_dangerous: bool = False
    denied_tools: set[str] = field(default_factory=set)

    def to_policies(self) -> list[ToolPolicy]:
        """Convert profile preferences into PolicyChain-compatible policies."""
        policies: list[ToolPolicy] = []

        if not self.allow_expensive:
            policies.append(
                ToolPolicy(
                    name=f"profile:{self.user_id}:no_expensive",
                    mode="*",
                    priority=10,
                    denied_tools={"analyze_ip", "batch_analyze", "compare_ips"},
                )
            )
        if not self.allow_write:
            policies.append(
                ToolPolicy(
                    name=f"profile:{self.user_id}:no_write",
                    mode="*",
                    priority=10,
                    denied_tools={
                        "memory_save",
                        "note_save",
                        "set_api_key",
                        "profile_update",
                        "calendar_create_event",
                        "calendar_sync_scheduler",
                    },
                )
            )
        if not self.allow_dangerous:
            policies.append(
                ToolPolicy(
                    name=f"profile:{self.user_id}:no_dangerous",
                    mode="*",
                    priority=10,
                    denied_tools={"run_bash"},
                )
            )
        if self.denied_tools:
            policies.append(
                ToolPolicy(
                    name=f"profile:{self.user_id}:custom_deny",
                    mode="*",
                    priority=10,
                    denied_tools=self.denied_tools,
                )
            )
        return policies


# ---------------------------------------------------------------------------
# Layer 2: Organization Policy — team/org overrides
# ---------------------------------------------------------------------------


@dataclass
class OrgPolicy:
    """Organization-level tool restrictions.

    Loaded from .geode/config.toml [policy.org] section.
    Org policies get priority=5 (highest) in the PolicyChain.
    """

    org_id: str = ""
    denied_tools: set[str] = field(default_factory=set)

    def to_policies(self) -> list[ToolPolicy]:
        """Convert org restrictions into PolicyChain-compatible policies."""
        if not self.denied_tools:
            return []
        return [
            ToolPolicy(
                name=f"org:{self.org_id}:deny",
                mode="*",
                priority=5,
                denied_tools=self.denied_tools,
            )
        ]


def load_profile_policy(profile_dir: str | None = None) -> ProfilePolicy:
    """Load user profile policy from ~/.geode/user_profile/preferences.toml.

    Returns a default (permissive) profile if no config exists.
    """
    import tomllib
    from pathlib import Path

    if profile_dir:
        pref_path = Path(profile_dir) / "preferences.toml"
    else:
        pref_path = Path.home() / ".geode" / "user_profile" / "preferences.toml"

    if not pref_path.exists():
        return ProfilePolicy()

    try:
        with open(pref_path, "rb") as f:
            data = tomllib.load(f)
        policy_section = data.get("policy", {})
        return ProfilePolicy(
            user_id=data.get("user_id", ""),
            allow_expensive=policy_section.get("allow_expensive", True),
            allow_write=policy_section.get("allow_write", True),
            allow_dangerous=policy_section.get("allow_dangerous", False),
            denied_tools=set(policy_section.get("denied_tools", [])),
        )
    except Exception:
        log.debug("Failed to load profile policy from %s", pref_path, exc_info=True)
        return ProfilePolicy()


def load_org_policy(config_path: str | None = None) -> OrgPolicy:
    """Load org policy from .geode/config.toml [policy.org] section.

    Returns a default (no restrictions) policy if no config exists.
    """
    import tomllib
    from pathlib import Path

    path = Path(config_path) if config_path else Path(".geode") / "config.toml"

    if not path.exists():
        return OrgPolicy()

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        org_section = data.get("policy", {}).get("org", {})
        return OrgPolicy(
            org_id=org_section.get("org_id", ""),
            denied_tools=set(org_section.get("denied_tools", [])),
        )
    except Exception:
        log.debug("Failed to load org policy from %s", path, exc_info=True)
        return OrgPolicy()


def build_6layer_chain(
    *,
    profile: ProfilePolicy | None = None,
    org: OrgPolicy | None = None,
    mode_policies: list[ToolPolicy] | None = None,
) -> PolicyChain:
    """Build a complete 6-layer PolicyChain.

    Layers:
      1. Profile (priority 10)
      2. Organization (priority 5)
      3. Mode-based (priority 100, from _build_default_policies)
      4-6. Agent/Node/SubAgent handled at execution time

    Usage::

        chain = build_6layer_chain(
            profile=load_profile_policy(),
            org=load_org_policy(),
        )
    """
    chain = PolicyChain()

    # Layer 2: Org (highest priority)
    if org:
        for p in org.to_policies():
            chain.add_policy(p)

    # Layer 1: Profile
    if profile:
        for p in profile.to_policies():
            chain.add_policy(p)

    # Layer 3: Mode-based (default policies from runtime)
    if mode_policies:
        for p in mode_policies:
            chain.add_policy(p)

    return chain


# ---------------------------------------------------------------------------
# Node-scoped tool allowlists (Phase 2-D) — Layer 5
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
