"""Claude Code-style agentic UI — minimal, informative tool call rendering.

Renders tool calls, plan steps, sub-agent dispatch, and token usage
in a clean, compact format inspired by Claude Code's output style.

Usage::

    from core.ui.agentic_ui import render_tool_call, render_tool_result, render_tokens

    render_tool_call("analyze_ip", {"ip_name": "Berserk"})
    # ▸ analyze_ip(ip_name="Berserk")

    render_tool_result("analyze_ip", {"tier": "S", "score": 81.3})
    # ✓ analyze_ip → S (81.3)

    render_tokens(model="claude-opus-4-6", input_tokens=1200, output_tokens=350, elapsed_s=2.1)
    # ✢ claude-opus-4-6 · ↓1.2k ↑350 · 2.1s
"""

from __future__ import annotations

import json
from typing import Any

from core.ui.console import console


def render_tool_call(tool_name: str, tool_input: dict[str, Any]) -> None:
    """Render a tool invocation line (Claude Code style)."""
    args_parts: list[str] = []
    for k, v in tool_input.items():
        if isinstance(v, str):
            args_parts.append(f'{k}="{v}"')
        elif isinstance(v, bool):
            args_parts.append(f"{k}={str(v).lower()}")
        elif isinstance(v, dict):
            args_parts.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
        else:
            args_parts.append(f"{k}={v}")
    args_str = ", ".join(args_parts)
    console.print(f"  [tool_name]▸ {tool_name}[/tool_name]([tool_args]{args_str}[/tool_args])")


def render_tool_result(tool_name: str, result: dict[str, Any]) -> None:
    """Render a tool completion line with key result info."""
    if result.get("error"):
        console.print(f"  [error]✗ {tool_name}[/error] — {result['error']}")
        return

    # Extract meaningful summary from result
    summary_parts: list[str] = []
    if "tier" in result:
        summary_parts.append(result["tier"])
    if "score" in result:
        summary_parts.append(str(result["score"]))
    if "count" in result:
        summary_parts.append(f"{result['count']} items")
    if "plan_id" in result:
        summary_parts.append(f"plan:{result['plan_id'][:8]}")

    summary = " · ".join(summary_parts) if summary_parts else "ok"
    console.print(f"  [success]✓ {tool_name}[/success] → {summary}")


def render_tokens(
    model: str,
    input_tokens: int,
    output_tokens: int,
    elapsed_s: float | None = None,
) -> None:
    """Render token usage line (Claude Code ✢ style)."""
    in_str = _fmt_tokens(input_tokens)
    out_str = _fmt_tokens(output_tokens)
    time_str = f" · {elapsed_s:.1f}s" if elapsed_s else ""
    console.print(f"  [token_info]✢ {model} · ↓{in_str} ↑{out_str}{time_str}[/token_info]")


def render_plan_steps(ip_name: str, steps: list[str]) -> None:
    """Render a plan summary (Claude Code ● style)."""
    console.print()
    console.print(f"  [header]● Plan: {ip_name}[/header]")
    for i, step in enumerate(steps, 1):
        console.print(f"    [plan_step]{i}. {step}[/plan_step]")
    console.print()


def render_subagent_dispatch(task_id: str, task_type: str, description: str) -> None:
    """Render a sub-agent delegation line."""
    console.print(f'  [subagent]▸ delegate_task[/subagent]({task_type}, "{description}")')


def render_subagent_complete(count: int, elapsed_s: float) -> None:
    """Render sub-agent batch completion."""
    console.print(f"  [success]✓ {count} sub-agents completed[/success] ({elapsed_s:.1f}s)")
    console.print()


def _fmt_tokens(n: int) -> str:
    """Format token count: 1200 → 1.2k, 500 → 500."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)
