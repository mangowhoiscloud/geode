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
from core.ui import spinner_glyph
from core.ui.fleet import FleetRegistry, set_last_fleet_snapshot
from core.ui.palette import (
    ACCENT,
    BOLD,
    DELEGATE,
    DIM,
    DONE_STRIKE,
    ERASE_EOL,
    ERASE_LINE,
    ERROR,
    FAIL,
    FAINT,
    FALLBACK_TERMINAL,
    GLYPH_ARROW,
    GLYPH_CANCEL,
    GLYPH_CYCLE,
    GLYPH_DELEGATE,
    GLYPH_FAIL,
    GLYPH_OK,
    GLYPH_REASONING,
    GLYPH_RESULT,
    GLYPH_SWITCH,
    GLYPH_THOUGHT,
    GLYPH_TODO,
    GLYPH_TURN,
    HIGHLIGHT,
    INFO,
    LINK,
    MIN_RENDER_WIDTH,
    NOTICE,
    OK,
    OK_BOLD,
    RESET,
    SECTION,
    TRUNCATE_FLEET_ROLE,
    TRUNCATE_REASONING,
    TRUNCATE_SUMMARY,
    TRUNCATE_THINKING_LABEL,
    WARN,
    cursor_down,
    cursor_up,
)
from core.ui.tool_tracker import ToolCallTracker, _truncate_display

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


@dataclass
class _ProgressPlanSurface:
    visible_lines: list[str] = field(default_factory=list)
    items: list[dict[str, str]] = field(default_factory=list)
    explanation: str = ""
    at_bottom: bool = False
    # Signature of the last checklist actually drawn (items + statuses +
    # explanation). Consecutive plan events carrying an identical state are
    # deduped against this so a re-emitted-but-unchanged plan never reprints.
    signature: str = ""
    rendered: bool = False


@dataclass
class _ToolActivityStat:
    count: int = 0
    errors: int = 0
    duration_s: float = 0.0
    summary: str = "ok"
    error: str = ""
    last_seq: int = 0


