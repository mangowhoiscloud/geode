"""Tool-list builder for ``AgenticLoop`` — base + registry + MCP merge.

Split out of ``_helpers.py`` in PR-HELPERS-3SPLIT (2026-05-24) per the
new Naming CANNOT row that forbids ``_helpers`` filenames once a
caller appears. The pre-split file co-hosted three unrelated
subsystem helpers (tool factory + sub-agent announce poller +
planner dispatch); ``_helpers.py`` as a name buried the actual
responsibility under a catch-all suffix.

This module owns the inference-time tool list:

- ``_BASE_TOOLS`` / ``AGENTIC_TOOLS`` — baseline list loaded from
  ``core/tools/base.py``'s centralised JSON.
- ``MAX_TOOL_RESULT_TOKENS`` / ``TOOL_LAZY_LOAD_THRESHOLD`` —
  module-level constants that legacy callers still read by attribute
  access on ``core.agent.loop`` (re-exported via the package
  ``__init__``).
- ``get_agentic_tools(registry, *, mcp_tools)`` — merges base +
  ``ToolRegistry`` extras + MCP definitions, dedups by ``name``,
  then applies the ADR-013 T1 description-override policy followed
  by the ADR-012 S0a tool_policy filter/order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.agent.tool_descriptions_policy import (
    _load_tool_descriptions_override,
    apply_tool_descriptions_policy,
)
from core.agent.tool_policy import _load_tool_policy_override, apply_tool_policy
from core.tools.base import load_all_tool_definitions

if TYPE_CHECKING:
    from core.tools.registry import ToolRegistry


# Load base tool definitions from centralized JSON (SOT: core/tools/base.py)
_BASE_TOOLS: list[dict[str, Any]] = load_all_tool_definitions()

# Backward-compatible alias
AGENTIC_TOOLS: list[dict[str, Any]] = _BASE_TOOLS


# ---------------------------------------------------------------------------
# Token guard — optional tool result truncation (P2-A)
# Default: unlimited (0). Frontier consensus: compression > hard cap.
# Server-side clear_tool_uses handles context accumulation.
# Set GEODE_MAX_TOOL_RESULT_TOKENS to a positive value to re-enable.
# ---------------------------------------------------------------------------
MAX_TOOL_RESULT_TOKENS = 0  # backward-compat alias; canonical: settings.max_tool_result_tokens
TOOL_LAZY_LOAD_THRESHOLD = 50  # Above this count, skip MCP lazy loading


def get_agentic_tools(
    registry: ToolRegistry | None = None,
    *,
    mcp_tools: list[dict[str, Any]] | None = None,
    force_include: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return the merged tool definitions for the agentic loop.

    Merges base tools, registry extras, and MCP tools into a single list.
    Deferred loading is NOT applied here — it happens at the Anthropic
    adapter (``core.llm.providers.anthropic.apply_tool_search_defer``,
    PR-TOOL-SEARCH-WIRE), where the official ``defer_loading`` field and
    the hosted tool-search tool are a Messages-API concern. This docstring
    previously claimed a defer threshold that the body never implemented
    (the v1.0 audit's doc-implementation parity finding).

    Args:
        registry: Optional ToolRegistry with additional native tools.
        mcp_tools: Optional MCP tool definitions to include.
        force_include: Tool names the caller's *explicit* allowlist (a
            sub-agent toolkit grant — see ``AgenticLoop.allowed_tool_names``)
            declared authoritative. The global ADR-012 ``tool_policy`` SoT
            (``tool-policy.json``, a self-improving-loop mutation surface) may
            *reorder* but MUST NOT *strip* these — otherwise a loop mutation
            silently revokes a tool a named sub-agent depends on. *Incident:
            PR-PILOT-PETRI-AUDIT-WIRING (2026-06-01) — a ``tool-policy.json``
            ``allowed_tools`` whitelist that omitted a toolkit-granted tool
            stripped it from a worker's model-visible surface BEFORE the
            toolkit ``allowed_tool_names`` filter ran, so the worker reported
            the tool "isn't in my available tool set" and skipped the work.
            (The originating case was the seed_pilot worker losing
            ``petri_audit``; PR-PILOT-UNIFY-DIM-EXTRACT 2026-06-04 later
            removed that worker — the Pilot now audits directly — but the
            guard still protects every other toolkit-granted sub-agent.)
            Pinned by ``tests/core/agent/test_tool_policy_force_include_toolkit.py``.
    """
    tools = list(_BASE_TOOLS)
    existing_names = {t["name"] for t in tools}
    if registry:
        for tool_def in registry.to_anthropic_tools():
            if tool_def["name"] not in existing_names:
                existing_names.add(tool_def["name"])
                tools.append(tool_def)
    # Merge MCP tools into the unified list (dedup across servers)
    if mcp_tools:
        existing_names = {t["name"] for t in tools}
        for mcp_tool in mcp_tools:
            name = mcp_tool.get("name")
            if name and name not in existing_names:
                existing_names.add(name)
                tools.append(mcp_tool)
    # ADR-013 T1 (2026-05-21) — tool descriptions override 적용.
    # base + registry + MCP merge 직후 + tool_policy filter/order 직전.
    # description override 가 먼저 적용돼야 tool_policy 가 갱신된 description
    # 기반의 forbidden/priority 판단 가능.
    tools = apply_tool_descriptions_policy(tools, _load_tool_descriptions_override())

    # ADR-012 S0a — 5축의 ``tool_policy`` SoT 가 인퍼런스 경로에서
    # 실제로 적용되는 단일 지점. 정책이 부재하면 ``apply_tool_policy``
    # 는 no-op (현재 행동 보존).
    #
    # PR-PILOT-PETRI-AUDIT-WIRING (2026-06-01) — ``force_include`` keeps
    # toolkit-granted tools (the sub-agent's explicit, authoritative
    # whitelist) out of the global tool_policy strip. Captured here *before*
    # the policy runs so a definition dropped by ``allowed_tools`` /
    # ``forbidden_tools`` can be reinstated afterwards. The policy still
    # governs ordering (priority_order) and every non-forced tool.
    preserved: list[dict[str, Any]] = []
    if force_include:
        seen: set[str] = set()
        for tool in tools:
            name = tool.get("name")
            if isinstance(name, str) and name in force_include and name not in seen:
                preserved.append(tool)
                seen.add(name)
    policed = apply_tool_policy(tools, _load_tool_policy_override())
    if preserved:
        policed_names = {t.get("name") for t in policed}
        # Re-add only the forced tools the policy stripped, preserving the
        # base merge order for the reinstated entries.
        reinstated = [t for t in preserved if t.get("name") not in policed_names]
        if reinstated:
            policed = policed + reinstated
    return policed
