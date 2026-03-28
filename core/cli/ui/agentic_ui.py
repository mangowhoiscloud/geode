"""Claude Code-style agentic UI — minimal, informative tool call rendering.

Renders tool calls, plan steps, sub-agent dispatch, and token usage
in a clean, compact format inspired by Claude Code's output style.

Usage::

    from core.cli.ui.agentic_ui import render_tool_call, render_tool_result, render_tokens

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

from core.cli.ui.console import console

# ───────────────────────────────────────────────────────────────────────────
# SessionMeter — session-level timing for status line
# ───────────────────────────────────────────────────────────────────────────


@dataclass
class SessionMeter:
    """Tracks session-level and per-turn timing for status line display."""

    start_time: float = field(default_factory=time.monotonic)
    model: str = ""
    _turn_start: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._turn_start = self.start_time

    def mark_turn_start(self) -> None:
        """Reset the per-turn timer (call before each agentic.run())."""
        self._turn_start = time.monotonic()

    # -- Session-level (cumulative) ----------------------------------------

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def elapsed_display(self) -> str:
        return self._format_seconds(self.elapsed_s)

    # -- Turn-level (per-turn delta) ---------------------------------------

    @property
    def turn_elapsed_s(self) -> float:
        return time.monotonic() - self._turn_start

    @property
    def turn_elapsed_display(self) -> str:
        return self._format_seconds(self.turn_elapsed_s)

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        s = int(seconds)
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

    When finalize() is called with 6+ total tools, renders a grouped
    summary by tool type instead of the simple collapsed count.
    """

    COLLAPSE_THRESHOLD = 5
    GROUPING_THRESHOLD = 6

    def __init__(self, *, quiet: bool = False) -> None:
        self._visible_count = 0
        self._collapsed_count = 0
        self._header_printed = False
        self._quiet = quiet  # suppress all console output (scheduler, headless)
        # Tool-type grouping state
        self._tool_type_counts: dict[str, int] = {}
        self._tool_type_last_summary: dict[str, str] = {}
        self._total_tool_count = 0
        self._round_count = 0

    def begin_round(self, label: str = "AgenticLoop") -> None:
        """Start a new agentic round — print header if not yet shown."""
        if not self._header_printed and not self._quiet:
            console.print(f"\n[bold]● {label}[/bold]")
            self._header_printed = True
        self._round_count += 1

    def log_tool_call(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Log a tool call. Returns True if visible, False if collapsed."""
        self._total_tool_count += 1
        self._tool_type_counts[tool_name] = self._tool_type_counts.get(tool_name, 0) + 1
        if self._quiet:
            return False
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
        """Log a tool result (only renders if the call was visible).

        Also tracks per-type last summary for grouped finalize display.
        """
        # Build summary string (needed for both visible rendering and grouping)
        summary = self._build_result_summary(tool_name, result)

        # Track per-type last summary for grouped display
        self._tool_type_last_summary[tool_name] = summary

        if not visible or self._quiet:
            return
        if result.get("error"):
            console.print(f"  ⎿ [error]✗ {tool_name}[/error] — {result['error']}")
            return
        console.print(f"  ⎿ [success]✓ {tool_name}[/success] → {summary}")

    @staticmethod
    def _build_result_summary(tool_name: str, result: dict[str, Any]) -> str:
        """Build a compact summary string from a tool result dict."""
        if result.get("error"):
            return str(result["error"])
        summary_parts: list[str] = []
        # Domain-specific keys (Game IP pipeline)
        if "tier" in result:
            summary_parts.append(result["tier"])
        if "score" in result:
            summary_parts.append(str(result["score"]))
        if "count" in result:
            summary_parts.append(f"{result['count']} items")
        if "plan_id" in result:
            summary_parts.append(f"plan:{result['plan_id'][:8]}")
        # Generic keys (MCP tools, web search, etc.)
        if not summary_parts:
            for key in ("output", "content", "text", "result", "message", "summary"):
                val = result.get(key)
                if val and isinstance(val, str):
                    # Truncate long values for display (max 80 chars)
                    preview = val.replace("\n", " ").strip()
                    if len(preview) > 80:
                        preview = preview[:77] + "..."
                    summary_parts.append(preview)
                    break
        return " · ".join(summary_parts) if summary_parts else "ok"

    def finalize(self) -> None:
        """Print collapsed count or grouped summary.

        When total tool count >= GROUPING_THRESHOLD (6), renders a grouped
        summary by tool type (e.g., ``web_search (3) · memory (2) · bash (1)``).
        Otherwise, falls back to the simple collapsed count message.
        """
        if self._total_tool_count >= self.GROUPING_THRESHOLD:
            # Grouped summary: tool_type (count) sorted by count descending
            sorted_types = sorted(self._tool_type_counts.items(), key=lambda x: -x[1])
            type_parts = [f"{name} ({count})" for name, count in sorted_types]
            group_line = " · ".join(type_parts)
            console.print(f"  ⎿ [dim]{group_line}[/dim]")
            rounds = max(self._round_count, 1)
            console.print(f"  ⎿ [dim]{self._total_tool_count} tools · {rounds} rounds[/dim]")
        elif self._collapsed_count > 0:
            console.print(f"  ⎿ [dim]+{self._collapsed_count} more tool uses (collapsed)[/dim]")

    def reset(self) -> None:
        """Reset for next run()."""
        self._visible_count = 0
        self._collapsed_count = 0
        self._header_printed = False
        self._tool_type_counts.clear()
        self._tool_type_last_summary.clear()
        self._total_tool_count = 0
        self._round_count = 0


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
        from core.llm.router import get_usage_accumulator

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


def render_subagent_progress(
    completed: int, total: int, latest_name: str, latest_time: float
) -> None:
    """Render sub-agent progress with counter.

    Shows progressive ``[completed/total]`` counter as each sub-agent finishes.
    """
    if completed < total:
        console.print(
            f"  [dim]⎿[/dim] [success]✓[/success] {latest_name} ({latest_time:.1f}s)"
            f"  [{completed}/{total}]"
        )
    else:
        console.print(
            f"  [dim]⎿[/dim] [success]✓[/success] {latest_name} ({latest_time:.1f}s)"
            f"  [{completed}/{total}]"
        )


def render_subagent_complete(count: int, elapsed_s: float) -> None:
    """Render sub-agent batch completion."""
    console.print(f"  [success]✓ {count} sub-agents completed[/success] ({elapsed_s:.1f}s)")
    console.print()


def render_status_line() -> None:
    """Render Claude Code-style status line after each agentic result.

    Shows **per-turn** metrics (elapsed, tokens, cost, context %) so that
    each user turn gets an independent measurement — matching Claude Code's
    behaviour where the timer and counters reset every turn.

    Format: ✢ Worked for 2s · claude-opus-4-6 · ↓1.2k ↑350 · $0.003 · 1% context
    """
    meter = get_session_meter()
    if meter is None:
        return
    try:
        from core.llm.token_tracker import get_tracker

        tracker = get_tracker()

        # Per-turn delta: if a snapshot was taken before agentic.run(),
        # compute delta; otherwise fall back to cumulative (first turn).
        snap = _turn_snapshot
        if snap is not None:
            delta = tracker.delta_since(snap)
            in_tok = delta.total_input_tokens
            out_tok = delta.total_output_tokens
            cost = delta.total_cost_usd
        else:
            acc = tracker.accumulator
            in_tok = acc.total_input_tokens
            out_tok = acc.total_output_tokens
            cost = acc.total_cost_usd

        in_str = _fmt_tokens(in_tok)
        out_str = _fmt_tokens(out_tok)
        ctx_pct = tracker.context_usage_pct_for(meter.model, in_tok)

        parts = [f"✢ Worked for {meter.turn_elapsed_display}"]
        parts.append(meter.model)
        parts.append(f"↓{in_str} ↑{out_str}")
        if cost > 0:
            parts.append(f"${cost:.4f}")
        parts.append(f"{ctx_pct:.0f}% context")

        line = " · ".join(parts)
        console.print(f"\n  [dim]{line}[/dim]")
    except Exception:
        # Fallback: just show elapsed time
        console.print(f"\n  [dim]✢ Worked for {meter.turn_elapsed_display}[/dim]")


def render_context_event(
    event_type: str,
    *,
    original_count: int = 0,
    new_count: int = 0,
) -> None:
    """Render context compression notification.

    Shows a dim notification when context is auto-compacted or pruned,
    so the user knows conversation history was compressed.

    Format::

        ⟳ Context compacted: 45 → 12 messages
        ⟳ Context pruned: 30 → 10 messages
    """
    if event_type == "exhausted":
        console.print(
            "  [warning]⟳ Context exhausted — pruning could not free enough space[/warning]"
        )
        return
    label = "compacted" if event_type == "compact" else "pruned"
    console.print(f"  [dim]⟳ Context {label}: {original_count} → {new_count} messages[/dim]")


def render_turn_summary(rounds: int, tool_count: int, elapsed_s: float, cost: float) -> None:
    """Render compact turn-end summary line.

    Format: ``──── 3 rounds · 8 tools · 4.2s · $0.012 ────``
    Only renders when there is meaningful activity (at least 1 tool call).
    """
    if tool_count == 0:
        return
    parts = [f"{rounds} rounds", f"{tool_count} tools", f"{elapsed_s:.1f}s"]
    if cost > 0:
        parts.append(f"${cost:.3f}")
    summary = " · ".join(parts)
    console.print(f"\n  [dim]──── {summary} ────[/dim]")


def render_action_summary(
    tool_calls: list[dict[str, Any]],
    rounds: int,
    elapsed_s: float,
    cost: float,
) -> str:
    """Render Tier 1 deterministic action summary with per-tool detail.

    Displays a header line (rounds/tools/time/cost) followed by individual
    tool call results.  Returns the summary string for storing in
    ``AgenticResult.summary``.  Zero LLM tokens consumed.
    """
    if not tool_calls:
        return ""

    lines: list[str] = []

    # Header
    header_parts = [f"{rounds} rounds", f"{len(tool_calls)} tools", f"{elapsed_s:.1f}s"]
    if cost > 0:
        header_parts.append(f"${cost:.3f}")
    header = " \u00b7 ".join(header_parts)
    lines.append("\u2500\u2500\u2500\u2500 Action Summary \u2500\u2500\u2500\u2500")
    lines.append(header)
    lines.append("")

    # Per-tool lines (cap at 10)
    for tc in tool_calls[:10]:
        name = tc.get("name") or tc.get("tool") or "?"
        inp = tc.get("input", {})
        result = tc.get("result", {})

        # Concise arg preview: first meaningful value
        arg_preview = ""
        if isinstance(inp, dict):
            for _k, v in inp.items():
                if v and _k not in ("verbose",):
                    arg_preview = str(v)[:30].replace("\n", " ")
                    break

        # Concise result preview
        result_preview = ""
        if isinstance(result, dict):
            if "error" in result:
                result_preview = f"ERR: {str(result['error'])[:25]}"
            elif "status" in result:
                result_preview = str(result["status"])
            elif "result" in result:
                result_preview = str(result["result"])[:30]
            else:
                for rk, rv in result.items():
                    if rk not in ("_meta", "_timing") and rv:
                        result_preview = str(rv)[:25]
                        break
        if not result_preview:
            result_preview = "ok"

        if arg_preview:
            lines.append(f"  {name}({arg_preview}) → {result_preview}")
        else:
            lines.append(f"  {name} → {result_preview}")

    if len(tool_calls) > 10:
        lines.append(f"  ... +{len(tool_calls) - 10} more")

    lines.append(
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
    )

    summary_text = "\n".join(lines)

    # Render to console
    for line in lines:
        console.print(f"  [dim]{line}[/dim]")

    return summary_text


# ───────────────────────────────────────────────────────────────────────────
# Per-turn snapshot state (set before each agentic.run(), read by render)
# ───────────────────────────────────────────────────────────────────────────

_turn_snapshot: Any = None  # UsageSnapshot | None


def mark_turn_start() -> None:
    """Snapshot current cumulative metrics and reset turn timer.

    Call this before each ``agentic.run()`` so that ``render_status_line()``
    can display per-turn deltas instead of session-cumulative totals.
    """
    global _turn_snapshot
    meter = get_session_meter()
    if meter is not None:
        meter.mark_turn_start()
    try:
        from core.llm.token_tracker import get_tracker

        _turn_snapshot = get_tracker().snapshot()
    except Exception:
        _turn_snapshot = None


def _fmt_tokens(n: int) -> str:
    """Format token count: 1200 → 1.2k, 500 → 500."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)