@dataclass
class _ActivitySurface:
    visible_lines: list[str] = field(default_factory=list)
    tool_stats: dict[str, _ToolActivityStat] = field(default_factory=dict)
    notices: list[str] = field(default_factory=list)
    thought_count: int = 0
    thought_items: int = 0
    at_bottom: bool = False
    append_signature: str = ""


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
    _PLAN_SURFACE_EVENTS = frozenset({"goal_decomposition", "plan_step", "progress_plan", "replan"})
    # Events whose handlers manage the live region themselves (erase/redraw at
    # the right moment) or print nothing — everything else gets an
    # erase-before-print so no stale live-region copy is ever left in scrollback.
    _LIVE_REGION_SELF_MANAGED = frozenset(
        {
            "goal_decomposition",
            "plan_step",
            "progress_plan",
            "replan",
            "tool_start",
            "tool_end",
            "thinking_start",
            "thinking_end",
            "tokens",
            "fast_chat_start",
        }
    )
    _MAX_ACTIVITY_TOOL_LINES = 5
    _MAX_ACTIVITY_NOTICE_LINES = 2
    _MAX_PLAN_VISIBLE_ITEMS = 5

    def __init__(self, *, live_regions: bool = True) -> None:
        self._live_regions = live_regions
        self._tool_tracker = ToolCallTracker(live_updates=live_regions)
        self._thinking = False
        self._thinking_thread: threading.Thread | None = None
        self._thinking_model = ""
        self._thinking_round = 0
        self._thinking_reflection = False
        self._thinking_region: _ThinkingRegion | None = None
        self._render_lock = threading.RLock()
        self._tty = sys.stdout.isatty() and live_regions
        self._stdin_stop = threading.Event()
        self._stdin_thread: threading.Thread | None = None
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
        self._progress_plan = _ProgressPlanSurface()
        self._activity_surface = _ActivitySurface()
        self._activity_spinner_line = ""
        self._activity_spinner_at_bottom = False
        self._activity_seq = 0
        # Stage 1 fleet view — per-sub-agent live state fed by subagent_state
        # events; read by the one-line fleet summary in the activity region.
        self._fleet = FleetRegistry()

    # -- Public API -----------------------------------------------------------

    def start_activity(self) -> None:
        """Start persistent activity spinner. Call before send_prompt()."""
        if not self._live_regions:
            self._out.write(f"  {spinner_glyph.ROSE}{spinner_glyph.GLYPH}{RESET} Working...\n")
            self._out.flush()
            return
        if not self._tty:
            return
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
                    self._record_tool_activity(event)
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
            if etype not in self._LIVE_REGION_SELF_MANAGED:
                self._erase_live_region()
            handler(event)

    def on_stream(self, data: str) -> None:
        """Handle raw console stream (Rich panels, pipeline output)."""
        # Spinners first — a spinner frame landing mid cursor-up erase would
        # corrupt the cursor position the erase math depends on.
        self._suppress_all_spinners()
        self._erase_live_region()
        if self._is_clearable_plain_stream(data):
            self._clearable_stream_parts.append(data)
        else:
            self._reset_clearable_stream_region()
        self._out.write(data)
        self._out.flush()

    def stop(self) -> None:
        """Stop all spinners and render turn status. Call when result arrives."""
        self._stop_stdin_reader()
        self._activity = False
        self._activity_suppressed = True
        self._stop_thinking()
        self._tool_tracker.stop()
        if self._activity_thread:
            self._activity_thread.join(timeout=0.3)
            self._activity_thread = None
        # Clear any leftover spinner line.
        with self._render_lock:
            self._erase_activity_locked()
            if self._live_regions:
                self._out.write(f"\r{ERASE_LINE}")
        # Clear the transient Markdown stream region BEFORE any live-region
        # render — _flush_repeat may redraw the region at the cursor, and the
        # upward stream-erase would eat those fresh rows if it ran after.
        self._clear_markdown_stream_region()
        self._out.flush()
        self._flush_repeat()
        # Freeze the activity block as the turn's final state, then release both
        # surfaces to scrollback so the final answer renders below them. The plan
        # checklist is transcript content — it was drawn by its own events and
        # already sits in scrollback, so it is never redrawn here.
        with self._render_lock:
            if self._activity_surface.tool_stats or self._activity_surface.notices:
                self._render_activity_region(force=True)
            self._progress_plan.at_bottom = False
            self._activity_surface.at_bottom = False
        # Render accumulated turn status (Claude Code style)
        self._render_turn_status()
        # Persist this turn's fleet for the between-turns `/fleet` view. Only
        # when the turn actually dispatched sub-agents, so a later plain turn
        # never wipes the most recent real fleet (see fleet.set_last_fleet_snapshot).
        fleet_snapshot = self._fleet.snapshot()
        if fleet_snapshot:
            set_last_fleet_snapshot(fleet_snapshot)

    # -- Core event handlers --------------------------------------------------

    def _handle_round_start(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()

    def _handle_fast_chat_start(self, event: dict[str, Any]) -> None:
        model = str(event.get("model", "") or "")
        provider = str(event.get("provider", "") or "")
        source = str(event.get("source", "") or "")
        route = " / ".join(part for part in (provider, source) if part)
        detail = f" · {route}" if route else ""
        label = f"Fast chat · {model}{detail}" if model else f"Fast chat{detail}"
        self._append_activity_notice(label)
        self._render_activity_region()

    def _handle_thinking_start(self, event: dict[str, Any]) -> None:
        self._activity_suppressed = True
        self._tool_tracker.stop()
        # Clear the bottom activity block so the thinking spinner flows below the
        # plan; the plan itself stays in scrollback (never re-emitted per phase).
        self._erase_live_region()
        with self._render_lock:
            self._thinking_region = _ThinkingRegion(start_ts=time.monotonic())
            self._thinking = True
            self._thinking_model = str(event.get("model", ""))
            self._thinking_round = int(event.get("round", 1))
            self._thinking_reflection = bool(event.get("reflection", False))
        if not self._live_regions:
            return
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
                    self._erase_thinking_visible_locked(region)
                    self._record_thought_activity_locked(region)
        self._activity_suppressed = False  # resume activity spinner
        # Redraw ONLY the activity block (thought/tool summary). The plan
        # checklist is never re-emitted at phase end — that per-phase reprint
        # is exactly what stacked N identical Plan blocks down the transcript.
        self._render_activity_region()

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
        # Clear the bottom activity block so tool rows flow below the plan; the
        # plan itself stays in scrollback (never re-emitted per phase).
        self._erase_live_region()
        self._tool_tracker.on_tool_start(event)

    def _handle_tool_end(self, event: dict[str, Any]) -> None:
        name = str(event.get("name", ""))
        self._record_tool_activity(event)
        self._tool_tracker.on_tool_end(event)
        # Resume activity when all tools done
        with self._tool_tracker._lock:
            tools = self._tool_tracker._tools
            all_done = all(t["done"] for t in tools)
            is_single = len(tools) == 1
        if all_done:
            self._activity_suppressed = False
            self._tool_tracker.suspend()
            with self._tool_tracker._lock:
                self._tool_tracker._tools.clear()
            # suspend() erased the tool rows; redraw ONLY the activity block.
            # The plan is not re-emitted at phase end (it lives in scrollback).
            self._render_activity_region()
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
            self._out.write(f"  {WARN}{GLYPH_CYCLE} Context exhausted{RESET}\n")
        else:
            label = "compacted" if action == "compact" else "pruned"
            tok_str = f", ~{tokens_est // 1000}k tokens freed" if tokens_est >= 1000 else ""
            self._out.write(
                f"  {DIM}{GLYPH_CYCLE} Context {label}: {before} {GLYPH_ARROW} {after} messages"
                f" ({removed} removed{tok_str}){RESET}\n"
            )
        self._out.flush()

    def _handle_subagent_dispatch(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        desc = str(event.get("description", ""))
        # Legacy aggregate dispatch is render-only: the fleet registry is fed
        # exclusively by the per-task `subagent_state` events, which carry a
        # matching terminal transition. Feeding on_dispatch here would create a
        # row the aggregate `subagent_complete` (no per-task id) can never
        # clear → a permanently-"running" fleet row (Codex catch).
        self._out.write(f'  {DELEGATE}{GLYPH_DELEGATE} delegate_task{RESET}("{desc}")\n')
        self._out.flush()

    def _handle_subagent_state(self, event: dict[str, Any]) -> None:
        """Feed a per-agent ``subagent_state`` transition into the fleet registry.

        Additive to the aggregate dispatch/progress/complete handlers (which
        keep working unchanged). After updating the registry, redraw the bottom
        activity region so the one-line fleet summary reflects the new state
        (or disappears when the last agent finishes).
        """
        task_id = str(event.get("task_id", ""))
        if not task_id:
            return
        self._fleet.on_state(
            task_id,
            role=str(event.get("role", "")),
            status=str(event.get("status", "running")),
            description=str(event.get("description", "")),
            tokens=int(event.get("tokens", 0) or 0),
            elapsed_s=float(event.get("elapsed_s", 0) or 0),
            # Stage 1.5 — the running child's current tool, plumbed over the
            # worker activity side-channel. "" at dispatch/completion or when the
            # caller did not opt into live activity; on_state ignores a blank one.
            current_activity=str(event.get("activity", "")),
        )
        self._render_activity_region()

    def _handle_subagent_progress(self, event: dict[str, Any]) -> None:
        completed = int(event.get("completed", 0))
        total = int(event.get("total", 0))
        name = str(event.get("name", ""))
        dur = float(event.get("duration_s", 0))
        mark = f"{DIM}{GLYPH_RESULT}{RESET} {OK}{GLYPH_OK}{RESET}"
        self._out.write(f"  {mark} {name} ({dur:.1f}s)  [{completed}/{total}]\n")
        self._out.flush()

    def _handle_subagent_complete(self, event: dict[str, Any]) -> None:
        count = int(event.get("count", 0))
        elapsed = float(event.get("elapsed_s", 0))
        self._out.write(f"  {OK}{GLYPH_OK} {count} sub-agents completed{RESET} ({elapsed:.1f}s)\n")
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
            f"\n  {DIM}Session: {calls} calls \u00b7 "
            f"\u2193{in_str} \u2191{out_str} \u00b7 "
            f"{RESET}{WARN}${cost:.4f}{RESET}\n\n"
        )
        self._out.flush()

    # -- AgenticLoop state change events --------------------------------------

    def _handle_budget_warning(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        budget = float(event.get("budget", 0))
        actual = float(event.get("actual", 0))
        pct = float(event.get("pct", 0))
        self._out.write(
            f"  {WARN}$ Budget warning: ${actual:.2f} / ${budget:.2f} ({pct:.0f}% used){RESET}\n"
        )
        self._out.flush()

    def _handle_reasoning_summary(self, event: dict[str, Any]) -> None:
        """v0.57.0 R6 — render a model's reasoning-summary chunk.

        Per-item granularity (not per-delta). Shown as a muted single
        line; full text is in the IPC event payload for any client that
        wants to display the complete summary.
        """
        text = str(event.get("text", "")).strip().replace("\n", " ")
        if len(text) > TRUNCATE_REASONING:
            text = text[: TRUNCATE_REASONING - 3] + "…"
        if not text:
            return
        # ANSI 90 = bright black (muted); matches console.print muted style.
        line = f"  {FAINT}{GLYPH_REASONING} thinking · {text}{RESET}\n"
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
            f"  {WARN}~ Retrying in {delay:.1f}s... "
            f"[{model} \u00b7 {attempt}/{max_r} \u00b7 {elapsed:.0f}s elapsed] "
            f"(Ctrl+C to skip){RESET}\n"
        )
        self._out.flush()

    def _handle_llm_error(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        severity = str(event.get("severity", "warning"))
        hint = str(event.get("hint", "LLM error"))
        model = str(event.get("model", ""))
        elapsed = float(event.get("elapsed_s", 0))
        # Severity -> style token (palette SoT)
        color = {"critical": ERROR, "error": ERROR, "warning": WARN}.get(severity, DIM)
        symbol = {"critical": "!!", "error": "!", "warning": "~"}.get(severity, "\u00b7")
        suffix = f" [{model} \u00b7 {elapsed:.1f}s]" if model else ""
        self._out.write(f"  {color}{symbol} {hint}{suffix}{RESET}\n")
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
            f"  {WARN}{GLYPH_CANCEL} Model switch required: {model} hit {error_type} "
            f"after {attempts} attempts{suffix}{RESET}\n"
        )
        self._out.flush()

    def _handle_cost_budget_exceeded(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        budget = float(event.get("budget", 0))
        actual = float(event.get("actual", 0))
        self._out.write(f"  {ERROR}$ Cost budget exceeded: ${actual:.2f} / ${budget:.2f}{RESET}\n")
        self._out.flush()

    def _handle_time_budget_expired(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        budget = float(event.get("budget_s", 0))
        elapsed = float(event.get("elapsed_s", 0))
        rounds = int(event.get("rounds", 0))
        self._out.write(
            f"  {WARN}\u23f1 Time expired: {elapsed:.0f}s / {budget:.0f}s"
            f" ({rounds} rounds){RESET}\n"
        )
        self._out.flush()

    def _handle_convergence_detected(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        rounds = int(event.get("rounds", 0))
        self._out.write(
            f"  {ERROR}{GLYPH_CYCLE} Convergence: repeating failure after {rounds} rounds{RESET}\n"
        )
        self._out.flush()

    def _handle_repeated_success_no_progress(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        tool = str(event.get("tool", ""))
        streak = int(event.get("streak", 0))
        rounds = int(event.get("rounds", 0))
        self._out.write(
            f"  {WARN}{GLYPH_CYCLE} No progress: {tool} returned the same success"
            f" {streak}x ({rounds} rounds){RESET}\n"
        )
        self._out.flush()

    def _handle_goal_decomposition(self, event: dict[str, Any]) -> None:
        steps = event.get("steps", [])
        if not isinstance(steps, list):
            return
        items = [
            {"step": str(step), "status": "in_progress" if i == 0 else "pending"}
            for i, step in enumerate(steps)
            if str(step).strip()
        ]
        if not items:
            return
        self._render_progress_plan_surface(items, f"{len(items)} steps")

    def _handle_plan_step(self, event: dict[str, Any]) -> None:
        current = int(event.get("current", 0))
        total = int(event.get("total", 0))
        revision = int(event.get("revision", 0))
        description = str(event.get("description", ""))
        if current <= 0 or total <= 0:
            return
        surface_items = list(self._progress_plan.items)
        if len(surface_items) != total:
            surface_items = [
                {"step": description if i == current else f"Step {i}", "status": "pending"}
                for i in range(1, total + 1)
            ]
        for idx, item in enumerate(surface_items, 1):
            if idx < current:
                item["status"] = "completed"
            elif idx == current:
                item["status"] = "in_progress"
                if description:
                    item["step"] = description
            else:
                item["status"] = "pending"
        rev = f" · rev {revision}" if revision else ""
        self._render_progress_plan_surface(surface_items, f"step {current}/{total}{rev}")

    def _handle_replan(self, event: dict[str, Any]) -> None:
        trigger = str(event.get("trigger", ""))
        step_count = int(event.get("step_count", 0))
        revision = int(event.get("revision", 0))
        suffix = f" · {trigger}" if trigger else ""
        rev = f" · rev {revision}" if revision else ""
        items = list(self._progress_plan.items)
        if step_count > 0 and len(items) != step_count:
            items = [{"step": f"Step {i}", "status": "pending"} for i in range(1, step_count + 1)]
        self._render_progress_plan_surface(items, f"revised{suffix} · {step_count} steps{rev}")

    def _handle_progress_plan(self, event: dict[str, Any]) -> None:
        """Render update_plan into the managed compact live region."""
        plan = event.get("plan", [])
        if not isinstance(plan, list):
            return
        items = [item for item in plan if isinstance(item, dict)]
        if not items:
            return

        explanation = str(event.get("explanation", "") or "").strip()
        self._render_progress_plan_surface(items, explanation)

    def _render_progress_plan_surface(self, items: list[dict[Any, Any]], explanation: str) -> None:
        normalized = [
            {
                "step": str(item.get("step", "")).strip(),
                "status": str(item.get("status", "pending")).strip() or "pending",
            }
            for item in items
            if str(item.get("step", "")).strip()
        ]
        if not normalized:
            return

        signature = self._plan_signature(normalized, explanation)
        with self._render_lock:
            plan = self._progress_plan
            # Dedup: a re-emitted plan carrying an identical state (same steps,
            # statuses, explanation) never reprints — only genuine state changes
            # draw a fresh checklist.
            if plan.rendered and signature == plan.signature:
                return
            plan.items = list(normalized)
            plan.explanation = explanation
            self._render_plan_region(signature)

    @staticmethod
    def _plan_signature(items: list[dict[str, str]], explanation: str) -> str:
        steps = "\x1e".join(f"{it.get('step', '')}\x1f{it.get('status', '')}" for it in items)
        return f"{steps}\x1d{explanation}"

    def _handle_tool_backpressure(self, event: dict[str, Any]) -> None:
        self._clear_activity_line()
        n = int(event.get("consecutive_errors", 0))
        self._out.write(f"  {WARN}\u23f8 Backpressure: {n} consecutive tool errors{RESET}\n")
        self._out.flush()

    def _handle_tool_diversity_forced(self, event: dict[str, Any]) -> None:
        tool = str(event.get("tool", ""))
        count = int(event.get("count", 0))
        self._append_activity_notice(
            f"{WARN}{GLYPH_CYCLE} Diversity: {tool} called {count}x"
            f" \u2014 hinting alternate path{RESET}"
        )
        self._render_activity_region()

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
        self._out.write(f"  {DIM}{GLYPH_SWITCH} Model: {frm} {GLYPH_ARROW} {to}{suffix}{RESET}\n")
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
        self._out.write(f"  {SECTION}{provider} OAuth Login{RESET}\n")
        self._out.write("\n")
        self._out.write("  1. Open this URL in your browser:\n")
        self._out.write(f"     {LINK}{uri}{RESET}\n")
        self._out.write("\n")
        self._out.write("  2. Enter this code:\n")
        self._out.write(f"     {HIGHLIGHT}{code}{RESET}\n")
        self._out.write("\n")
        if uri:
            self._out.write(f"  {DIM}Press [Enter] to open the URL in your browser.{RESET}\n")
            from core.ui.oauth_browser import start_oauth_browser_watcher

            start_oauth_browser_watcher(uri)
        self._out.write(f"  {DIM}Waiting for sign-in... (Ctrl+C to cancel){RESET}\n")
        self._out.flush()

    def _handle_oauth_login_pending(self, event: dict[str, Any]) -> None:
        """Heartbeat — overwrite a single 'Waiting…' line in place."""
        elapsed = int(event.get("elapsed_s", 0))
        self._out.write(f"\r  {DIM}Waiting... ({elapsed}s){RESET}{ERASE_EOL}")
        self._out.flush()

    def _handle_oauth_login_success(self, event: dict[str, Any]) -> None:
        provider = str(event.get("provider", ""))
        email = str(event.get("email", ""))
        account_id = str(event.get("account_id", ""))
        plan_type = str(event.get("plan_type", ""))
        stored_at = str(event.get("stored_at", ""))
        # Wipe the heartbeat line, then announce success.
        self._out.write(f"\r{ERASE_LINE}\n")
        self._out.write(f"  {OK_BOLD}{GLYPH_OK} {provider} login successful{RESET}\n")
        if email or account_id:
            self._out.write(f"  {DIM}  Account:{RESET} {email or account_id}\n")
        if plan_type:
            self._out.write(f"  {DIM}  Plan:{RESET} {plan_type}\n")
        if stored_at:
            self._out.write(f"  {DIM}  Stored:{RESET} {stored_at}\n")
        self._out.write("\n")
        self._out.flush()

    def _handle_oauth_login_failed(self, event: dict[str, Any]) -> None:
        provider = str(event.get("provider", ""))
        reason = str(event.get("reason", ""))
        self._out.write(f"\r{ERASE_LINE}\n")
        self._out.write(f"  {ERROR}{GLYPH_FAIL} {provider} login failed:{RESET} {reason}\n\n")
        self._out.flush()

    # -- Billing error (v0.51.1 IPC parity) -----------------------------------

    def _handle_billing_error(self, event: dict[str, Any]) -> None:
        message = str(event.get("message", ""))
        self._clear_activity_line()
        self._out.write(f"\n  {ERROR}{GLYPH_FAIL} Billing error{RESET} — {message}\n\n")
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
        self._out.write(f"\n  {ERROR}⚠ {label} quota exhausted{RESET}\n")
        if message:
            self._out.write(f"  {message}\n")
        if plan_id and plan_id != plan_label:
            self._out.write(f"  Plan: {BOLD}{plan_id}{RESET}\n")
        if resets_in > 0:
            mins = resets_in // 60
            ttl = f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins}m"
            self._out.write(f"  Resets in: {BOLD}{ttl}{RESET}\n")
        self._out.write(f"\n  {BOLD}Options:{RESET}\n")
        self._out.write("    1. Wait for quota reset\n")
        if provider:
            self._out.write(
                f"    2. Switch auth: {INFO}/login set-key {provider} <api-key>{RESET}\n"
            )
        else:
            self._out.write(
                f"    2. Switch auth: {INFO}/login set-key <provider> <api-key>{RESET}\n"
            )
        self._out.write(f"    3. Switch provider: {INFO}/model <other-model>{RESET}\n")
        if upgrade_url:
            self._out.write(f"    4. Upgrade plan: {INFO}{upgrade_url}{RESET}\n")
        self._out.write("\n")
        self._out.flush()

    # -- Pipeline milestone events (client-side rendering) --------------------

    def _handle_pipeline_header(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        subject = str(event.get("subject_id", ""))
        mode = str(event.get("pipeline_mode", ""))
        model = str(event.get("model", ""))
        ver = str(event.get("version", ""))
        self._out.write(f"\n  {SECTION}GEODE v{ver}{RESET}\n")
        self._out.write(f"  Subject: {BOLD}{subject}{RESET}\n")
        self._out.write(f"  Pipeline: {mode} | Model: {model}\n\n")
        self._out.flush()

    def _handle_pipeline_gather(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        name = str(event.get("subject_id", ""))
        subject_type = str(event.get("subject_type", ""))
        source = str(event.get("source", ""))
        metrics = event.get("metrics", {})
        signals = event.get("signals", {})
        self._out.write(f"  {SECTION}{GLYPH_DELEGATE} GATHER{RESET} {name}")
        if subject_type:
            self._out.write(f" ({subject_type})")
        if source:
            self._out.write(f" \u2014 {source}")
        self._out.write("\n")
        if isinstance(metrics, dict) and metrics:
            parts = [f"{k}={v}" for k, v in list(metrics.items())[:4]]
            self._out.write(f"    {DIM}{' | '.join(parts)}{RESET}\n")
        if isinstance(signals, dict) and signals:
            parts = [f"{k}={v}" for k, v in list(signals.items())[:4]]
            self._out.write(f"    {DIM}Signals: {' | '.join(parts)}{RESET}\n")
        self._out.flush()

    def _handle_pipeline_analysis(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        analysts = event.get("analysts", [])
        self._out.write(f"  {SECTION}{GLYPH_DELEGATE} ANALYZE{RESET} {len(analysts)} analysts\n")
        for a in analysts:
            name = str(a.get("analyst", ""))
            score = float(a.get("score", 0))
            finding = str(a.get("finding", ""))[:50]
            color = OK if score >= 4.0 else NOTICE if score >= 3.0 else FAIL
            self._out.write(f"    {name:<18} {color}{score:.1f}{RESET}  {finding}\n")
        self._out.flush()

    def _handle_pipeline_evaluation(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        evals = event.get("evaluators", {})
        self._out.write(f"  {SECTION}{GLYPH_DELEGATE} EVALUATE{RESET} {len(evals)} evaluators\n")
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
                color = OK if score >= 80 else NOTICE if score >= 60 else FAIL
                self._out.write(f"    {label:<18} {color}{score:.0f}/100{RESET}  {rationale}\n")
        self._out.flush()

    def _handle_pipeline_score(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        score = float(event.get("final_score", 0))
        conf = float(event.get("confidence", 0))
        subscores = event.get("subscores", {})
        self._out.write(f"  {SECTION}{GLYPH_DELEGATE} SCORE{RESET} {score:.1f}/100")
        if conf > 0:
            self._out.write(f" \u00b7 confidence {conf:.1f}%")
        self._out.write("\n")
        if isinstance(subscores, dict) and subscores:
            parts = [f"{k}={v:.1f}" for k, v in subscores.items()]
            self._out.write(f"    {DIM}{' | '.join(parts)}{RESET}\n")
        self._out.flush()

    def _handle_pipeline_verification(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        g = (
            f"{OK}{GLYPH_OK}{RESET}"
            if event.get("guardrails_pass")
            else f"{FAIL}{GLYPH_FAIL}{RESET}"
        )
        self._out.write(f"  {SECTION}{GLYPH_DELEGATE} VERIFY{RESET} Guardrails {g}\n")
        details = event.get("details", [])
        for d in details[:3]:
            self._out.write(f"    {NOTICE}- {d}{RESET}\n")
        self._out.flush()

    def _handle_feedback_loop(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        iteration = int(event.get("iteration", 0))
        conf = float(event.get("confidence", 0))
        threshold = float(event.get("threshold", 0))
        self._out.write(
            f"  {DIM}{GLYPH_CYCLE} Feedback loop #{iteration}:"
            f" confidence {conf:.1f}% < {threshold:.1f}%{RESET}\n"
        )
        self._out.flush()

    def _handle_node_skipped(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        node = str(event.get("node", ""))
        reason = str(event.get("reason", ""))
        self._out.write(f"  {DIM}\u2933 Skipped: {node} ({reason}){RESET}\n")
        self._out.flush()

    def _handle_pipeline_result(self, event: dict[str, Any]) -> None:
        self._suppress_all_spinners()
        tier = str(event.get("tier", "?"))
        score = float(event.get("final_score", 0))
        cause = str(event.get("cause", ""))
        narrative = str(event.get("narrative", ""))
        segment = str(event.get("target_segment", ""))
        action = str(event.get("action", "")).replace("_", " ").title()
        tier_color = {"S": ACCENT, "A": OK_BOLD, "B": WARN, "C": ERROR}.get(tier, BOLD)
        self._out.write(f"\n  {SECTION}{GLYPH_DELEGATE} RESULT{RESET}\n")
        self._out.write(f"    {tier_color}{tier}{RESET}  {score:.1f} pts  |  {cause}\n")
        if narrative:
            self._out.write(f"    {narrative}\n")
        if segment:
            self._out.write(f"    {DIM}Target:{RESET} {segment}\n")
        if action:
            self._out.write(f"    {DIM}Action:{RESET} {action}\n")
        errors = event.get("errors", [])
        if errors:
            self._out.write(f"    {WARN}\u26a0 {len(errors)} warnings{RESET}\n")
            for err in errors[:5]:
                self._out.write(f"      {NOTICE}- {err}{RESET}\n")
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
        parts = [f"{GLYPH_TURN} Worked for {format_elapsed(elapsed)}"]
        if self._turn_model:
            parts.append(self._turn_model)
        parts.append(f"\u2193{in_str} \u2191{out_str}")
        if self._turn_cost > 0:
            parts.append(f"${self._turn_cost:.4f}")
        line = " \u00b7 ".join(parts)
        self._out.write(f"\n  {DIM}{line}{RESET}\n")
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
        count = self._repeat_count
        self._in_repeat = False
        self._repeat_name = ""
        self._last_batch_tool = ""
        if count <= 1:
            return
        self._render_activity_region()

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

    def _animate_activity(self) -> None:
        """Persistent activity spinner — runs until stop() is called."""
        while self._activity:
            if not self._activity_suppressed:
                body = spinner_glyph.shimmer(f"{spinner_glyph.GLYPH} Working…", time.monotonic())
                # Under the render lock: a frame landing mid live-region erase
                # would corrupt the cursor position the erase math depends on.
                with self._render_lock:
                    if self._activity and not self._activity_suppressed:
                        line = f"  {body}"
                        self._out.write(f"\r{ERASE_LINE}{line}")
                        self._activity_spinner_line = line
                        self._activity_spinner_at_bottom = True
                        self._out.flush()
            time.sleep(0.05)

    def _animate_thinking(self) -> None:
        """Thinking spinner — overrides activity spinner."""
        while self._thinking:
            self._render_thinking_frame()
            time.sleep(0.05)

    def _thinking_label(self) -> str:
        """Claude Code-style contextual label: reflection > active plan step > whimsy.

        The whimsical gerund is a fallback seeded by the turn start \u2014 one word
        per turn, never flipping mid-turn.
        """
        if self._thinking_reflection:
            return "Reflecting"
        active = next(
            (
                str(item.get("step", ""))
                for item in self._progress_plan.items
                if item.get("status") == "in_progress" and item.get("step")
            ),
            "",
        )
        if active:
            return _truncate_display(active, TRUNCATE_THINKING_LABEL)
        return spinner_glyph.gerund(self._turn_start)

    def _render_thinking_frame(self) -> None:
        if not self._live_regions:
            return
        with self._render_lock:
            if not self._thinking:
                return
            region = self._thinking_region
            el = time.monotonic() - region.start_ts if region is not None else time.monotonic()
            word = self._thinking_label() + "\u2026"
            if self._thinking_round > 1:
                word += f" (round {self._thinking_round})"
            body = spinner_glyph.shimmer(f"{spinner_glyph.GLYPH} {word}", el)
            meta = f" {DIM}({spinner_glyph.elapsed(el)}){RESET}" if region is not None else ""
            self._out.write(f"\r{ERASE_LINE}  {body}{meta}")
            self._out.flush()

    def _stop_thinking(self) -> None:
        if self._thinking:
            with self._render_lock:
                self._thinking = False
            if self._thinking_thread:
                self._thinking_thread.join(timeout=0.3)
                self._thinking_thread = None
            if self._live_regions:
                with self._render_lock:
                    self._out.write(f"\r{ERASE_LINE}")
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
        rows = self._visual_rows(region.visible_lines)
        self._erase_visual_rows_locked(rows)

    def _erase_lines_locked(self, lines: list[str]) -> None:
        self._erase_visual_rows_locked(self._visual_rows(lines))

    def _erase_visual_rows_locked(self, rows: int) -> None:
        self._out.write(f"\r{ERASE_LINE}")
        if rows <= 0:
            return
        self._out.write(cursor_up(rows))
        for idx in range(rows):
            self._out.write(f"\r{ERASE_LINE}")
            if idx < rows - 1:
                self._out.write(cursor_down(1))
        if rows > 1:
            self._out.write(cursor_up(rows - 1))

    def _thinking_header(self, region: _ThinkingRegion, *, still_running: bool) -> str:
        elapsed = time.monotonic() - region.start_ts
        suffix = " \u2026 (still running)" if still_running else ""
        return (
            f"  {FAINT}{GLYPH_THOUGHT} Thought for {format_elapsed(elapsed)} \u00b7 "
            f"{len(region.items)} items{suffix}{RESET}\n"
        )

    def _thinking_visual_rows(self, lines: list[str]) -> int:
        return self._visual_rows(lines)

    def _visual_rows(self, lines: list[str]) -> int:
        width = max(MIN_RENDER_WIDTH, shutil.get_terminal_size(fallback=FALLBACK_TERMINAL).columns)
        rows = 0
        for line in lines:
            plain = _ANSI_ESCAPE.sub("", line).rstrip("\n")
            rows += max(1, (len(plain) + width - 1) // width)
        return rows

    def _erase_live_region(self) -> None:
        """Prepare the bottom rows for foreign output printing immediately after.

        The activity block is a genuine bottom-anchored live surface, so it is
        erased in place (cursor-up) while still bottom-most. The plan checklist
        is transcript content — it is never cursor-erased; it is only *released*
        (marked no-longer-bottom-most) so it scrolls up with the foreign output
        and the next plan event draws a fresh copy below instead of stacking.
        """
        with self._render_lock:
            self._erase_activity_locked()
            self._release_plan_locked()

    def _erase_activity_locked(self) -> None:
        """Cursor-up erase the activity block if it is still the bottom-most row."""
        if self._activity_spinner_at_bottom and self._activity_spinner_line:
            self._erase_lines_locked([self._activity_spinner_line])
            self._activity_spinner_line = ""
            self._activity_spinner_at_bottom = False
        surface = self._activity_surface
        if surface.at_bottom and surface.visible_lines:
            self._erase_lines_locked(surface.visible_lines)
            surface.visible_lines = []
            surface.at_bottom = False

    def _release_plan_locked(self) -> None:
        """Release the plan checklist to scrollback (leave it drawn, just not bottom-most)."""
        self._progress_plan.at_bottom = False

    def _render_plan_region(self, signature: str) -> None:
        """Draw the compact task list once per state change (Claude Code todo).

        Drawn only from plan events (progress_plan / plan_step / replan /
        goal_decomposition), never from a thinking/tool phase. If the previous
        checklist is still the bottom-most thing (a rapid consecutive update with
        nothing printed since), it is erased in place and redrawn so an update
        does not duplicate; the moment anything else printed it is released, and
        the new checklist draws fresh below (the prior copy stays in scrollback).
        """
        with self._render_lock:
            self._suppress_all_spinners()
            plan = self._progress_plan
            # If the activity block sits below the plan, clear it first so the
            # plan never ends up rendered below its own activity summary.
            self._erase_activity_locked()
            if plan.at_bottom and plan.visible_lines:
                self._erase_lines_locked(plan.visible_lines)
            plan_lines = self._render_full_progress_plan(plan.items, plan.explanation)
            for line in plan_lines:
                self._out.write(line)
            plan.visible_lines = plan_lines
            # Non-TTY (piped/log) output is append-only: never mark at_bottom,
            # so no cursor-up erase sequences are ever emitted into a pipe.
            plan.at_bottom = self._tty
            plan.signature = signature
            plan.rendered = True
            self._out.flush()

    def _render_activity_region(self, *, force: bool = False) -> None:
        """Redraw the bottom-anchored activity block (tool/thought summary) in place.

        The activity block legitimately updates as tools/thoughts accumulate, so
        it keeps its own single moving copy. It never carries the plan checklist,
        which is drawn separately by plan events and scrolls up independently.
        """
        with self._render_lock:
            activity_lines = self._render_activity_lines()
            if not activity_lines:
                return
            surface = self._activity_surface
            if not self._live_regions:
                signature = "".join(_ANSI_ESCAPE.sub("", line) for line in activity_lines)
                if signature == surface.append_signature:
                    return
                for line in activity_lines:
                    self._out.write(line)
                surface.visible_lines = []
                surface.at_bottom = False
                surface.append_signature = signature
                self._progress_plan.at_bottom = False
                self._out.flush()
                return
            self._erase_activity_locked()
            for line in activity_lines:
                self._out.write(line)
            surface.visible_lines = activity_lines
            # Non-TTY (piped/log) output is append-only: never mark at_bottom.
            surface.at_bottom = self._tty
            # The activity block is now the bottom-most row; the plan (above it)
            # is no longer erasable in place.
            self._progress_plan.at_bottom = False
            self._out.flush()

    def _record_tool_activity(self, event: dict[str, Any]) -> None:
        name = str(event.get("name", "")) or "tool"
        error = str(event.get("error", "") or "")
        summary = str(event.get("summary", "") or ("error" if error else "ok"))
        try:
            duration_s = float(str(event.get("duration_s", 0) or 0))
        except ValueError:
            duration_s = 0.0
        with self._render_lock:
            self._activity_seq += 1
            stat = self._activity_surface.tool_stats.setdefault(name, _ToolActivityStat())
            stat.count += 1
            stat.duration_s += max(0.0, duration_s)
            stat.summary = summary
            stat.last_seq = self._activity_seq
            stat.error = error
            if error:
                stat.errors += 1

    def _record_thought_activity_locked(self, region: _ThinkingRegion) -> None:
        # Trivially empty thinking phases ("Thought for 0s · 0 items") are
        # round-trip noise, not activity — drop them entirely.
        elapsed = time.monotonic() - region.start_ts
        if not region.items and elapsed < 1.0:
            return
        surface = self._activity_surface
        surface.thought_count += 1
        surface.thought_items += len(region.items)
        self._append_activity_notice_locked(
            _ANSI_ESCAPE.sub("", self._thinking_header(region, still_running=False)).strip()
        )

    def _append_activity_notice(self, text: str) -> None:
        with self._render_lock:
            self._append_activity_notice_locked(text)

    def _append_activity_notice_locked(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        notices = self._activity_surface.notices
        notices.append(clean)
        del notices[: max(0, len(notices) - self._MAX_ACTIVITY_NOTICE_LINES)]

    def _render_activity_lines(self) -> list[str]:
        surface = self._activity_surface
        tool_total = sum(stat.count for stat in surface.tool_stats.values())
        parts: list[str] = []
        if tool_total:
            parts.append(f"{tool_total} tool calls")
        if surface.thought_count:
            parts.append(f"{surface.thought_count} thoughts")
        fleet_line = self._fleet_summary_line()
        if not parts and not surface.notices and not fleet_line:
            return []

        lines: list[str] = []
        if parts or surface.notices:
            lines.append(f"\n  {DIM}Activity · {' · '.join(parts) or 'updated'}{RESET}\n")
            stats = sorted(
                surface.tool_stats.items(),
                key=lambda item: (-item[1].count, -item[1].last_seq, item[0]),
            )
            for name, stat in stats[: self._MAX_ACTIVITY_TOOL_LINES]:
                symbol = GLYPH_FAIL if stat.errors else GLYPH_OK
                color = FAIL if stat.errors else OK
                count = f" \u00d7{stat.count}" if stat.count > 1 else ""
                duration = f" ({stat.duration_s:.1f}s)" if stat.duration_s > 0 else ""
                if stat.errors:
                    # Honest mixed-outcome summary \u2014 never "\u2717 \u2026 \u2192 ok" (a red
                    # cross next to a stale success summary reads as a contradiction).
                    summary = stat.error or f"{stat.errors}/{stat.count} failed \u00b7 last ok"
                else:
                    summary = stat.summary or "ok"
                summary = _truncate_display(summary, TRUNCATE_SUMMARY)
                lines.append(
                    f"    {color}{symbol} {name}{RESET}{count} {GLYPH_ARROW} {summary}{duration}\n"
                )
            omitted = len(stats) - self._MAX_ACTIVITY_TOOL_LINES
            if omitted > 0:
                lines.append(f"    {DIM}\u2026 +{omitted} tool types{RESET}\n")
            for notice in surface.notices[-self._MAX_ACTIVITY_NOTICE_LINES :]:
                lines.append(f"    {DIM}{notice}{RESET}\n")
        if fleet_line:
            # A leading blank row only when the fleet line stands alone (no
            # Activity header above it), so it is not glued to prior output.
            lead = "" if lines else "\n"
            lines.append(f"{lead}  {fleet_line}\n")
        return lines

    def _fleet_summary_line(self) -> str:
        """One compact line summarising the running sub-agents, or '' if none.

        ``\u25c6 Fleet \u00b7 N running \u00b7 role_a, role_b`` uses the rose GEODE mark for
        running, a dim body, no emoji, truncated to fit the terminal width. Drawn
        only while at least one sub-agent is running (Stage 1 fleet view).

        Stage 1.5 \u2014 when exactly one sub-agent is running and its live current
        tool is known, the single label carries it (``role \u00b7 tool``). This stays
        one line; the multi-line per-agent activity breakdown is Stage 2.
        """
        running = self._fleet.running()
        if not running:
            return ""
        labels = [
            agent.role or _truncate_display(agent.description, TRUNCATE_FLEET_ROLE) or agent.task_id
            for agent in running
        ]
        # Single running agent with a known live tool → surface it inline (one
        # line, still width-truncated below). Kept to the single-agent case so
        # the comma-joined multi-agent list never turns into an ambiguous soup.
        if len(running) == 1 and running[0].current_activity:
            labels[0] = f"{labels[0]} \u00b7 {running[0].current_activity}"
        prefix = f"Fleet \u00b7 {len(running)} running \u00b7 "
        width = max(MIN_RENDER_WIDTH, shutil.get_terminal_size(fallback=FALLBACK_TERMINAL).columns)
        # Budget: total width minus the 2-space indent, the rose mark + space,
        # and the prefix; the remainder is for the comma-joined role names.
        budget = max(8, width - 2 - 2 - len(prefix))
        names = _truncate_display(", ".join(labels), budget)
        mark = f"{spinner_glyph.ROSE}{spinner_glyph.GLYPH}{RESET}"
        return f"{mark} {DIM}{prefix}{names}{RESET}"

    def _render_full_progress_plan(
        self, items: list[dict[Any, Any]], explanation: str
    ) -> list[str]:
        total = len(items)
        completed = sum(1 for item in items if str(item.get("status", "")) == "completed")
        header = f"Tasks · {completed}/{total} done"
        if explanation:
            header = f"{header} · {explanation}"
        # Signature rose (not mint) for the checklist header — the plan surface
        # shares GEODE's one hue with the spinner and the active-step mark.
        lines = ["\n", f"  {spinner_glyph.ROSE}{header}{RESET}\n"]
        visible_items, hidden_before, hidden_after = self._visible_plan_window(items)
        if hidden_before:
            lines.append(f"    {DIM}… {hidden_before} earlier{RESET}\n")
        for item in visible_items:
            status = str(item.get("status", "pending"))
            step = str(item.get("step", ""))
            symbol, style, text_style = self._progress_plan_symbol(status)
            lines.append(f"    {style}{symbol}{RESET} {text_style}{step}{RESET}\n")
        if hidden_after:
            lines.append(f"    {DIM}… {hidden_after} later{RESET}\n")
        lines.append("\n")
        return lines

    def _visible_plan_window(
        self, items: list[dict[Any, Any]]
    ) -> tuple[list[dict[Any, Any]], int, int]:
        """Return the Claude Code-scale task-list window around the active item."""
        if len(items) <= self._MAX_PLAN_VISIBLE_ITEMS:
            return items, 0, 0
        active_idx = next(
            (idx for idx, item in enumerate(items) if str(item.get("status", "")) == "in_progress"),
            -1,
        )
        if active_idx < 0:
            active_idx = next(
                (
                    idx
                    for idx, item in enumerate(items)
                    if str(item.get("status", "pending")) == "pending"
                ),
                len(items) - 1,
            )
        half = self._MAX_PLAN_VISIBLE_ITEMS // 2
        start = max(0, active_idx - half)
        end = min(len(items), start + self._MAX_PLAN_VISIBLE_ITEMS)
        start = max(0, end - self._MAX_PLAN_VISIBLE_ITEMS)
        return items[start:end], start, len(items) - end

    @staticmethod
    def _progress_plan_symbol(status: str) -> tuple[str, str, str]:
        """(symbol, symbol_style, text_style) — the Claude Code todo visual language:
        completed = checked off (dim + strikethrough), active = the rose GEODE mark
        in bold, pending = quiet. SGR 9 (strike) degrades to plain dim where unsupported.
        """
        if status == "completed":
            return GLYPH_OK, OK, DONE_STRIKE
        if status == "in_progress":
            return spinner_glyph.GLYPH, spinner_glyph.ROSE, BOLD
        return GLYPH_TODO, DIM, DIM

    def _suppress_all_spinners(self) -> None:
        """Stop thinking + tool spinners, clear line for new content."""
        self._activity_suppressed = True
        self._stop_thinking()
        self._tool_tracker.suspend()
        with self._render_lock:
            self._erase_activity_locked()
            if self._live_regions:
                self._out.write(f"\r{ERASE_LINE}")
            self._out.flush()

    def _clear_activity_line(self) -> None:
        """Clear the activity spinner line before writing a permanent line."""
        if self._activity and not self._activity_suppressed:
            with self._render_lock:
                self._erase_activity_locked()
                if self._live_regions:
                    self._out.write(f"\r{ERASE_LINE}")
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
        self._out.write(f"\r{ERASE_LINE}")
        moves = visual_lines if text.endswith("\n") else max(visual_lines - 1, 0)
        for _ in range(moves):
            self._out.write(cursor_up(1) + ERASE_LINE)
