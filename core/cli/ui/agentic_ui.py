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
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core.cli.ui.console import console

# Thread-local IPC writer for structured tool events.
# When set (by CLIPoller._run_prompt_streaming), OperationLogger sends
# tool_start/tool_end events instead of console.print — enabling the
# thin client to render per-tool spinners with in-place ✓ updates.
_ipc_writer_local = threading.local()

# Thread-local pipeline IP name for forward-compatible event tagging.
# Set by _run_analysis() before pipeline execution; read by emit_pipeline_*
# functions to tag events with the originating IP (for future parallel UI).
_pipeline_ip_local = threading.local()


def set_pipeline_ip(ip_name: str) -> None:
    """Set the current pipeline's IP name (thread-safe)."""
    _pipeline_ip_local.ip_name = ip_name


def _get_pipeline_ip() -> str:
    """Get the current pipeline's IP name."""
    return getattr(_pipeline_ip_local, "ip_name", "")

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
        # Per-tool start time for accurate server-side duration
        self._tool_start_times: dict[str, float] = {}

    def begin_round(self, label: str = "AgenticLoop") -> None:
        """Start a new agentic round — print header if not yet shown."""
        self._round_count += 1
        if self._quiet:
            return
        if self._header_printed:
            return
        self._header_printed = True
        writer = getattr(_ipc_writer_local, "writer", None)
        if writer is not None:
            writer.send_event("round_start", round=self._round_count)
        else:
            console.print(f"\n[bold]● {label}[/bold]")

    def log_tool_call(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Log a tool call. Returns True if visible, False if collapsed."""
        tool_id = self._total_tool_count
        self._total_tool_count += 1
        self._tool_type_counts[tool_name] = self._tool_type_counts.get(tool_name, 0) + 1
        if self._quiet:
            return False

        # Build args preview string
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

        # Track start time for server-side duration measurement
        self._tool_start_times[tool_name] = time.monotonic()

        # IPC mode: send structured event (client renders spinner + ✓)
        writer = getattr(_ipc_writer_local, "writer", None)
        if writer is not None:
            writer.send_event(
                "tool_start",
                id=tool_id,
                name=tool_name,
                args_preview=args_str.replace("\n", " ")[:120],
            )
            self._visible_count += 1
            return True

        # Direct mode: console.print
        if self._visible_count < self.COLLAPSE_THRESHOLD:
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
        summary = self._build_result_summary(tool_name, result)
        self._tool_type_last_summary[tool_name] = summary

        if not visible or self._quiet:
            return

        is_error = bool(result.get("error"))

        # IPC mode: send structured event with server-measured duration
        writer = getattr(_ipc_writer_local, "writer", None)
        if writer is not None:
            start = self._tool_start_times.pop(tool_name, 0.0)
            duration_s = round(time.monotonic() - start, 1) if start else 0.0
            writer.send_event(
                "tool_end",
                name=tool_name,
                summary=summary[:80],
                error=result.get("error", "") if is_error else "",
                duration_s=duration_s,
            )
            return

        # Direct mode: console.print
        if is_error:
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
        """Print collapsed count summary.

        In IPC mode: skip (client renders individual tool lines via ToolCallTracker).
        In direct mode: show compact aggregate count when tools exceed threshold.
        """
        # IPC mode — client already renders per-tool ✓ lines
        writer = getattr(_ipc_writer_local, "writer", None)
        if writer is not None:
            return
        if self._total_tool_count >= self.GROUPING_THRESHOLD:
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
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "tokens",
            model=model,
            input=input_tokens,
            output=output_tokens,
            cost=cost_usd or 0.0,
        )
        return
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
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("subagent_dispatch", task_id=task_id, description=description)
        return
    console.print(f'  [subagent]▸ delegate_task[/subagent]({task_type}, "{description}")')


def render_subagent_progress(
    completed: int, total: int, latest_name: str, latest_time: float
) -> None:
    """Render sub-agent progress with counter."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "subagent_progress",
            completed=completed,
            total=total,
            name=latest_name,
            duration_s=round(latest_time, 1),
        )
        return
    console.print(
        f"  [dim]⎿[/dim] [success]✓[/success] {latest_name} ({latest_time:.1f}s)"
        f"  [{completed}/{total}]"
    )


