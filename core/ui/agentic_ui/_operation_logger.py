"""OperationLogger — progressive tree log with auto-collapse."""

from __future__ import annotations

import json
import time
from typing import Any

from core.ui.agentic_ui._state import _ipc_writer_local


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
        from core.ui import agentic_ui as _pkg

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
            _pkg.console.print(f"\n[bold]● {label}[/bold]")

    def log_tool_call(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Log a tool call. Returns True if visible, False if collapsed."""
        from core.ui import agentic_ui as _pkg

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
            _pkg.console.print(
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
        from core.ui import agentic_ui as _pkg

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
            _pkg.console.print(f"  ⎿ [error]✗ {tool_name}[/error] — {result['error']}")
            return
        _pkg.console.print(f"  ⎿ [success]✓ {tool_name}[/success] → {summary}")

    @staticmethod
    def _build_result_summary(tool_name: str, result: dict[str, Any]) -> str:
        """Build a compact summary string from a tool result dict."""
        if result.get("error"):
            return str(result["error"])
        summary_parts: list[str] = []
        # Optional domain-pipeline summary keys.
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
        from core.ui import agentic_ui as _pkg

        # IPC mode — client already renders per-tool ✓ lines
        writer = getattr(_ipc_writer_local, "writer", None)
        if writer is not None:
            return
        if self._total_tool_count >= self.GROUPING_THRESHOLD:
            rounds = max(self._round_count, 1)
            _pkg.console.print(f"  ⎿ [dim]{self._total_tool_count} tools · {rounds} rounds[/dim]")
        elif self._collapsed_count > 0:
            _pkg.console.print(
                f"  ⎿ [dim]+{self._collapsed_count} more tool uses (collapsed)[/dim]"
            )

    def reset(self) -> None:
        """Reset for next run()."""
        self._visible_count = 0
        self._collapsed_count = 0
        self._header_printed = False
        self._tool_type_counts.clear()
        self._tool_type_last_summary.clear()
        self._total_tool_count = 0
        self._round_count = 0
