"""Client-side event renderer — direct terminal rendering for all IPC events.

Handles structured events from serve (tool_start/end, tokens, thinking,
round_start, context_event, subagent, turn_end) and renders them with
spinners, in-place ✓ updates, and ANSI styling.

Replaces raw console stream for agentic UI — client owns all rendering.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

from core.cli.ui.tool_tracker import ToolCallTracker


def _fmt_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class EventRenderer:
    """Dispatches IPC events to appropriate rendering handlers."""

    def __init__(self) -> None:
        self._tool_tracker = ToolCallTracker()
        self._thinking = False
        self._thinking_thread: threading.Thread | None = None
        self._thinking_model = ""
        self._thinking_round = 0
        self._round_header_printed = False
        self._out = sys.stdout

    def on_event(self, event: dict[str, Any]) -> None:
        """Handle a structured event from serve."""
        etype = str(event.get("type", ""))
        handler = getattr(self, f"_handle_{etype}", None)
        if handler:
            handler(event)

    def on_stream(self, data: str) -> None:
        """Handle raw console stream (Rich panels, pipeline output)."""
        self._stop_thinking()
        self._tool_tracker.stop()
        self._out.write(data)
        self._out.flush()

    def stop(self) -> None:
        """Flush all pending state."""
        self._stop_thinking()
        self._tool_tracker.stop()

    # -- Event handlers -------------------------------------------------------

    def _handle_round_start(self, event: dict[str, Any]) -> None:
        if not self._round_header_printed:
            self._round_header_printed = True
            self._out.write("\n\033[1m● AgenticLoop\033[0m\n")
            self._out.flush()

    def _handle_thinking_start(self, event: dict[str, Any]) -> None:
        self._tool_tracker.stop()
        self._thinking = True
        self._thinking_model = str(event.get("model", ""))
        self._thinking_round = int(event.get("round", 1))
        self._thinking_thread = threading.Thread(target=self._animate_thinking, daemon=True)
        self._thinking_thread.start()

    def _handle_thinking_end(self, _event: dict[str, Any]) -> None:
        self._stop_thinking()

    def _handle_tool_start(self, event: dict[str, Any]) -> None:
        self._stop_thinking()
        self._tool_tracker.on_tool_start(event)

    def _handle_tool_end(self, event: dict[str, Any]) -> None:
        self._tool_tracker.on_tool_end(event)

    def _handle_tokens(self, event: dict[str, Any]) -> None:
        self._stop_thinking()
        self._tool_tracker.stop()
        model = str(event.get("model", ""))
        in_tok = int(event.get("input", 0))
        out_tok = int(event.get("output", 0))
        cost = float(event.get("cost", 0))
        in_str = _fmt_tokens(in_tok)
        out_str = _fmt_tokens(out_tok)
        cost_str = f" · ${cost:.4f}" if cost > 0 else ""
        self._out.write(f"  \033[2m✢ {model} · ↓{in_str} ↑{out_str}{cost_str}\033[0m\n")
        self._out.flush()

    def _handle_turn_end(self, event: dict[str, Any]) -> None:
        rounds = int(event.get("rounds", 0))
        tools = int(event.get("tools", 0))
        elapsed = float(event.get("elapsed_s", 0))
        cost = float(event.get("cost", 0))
        if tools == 0:
            return
        parts = [f"{rounds} rounds", f"{tools} tools", f"{elapsed:.1f}s"]
        if cost > 0:
            parts.append(f"${cost:.3f}")
        summary = " · ".join(parts)
        self._out.write(f"\n  \033[2m──── {summary} ────\033[0m\n")
        self._out.flush()

    def _handle_context_event(self, event: dict[str, Any]) -> None:
        action = str(event.get("action", ""))
        before = int(event.get("before", 0))
        after = int(event.get("after", 0))
        if action == "exhausted":
            self._out.write("  \033[1;33m⟳ Context exhausted\033[0m\n")
        else:
            label = "compacted" if action == "compact" else "pruned"
            self._out.write(f"  \033[2m⟳ Context {label}: {before} → {after} messages\033[0m\n")
        self._out.flush()

    def _handle_subagent_dispatch(self, event: dict[str, Any]) -> None:
        desc = str(event.get("description", ""))
        self._out.write(f'  \033[34;1m▸ delegate_task\033[0m("{desc}")\n')
        self._out.flush()

    def _handle_subagent_progress(self, event: dict[str, Any]) -> None:
        completed = int(event.get("completed", 0))
        total = int(event.get("total", 0))
        name = str(event.get("name", ""))
        dur = float(event.get("duration_s", 0))
        self._out.write(
            f"  \033[2m⎿\033[0m \033[32m✓\033[0m {name} ({dur:.1f}s)  [{completed}/{total}]\n"
        )
        self._out.flush()

    def _handle_subagent_complete(self, event: dict[str, Any]) -> None:
        count = int(event.get("count", 0))
        elapsed = float(event.get("elapsed_s", 0))
        self._out.write(f"  \033[32m✓ {count} sub-agents completed\033[0m ({elapsed:.1f}s)\n")
        self._out.flush()

    def _handle_session_cost(self, event: dict[str, Any]) -> None:
        calls = int(event.get("calls", 0))
        in_tok = int(event.get("input", 0))
        out_tok = int(event.get("output", 0))
        cost = float(event.get("cost", 0))
        if calls == 0:
            return
        self._out.write("\n  \033[1mSession Cost Summary\033[0m\n")
        self._out.write(f"  \033[2mCalls:\033[0m {calls}\n")
        self._out.write(f"  \033[2mTokens:\033[0m ↓{_fmt_tokens(in_tok)} ↑{_fmt_tokens(out_tok)}\n")
        self._out.write(f"  \033[1;33mTotal: ${cost:.4f}\033[0m\n")
        breakdown = event.get("breakdown", {})
        if isinstance(breakdown, dict) and len(breakdown) > 1:
            for m, c in sorted(breakdown.items(), key=lambda x: -x[1]):
                self._out.write(f"    \033[2m{m}:\033[0m ${c:.4f}\n")
        self._out.write("\n")
        self._out.flush()

    # -- AgenticLoop state change events --------------------------------------

    def _handle_model_escalation(self, event: dict[str, Any]) -> None:
        frm = str(event.get("from_model", ""))
        to = str(event.get("to_model", ""))
        n = int(event.get("failures", 0))
        self._out.write(
            f"  \033[1;33m⚡ Model escalated: {frm} → {to} (after {n} failures)\033[0m\n"
        )
        self._out.flush()

    def _handle_cost_budget_exceeded(self, event: dict[str, Any]) -> None:
        budget = float(event.get("budget", 0))
        actual = float(event.get("actual", 0))
        self._out.write(
            f"  \033[1;31m$ Cost budget exceeded: ${actual:.2f} / ${budget:.2f}\033[0m\n"
        )
        self._out.flush()

    def _handle_time_budget_expired(self, event: dict[str, Any]) -> None:
        budget = float(event.get("budget_s", 0))
        elapsed = float(event.get("elapsed_s", 0))
        rounds = int(event.get("rounds", 0))
        self._out.write(
            f"  \033[1;33m⏱ Time expired: {elapsed:.0f}s / {budget:.0f}s ({rounds} rounds)\033[0m\n"
        )
        self._out.flush()

    def _handle_convergence_detected(self, event: dict[str, Any]) -> None:
        rounds = int(event.get("rounds", 0))
        self._out.write(
            f"  \033[1;31m⟳ Convergence: repeating failure after {rounds} rounds\033[0m\n"
        )
        self._out.flush()

    def _handle_goal_decomposition(self, event: dict[str, Any]) -> None:
        steps = event.get("steps", [])
        self._out.write(f"  \033[2m● Goal decomposed into {len(steps)} steps\033[0m\n")
        for i, s in enumerate(steps[:5], 1):
            self._out.write(f"    \033[2m{i}. {s}\033[0m\n")
        self._out.flush()

    def _handle_tool_backpressure(self, event: dict[str, Any]) -> None:
        n = int(event.get("consecutive_errors", 0))
        self._out.write(f"  \033[1;33m⏸ Backpressure: {n} consecutive tool errors\033[0m\n")
        self._out.flush()

    def _handle_tool_diversity_forced(self, event: dict[str, Any]) -> None:
        tool = str(event.get("tool", ""))
        count = int(event.get("count", 0))
        self._out.write(
            f"  \033[1;33m⟳ Diversity: {tool} called {count}x — forcing alternative\033[0m\n"
        )
        self._out.flush()

    def _handle_model_switched(self, event: dict[str, Any]) -> None:
        frm = str(event.get("from_model", ""))
        to = str(event.get("to_model", ""))
        self._out.write(f"  \033[2m⇄ Model: {frm} → {to}\033[0m\n")
        self._out.flush()

    def _handle_checkpoint_saved(self, event: dict[str, Any]) -> None:
        pass  # silent — no user-visible output needed

    # -- Pipeline milestone events --------------------------------------------

    def _handle_pipeline_gather(self, event: dict[str, Any]) -> None:
        name = str(event.get("ip_name", ""))
        year = event.get("release_year", "")
        dau = int(event.get("dau", 0))
        rev = int(event.get("revenue", 0))
        self._out.write(f"  \033[36m▸ GATHER\033[0m {name} ({year}) — DAU={dau:,} Rev=${rev:,}\n")
        self._out.flush()

    def _handle_pipeline_analysis(self, event: dict[str, Any]) -> None:
        analysts = event.get("analysts", [])
        self._out.write(f"  \033[36m▸ ANALYZE\033[0m {len(analysts)} analysts\n")
        for a in analysts:
            name = str(a.get("analyst", ""))
            score = float(a.get("score", 0))
            finding = str(a.get("finding", ""))[:40]
            self._out.write(f"    {name}: {score:.1f} — {finding}\n")
        self._out.flush()

    def _handle_pipeline_evaluation(self, event: dict[str, Any]) -> None:
        evals = event.get("evaluators", {})
        self._out.write(f"  \033[36m▸ EVALUATE\033[0m {len(evals)} evaluators\n")
        if isinstance(evals, dict):
            for key, val in evals.items():
                score = float(val.get("score", 0)) if isinstance(val, dict) else 0
                self._out.write(f"    {key}: {score:.0f}/100\n")
        self._out.flush()

    def _handle_pipeline_score(self, event: dict[str, Any]) -> None:
        score = float(event.get("final_score", 0))
        tier = str(event.get("tier", "?"))
        conf = float(event.get("confidence", 0))
        self._out.write(f"  \033[36m▸ SCORE\033[0m {tier} ({score:.1f})")
        if conf > 0:
            self._out.write(f" · confidence {conf:.1f}%")
        self._out.write("\n")
        self._out.flush()

    def _handle_pipeline_verification(self, event: dict[str, Any]) -> None:
        g = "✓" if event.get("guardrails_pass") else "✗"
        b = "✓" if event.get("biasbuster_pass") else "✗"
        self._out.write(f"  \033[36m▸ VERIFY\033[0m Guardrails {g} | BiasBuster {b}\n")
        self._out.flush()

    def _handle_feedback_loop(self, event: dict[str, Any]) -> None:
        iteration = int(event.get("iteration", 0))
        conf = float(event.get("confidence", 0))
        threshold = float(event.get("threshold", 0))
        self._out.write(
            f"  \033[2m⟳ Feedback loop #{iteration}:"
            f" confidence {conf:.1f}% < {threshold:.1f}%\033[0m\n"
        )
        self._out.flush()

    def _handle_node_skipped(self, event: dict[str, Any]) -> None:
        node = str(event.get("node", ""))
        reason = str(event.get("reason", ""))
        self._out.write(f"  \033[2m⤳ Skipped: {node} ({reason})\033[0m\n")
        self._out.flush()

    # -- Internal helpers -----------------------------------------------------

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def _animate_thinking(self) -> None:
        """Background animation loop for thinking spinner (80ms per frame)."""
        while self._thinking:
            self._render_thinking_frame()
            time.sleep(0.08)

    def _render_thinking_frame(self) -> None:
        if not self._thinking:
            return
        frame = self._FRAMES[int(time.monotonic() * 12) % len(self._FRAMES)]
        r = self._thinking_round
        label = "Thinking..." if r <= 1 else f"Thinking... (round {r})"
        self._out.write(f"\r\033[2K  {frame} \033[2m✢ {label}\033[0m")
        self._out.flush()

    def _stop_thinking(self) -> None:
        if self._thinking:
            self._thinking = False
            if self._thinking_thread:
                self._thinking_thread.join(timeout=0.3)
                self._thinking_thread = None
            self._out.write("\r\033[2K")
            self._out.flush()