def render_subagent_complete(count: int, elapsed_s: float) -> None:
    """Render sub-agent batch completion."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("subagent_complete", count=count, elapsed_s=round(elapsed_s, 1))
        return
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
    """Render context compression notification with detail."""
    removed = original_count - new_count
    # Rough estimate: ~250 tokens per message on average
    tokens_est = removed * 250
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "context_event",
            action=event_type,
            before=original_count,
            after=new_count,
            removed=removed,
            tokens_estimate=tokens_est,
        )
        return
    if event_type == "exhausted":
        console.print(
            "  [warning]⟳ Context exhausted — pruning could not free enough space[/warning]"
        )
        return
    label = "compacted" if event_type == "compact" else "pruned"
    tok_str = f", ~{tokens_est // 1000}k tokens freed" if tokens_est >= 1000 else ""
    console.print(
        f"  [dim]⟳ Context {label}: {original_count} → {new_count} messages"
        f" ({removed} removed{tok_str})[/dim]"
    )


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


# ───────────────────────────────────────────────────────────────────────────
# Structured IPC event emitters — AgenticLoop state changes
# ───────────────────────────────────────────────────────────────────────────


def emit_budget_warning(budget: float, actual: float, pct: float) -> None:
    """Emit proactive budget warning at 80% threshold."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("budget_warning", budget=budget, actual=actual, pct=pct)
        return
    console.print(
        f"  [warning]$ Budget warning: ${actual:.2f} / ${budget:.2f} ({pct:.0f}% used)[/warning]"
    )


def emit_retry_wait(
    model: str,
    attempt: int,
    max_retries: int,
    delay_s: float,
    elapsed_s: float,
    error_type: str,
) -> None:
    """Emit retry_wait event during LLM retry backoff."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "retry_wait",
            model=model,
            attempt=attempt,
            max_retries=max_retries,
            delay_s=delay_s,
            elapsed_s=elapsed_s,
            error_type=error_type,
        )
        return
    console.print(
        f"  [warning]~ Retrying in {delay_s:.1f}s... "
        f"[{model} · {attempt}/{max_retries} · {elapsed_s:.0f}s elapsed] "
        f"(Ctrl+C to skip)[/warning]"
    )


def emit_llm_error(
    error_type: str,
    severity: str,
    hint: str,
    model: str,
    provider: str,
    attempt: int = 0,
    elapsed_s: float = 0.0,
) -> None:
    """Emit llm_error event with severity classification and actionable hint."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "llm_error",
            error_type=error_type,
            severity=severity,
            hint=hint,
            model=model,
            provider=provider,
            attempt=attempt,
            elapsed_s=elapsed_s,
        )
        return
    # Severity -> Rich style mapping
    style = {"critical": "error", "error": "error", "warning": "warning"}.get(severity, "dim")
    symbol = {"critical": "!!", "error": "!", "warning": "~"}.get(severity, "·")
    console.print(f"  [{style}]{symbol} {hint} [{model} · {elapsed_s:.1f}s][/{style}]")


def emit_model_escalation(from_model: str, to_model: str, failures: int) -> None:
    """Emit model_escalation event when LLM failures trigger auto-switch."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "model_escalation",
            from_model=from_model,
            to_model=to_model,
            failures=failures,
        )
        return
    console.print(
        f"  [warning]⚡ Model escalated: {from_model} → {to_model}"
        f" (after {failures} failures)[/warning]"
    )


def emit_cost_budget_exceeded(budget: float, actual: float) -> None:
    """Emit cost_budget_exceeded event when session cost hits limit."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("cost_budget_exceeded", budget=budget, actual=actual)
        return
    console.print(f"  [error]$ Cost budget exceeded: ${actual:.2f} / ${budget:.2f}[/error]")


def emit_time_budget_expired(budget_s: float, elapsed_s: float, rounds: int) -> None:
    """Emit time_budget_expired event when time limit reached."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "time_budget_expired",
            budget_s=budget_s,
            elapsed_s=elapsed_s,
            rounds=rounds,
        )
        return
    console.print(
        f"  [warning]⏱ Time budget expired: {elapsed_s:.0f}s / {budget_s:.0f}s"
        f" ({rounds} rounds)[/warning]"
    )


def emit_convergence_detected(error_pattern: str, rounds: int) -> None:
    """Emit convergence_detected event when stuck loop is broken."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("convergence_detected", error=error_pattern, rounds=rounds)
        return
    console.print(
        f"  [error]⟳ Convergence detected: repeating failure after {rounds} rounds[/error]"
    )


def emit_goal_decomposition(steps: list[str]) -> None:
    """Emit goal_decomposition event when multi-step plan is created."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("goal_decomposition", steps=steps, count=len(steps))
        return
    console.print(f"  [dim]● Goal decomposed into {len(steps)} steps[/dim]")


def emit_tool_backpressure(consecutive_errors: int) -> None:
    """Emit tool_backpressure event when error recovery kicks in."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("tool_backpressure", consecutive_errors=consecutive_errors)
        return
    console.print(
        f"  [warning]⏸ Tool backpressure: {consecutive_errors} consecutive errors[/warning]"
    )


