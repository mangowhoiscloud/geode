"""AgenticLoop internal helpers — tool factory + sub-agent announce + decomposition.

Originally extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7)
into three sibling modules (``_helpers.py`` + ``_announce.py`` +
``_decomposition.py``). PR-CLEANUP-1 (2026-05-23) consolidated the
announce-queue poller and decomposition dispatcher into this module —
all three were <100 LOC each and shared the same caller (``agent_loop.py``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.agent.sub_agent import SubAgentResult, drain_announced_results
from core.agent.tool_descriptions_policy import (
    _load_tool_descriptions_override,
    apply_tool_descriptions_policy,
)
from core.agent.tool_policy import _load_tool_policy_override, apply_tool_policy
from core.tools.base import load_all_tool_definitions

if TYPE_CHECKING:
    from core.tools.registry import ToolRegistry

    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Sub-agent announce-queue polling (PR-CLEANUP-1 흡수, was ``_announce.py``)
# ---------------------------------------------------------------------------


def check_announced_results(loop: AgenticLoop, messages: list[dict[str, Any]]) -> int:
    """Poll for sub-agent announced results and inject into conversation.

    Drains the announce queue for this parent session and adds each
    completed sub-agent's summary as a system event message.

    OpenClaw Spawn+Announce pattern: parent polls at each round start.
    """
    if not loop._parent_session_key:
        return 0
    announced: list[SubAgentResult] = drain_announced_results(loop._parent_session_key)
    if not announced:
        return 0
    for result in announced:
        status_label = "completed" if result.success else "failed"
        content = f"Sub-agent {status_label}: task_id={result.task_id}, summary={result.summary}"
        if result.error_message:
            content += f", error={result.error_message}"
        loop.context.add_system_event("subagent_completed", content)
        messages.append({"role": "user", "content": f"[system:subagent_completed] {content}"})
        log.debug("Injected announce for task_id=%s", result.task_id)
    return len(announced)


# ---------------------------------------------------------------------------
# Goal decomposition dispatch (PR-CLEANUP-1 흡수, was ``_decomposition.py``)
# ---------------------------------------------------------------------------


async def try_decompose(loop: AgenticLoop, user_input: str) -> str | None:
    """Run the planner LLM (when warranted) and install the Plan.

    Returns ``None`` either way. Async because ``decompose_async``
    awaits ``loop._call_llm``. Pre-A1 callers received a markdown
    suffix string — that path is gone (Plan body now lives on
    ``SessionMetrics.active_plan`` and is rendered at ``arun`` entry
    via ``_consume_plan_hint``).
    """
    if not loop._enable_goal_decomposition:
        return None
    try:
        from core.agent.plan import decompose_async
        from core.observability.session_metrics import current_session_metrics

        plan = await decompose_async(loop, user_input, tools=loop._tools)
        if plan is None:
            return None

        # Install the explicit Plan on SessionMetrics so subsequent
        # ``arun`` invocations + the replan path read the same object.
        # ``reset_attempts=True`` because this is the initial install —
        # no prior step attempts to preserve.
        current_session_metrics().set_active_plan(plan, reset_attempts=True)

        # Emit structured events for thin client. ``emit_goal_decomposition``
        # is the legacy summary; ``emit_plan_step`` (PR-CL-A1) emits the
        # current-step detail so UIs can render "Step 1/N: …".
        from core.ui.agentic_ui import emit_goal_decomposition, emit_plan_step

        emit_goal_decomposition([step.description for step in plan.steps])
        first_step = plan.current_step()
        if first_step is not None:
            emit_plan_step(
                current=plan.current + 1,
                total=len(plan.steps),
                description=first_step.description,
                revision=plan.revision,
            )
        log.info(
            "decompose_async: installed %d-step Plan on SessionMetrics",
            len(plan.steps),
        )
        return None
    except Exception:
        log.debug("Goal decomposition skipped", exc_info=True)
        return None
