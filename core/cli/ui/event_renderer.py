"""Client-side event renderer — direct terminal rendering for all IPC events.

Handles structured events from serve (tool_start/end, tokens, thinking,
round_start, context_event, subagent, turn_end, pipeline milestones)
and renders them with spinners, in-place updates, and ANSI styling.

Persistent activity spinner runs from prompt send until result arrives.
Thinking/tool spinners override it; it resumes between events.
Pipeline panels render client-side from structured events (no raw stream).
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
    """Dispatches IPC events to appropriate rendering handlers.

    Lifecycle::

        renderer = EventRenderer()
        renderer.start_activity()            # persistent spinner ON
        result = client.send_prompt(
            text,
            on_stream=renderer.on_stream,
            on_event=renderer.on_event,      # events override spinner
        )
        renderer.stop()                      # everything OFF
    """

    # Events suppressed during repeat mode (same tool called sequentially)
    _REPEAT_SUPPRESSIBLE = frozenset(
        {"tool_start", "tool_end", "tokens", "thinking_start", "thinking_end", "round_start"}
    )

    def __init__(self) -> None:
        self._tool_tracker = ToolCallTracker()
        self._thinking = False
        self._thinking_thread: threading.Thread | None = None
        self._thinking_model = ""
        self._thinking_round = 0
        self._round_header_printed = False
        self._out = sys.stdout
        # Persistent activity spinner state
        self._activity = False
        self._activity_suppressed = False
        self._activity_thread: threading.Thread | None = None
        # Cross-batch repeat counter: collapses sequential same-tool calls
        self._repeat_name: str = ""
        self._repeat_count: int = 0
        self._repeat_dur: float = 0.0
        self._repeat_summary: str = ""
        self._in_repeat: bool = False
        self._last_batch_tool: str = ""  # tool name from last single-tool batch

    # -- Public API -----------------------------------------------------------

    def start_activity(self) -> None:
        """Start persistent activity spinner. Call before send_prompt()."""
        self._activity = True
        self._activity_suppressed = False
        self._activity_thread = threading.Thread(target=self._animate_activity, daemon=True)
        self._activity_thread.start()

    def on_event(self, event: dict[str, Any]) -> None:
        """Handle a structured event from serve."""
        etype = str(event.get("type", ""))

        # Repeat mode: suppress intermediate events for sequential same-tool calls
        if self._in_repeat and etype in self._REPEAT_SUPPRESSIBLE:
            if etype == "tool_start":
                name = str(event.get("name", ""))
                if name == self._repeat_name:
                    return  # same tool again, stay in repeat mode
                self._flush_repeat()  # different tool, flush and handle normally
            elif etype == "tool_end":
                name = str(event.get("name", ""))
                if name == self._repeat_name:
                    self._repeat_count += 1
                    dur = event.get("duration_s")
                    if dur is not None:
                        self._repeat_dur += float(str(dur))
                    self._repeat_summary = str(event.get("summary", "ok"))
                    return  # accumulated, stay in repeat mode
                self._flush_repeat()
            else:
                return  # suppress tokens/thinking/round_start during repeat

        handler = getattr(self, f"_handle_{etype}", None)
        if handler:
            handler(event)

    def on_stream(self, data: str) -> None:
        """Handle raw console stream (Rich panels, pipeline output)."""
        self._suppress_all_spinners()
        self._out.write(data)
        self._out.flush()

    def stop(self) -> None:
        """Stop all spinners. Call when result arrives."""
        self._flush_repeat()
        self._activity = False
        self._activity_suppressed = True
        self._stop_thinking()
        self._tool_tracker.stop()
        if self._activity_thread:
            self._activity_thread.join(timeout=0.3)
            self._activity_thread = None
        # Clear any leftover spinner line
        self._out.write("\r\033[2K")
        self._out.flush()

    # -- Core event handlers --------------------------------------------------

    def _handle_round_start(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        if not self._round_header_printed:
            self._round_header_printed = True
            self._out.write("\n\033[1m\u25cf AgenticLoop\033[0m\n")
            self._out.flush()

    def _handle_thinking_start(self, event: dict[str, Any]) -> None:
        self._activity_suppressed = True
        self._tool_tracker.stop()
        self._thinking = True
        self._thinking_model = str(event.get("model", ""))
        self._thinking_round = int(event.get("round", 1))
        self._thinking_thread = threading.Thread(target=self._animate_thinking, daemon=True)
        self._thinking_thread.start()

    def _handle_thinking_end(self, _event: dict[str, Any]) -> None:
        self._stop_thinking()
        self._activity_suppressed = False  # resume activity spinner

    def _handle_tool_start(self, event: dict[str, Any]) -> None:
        name = str(event.get("name", ""))

        # Detect repeat onset: same tool as last single-tool batch
        if self._last_batch_tool and name == self._last_batch_tool:
            # Enter repeat mode — suppress this tool_start
            self._in_repeat = True
            self._repeat_name = name
            # count/dur/summary already set from last batch's tool_end
            return

        self._activity_suppressed = True
        self._stop_thinking()
        self._tool_tracker.on_tool_start(event)

    def _handle_tool_end(self, event: dict[str, Any]) -> None:
        name = str(event.get("name", ""))
        self._tool_tracker.on_tool_end(event)
        # Resume activity when all tools done
        with self._tool_tracker._lock:
            tools = self._tool_tracker._tools
            all_done = all(t["done"] for t in tools)
            is_single = len(tools) == 1
        if all_done:
            self._activity_suppressed = False
            # Track last single-tool batch for repeat detection
            if is_single:
                dur = event.get("duration_s")
                self._last_batch_tool = name
                self._repeat_count = 1
                self._repeat_dur = float(str(dur)) if dur is not None else 0.0
                self._repeat_summary = str(event.get("summary", "ok"))
            else:
                self._last_batch_tool = ""

    def _handle_tokens(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        model = str(event.get("model", ""))
        in_tok = int(event.get("input", 0))
        out_tok = int(event.get("output", 0))
        cost = float(event.get("cost", 0))
        in_str = _fmt_tokens(in_tok)
        out_str = _fmt_tokens(out_tok)
        cost_str = f" \u00b7 ${cost:.4f}" if cost > 0 else ""
        self._out.write(
            f"  \033[2m\u2722 {model} \u00b7 \u2193{in_str} \u2191{out_str}{cost_str}\033[0m\n"
        )
        self._out.flush()
        self._activity_suppressed = False  # resume after tokens line

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
        summary = " \u00b7 ".join(parts)
        line = f"\u2500\u2500\u2500\u2500 {summary} \u2500\u2500\u2500\u2500"
        self._out.write(f"\n  \033[2m{line}\033[0m\n")
        self._out.flush()

    def _handle_context_event(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        action = str(event.get("action", ""))
        before = int(event.get("before", 0))
        after = int(event.get("after", 0))
        removed = int(event.get("removed", before - after))
        tokens_est = int(event.get("tokens_estimate", removed * 250))
        if action == "exhausted":
            self._out.write("  \033[1;33m\u27f3 Context exhausted\033[0m\n")
        else:
            label = "compacted" if action == "compact" else "pruned"
            tok_str = f", ~{tokens_est // 1000}k tokens freed" if tokens_est >= 1000 else ""
            self._out.write(
                f"  \033[2m\u27f3 Context {label}: {before} \u2192 {after} messages"
                f" ({removed} removed{tok_str})\033[0m\n"
            )
        self._out.flush()

    def _handle_subagent_dispatch(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        desc = str(event.get("description", ""))
        self._out.write(f'  \033[34;1m\u25b8 delegate_task\033[0m("{desc}")\n')
        self._out.flush()

    def _handle_subagent_progress(self, event: dict[str, Any]) -> None:
        completed = int(event.get("completed", 0))
        total = int(event.get("total", 0))
        name = str(event.get("name", ""))
        dur = float(event.get("duration_s", 0))
        mark = "\033[2m\u23bf\033[0m \033[32m\u2713\033[0m"
        self._out.write(f"  {mark} {name} ({dur:.1f}s)  [{completed}/{total}]\n")
        self._out.flush()

    def _handle_subagent_complete(self, event: dict[str, Any]) -> None:
        count = int(event.get("count", 0))
        elapsed = float(event.get("elapsed_s", 0))
        self._out.write(f"  \033[32m\u2713 {count} sub-agents completed\033[0m ({elapsed:.1f}s)\n")
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
        self._out.write(
            f"  \033[2mTokens:\033[0m \u2193{_fmt_tokens(in_tok)} \u2191{_fmt_tokens(out_tok)}\n"
        )
        self._out.write(f"  \033[1;33mTotal: ${cost:.4f}\033[0m\n")
        breakdown = event.get("breakdown", {})
        if isinstance(breakdown, dict) and len(breakdown) > 1:
            for m, c in sorted(breakdown.items(), key=lambda x: -x[1]):
                self._out.write(f"    \033[2m{m}:\033[0m ${c:.4f}\n")
        self._out.write("\n")
        self._out.flush()

    # -- AgenticLoop state change events --------------------------------------

    def _handle_budget_warning(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        budget = float(event.get("budget", 0))
        actual = float(event.get("actual", 0))
        pct = float(event.get("pct", 0))
        self._out.write(
            f"  \033[1;33m$ Budget warning: ${actual:.2f} / ${budget:.2f}"
            f" ({pct:.0f}% used)\033[0m\n"
        )
        self._out.flush()

    def _handle_retry_wait(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        model = str(event.get("model", ""))
        attempt = int(event.get("attempt", 0))
        max_r = int(event.get("max_retries", 0))
        delay = float(event.get("delay_s", 0))
        elapsed = float(event.get("elapsed_s", 0))
        self._out.write(
            f"  \033[1;33m~ Retrying in {delay:.1f}s... "
            f"[{model} \u00b7 {attempt}/{max_r} \u00b7 {elapsed:.0f}s elapsed] "
            f"(Ctrl+C to skip)\033[0m\n"
        )
        self._out.flush()

    def _handle_llm_error(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        severity = str(event.get("severity", "warning"))
        hint = str(event.get("hint", "LLM error"))
        model = str(event.get("model", ""))
        elapsed = float(event.get("elapsed_s", 0))
        # Severity -> ANSI color: critical/error=31(red), warning=33(yellow), info=2(dim)
        color = {"critical": "1;31", "error": "1;31", "warning": "1;33"}.get(severity, "2")
        symbol = {"critical": "!!", "error": "!", "warning": "~"}.get(severity, "\u00b7")
        suffix = f" [{model} \u00b7 {elapsed:.1f}s]" if model else ""
        self._out.write(f"  \033[{color}m{symbol} {hint}{suffix}\033[0m\n")
        self._out.flush()

    def _handle_model_escalation(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        frm = str(event.get("from_model", ""))
        to = str(event.get("to_model", ""))
        n = int(event.get("failures", 0))
        self._out.write(
            f"  \033[1;33m\u26a1 Model escalated: {frm} \u2192 {to} (after {n} failures)\033[0m\n"
        )
        self._out.flush()

    def _handle_cost_budget_exceeded(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        budget = float(event.get("budget", 0))
        actual = float(event.get("actual", 0))
        self._out.write(
            f"  \033[1;31m$ Cost budget exceeded: ${actual:.2f} / ${budget:.2f}\033[0m\n"
        )
        self._out.flush()

    def _handle_time_budget_expired(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        budget = float(event.get("budget_s", 0))
        elapsed = float(event.get("elapsed_s", 0))
        rounds = int(event.get("rounds", 0))
        self._out.write(
            f"  \033[1;33m\u23f1 Time expired: {elapsed:.0f}s / {budget:.0f}s"
            f" ({rounds} rounds)\033[0m\n"
        )
        self._out.flush()

    def _handle_convergence_detected(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        rounds = int(event.get("rounds", 0))
        self._out.write(
            f"  \033[1;31m\u27f3 Convergence: repeating failure after {rounds} rounds\033[0m\n"
        )
        self._out.flush()

    def _handle_goal_decomposition(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        steps = event.get("steps", [])
        self._out.write(f"  \033[2m\u25cf Goal decomposed into {len(steps)} steps\033[0m\n")
        for i, s in enumerate(steps[:5], 1):
            self._out.write(f"    \033[2m{i}. {s}\033[0m\n")
        self._out.flush()

    def _handle_tool_backpressure(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        n = int(event.get("consecutive_errors", 0))
        self._out.write(f"  \033[1;33m\u23f8 Backpressure: {n} consecutive tool errors\033[0m\n")
        self._out.flush()

    def _handle_tool_diversity_forced(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        tool = str(event.get("tool", ""))
        count = int(event.get("count", 0))
        self._out.write(
            f"  \033[1;33m\u27f3 Diversity: {tool} called {count}x"
            " \u2014 forcing alternative\033[0m\n"
        )
        self._out.flush()

    def _handle_model_switched(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        frm = str(event.get("from_model", ""))
        to = str(event.get("to_model", ""))
        self._out.write(f"  \033[2m\u21c4 Model: {frm} \u2192 {to}\033[0m\n")
        self._out.flush()

    def _handle_checkpoint_saved(self, event: dict[str, Any]) -> None:
        pass  # silent — no user-visible output needed

    # -- Pipeline milestone events (client-side rendering) --------------------

    def _handle_pipeline_header(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        ip = str(event.get("ip_name", ""))
        mode = str(event.get("pipeline_mode", ""))
        model = str(event.get("model", ""))
        ver = str(event.get("version", ""))
        self._out.write(f"\n  \033[1;36mGEODE v{ver}\033[0m\n")
        self._out.write(f"  Analyzing: \033[1m{ip}\033[0m\n")
        self._out.write(f"  Pipeline: {mode} | Model: {model}\n\n")
        self._out.flush()

    def _handle_pipeline_gather(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        name = str(event.get("ip_name", ""))
        year = event.get("release_year", "")
        media = str(event.get("media_type", ""))
        studio = str(event.get("studio", ""))
        dau = int(event.get("dau", 0))
        rev = int(event.get("revenue", 0))
        self._out.write(f"  \033[36;1m\u25b8 GATHER\033[0m {name}")
        if media or year:
            self._out.write(f" ({media}, {year})")
        if studio:
            self._out.write(f" \u2014 {studio}")
        self._out.write("\n")
        if dau or rev:
            dau_s = f"{dau:,}" if dau else "n/a"
            rev_s = f"${rev:,}" if rev else "n/a"
            self._out.write(f"    \033[2mDAU={dau_s} | Revenue={rev_s}\033[0m\n")
        self._out.flush()

    def _handle_pipeline_analysis(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        analysts = event.get("analysts", [])
        self._out.write(f"  \033[36;1m\u25b8 ANALYZE\033[0m {len(analysts)} analysts\n")
        for a in analysts:
            name = str(a.get("analyst", ""))
            score = float(a.get("score", 0))
            finding = str(a.get("finding", ""))[:50]
            color = "32" if score >= 4.0 else "33" if score >= 3.0 else "31"
            self._out.write(f"    {name:<18} \033[{color}m{score:.1f}\033[0m  {finding}\n")
        self._out.flush()

    def _handle_pipeline_evaluation(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        evals = event.get("evaluators", {})
        self._out.write(f"  \033[36;1m\u25b8 EVALUATE\033[0m {len(evals)} evaluators\n")
        if isinstance(evals, dict):
            labels = {
                "quality_judge": "Quality",
                "hidden_value": "Hidden",
                "community_momentum": "Momentum",
            }
            for key, val in sorted(evals.items()):
                label = labels.get(key, key.replace("_", " ").title())
                score = float(val.get("score", 0)) if isinstance(val, dict) else 0
                rationale = str(val.get("rationale", ""))[:50] if isinstance(val, dict) else ""
                color = "32" if score >= 80 else "33" if score >= 60 else "31"
                self._out.write(
                    f"    {label:<18} \033[{color}m{score:.0f}/100\033[0m  {rationale}\n"
                )
        self._out.flush()

    def _handle_pipeline_score(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        score = float(event.get("final_score", 0))
        tier = str(event.get("tier", "?"))
        conf = float(event.get("confidence", 0))
        subscores = event.get("subscores", {})
        # Tier color
        tier_color = {"S": "1;35", "A": "1;32", "B": "1;33", "C": "1;31"}.get(tier, "1")
        self._out.write(
            f"  \033[36;1m\u25b8 SCORE\033[0m \033[{tier_color}m{tier}\033[0m ({score:.1f}/100)"
        )
        if conf > 0:
            self._out.write(f" \u00b7 confidence {conf:.1f}%")
        self._out.write("\n")
        # Subscores
        if isinstance(subscores, dict) and subscores:
            parts = [f"{k}={v:.1f}" for k, v in subscores.items()]
            self._out.write(f"    \033[2m{' | '.join(parts)}\033[0m\n")
        self._out.flush()

    def _handle_pipeline_verification(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        g = "\033[32m\u2713\033[0m" if event.get("guardrails_pass") else "\033[31m\u2717\033[0m"
        b = "\033[32m\u2713\033[0m" if event.get("biasbuster_pass") else "\033[31m\u2717\033[0m"
        self._out.write(f"  \033[36;1m\u25b8 VERIFY\033[0m Guardrails {g} | BiasBuster {b}\n")
        self._out.flush()

    def _handle_feedback_loop(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        iteration = int(event.get("iteration", 0))
        conf = float(event.get("confidence", 0))
        threshold = float(event.get("threshold", 0))
        self._out.write(
            f"  \033[2m\u27f3 Feedback loop #{iteration}:"
            f" confidence {conf:.1f}% < {threshold:.1f}%\033[0m\n"
        )
        self._out.flush()

    def _handle_node_skipped(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        node = str(event.get("node", ""))
        reason = str(event.get("reason", ""))
        self._out.write(f"  \033[2m\u2933 Skipped: {node} ({reason})\033[0m\n")
        self._out.flush()

    def _handle_pipeline_result(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        tier = str(event.get("tier", "?"))
        score = float(event.get("final_score", 0))
        cause = str(event.get("cause", ""))
        narrative = str(event.get("narrative", ""))
        segment = str(event.get("target_segment", ""))
        action = str(event.get("action", "")).replace("_", " ").title()
        tier_color = {"S": "1;35", "A": "1;32", "B": "1;33", "C": "1;31"}.get(tier, "1")
        self._out.write("\n  \033[36;1m\u25b8 RESULT\033[0m\n")
        self._out.write(f"    \033[{tier_color}m{tier}\033[0m  {score:.1f} pts  |  {cause}\n")
        if narrative:
            self._out.write(f"    {narrative}\n")
        if segment:
            self._out.write(f"    \033[2mTarget:\033[0m {segment}\n")
        if action:
            self._out.write(f"    \033[2mAction:\033[0m {action}\n")
        self._out.write("\n")
        self._out.flush()

    # -- Repeat mode helpers ---------------------------------------------------

    def _flush_repeat(self) -> None:
        """Emit accumulated repeat summary and exit repeat mode."""
        if not self._in_repeat:
            return
        name = self._repeat_name
        count = self._repeat_count
        dur = self._repeat_dur
        summary = self._repeat_summary
        self._in_repeat = False
        self._repeat_name = ""
        self._last_batch_tool = ""
        if count <= 1:
            return
        self._clear_activity_line()
        dur_str = f" ({dur:.1f}s)" if dur > 0 else ""
        self._out.write(
            f"  \033[32m\u2713 {name}\033[0m"
            f" \u00d7{count} \u2192 {summary}{dur_str}\n"
        )
        self._out.flush()

    # -- Internal helpers -----------------------------------------------------

    _FRAMES = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"

    def _animate_activity(self) -> None:
        """Persistent activity spinner — runs until stop() is called."""
        while self._activity:
            if not self._activity_suppressed:
                frame = self._FRAMES[int(time.monotonic() * 12) % len(self._FRAMES)]
                self._out.write(f"\r\033[2K  {frame} \033[2mWorking...\033[0m")
                self._out.flush()
            time.sleep(0.08)

    def _animate_thinking(self) -> None:
        """Thinking spinner — overrides activity spinner."""
        while self._thinking:
            self._render_thinking_frame()
            time.sleep(0.08)

    def _render_thinking_frame(self) -> None:
        if not self._thinking:
            return
        frame = self._FRAMES[int(time.monotonic() * 12) % len(self._FRAMES)]
        r = self._thinking_round
        label = "Thinking..." if r <= 1 else f"Thinking... (round {r})"
        self._out.write(f"\r\033[2K  {frame} \033[2m\u2722 {label}\033[0m")
        self._out.flush()

    def _stop_thinking(self) -> None:
        if self._thinking:
            self._thinking = False
            if self._thinking_thread:
                self._thinking_thread.join(timeout=0.3)
                self._thinking_thread = None
            self._out.write("\r\033[2K")
            self._out.flush()

    def _suppress_all_spinners(self) -> None:
        """Stop thinking + tool spinners, clear line for new content."""
        self._activity_suppressed = True
        self._stop_thinking()
        self._tool_tracker.stop()
        self._out.write("\r\033[2K")
        self._out.flush()

    def _clear_activity_line(self) -> None:
        """Clear the activity spinner line before writing a permanent line."""
        if self._activity and not self._activity_suppressed:
            self._out.write("\r\033[2K")
            self._out.flush()
