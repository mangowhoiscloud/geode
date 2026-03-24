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
import time
from dataclasses import dataclass, field
from typing import Any

from core.ui.console import console

# ───────────────────────────────────────────────────────────────────────────
# SessionMeter — session-level timing for status line
# ───────────────────────────────────────────────────────────────────────────


@dataclass
class SessionMeter:
    """Tracks session-level timing for status line display."""

    start_time: float = field(default_factory=time.monotonic)
    model: str = ""

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def elapsed_display(self) -> str:
        s = int(self.elapsed_s)
        if s < 60:
            return f"{s}s"
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s"


_session_meter: SessionMeter | None = None


def init_session_meter(model: str = "") -> SessionMeter:
    """Initialize the session meter singleton."""
    global _session_meter
    if not model:
        from core.config import ANTHROPIC_PRIMARY

        model = ANTHROPIC_PRIMARY
    _session_meter = SessionMeter(model=model)
    return _session_meter


def update_session_model(model: str) -> None:
    """Update the session meter's model after /model switch."""
    if _session_meter is not None:
        _session_meter.model = model


def get_session_meter() -> SessionMeter | None:
    """Return the current session meter (None if not initialized)."""
    return _session_meter


# ───────────────────────────────────────────────────────────────────────────
# OperationLogger — progressive tree log with auto-collapse
# ───────────────────────────────────────────────────────────────────────────


class OperationLogger:
    """Tracks tool call rendering within a single agentic round.

    Manages the progressive log display with tree structure and
    auto-collapse after COLLAPSE_THRESHOLD visible operations.
    """

    COLLAPSE_THRESHOLD = 5

    def __init__(self) -> None:
        self._visible_count = 0
        self._collapsed_count = 0
        self._header_printed = False

    def begin_round(self, label: str = "AgenticLoop") -> None:
        """Start a new agentic round — print header if not yet shown."""
        if not self._header_printed:
            console.print(f"\n[bold]● {label}[/bold]")
            self._header_printed = True

    def log_tool_call(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Log a tool call. Returns True if visible, False if collapsed."""
        if self._visible_count < self.COLLAPSE_THRESHOLD:
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
            console.print(
                f"  ⎿ [tool_name]▸ {tool_name}[/tool_name]([tool_args]{args_str}[/tool_args])"
            )
            self._visible_count += 1
            return True
        self._collapsed_count += 1
        return False

    def log_tool_result(
        self, tool_name: str, result: dict[str, Any], *, visible: bool = True
    ) -> None:
        """Log a tool result (only renders if the call was visible)."""
        if not visible:
            return
        if result.get("error"):
            console.print(f"  ⎿ [error]✗ {tool_name}[/error] — {result['error']}")
            return
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
        console.print(f"  ⎿ [success]✓ {tool_name}[/success] → {summary}")

    def finalize(self) -> None:
        """Print collapsed count if any tools were hidden."""
        if self._collapsed_count > 0:
            console.print(f"  ⎿ [dim]+{self._collapsed_count} more tool uses (collapsed)[/dim]")

    def reset(self) -> None:
        """Reset for next run()."""
        self._visible_count = 0
        self._collapsed_count = 0
        self._header_printed = False


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
    cost_usd: float | None = None,
) -> None:
    """Render token usage line (Claude Code ✢ style)."""
    in_str = _fmt_tokens(input_tokens)
    out_str = _fmt_tokens(output_tokens)
    time_str = f" · {elapsed_s:.1f}s" if elapsed_s else ""
    cost_str = f" · ${cost_usd:.4f}" if cost_usd and cost_usd > 0 else ""
    line = f"  [token_info]✢ {model} · ↓{in_str} ↑{out_str}"
    line += f"{cost_str}{time_str}[/token_info]"
    console.print(line)


def render_session_cost_summary() -> None:
    """Render cumulative session cost summary."""
    try:
        from core.llm.client import get_usage_accumulator

        acc = get_usage_accumulator()
        if not acc.calls:
            return
        console.print()
        console.print("  [bold]Session Cost Summary[/bold]")
        console.print(f"  [dim]Calls:[/dim] {len(acc.calls)}")
        in_str = _fmt_tokens(acc.total_input_tokens)
        out_str = _fmt_tokens(acc.total_output_tokens)
        console.print(f"  [dim]Tokens:[/dim] ↓{in_str} ↑{out_str}")
        console.print(f"  [warning]Total: ${acc.total_cost_usd:.4f}[/warning]")
        # Per-model breakdown
        model_costs: dict[str, float] = {}
        model_calls: dict[str, int] = {}
        for u in acc.calls:
            model_costs[u.model] = model_costs.get(u.model, 0) + u.cost_usd
            model_calls[u.model] = model_calls.get(u.model, 0) + 1
        if len(model_costs) > 1:
            for m, c in sorted(model_costs.items(), key=lambda x: -x[1]):
                console.print(f"    [dim]{m}:[/dim] ${c:.4f} ({model_calls[m]} calls)")
        console.print()
    except Exception:
        return  # accumulator not available yet


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


def render_status_line() -> None:
    """Render Claude Code-style status line after each agentic result.

    Format: ✢ Worked for 48s · claude-opus-4-6 · ↓12.3k ↑2.1k · $0.42 · 11% context
    """
    meter = get_session_meter()
    if meter is None:
        return
    try:
        from core.llm.token_tracker import get_tracker

        tracker = get_tracker()
        acc = tracker.accumulator
        in_str = _fmt_tokens(acc.total_input_tokens)
        out_str = _fmt_tokens(acc.total_output_tokens)
        cost = acc.total_cost_usd
        ctx_pct = tracker.context_usage_pct(meter.model)

        parts = [f"✢ Worked for {meter.elapsed_display}"]
        parts.append(meter.model)
        parts.append(f"↓{in_str} ↑{out_str}")
        if cost > 0:
            parts.append(f"${cost:.4f}")
        parts.append(f"{ctx_pct:.0f}% context")

        line = " · ".join(parts)
        console.print(f"\n  [dim]{line}[/dim]")
    except Exception:
        # Fallback: just show elapsed time
        console.print(f"\n  [dim]✢ Worked for {meter.elapsed_display}[/dim]")


def _fmt_tokens(n: int) -> str:
    """Format token count: 1200 → 1.2k, 500 → 500."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)
