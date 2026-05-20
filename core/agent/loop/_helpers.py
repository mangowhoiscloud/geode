"""Tool definition factory + agentic-tool constants.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7).
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


def get_agentic_tools(
    registry: ToolRegistry | None = None,
    *,
    mcp_tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return tool definitions with unified deferred loading for native + MCP tools.

    Merges base tools, registry extras, and MCP tools into a single list.
    When the combined count exceeds the defer threshold (10), deferred loading
    activates: core tools stay loaded, the rest are deferred via tool_search.

    Args:
        registry: Optional ToolRegistry with additional native tools.
        mcp_tools: Optional MCP tool definitions to include.
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
    return apply_tool_policy(tools, _load_tool_policy_override())


# ---------------------------------------------------------------------------
# Token guard — optional tool result truncation (P2-A)
# Default: unlimited (0). Frontier consensus: compression > hard cap.
# Server-side clear_tool_uses handles context accumulation.
# Set GEODE_MAX_TOOL_RESULT_TOKENS to a positive value to re-enable.
# ---------------------------------------------------------------------------
MAX_TOOL_RESULT_TOKENS = 0  # backward-compat alias; canonical: settings.max_tool_result_tokens
TOOL_LAZY_LOAD_THRESHOLD = 50  # Above this count, skip MCP lazy loading