def emit_tool_diversity_forced(tool_name: str, count: int) -> None:
    """Emit tool_diversity_forced event when same tool repeated too many times."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("tool_diversity_forced", tool=tool_name, count=count)
        return
    console.print(
        f"  [warning]⟳ Diversity forced: {tool_name} called {count}x consecutively[/warning]"
    )


def emit_model_switched(from_model: str, to_model: str, reason: str) -> None:
    """Emit model_switched event for user-initiated model change."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "model_switched",
            from_model=from_model,
            to_model=to_model,
            reason=reason,
        )


def emit_checkpoint_saved(session_id: str, round_idx: int) -> None:
    """Emit checkpoint_saved event after session state is persisted."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("checkpoint_saved", session_id=session_id, round_idx=round_idx)


# ───────────────────────────────────────────────────────────────────────────
# Structured IPC event emitters — Pipeline milestones
# ───────────────────────────────────────────────────────────────────────────


def emit_pipeline_gather(
    ip_info: dict[str, Any],
    monolake: dict[str, Any],
    signals: dict[str, Any] | None = None,
) -> None:
    """Emit pipeline_gather event with structured IP metadata + signals."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    sig = signals or {}
    writer.send_event(
        "pipeline_gather",
        ip_name=ip_info.get("ip_name", ""),
        media_type=ip_info.get("media_type", ""),
        release_year=ip_info.get("release_year", 0),
        studio=ip_info.get("studio", ""),
        dau=monolake.get("dau_current", 0),
        revenue=monolake.get("revenue_ltm", 0),
        youtube_views=sig.get("youtube_views", 0),
        reddit_subscribers=sig.get("reddit_subscribers", 0),
        fan_art_yoy_pct=sig.get("fan_art_yoy_pct", 0),
    )


def emit_pipeline_analysis(analyses: list[dict[str, Any]]) -> None:
    """Emit pipeline_analysis event with per-analyst scores."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    items = []
    for a in analyses:
        items.append(
            {
                "analyst": getattr(a, "analyst_type", str(a)),
                "score": getattr(a, "score", 0),
                "finding": getattr(a, "key_finding", ""),
            }
        )
    writer.send_event("pipeline_analysis", analysts=items, count=len(items))


def emit_pipeline_evaluation(evaluations: dict[str, Any]) -> None:
    """Emit pipeline_evaluation event with per-evaluator scores."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    items = {}
    for key, ev in evaluations.items():
        items[key] = {
            "score": getattr(ev, "composite_score", 0),
            "rationale": getattr(ev, "rationale", "")[:100],
        }
    writer.send_event("pipeline_evaluation", evaluators=items, count=len(items))


def emit_pipeline_score(
    final_score: float,
    subscores: dict[str, float],
    confidence: float,
    tier: str,
    *,
    psm: Any | None = None,
) -> None:
    """Emit pipeline_score event with PSM results."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    writer.send_event(
        "pipeline_score",
        final_score=final_score,
        subscores=subscores,
        confidence=confidence,
        tier=tier,
        att_pct=getattr(psm, "att_pct", 0) if psm else 0,
        z_value=getattr(psm, "z_value", 0) if psm else 0,
        rosenbaum_gamma=getattr(psm, "rosenbaum_gamma", 0) if psm else 0,
    )


def emit_pipeline_verification(
    guardrails_pass: bool,
    biasbuster_pass: bool,
    *,
    details: list[str] | None = None,
) -> None:
    """Emit pipeline_verification event with optional failure details."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    writer.send_event(
        "pipeline_verification",
        guardrails_pass=guardrails_pass,
        biasbuster_pass=biasbuster_pass,
        details=details or [],
    )


def emit_feedback_loop(iteration: int, confidence: float, threshold: float) -> None:
    """Emit feedback_loop event when confidence loop re-runs."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "feedback_loop",
            iteration=iteration,
            confidence=confidence,
            threshold=threshold,
        )
        return
    console.print(
        f"  [dim]⟳ Feedback loop iteration {iteration}:"
        f" confidence {confidence:.1f}% < {threshold:.1f}%[/dim]"
    )


def emit_node_skipped(node: str, reason: str) -> None:
    """Emit node_skipped event when pipeline node is dynamically skipped."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("node_skipped", node=node, reason=reason)
        return
    console.print(f"  [dim]⤳ Node skipped: {node} ({reason})[/dim]")


def _fmt_tokens(n: int) -> str:
    """Format token count: 1200 → 1.2k, 500 → 500."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)
