"""Client-side event renderer — direct terminal rendering for all IPC events.

Handles structured events from serve (tool_start/end, tokens, thinking,
round_start, context_event, subagent, turn_end, pipeline milestones)
and renders them with spinners, in-place updates, and ANSI styling.

Persistent activity spinner runs from prompt send until result arrives.
Thinking/tool spinners override it; it resumes between events.
Pipeline panels render client-side from structured events (no raw stream).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import select
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core.time_format import format_elapsed
from core.ui.tool_tracker import ToolCallTracker

log = logging.getLogger(__name__)

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_MARKDOWN_TEXT_MARKER = re.compile(
    r"(\*\*[^*\n][\s\S]*?\*\*|__[^_\n][\s\S]*?__|`[^`\n]+`|^#{1,6}\s|\n#{1,6}\s)"
)


def _fmt_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


@dataclass
class _ThinkingRegion:
    start_ts: float
    items: list[str] = field(default_factory=list)
    visible_lines: list[str] = field(default_factory=list)
    is_collapsed: bool = False
    ended: bool = False


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
        self._thinking_region: _ThinkingRegion | None = None
        self._render_lock = threading.RLock()
        self._tty = sys.stdout.isatty()
        self._stdin_stop = threading.Event()
        self._stdin_thread: threading.Thread | None = None
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
        # Accumulated turn metrics — rendered once at stop()
        self._turn_start: float = time.monotonic()
        self._turn_model: str = ""
        self._turn_in_tokens: int = 0
        self._turn_out_tokens: int = 0
        self._turn_cost: float = 0.0
        # Raw daemon console output is normally Rich/status UI. If the daemon
        # accidentally streams plain assistant Markdown, keep enough state to
        # erase that transient region before final Markdown rendering happens.
        self._clearable_stream_parts: list[str] = []

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
            self._reset_clearable_stream_region()
            handler(event)

    def on_stream(self, data: str) -> None:
        """Handle raw console stream (Rich panels, pipeline output)."""
        self._suppress_all_spinners()
        if self._is_clearable_plain_stream(data):
            self._clearable_stream_parts.append(data)
        else:
            self._reset_clearable_stream_region()
        self._out.write(data)
        self._out.flush()

    def stop(self) -> None:
        """Stop all spinners and render turn status. Call when result arrives."""
        self._flush_repeat()
        self._stop_stdin_reader()
        self._activity = False
        self._activity_suppressed = True
        self._stop_thinking()
        self._tool_tracker.stop()
        if self._activity_thread:
            self._activity_thread.join(timeout=0.3)
            self._activity_thread = None
        # Clear any leftover spinner line
        self._out.write("\r\033[2K")
        self._clear_markdown_stream_region()
        self._out.flush()
        # Render accumulated turn status (Claude Code style)
        self._render_turn_status()

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
        with self._render_lock:
            self._thinking_region = _ThinkingRegion(start_ts=time.monotonic())
            self._thinking = True
            self._thinking_model = str(event.get("model", ""))
            self._thinking_round = int(event.get("round", 1))
        self._start_stdin_reader()
        self._thinking_thread = threading.Thread(target=self._animate_thinking, daemon=True)
        self._thinking_thread.start()

    def _handle_thinking_end(self, _event: dict[str, Any]) -> None:
        self._stop_thinking()
        with self._render_lock:
            region = self._thinking_region
            if region:
                region.ended = True
                if self._tty:
                    self._collapse_thinking_region_locked(region, still_running=False)
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
        # Accumulate per-turn — rendered once at stop() as a single status line
        self._turn_model = str(event.get("model", "")) or self._turn_model
        self._turn_in_tokens += int(event.get("input", 0))
        self._turn_out_tokens += int(event.get("output", 0))
        self._turn_cost += float(event.get("cost", 0))

    def _handle_turn_end(self, event: dict[str, Any]) -> None:
        # Render accumulated status line (Claude Code style)
        self._render_turn_status()

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
        in_str = _fmt_tokens(in_tok)
        out_str = _fmt_tokens(out_tok)
        self._out.write(
            f"\n  \033[2mSession: {calls} calls \u00b7 "
            f"\u2193{in_str} \u2191{out_str} \u00b7 "
            f"\033[0m\033[1;33m${cost:.4f}\033[0m\n\n"
        )
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

    def _handle_reasoning_summary(self, event: dict[str, Any]) -> None:
        """v0.57.0 R6 — render a model's reasoning-summary chunk.

        Per-item granularity (not per-delta). Shown as a muted single
        line; full text is in the IPC event payload for any client that
        wants to display the complete summary.
        """
        text = str(event.get("text", "")).strip().replace("\n", " ")
        if len(text) > 240:
            text = text[:237] + "…"
        if not text:
            return
        # ANSI 90 = bright black (muted); matches console.print muted style.
        line = f"  \033[90m∙ thinking · {text}\033[0m\n"
        with self._render_lock:
            self._clear_activity_line()
            region = self._thinking_region
            if region:
                region.items.append(line)
                if region.is_collapsed and self._tty:
                    return
                region.visible_lines.append(line)
            self._out.write(line)
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

    def _handle_model_switch_required(self, event: dict[str, Any]) -> None:
        """Render the v0.90.0 model_switch_required event.

        Replaces ``_handle_model_escalation`` (which surfaced the silent
        auto-swap that no longer happens). The user picks the next model
        manually with ``/model``.
        """
        self._clear_activity_line()
        model = str(event.get("model", ""))
        error_type = str(event.get("error_type", "unknown"))
        attempts = int(event.get("attempts", 0))
        suggestions = event.get("suggested_models") or []
        suffix = (
            f" \u2014 try /model {' | '.join(suggestions)}" if suggestions else " \u2014 run /model"
        )
        self._out.write(
            f"  \033[1;33m\u2715 Model switch required: {model} hit {error_type} "
            f"after {attempts} attempts{suffix}\033[0m\n"
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
        # v0.50.0: surface the reason so users can tell quota exhaustion
        # ("rate_limit") apart from context overflow ("failure_escalation").
        # Pre-0.50 the bare arrow left users guessing why the model changed
        # mid-turn.
        reason = str(event.get("reason", ""))
        suffix = f"  ({reason})" if reason else ""
        self._out.write(f"  \033[2m\u21c4 Model: {frm} \u2192 {to}{suffix}\033[0m\n")
        self._out.flush()

    def _handle_checkpoint_saved(self, event: dict[str, Any]) -> None:
        pass  # silent — no user-visible output needed

    # -- OAuth device-code events (v0.51.1 IPC parity) ------------------------

    def _handle_oauth_login_started(self, event: dict[str, Any]) -> None:
        """Render the device-code prompt with URL + user code highlighted.

        Also spawns a daemon thread that opens the verification URI in the
        user's default browser the first time stdin yields a line (typically
        Enter). The daemon dies with the process — no explicit cleanup
        needed.
        """
        self._suppress_all_spinners()
        provider = str(event.get("provider", ""))
        uri = str(event.get("verification_uri", ""))
        code = str(event.get("user_code", ""))
        self._out.write("\n")
        self._out.write(f"  \033[1;36m{provider} OAuth Login\033[0m\n")
        self._out.write("\n")
        self._out.write("  1. Open this URL in your browser:\n")
        self._out.write(f"     \033[94m{uri}\033[0m\n")
        self._out.write("\n")
        self._out.write("  2. Enter this code:\n")
        self._out.write(f"     \033[1;93m{code}\033[0m\n")
        self._out.write("\n")
        if uri:
            self._out.write("  \033[2mPress [Enter] to open the URL in your browser.\033[0m\n")
            from core.ui.oauth_browser import start_oauth_browser_watcher

            start_oauth_browser_watcher(uri)
        self._out.write("  \033[2mWaiting for sign-in... (Ctrl+C to cancel)\033[0m\n")
        self._out.flush()

    def _handle_oauth_login_pending(self, event: dict[str, Any]) -> None:
        """Heartbeat — overwrite a single 'Waiting…' line in place."""
        elapsed = int(event.get("elapsed_s", 0))
        self._out.write(f"\r  \033[2mWaiting... ({elapsed}s)\033[0m\033[K")
        self._out.flush()

    def _handle_oauth_login_success(self, event: dict[str, Any]) -> None:
        provider = str(event.get("provider", ""))
        email = str(event.get("email", ""))
        account_id = str(event.get("account_id", ""))
        plan_type = str(event.get("plan_type", ""))
        stored_at = str(event.get("stored_at", ""))
        # Wipe the heartbeat line, then announce success.
        self._out.write("\r\033[2K\n")
        self._out.write(f"  \033[1;32m✓ {provider} login successful\033[0m\n")
        if email or account_id:
            self._out.write(f"  \033[2m  Account:\033[0m {email or account_id}\n")
        if plan_type:
            self._out.write(f"  \033[2m  Plan:\033[0m {plan_type}\n")
        if stored_at:
            self._out.write(f"  \033[2m  Stored:\033[0m {stored_at}\n")
        self._out.write("\n")
        self._out.flush()

    def _handle_oauth_login_failed(self, event: dict[str, Any]) -> None:
        provider = str(event.get("provider", ""))
        reason = str(event.get("reason", ""))
        self._out.write("\r\033[2K\n")
        self._out.write(f"  \033[1;31m✗ {provider} login failed:\033[0m {reason}\n\n")
        self._out.flush()

    # -- Billing error (v0.51.1 IPC parity) -----------------------------------

    def _handle_billing_error(self, event: dict[str, Any]) -> None:
        message = str(event.get("message", ""))
        self._clear_activity_line()
        self._out.write(f"\n  \033[1;31m✗ Billing error\033[0m — {message}\n\n")
        self._out.flush()

    def _handle_quota_exhausted(self, event: dict[str, Any]) -> None:
        """v0.53.0 — render plan-aware quota panel.

        Multi-line: header (provider/plan) + reset-time + 3 actionable
        options (wait / switch auth / switch provider). Replaces the
        single-line billing_error UX which gave the user no next step.
        """
        provider = str(event.get("provider", ""))
        plan_id = str(event.get("plan_id", ""))
        plan_label = str(event.get("plan_display_name", ""))
        upgrade_url = str(event.get("upgrade_url", ""))
        resets_in = int(event.get("resets_in_seconds", 0) or 0)
        message = str(event.get("message", ""))

        self._clear_activity_line()
        label = plan_label or provider or "Provider"
        self._out.write(f"\n  \033[1;31m⚠ {label} quota exhausted\033[0m\n")
        if message:
            self._out.write(f"  {message}\n")
        if plan_id and plan_id != plan_label:
            self._out.write(f"  Plan: \033[1m{plan_id}\033[0m\n")
        if resets_in > 0:
            mins = resets_in // 60
            ttl = f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins}m"
            self._out.write(f"  Resets in: \033[1m{ttl}\033[0m\n")
        self._out.write("\n  \033[1mOptions:\033[0m\n")
        self._out.write("    1. Wait for quota reset\n")
        if provider:
            self._out.write(
                f"    2. Switch auth: \033[36m/login set-key {provider} <api-key>\033[0m\n"
            )
        else:
            self._out.write(
                "    2. Switch auth: \033[36m/login set-key <provider> <api-key>\033[0m\n"
            )
        self._out.write("    3. Switch provider: \033[36m/model <other-model>\033[0m\n")
        if upgrade_url:
            self._out.write(f"    4. Upgrade plan: \033[36m{upgrade_url}\033[0m\n")
        self._out.write("\n")
        self._out.flush()

    # -- Pipeline milestone events (client-side rendering) --------------------

    def _handle_pipeline_header(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        subject = str(event.get("subject_id", ""))
        mode = str(event.get("pipeline_mode", ""))
        model = str(event.get("model", ""))
        ver = str(event.get("version", ""))
        self._out.write(f"\n  \033[1;36mGEODE v{ver}\033[0m\n")
        self._out.write(f"  Subject: \033[1m{subject}\033[0m\n")
        self._out.write(f"  Pipeline: {mode} | Model: {model}\n\n")
        self._out.flush()

    def _handle_pipeline_gather(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        name = str(event.get("subject_id", ""))
        subject_type = str(event.get("subject_type", ""))
        source = str(event.get("source", ""))
        metrics = event.get("metrics", {})
        signals = event.get("signals", {})
        self._out.write(f"  \033[36;1m\u25b8 GATHER\033[0m {name}")
        if subject_type:
            self._out.write(f" ({subject_type})")
        if source:
            self._out.write(f" \u2014 {source}")
        self._out.write("\n")
        if isinstance(metrics, dict) and metrics:
            parts = [f"{k}={v}" for k, v in list(metrics.items())[:4]]
            self._out.write(f"    \033[2m{' | '.join(parts)}\033[0m\n")
        if isinstance(signals, dict) and signals:
            parts = [f"{k}={v}" for k, v in list(signals.items())[:4]]
            self._out.write(f"    \033[2mSignals: {' | '.join(parts)}\033[0m\n")
        self._out.flush()

    def _handle_pipeline_analysis(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
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
        self._suppress_all_spinners()
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
        self._suppress_all_spinners()
        score = float(event.get("final_score", 0))
        conf = float(event.get("confidence", 0))
        subscores = event.get("subscores", {})
        self._out.write(f"  \033[36;1m\u25b8 SCORE\033[0m {score:.1f}/100")
        if conf > 0:
            self._out.write(f" \u00b7 confidence {conf:.1f}%")
        self._out.write("\n")
        if isinstance(subscores, dict) and subscores:
            parts = [f"{k}={v:.1f}" for k, v in subscores.items()]
            self._out.write(f"    \033[2m{' | '.join(parts)}\033[0m\n")
        self._out.flush()

    def _handle_pipeline_verification(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        g = "\033[32m\u2713\033[0m" if event.get("guardrails_pass") else "\033[31m\u2717\033[0m"
        self._out.write(f"  \033[36;1m\u25b8 VERIFY\033[0m Guardrails {g}\n")
        details = event.get("details", [])
        for d in details[:3]:
            self._out.write(f"    \033[33m- {d}\033[0m\n")
        self._out.flush()

    def _handle_feedback_loop(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        iteration = int(event.get("iteration", 0))
        conf = float(event.get("confidence", 0))
        threshold = float(event.get("threshold", 0))
        self._out.write(
            f"  \033[2m\u27f3 Feedback loop #{iteration}:"
            f" confidence {conf:.1f}% < {threshold:.1f}%\033[0m\n"
        )
        self._out.flush()

    def _handle_node_skipped(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        node = str(event.get("node", ""))
        reason = str(event.get("reason", ""))
        self._out.write(f"  \033[2m\u2933 Skipped: {node} ({reason})\033[0m\n")
        self._out.flush()

    def _handle_pipeline_result(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
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
        errors = event.get("errors", [])
        if errors:
            self._out.write(f"    \033[1;33m\u26a0 {len(errors)} warnings\033[0m\n")
            for err in errors[:5]:
                self._out.write(f"      \033[33m- {err}\033[0m\n")
        self._out.write("\n")
        self._out.flush()

    # -- Turn status -----------------------------------------------------------

    def _render_turn_status(self) -> None:
        """Render Claude Code-style status line: ✢ Worked for Xs · model · ↓Nk ↑Nk · $X.XX"""
        if self._turn_in_tokens == 0 and self._turn_out_tokens == 0:
            return
        elapsed = time.monotonic() - self._turn_start
        in_str = _fmt_tokens(self._turn_in_tokens)
        out_str = _fmt_tokens(self._turn_out_tokens)
        parts = [f"\u2722 Worked for {format_elapsed(elapsed)}"]
        if self._turn_model:
            parts.append(self._turn_model)
        parts.append(f"\u2193{in_str} \u2191{out_str}")
        if self._turn_cost > 0:
            parts.append(f"${self._turn_cost:.4f}")
        line = " \u00b7 ".join(parts)
        self._out.write(f"\n  \033[2m{line}\033[0m\n")
        self._out.flush()
        # Reset so duplicate stop() calls don't double-render
        self._turn_in_tokens = 0
        self._turn_out_tokens = 0
        self._turn_cost = 0.0

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
        self._out.write(f"  \033[32m\u2713 {name}\033[0m \u00d7{count} \u2192 {summary}{dur_str}\n")
        self._out.flush()

    # -- HITL approval spinner coordination ------------------------------------

    def suspend_for_approval(self) -> None:
        """Suspend all spinners for HITL approval prompt.

        Must be called before ``console.input()`` to prevent ANSI cursor-up
        race between spinner daemon threads and the input line.
        """
        self._suppress_all_spinners()

    def resume_from_approval(self) -> None:
        """Resume activity spinner after HITL approval completes."""
        self._activity_suppressed = False

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
        with self._render_lock:
            if not self._thinking:
                return
            frame = self._FRAMES[int(time.monotonic() * 12) % len(self._FRAMES)]
            r = self._thinking_round
            label = "Thinking..." if r <= 1 else f"Thinking... (round {r})"
            self._out.write(f"\r\033[2K  {frame} \033[2m\u2722 {label}\033[0m")
            self._out.flush()

    def _stop_thinking(self) -> None:
        if self._thinking:
            with self._render_lock:
                self._thinking = False
            if self._thinking_thread:
                self._thinking_thread.join(timeout=0.3)
                self._thinking_thread = None
            with self._render_lock:
                self._out.write("\r\033[2K")
                self._out.flush()

    # -- Thinking collapse / Ctrl+O -------------------------------------------

    def _start_stdin_reader(self) -> None:
        if not self._tty or (self._stdin_thread and self._stdin_thread.is_alive()):
            return
        try:
            if not sys.stdin.isatty():
                return
            sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            return

        self._stdin_stop.clear()
        self._stdin_thread = threading.Thread(target=self._read_ctrl_o, daemon=True)
        self._stdin_thread.start()

    def _stop_stdin_reader(self) -> None:
        self._stdin_stop.set()
        if self._stdin_thread:
            self._stdin_thread.join(timeout=0.3)
            self._stdin_thread = None

    def _read_ctrl_o(self) -> None:
        try:
            fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            return

        old_attrs: list[Any] | None = None
        termios_mod: Any | None = None
        try:
            import termios
            import tty
        except ImportError:
            termios_mod = None
        else:
            termios_mod = termios
            try:
                old_attrs = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                attrs = termios.tcgetattr(fd)
                if hasattr(termios, "IEXTEN"):
                    attrs[3] &= ~termios.IEXTEN
                    termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
            except (OSError, termios.error):
                if old_attrs is not None:
                    with contextlib.suppress(OSError, termios.error):
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
                old_attrs = None
        try:
            while not self._stdin_stop.is_set() and self._activity:
                try:
                    readable, _, _ = select.select([fd], [], [], 0.05)
                except (OSError, ValueError):
                    break
                if not readable:
                    continue
                try:
                    data = os.read(fd, 1)
                except OSError:
                    break
                if data == b"\x0f":
                    self._toggle_thinking_collapse()
        finally:
            if old_attrs is not None and termios_mod is not None:
                with contextlib.suppress(OSError, termios_mod.error):
                    termios_mod.tcsetattr(fd, termios_mod.TCSADRAIN, old_attrs)

    def _toggle_thinking_collapse(self) -> None:
        if not self._tty:
            return
        with self._render_lock:
            region = self._thinking_region
            if not region:
                return
            if region.is_collapsed:
                self._expand_thinking_region_locked(region)
            else:
                self._collapse_thinking_region_locked(region, still_running=not region.ended)
            self._out.flush()

    def _collapse_thinking_region_locked(
        self, region: _ThinkingRegion, *, still_running: bool
    ) -> None:
        self._erase_thinking_visible_locked(region)
        header = self._thinking_header(region, still_running=still_running)
        self._out.write(header)
        region.visible_lines = [header]
        region.is_collapsed = True

    def _expand_thinking_region_locked(self, region: _ThinkingRegion) -> None:
        self._erase_thinking_visible_locked(region)
        for line in region.items:
            self._out.write(line)
        region.visible_lines = list(region.items)
        region.is_collapsed = False

    def _erase_thinking_visible_locked(self, region: _ThinkingRegion) -> None:
        rows = self._thinking_visual_rows(region.visible_lines)
        self._out.write("\r\033[2K")
        if rows <= 0:
            return
        self._out.write(f"\033[{rows}A")
        for idx in range(rows):
            self._out.write("\r\033[2K")
            if idx < rows - 1:
                self._out.write("\033[1B")
        if rows > 1:
            self._out.write(f"\033[{rows - 1}A")

    def _thinking_header(self, region: _ThinkingRegion, *, still_running: bool) -> str:
        elapsed = time.monotonic() - region.start_ts
        suffix = " \u2026 (still running)" if still_running else ""
        return (
            f"  \033[90m\u2726 Thought for {format_elapsed(elapsed)} \u00b7 "
            f"{len(region.items)} items{suffix}\033[0m\n"
        )

    def _thinking_visual_rows(self, lines: list[str]) -> int:
        width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)
        rows = 0
        for line in lines:
            plain = _ANSI_ESCAPE.sub("", line).rstrip("\n")
            rows += max(1, (len(plain) + width - 1) // width)
        return rows

    def _suppress_all_spinners(self) -> None:
        """Stop thinking + tool spinners, clear line for new content."""
        self._activity_suppressed = True
        self._stop_thinking()
        self._tool_tracker.suspend()
        self._out.write("\r\033[2K")
        self._out.flush()

    def _clear_activity_line(self) -> None:
        """Clear the activity spinner line before writing a permanent line."""
        if self._activity and not self._activity_suppressed:
            self._out.write("\r\033[2K")
            self._out.flush()

    @staticmethod
    def _is_clearable_plain_stream(data: str) -> bool:
        """Return True for plain text stream chunks that can be safely erased."""
        if not data:
            return False
        if _ANSI_ESCAPE.search(data):
            return False
        return not any(ch in data for ch in "\b\f\v")

    def _reset_clearable_stream_region(self) -> None:
        self._clearable_stream_parts.clear()

    def _clear_markdown_stream_region(self) -> None:
        text = "".join(self._clearable_stream_parts)
        self._reset_clearable_stream_region()
        if not text or not _MARKDOWN_TEXT_MARKER.search(text):
            return

        visual_lines = len(text.splitlines()) or 1
        self._out.write("\r\033[2K")
        moves = visual_lines if text.endswith("\n") else max(visual_lines - 1, 0)
        for _ in range(moves):
            self._out.write("\033[1A\033[2K")
