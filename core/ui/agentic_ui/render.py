"""Render functions for tool calls, results, tokens, plans, sub-agents, status."""

from __future__ import annotations

import json
from typing import Any

from core.ui.agentic_ui._state import (
    _ipc_writer_local,
    get_session_meter,
)
from core.ui.event_renderer import _fmt_tokens


def render_tool_call(tool_name: str, tool_input: dict[str, Any]) -> None:
    """Render a tool invocation line (Claude Code style)."""
    from core.ui import agentic_ui as _pkg

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
    _pkg.console.print(f"  [tool_name]▸ {tool_name}[/tool_name]([tool_args]{args_str}[/tool_args])")


def render_tool_result(tool_name: str, result: dict[str, Any]) -> None:
    """Render a tool completion line with key result info."""
    from core.ui import agentic_ui as _pkg

    if result.get("error"):
        _pkg.console.print(f"  [error]✗ {tool_name}[/error] — {result['error']}")
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
    _pkg.console.print(f"  [success]✓ {tool_name}[/success] → {summary}")


def render_tokens(
    model: str,
    input_tokens: int,
    output_tokens: int,
    elapsed_s: float | None = None,
    cost_usd: float | None = None,
) -> None:
    """Render token usage line (Claude Code ✢ style)."""
    from core.ui import agentic_ui as _pkg

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
    _pkg.console.print(line)


def render_session_cost_summary() -> None:
    """Render cumulative session cost summary."""
    from core.ui import agentic_ui as _pkg

    try:
        from core.llm.router import get_usage_accumulator

        acc = get_usage_accumulator()
        if not acc.calls:
            return
        _pkg.console.print()
        _pkg.console.print("  [bold]Session Cost Summary[/bold]")
        _pkg.console.print(f"  [dim]Calls:[/dim] {len(acc.calls)}")
        in_str = _fmt_tokens(acc.total_input_tokens)
        out_str = _fmt_tokens(acc.total_output_tokens)
        _pkg.console.print(f"  [dim]Tokens:[/dim] ↓{in_str} ↑{out_str}")
        _pkg.console.print(f"  [warning]Total: ${acc.total_cost_usd:.4f}[/warning]")
        # Per-model breakdown
        model_costs: dict[str, float] = {}
        model_calls: dict[str, int] = {}
        for u in acc.calls:
            model_costs[u.model] = model_costs.get(u.model, 0) + u.cost_usd
            model_calls[u.model] = model_calls.get(u.model, 0) + 1
        if len(model_costs) > 1:
            for m, c in sorted(model_costs.items(), key=lambda x: -x[1]):
                _pkg.console.print(f"    [dim]{m}:[/dim] ${c:.4f} ({model_calls[m]} calls)")
        _pkg.console.print()
    except Exception:
        return  # accumulator not available yet


def render_plan_steps(subject_id: str, steps: list[str]) -> None:
    """Render a plan summary (Claude Code ● style)."""
    from core.ui import agentic_ui as _pkg

    _pkg.console.print()
    _pkg.console.print(f"  [header]● Plan: {subject_id}[/header]")
    for i, step in enumerate(steps, 1):
        _pkg.console.print(f"    [plan_step]{i}. {step}[/plan_step]")
    _pkg.console.print()


def render_progress_plan(plan: list[dict[str, str]], *, explanation: str = "") -> None:
    """Render a non-blocking progress checklist."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("progress_plan", plan=plan, explanation=explanation)
        return

    from core.ui import spinner_glyph

    # Same todo visual language as the IPC plan surface (EventRenderer):
    # checked-off / rose GEODE mark on the active step / quiet pending.
    status_style = {
        "pending": ("○", "dim", "dim"),
        "in_progress": (spinner_glyph.GLYPH, f"bold {spinner_glyph.ROSE_HEX}", "bold"),
        "completed": ("✓", "success", "dim strike"),
    }
    _pkg.console.print()
    header = "Plan"
    if explanation:
        header = f"Plan · {explanation}"
    _pkg.console.print(f"  [header]{header}[/header]")
    for item in plan:
        status = item.get("status", "pending")
        symbol, style, text_style = status_style.get(status, ("○", "dim", "dim"))
        step = item.get("step", "")
        _pkg.console.print(f"    [{style}]{symbol}[/{style}] [{text_style}]{step}[/{text_style}]")
    _pkg.console.print()


def render_subagent_dispatch(task_id: str, task_type: str, description: str) -> None:
    """Render a sub-agent delegation line."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("subagent_dispatch", task_id=task_id, description=description)
        return
    _pkg.console.print(f'  [subagent]▸ delegate_task[/subagent]({task_type}, "{description}")')


def render_subagent_progress(
    completed: int, total: int, latest_name: str, latest_time: float
) -> None:
    """Render sub-agent progress with counter."""
    from core.ui import agentic_ui as _pkg

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
    _pkg.console.print(
        f"  [dim]⎿[/dim] [success]✓[/success] {latest_name} ({latest_time:.1f}s)"
        f"  [{completed}/{total}]"
    )


def render_subagent_complete(count: int, elapsed_s: float) -> None:
    """Render sub-agent batch completion."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("subagent_complete", count=count, elapsed_s=round(elapsed_s, 1))
        return
    _pkg.console.print(f"  [success]✓ {count} sub-agents completed[/success] ({elapsed_s:.1f}s)")
    _pkg.console.print()


def render_status_line() -> None:
    """Render Claude Code-style status line after each agentic result.

    Shows **per-turn** metrics (elapsed, tokens, cost, context %) so that
    each user turn gets an independent measurement — matching Claude Code's
    behaviour where the timer and counters reset every turn.

    Format: ✢ Worked for 2s · claude-opus-4-6 · ↓1.2k ↑350 · $0.003 · 1% context
    """
    from core.ui import agentic_ui as _pkg

    meter = get_session_meter()
    if meter is None:
        return
    try:
        from core.llm.token_tracker import get_tracker

        tracker = get_tracker()

        # Per-turn delta: if a snapshot was taken before agentic.run(),
        # compute delta; otherwise fall back to cumulative (first turn).
        snap = _pkg._turn_snapshot
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
        _pkg.console.print(f"\n  [dim]{line}[/dim]")
    except Exception:
        # Fallback: just show elapsed time
        _pkg.console.print(f"\n  [dim]✢ Worked for {meter.turn_elapsed_display}[/dim]")


def render_context_event(
    event_type: str,
    *,
    original_count: int = 0,
    new_count: int = 0,
) -> None:
    """Render context compression notification with detail."""
    from core.ui import agentic_ui as _pkg

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
        _pkg.console.print(
            "  [warning]⟳ Context exhausted — pruning could not free enough space[/warning]"
        )
        return
    label = "compacted" if event_type == "compact" else "pruned"
    tok_str = f", ~{tokens_est // 1000}k tokens freed" if tokens_est >= 1000 else ""
    _pkg.console.print(
        f"  [dim]⟳ Context {label}: {original_count} → {new_count} messages"
        f" ({removed} removed{tok_str})[/dim]"
    )
