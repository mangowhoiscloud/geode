"""Turn-end summary rendering and per-turn snapshot lifecycle.

The ``_turn_snapshot`` global lives on the package ``__init__.py`` so test
fixtures patching ``core.ui.agentic_ui._turn_snapshot`` flow through; the
functions below read/write it via the package namespace.
"""

from __future__ import annotations

from typing import Any

from core.ui.agentic_ui._state import get_session_meter


def render_turn_summary(rounds: int, tool_count: int, elapsed_s: float, cost: float) -> None:
    """Render compact turn-end summary line.

    Format: ``──── 3 rounds · 8 tools · 4.2s · $0.012 ────``
    Only renders when there is meaningful activity (at least 1 tool call).
    """
    from core.ui import agentic_ui as _pkg

    if tool_count == 0:
        return
    parts = [f"{rounds} rounds", f"{tool_count} tools", f"{elapsed_s:.1f}s"]
    if cost > 0:
        parts.append(f"${cost:.3f}")
    summary = " · ".join(parts)
    _pkg.console.print(f"\n  [dim]──── {summary} ────[/dim]")


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
    from core.ui import agentic_ui as _pkg

    if not tool_calls:
        return ""

    lines: list[str] = []

    # Header
    header_parts = [f"{rounds} rounds", f"{len(tool_calls)} tools", f"{elapsed_s:.1f}s"]
    if cost > 0:
        header_parts.append(f"${cost:.3f}")
    header = " · ".join(header_parts)
    lines.append("──── Action Summary ────")
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

    lines.append("────────────────────────")

    summary_text = "\n".join(lines)

    # Render to console
    for line in lines:
        _pkg.console.print(f"  [dim]{line}[/dim]")

    return summary_text


# ───────────────────────────────────────────────────────────────────────────
# Per-turn snapshot state (set before each agentic.run(), read by render)
# ───────────────────────────────────────────────────────────────────────────
#
# The canonical ``_turn_snapshot`` global lives on the package ``__init__.py``
# so test fixtures patching ``mod._turn_snapshot`` flow through to readers.


def mark_turn_start() -> None:
    """Snapshot current cumulative metrics and reset turn timer.

    Call this before each ``agentic.run()`` so that ``render_status_line()``
    can display per-turn deltas instead of session-cumulative totals.
    """
    from core.ui import agentic_ui as _pkg

    meter = get_session_meter()
    if meter is not None:
        meter.mark_turn_start()
    try:
        from core.llm.token_tracker import get_tracker

        _pkg._turn_snapshot = get_tracker().snapshot()
    except Exception:
        _pkg._turn_snapshot = None
