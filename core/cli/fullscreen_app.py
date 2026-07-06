"""Full-screen thin CLI UI.

Owns the whole interactive terminal with prompt_toolkit:

    transcript (append-only)
    plan pane (fixed)
    status pane (fixed)
    input pane (fixed, GEODE rose border)

This avoids the old split-brain terminal model where PromptSession owned the
input line while EventRenderer moved status rows with raw cursor-up ANSI.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.formatted_text.base import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Dimension, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.widgets import Frame

from core import __version__
from core.time_format import format_elapsed
from core.ui import spinner_glyph
from core.ui.geodi_art import geodi_pixel_lines
from core.ui.mascot import _spec_lines

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TRANSCRIPT_HIDDEN_TOOLS = frozenset({"update_plan"})
_MARKDOWN_SPECIAL_PREFIXES = ("#", "-", "*", "1.", "```", ">", "|", "_")


def _plain(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text).replace("\r", "")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _wrap_plain_line(line: str, width: int) -> list[str]:
    """Wrap a transcript line to terminal width without adding hyphenation."""
    if width <= 1:
        return [line]
    if not line:
        return [""]

    def continuation_prefix(value: str) -> str:
        if value.startswith("  └ ") or value.startswith("  │ "):
            return "  │ "
        if value.startswith("    "):
            return "    "
        if value.startswith("• "):
            return "  │ "
        if value.startswith("> "):
            return "  "
        return ""

    def take_chunk(value: str, limit: int) -> tuple[str, str]:
        if len(value) <= limit:
            return value, ""
        cut = value.rfind(" ", 0, limit + 1)
        if cut < max(4, limit // 3):
            cut = limit
        return value[:cut].rstrip(), value[cut:].lstrip()

    current = line
    chunks: list[str] = []
    chunk, current = take_chunk(current, width)
    chunks.append(chunk)
    prefix = continuation_prefix(line)
    continuation_width = max(1, width - len(prefix))
    while current:
        chunk, current = take_chunk(current, continuation_width)
        chunks.append(f"{prefix}{chunk}")
    return [chunk for chunk in chunks if chunk != ""]


def _line_style(line: str) -> str:
    if line.startswith(">"):
        return "class:transcript"
    if line.startswith("  └ error:") or line.startswith("• Error"):
        return "class:err"
    if line.startswith("  └") or line.startswith("  │") or line.startswith("    "):
        return "class:transcript"
    if line.startswith("• "):
        return "class:event"
    if line.startswith("[system]"):
        return "class:dim"
    if line.startswith("Done in ") or line.startswith("✢ Worked for "):
        return "class:dim"
    return "class:transcript"


def _is_transcript_control_line(line: str) -> bool:
    return (
        line.startswith("> ")
        or line.startswith("• ")
        or line.startswith("  └")
        or line.startswith("  │")
        or line.startswith("[system]")
        or line.startswith("Done in ")
        or line.startswith("✢ Worked for ")
    )


def _looks_like_markdown(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(_MARKDOWN_SPECIAL_PREFIXES) or "**" in line or "`" in line


def _markdown_to_plain_lines(text: str, width: int) -> list[str]:
    if not text.strip():
        return [""]
    if not any(_looks_like_markdown(line) for line in text.splitlines()):
        lines: list[str] = []
        for line in text.splitlines() or [""]:
            lines.extend(_wrap_plain_line(line.rstrip(), width))
        return lines
    try:
        from rich.console import Console
        from rich.markdown import Markdown

        from core.ui.cjk_markdown import cjk_safe_emphasis

        buffer = StringIO()
        console = Console(
            file=buffer,
            force_terminal=False,
            width=max(20, width),
            color_system=None,
        )
        console.print(Markdown(cjk_safe_emphasis(text)))
        rendered = buffer.getvalue()
    except Exception:
        rendered = text
    lines = [line.rstrip() for line in rendered.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines or [""]


def _materialize_transcript_lines(source_lines: list[str], width: int) -> list[str]:
    rows: list[str] = []
    markdown_block: list[str] = []

    def flush_markdown() -> None:
        if not markdown_block:
            return
        rows.extend(_markdown_to_plain_lines("\n".join(markdown_block), width))
        markdown_block.clear()

    for line in source_lines:
        if _is_transcript_control_line(line):
            flush_markdown()
            rows.extend(_wrap_plain_line(line, width))
            continue
        markdown_block.append(line)
    flush_markdown()
    return rows


def _gradient_fragments(style_prefix: str, text: str) -> list[tuple[str, str]]:
    colors = ("#e77dae", "#ed8fbc", "#f2a6ca", "#f7bfd9")
    phase = int(time.monotonic() * 8) % len(colors)
    fragments: list[tuple[str, str]] = []
    for i, char in enumerate(text):
        color = colors[(i + phase) % len(colors)]
        fragments.append((f"{style_prefix} fg:{color}", char))
    return fragments


def _progress_plan_window(
    items: list[dict[str, str]], *, max_items: int
) -> tuple[list[dict[str, str]], int, int]:
    if len(items) <= max_items:
        return items, 0, 0
    active_idx = next(
        (idx for idx, item in enumerate(items) if item.get("status") == "in_progress"),
        -1,
    )
    if active_idx < 0:
        active_idx = next(
            (idx for idx, item in enumerate(items) if item.get("status", "pending") == "pending"),
            len(items) - 1,
        )
    half = max_items // 2
    start = max(0, active_idx - half)
    end = min(len(items), start + max_items)
    start = max(0, end - max_items)
    return items[start:end], start, len(items) - end


def _progress_plan_symbol(status: str) -> tuple[str, str, str]:
    if status == "completed":
        return "✓", "class:ok", "class:done-step"
    if status == "in_progress":
        return spinner_glyph.GLYPH, "class:run", "class:active-step"
    return "○", "class:dim", "class:dim"


def _format_activity_summary(summary: str, limit: int = 60) -> str:
    return _truncate(summary.replace("\n", " "), limit)


class _BottomTranscriptControl(UIControl):
    """Bottom-align transcript rows so new activity grows upward from input."""

    def __init__(self, state: FullscreenState, lock: Any, on_scroll: Any) -> None:
        self._state = state
        self._lock = lock
        self._on_scroll = on_scroll

    def is_focusable(self) -> bool:
        return False

    def create_content(self, width: int, height: int | None) -> UIContent:
        viewport_height = max(0, height or 0)
        viewport_width = max(1, width)
        with self._lock:
            source_lines = list(self._state.transcript)
            scroll_offset = max(0, self._state.transcript_scroll)
            self._state.transcript_view_width = viewport_width
            self._state.transcript_view_height = viewport_height

        wrapped = _materialize_transcript_lines(source_lines, viewport_width)
        max_scroll = max(0, len(wrapped) - viewport_height)
        scroll_offset = min(scroll_offset, max_scroll)
        with self._lock:
            self._state.transcript_scroll = scroll_offset

        if scroll_offset:
            end = max(0, len(wrapped) - scroll_offset)
            visible = wrapped[max(0, end - viewport_height) : end]
        else:
            visible = wrapped[-viewport_height:] if viewport_height else wrapped
        blanks = [""] * max(0, viewport_height - len(visible))
        rows = blanks + visible

        def get_line(index: int) -> StyleAndTextTuples:
            if index >= len(rows):
                return []
            line = rows[index]
            if not line:
                return [("class:transcript", "")]
            return [(_line_style(line), line)]

        return UIContent(get_line=get_line, line_count=len(rows), show_cursor=False)

    def mouse_handler(self, mouse_event: MouseEvent) -> None:
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self._on_scroll(4)
        elif mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self._on_scroll(-4)


@dataclass
class ActivityStat:
    count: int = 0
    errors: int = 0
    duration_s: float = 0.0
    summary: str = "ok"
    error: str = ""
    last_seq: int = 0


@dataclass
class FullscreenState:
    transcript: list[str] = field(default_factory=list)
    transcript_scroll: int = 0
    transcript_view_width: int = 80
    transcript_view_height: int = 0
    plan_items: list[dict[str, str]] = field(default_factory=list)
    plan_explanation: str = ""
    plan_signature: str = ""
    activity_stats: dict[str, ActivityStat] = field(default_factory=dict)
    activity_notices: list[str] = field(default_factory=list)
    activity_seq: int = 0
    thought_count: int = 0
    thought_items: int = 0
    progress_collapsed: bool = False
    status: str = ""
    activity: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    turn_started_at: float = 0.0
    busy: bool = False
    cwd: str = field(default_factory=lambda: str(Path.cwd()))
    approval_pending: bool = False
    approval_detail: str = ""


class FullscreenThinCli:
    """Prompt_toolkit Application wrapper for the thin CLI IPC client."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.state = FullscreenState()
        self._lock = threading.RLock()
        self._app: Application[Any] | None = None
        self._stream_started = False
        self._approval_event: threading.Event | None = None
        self._approval_decision = "n"
        self._status_tick_stop = threading.Event()
        self._status_tick_thread: threading.Thread | None = None

        self.header_control = FormattedTextControl(self._header_fragments)
        self.transcript_control = _BottomTranscriptControl(
            self.state,
            self._lock,
            self._scroll_transcript,
        )
        self.activity_control = FormattedTextControl(self._activity_fragments)
        self.plan_control = FormattedTextControl(self._plan_fragments)
        self.status_control = FormattedTextControl(self._status_fragments)
        self.footer_control = FormattedTextControl(self._footer_fragments)
        self.input_buffer = Buffer(multiline=False)
        self.input_window = Window(
            BufferControl(
                buffer=self.input_buffer,
                input_processors=[BeforeInput(FormattedText([("class:input", "> ")]))],
            ),
            height=1,
            style="class:input",
        )
        self.input_frame = Frame(
            self.input_window,
            style="class:input-border",
            height=3,
        )

        self.kb = self._build_key_bindings()
        self.layout = Layout(self._build_root(), focused_element=self.input_window)
        self.app: Application[Any] = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            mouse_support=True,
            style=self._style(),
        )
        self._app = self.app

    @staticmethod
    def _style() -> Any:
        from prompt_toolkit.styles import Style

        rose = spinner_glyph.ROSE_HEX
        return Style.from_dict(
            {
                "transcript": "fg:#f4f4f5 bg:#20242c",
                "header": "bg:#20242c",
                "plan": "fg:#f4f4f5 bg:#20242c",
                "status": "fg:#f4f4f5 bg:#20242c",
                "activity": "fg:#f4f4f5 bg:#20242c",
                "prompt": "fg:#f4f4f5 bg:#20242c",
                "input": "fg:#ffffff bg:#383d46",
                "input-border": f"fg:{rose} bg:#20242c",
                "footer": "fg:#d7d7d7 bg:#20242c",
                "cwd": "fg:#8fd694 bg:#20242c",
                "event": "bold fg:#f4f4f5",
                "dim": "fg:#8a8f98",
                "ok": "fg:#8fd694",
                "err": "fg:#ff8f8f",
                "run": f"bold fg:{rose}",
                "active-step": "bold fg:#f4f4f5",
                "done-step": "fg:#8a8f98",
            }
        )

    def _build_root(self) -> Any:
        return HSplit(
            [
                Window(self.header_control, height=7, style="class:header"),
                Window(
                    self.transcript_control,
                    style="class:transcript",
                    wrap_lines=False,
                    always_hide_cursor=True,
                ),
                Window(
                    self.plan_control,
                    height=Dimension(min=0, max=7),
                    style="class:plan",
                ),
                Window(
                    self.activity_control,
                    height=Dimension(min=0, max=7),
                    style="class:activity",
                ),
                Window(self.status_control, height=2, style="class:status"),
                self.input_frame,
                Window(self.footer_control, height=1, style="class:footer"),
            ]
        )

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("enter")
        def _submit(_event: Any) -> None:
            if self.state.approval_pending:
                return
            text = self.input_buffer.text.strip()
            self.input_buffer.text = ""
            if text:
                self._submit_text(text)

        @kb.add("pageup")
        def _scroll_up(_event: Any) -> None:
            self._scroll_transcript(12)

        @kb.add("pagedown")
        def _scroll_down(_event: Any) -> None:
            self._scroll_transcript(-12)

        @kb.add("c-up")
        def _scroll_up_small(_event: Any) -> None:
            self._scroll_transcript(3)

        @kb.add("c-down")
        def _scroll_down_small(_event: Any) -> None:
            self._scroll_transcript(-3)

        @kb.add("escape", "pageup")
        @kb.add("home")
        def _scroll_top(_event: Any) -> None:
            self._scroll_transcript(10_000)

        @kb.add("escape", "pagedown")
        @kb.add("end")
        def _scroll_bottom(_event: Any) -> None:
            self._scroll_transcript(-10_000)

        @kb.add("c-o")
        def _toggle_progress(_event: Any) -> None:
            self._toggle_progress_details()

        pending = Condition(lambda: self.state.approval_pending)

        @kb.add("y", filter=pending)
        def _approve_yes(_event: Any) -> None:
            self._resolve_approval("y")

        @kb.add("n", filter=pending)
        def _approve_no(_event: Any) -> None:
            self._resolve_approval("n")

        @kb.add("a", filter=pending)
        def _approve_always(_event: Any) -> None:
            self._resolve_approval("a")

        @kb.add("c-c")
        def _interrupt(_event: Any) -> None:
            if self.state.approval_pending:
                self._resolve_approval("n")
                return
            self._append_event("Interrupted")
            self._set_status("")

        @kb.add("c-d")
        def _exit(event: Any) -> None:
            event.app.exit()

        return kb

    def run(self) -> None:
        self.app.run()

    def _invalidate(self) -> None:
        app = self._app
        if app is not None:
            app.invalidate()

    def _ensure_status_ticker(self) -> None:
        thread = self._status_tick_thread
        if thread is not None and thread.is_alive():
            return
        self._status_tick_stop.clear()
        self._status_tick_thread = threading.Thread(target=self._status_tick_loop, daemon=True)
        self._status_tick_thread.start()

    def _stop_status_ticker(self) -> None:
        self._status_tick_stop.set()
        thread = self._status_tick_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        self._status_tick_thread = None

    def _status_tick_loop(self) -> None:
        while not self._status_tick_stop.wait(0.125):
            with self._lock:
                active = self.state.busy or bool(self.state.status)
            if not active:
                break
            self._invalidate()
        self._invalidate()

    def _append(self, text: str) -> None:
        with self._lock:
            for line in _plain(text).splitlines() or [""]:
                self.state.transcript.append(line)
            del self.state.transcript[: max(0, len(self.state.transcript) - 1000)]
        self._invalidate()

    def _scroll_transcript(self, delta: int) -> None:
        with self._lock:
            max_scroll = self._max_transcript_scroll_locked()
            self.state.transcript_scroll = min(
                max_scroll,
                max(0, self.state.transcript_scroll + delta),
            )
        self._invalidate()

    def _max_transcript_scroll_locked(self) -> int:
        rows = _materialize_transcript_lines(
            list(self.state.transcript),
            max(1, self.state.transcript_view_width),
        )
        return max(0, len(rows) - max(0, self.state.transcript_view_height))

    def _toggle_progress_details(self) -> None:
        with self._lock:
            self.state.progress_collapsed = not self.state.progress_collapsed
        self._invalidate()

    def _append_event(self, title: str, detail: str = "", *, error: bool = False) -> None:
        lines = [f"• {title}"]
        if detail:
            prefix = "  └ error: " if error else "  └ "
            lines.append(f"{prefix}{detail}")
        self._append("\n".join(lines))

    def _replace_recent_transcript_line(self, old: str, new: str) -> bool:
        with self._lock:
            for index in range(len(self.state.transcript) - 1, -1, -1):
                if self.state.transcript[index] == old:
                    self.state.transcript[index] = new
                    self._invalidate()
                    return True
        return False

    def _set_status(self, status: str, activity: str = "") -> None:
        with self._lock:
            self.state.status = status
            self.state.activity = activity
        self._invalidate()

    def _submit_text(self, text: str) -> None:
        with self._lock:
            if self.state.busy:
                self._append_event("Busy", "wait for the current run to finish")
                return
            self.state.busy = True
            self.state.turn_started_at = time.monotonic()
            self.state.input_tokens = 0
            self.state.output_tokens = 0
            self.state.cost = 0.0
            self.state.activity = ""
            self.state.transcript_scroll = 0
            self.state.activity_stats.clear()
            self.state.activity_notices.clear()
            self.state.activity_seq = 0
            self.state.thought_count = 0
            self.state.thought_items = 0
            self.state.progress_collapsed = False
            self._stream_started = False
        self._append(f"> {text}")
        self._set_status("Working")
        self._ensure_status_ticker()
        threading.Thread(target=self._run_text, args=(text,), daemon=True).start()

    def _run_text(self, text: str) -> None:
        try:
            if text.lower() in {"exit", "quit", "q"}:
                self._app_exit_threadsafe()
                return
            if text.startswith("/"):
                cmd = text.split()[0]
                response = self.client.send_command(cmd, text[len(cmd) :].strip())
                self._handle_command_response(response)
                return
            response = self.client.send_prompt(
                text,
                on_stream=self._on_stream,
                on_event=self._on_event,
                on_approval_request=self._on_approval_request,
            )
            self._handle_prompt_response(response)
        finally:
            with self._lock:
                self.state.busy = False
                self.state.approval_pending = False
            self._set_status("")
            self._stop_status_ticker()

    def _app_exit_threadsafe(self) -> None:
        app = self._app
        if app is None:
            return
        try:
            app.exit()
        except Exception:
            self._append_event("Exit requested")

    def _handle_command_response(self, response: dict[str, Any]) -> None:
        output = str(response.get("output", "") or "")
        if output:
            self._append(output)
        if response.get("status") == "error":
            self._append_event("Error", str(response.get("message", "Command failed")), error=True)
        if response.get("should_break"):
            self._app_exit_threadsafe()

    def _handle_prompt_response(self, response: dict[str, Any]) -> None:
        if response.get("type") == "error":
            self._append_event("Error", str(response.get("message", "Unknown error")), error=True)
            return
        text = str(response.get("text", "") or "")
        if text and not self._stream_started:
            self._append(text)
        self._append(self._done_line())

    def _done_line(self) -> str:
        with self._lock:
            elapsed = time.monotonic() - self.state.turn_started_at
            parts = [f"✢ Worked for {format_elapsed(elapsed)}"]
            if self.state.model:
                parts.append(self.state.model)
            if self.state.input_tokens or self.state.output_tokens:
                parts.append(f"down {self.state.input_tokens} up {self.state.output_tokens}")
            if self.state.cost:
                parts.append(f"${self.state.cost:.4f}")
        return " - ".join(parts)

    def _on_stream(self, data: str) -> None:
        self._stream_started = True
        if data:
            self._append(data)

    def _on_event(self, event: dict[str, Any]) -> None:
        etype = str(event.get("type", ""))
        if etype == "progress_plan":
            plan = event.get("plan", [])
            if isinstance(plan, list):
                explanation = str(event.get("explanation", "") or "")
                self._set_plan_items(
                    [
                        {
                            "step": str(item.get("step", "")),
                            "status": str(item.get("status", "pending")),
                        }
                        for item in plan
                        if isinstance(item, dict)
                    ],
                    explanation=explanation,
                )
            self._invalidate()
            return
        if etype == "goal_decomposition":
            steps = event.get("steps", [])
            if isinstance(steps, list):
                self._set_plan_items(
                    [
                        {
                            "step": str(step),
                            "status": "in_progress" if i == 0 else "pending",
                        }
                        for i, step in enumerate(steps)
                    ],
                    explanation=f"{len(steps)} steps" if steps else "",
                )
            self._set_status("Planning")
            return
        if etype == "plan_step":
            self._handle_plan_step_event(event)
            self._set_status("Planning")
            return
        if etype == "replan":
            self._handle_replan_event(event)
            self._set_status("Planning")
            return
        if etype == "thinking_start":
            self._set_status("Thinking")
            return
        if etype == "thinking_end":
            with self._lock:
                self.state.thought_count += 1
            self._set_status("Working")
            return
        if etype == "tool_start":
            name = str(event.get("name", "tool"))
            self._set_status("Running", f"tool: {name}")
            return
        if etype == "tool_end":
            name = str(event.get("name", "tool"))
            error = str(event.get("error", "") or "")
            summary = str(event.get("summary", "") or ("error" if error else "ok"))
            if name not in _TRANSCRIPT_HIDDEN_TOOLS:
                self._record_activity_tool(name, summary=summary, error=error, event=event)
            self._set_status("Working")
            return
        if etype == "tokens":
            with self._lock:
                self.state.model = str(event.get("model", "")) or self.state.model
                self.state.input_tokens += int(event.get("input", 0) or 0)
                self.state.output_tokens += int(event.get("output", 0) or 0)
                self.state.cost += float(event.get("cost", 0) or 0)
            self._invalidate()
            return
        if etype in {"quota_exhausted", "billing_error", "llm_error"}:
            self._append_event(
                "Error",
                str(event.get("message") or event.get("hint") or etype),
                error=True,
            )
            return
        if etype == "reasoning_summary":
            text = str(event.get("text", "")).strip().replace("\n", " ")
            if text:
                with self._lock:
                    self.state.thought_items += 1
                    self.state.activity_notices.append(f"Thought: {_truncate(text, 120)}")
                    del self.state.activity_notices[: max(0, len(self.state.activity_notices) - 2)]
                self._invalidate()

    def _record_activity_tool(
        self,
        name: str,
        *,
        summary: str,
        error: str,
        event: dict[str, Any],
    ) -> None:
        try:
            duration_s = float(str(event.get("duration_s", 0) or 0))
        except ValueError:
            duration_s = 0.0
        with self._lock:
            self.state.activity_seq += 1
            stat = self.state.activity_stats.setdefault(name, ActivityStat())
            stat.count += 1
            stat.duration_s += max(0.0, duration_s)
            stat.summary = summary or "ok"
            stat.error = error
            stat.last_seq = self.state.activity_seq
            if error:
                stat.errors += 1
        self._invalidate()

    def _on_approval_request(self, msg: dict[str, Any]) -> str:
        tool = str(msg.get("tool_name", "?"))
        detail = str(msg.get("detail", "") or "").replace("\n", " ")
        with self._lock:
            self.state.approval_pending = True
            self.state.approval_detail = f"{tool}: {_truncate(detail, 120)}"
            self._approval_decision = "n"
            self._approval_event = threading.Event()
        self._append_event("Approval", self.state.approval_detail)
        self._set_status("Approval required", "press y allow, n deny, a always")
        event = self._approval_event
        event.wait()
        return self._approval_decision

    def _resolve_approval(self, decision: str) -> None:
        with self._lock:
            self._approval_decision = decision
            self.state.approval_pending = False
            self.state.approval_detail = ""
            event = self._approval_event
            self._approval_event = None
        self._append_event("Approval decision", decision)
        if event is not None:
            event.set()
        self._invalidate()

    def _set_plan_items(self, items: list[dict[str, str]], *, explanation: str = "") -> None:
        normalized = [
            {
                "step": str(item.get("step", "")).strip(),
                "status": str(item.get("status", "pending")).strip() or "pending",
            }
            for item in items
            if str(item.get("step", "")).strip()
        ]
        clean_explanation = explanation.strip()
        signature = self._plan_signature(normalized, clean_explanation)
        with self._lock:
            self.state.plan_items = normalized
            self.state.plan_explanation = clean_explanation
            self.state.plan_signature = signature
        self._invalidate()

    @staticmethod
    def _plan_signature(items: list[dict[str, str]], explanation: str) -> str:
        parts = [explanation]
        parts.extend(f"{item.get('status', '')}:{item.get('step', '')}" for item in items)
        return "\n".join(parts)

    def _handle_plan_step_event(self, event: dict[str, Any]) -> None:
        current = int(event.get("current", 0) or 0)
        total = int(event.get("total", 0) or 0)
        revision = int(event.get("revision", 0) or 0)
        description = str(event.get("description", "") or "")
        if current <= 0 or total <= 0:
            return
        with self._lock:
            items = list(self.state.plan_items)
        if len(items) != total:
            items = [
                {"step": description if i == current else f"Step {i}", "status": "pending"}
                for i in range(1, total + 1)
            ]
        for idx, item in enumerate(items, 1):
            if idx < current:
                item["status"] = "completed"
            elif idx == current:
                item["status"] = "in_progress"
                if description:
                    item["step"] = description
            else:
                item["status"] = "pending"
        rev = f"rev {revision}" if revision else ""
        self._set_plan_items(
            items, explanation=f"step {current}/{total}{(' · ' + rev) if rev else ''}"
        )

    def _handle_replan_event(self, event: dict[str, Any]) -> None:
        trigger = str(event.get("trigger", "") or "")
        step_count = int(event.get("step_count", 0) or 0)
        revision = int(event.get("revision", 0) or 0)
        with self._lock:
            items = list(self.state.plan_items)
        if step_count > 0 and len(items) != step_count:
            items = [{"step": f"Step {i}", "status": "pending"} for i in range(1, step_count + 1)]
        parts = ["revised"]
        if trigger:
            parts.append(trigger)
        if step_count:
            parts.append(f"{step_count} steps")
        if revision:
            parts.append(f"rev {revision}")
        self._set_plan_items(items, explanation=" · ".join(parts))

    def _plan_fragments(self) -> FormattedText:
        with self._lock:
            items = list(self.state.plan_items)
            explanation = self.state.plan_explanation
            collapsed = self.state.progress_collapsed
        if not items:
            return FormattedText([])
        completed = sum(1 for item in items if item.get("status") == "completed")
        header = f"Tasks · {completed}/{len(items)} done"
        if explanation:
            header = f"{header} · {explanation}"
        if collapsed:
            active = next(
                (item.get("step", "") for item in items if item.get("status") == "in_progress"),
                "",
            )
            suffix = f" · {active}" if active else ""
            return FormattedText(
                [
                    ("class:run", f"  {header}"),
                    ("class:dim", f"{suffix} · Ctrl+O expand"),
                ]
            )
        fragments: list[tuple[str, str]] = [("class:run", f"  {header}"), ("", "\n")]
        visible, hidden_before, hidden_after = _progress_plan_window(items, max_items=5)
        if hidden_before:
            fragments.append(("class:dim", f"    … {hidden_before} earlier\n"))
        for item in visible:
            status = item.get("status", "pending")
            mark, symbol_style, text_style = _progress_plan_symbol(status)
            fragments.append((symbol_style, f"    {mark} "))
            fragments.append(("", item.get("step", "")))
            if text_style != "":
                step = item.get("step", "")
                fragments.pop()
                fragments.append((text_style, step))
            fragments.append(("", "\n"))
        if hidden_after:
            fragments.append(("class:dim", f"    … {hidden_after} later"))
        return FormattedText(fragments)

    def _activity_fragments(self) -> FormattedText:
        with self._lock:
            stats = dict(self.state.activity_stats)
            notices = list(self.state.activity_notices)
            thought_count = self.state.thought_count
            thought_items = self.state.thought_items
            collapsed = self.state.progress_collapsed
        tool_total = sum(stat.count for stat in stats.values())
        if not tool_total and not thought_count and not notices:
            return FormattedText([])

        parts: list[str] = []
        if tool_total:
            parts.append(f"{tool_total} tool calls")
        if thought_count:
            parts.append(f"{thought_count} thoughts")
        if collapsed:
            latest_tool = next(
                (
                    name
                    for name, _stat in sorted(
                        stats.items(),
                        key=lambda item: (-item[1].last_seq, item[0]),
                    )
                ),
                "",
            )
            suffix = f" · latest {latest_tool}" if latest_tool else ""
            return FormattedText(
                [
                    ("class:dim", f"  Activity · {' · '.join(parts) or 'updated'}"),
                    ("class:dim", f"{suffix} · collapsed · Ctrl+O expand"),
                ]
            )
        fragments: list[tuple[str, str]] = [
            ("class:dim", f"  Activity · {' · '.join(parts) or 'updated'}\n")
        ]
        ordered = sorted(
            stats.items(),
            key=lambda item: (-item[1].count, -item[1].last_seq, item[0]),
        )
        for name, stat in ordered[:5]:
            if stat.errors:
                fragments.append(("class:err", f"    ✗ {name}"))
                summary = stat.error or f"{stat.errors}/{stat.count} failed"
            else:
                fragments.append(("class:ok", f"    ✓ {name}"))
                summary = stat.summary or "ok"
            if stat.count > 1:
                fragments.append(("class:dim", f" ×{stat.count}"))
            fragments.append(("class:dim", " → "))
            fragments.append(("class:transcript", _format_activity_summary(summary)))
            if stat.duration_s > 0:
                fragments.append(("class:dim", f" ({stat.duration_s:.1f}s)"))
            fragments.append(("", "\n"))
        omitted = len(ordered) - 5
        if omitted > 0:
            fragments.append(("class:dim", f"    … +{omitted} tool types\n"))
        if thought_count and not notices:
            fragments.append(("class:dim", f"    Thought for this turn · {thought_items} items\n"))
        for notice in notices[-2:]:
            fragments.append(("class:dim", f"    {notice}\n"))
        return FormattedText(fragments)

    def _status_fragments(self) -> FormattedText:
        with self._lock:
            status = self.state.status
            activity = self.state.activity
            model = self.state.model
            busy = self.state.busy
            started = self.state.turn_started_at
            input_tokens = self.state.input_tokens
            output_tokens = self.state.output_tokens
            cost = self.state.cost
        if not status:
            return FormattedText([("class:dim", "")])
        if status == "Working":
            label = "Working.."
        elif status == "Running":
            label = "Running.."
        elif status == "Thinking":
            label = "Thinking.."
        elif status == "Planning":
            label = "Planning.."
        else:
            label = status
        details: list[str] = []
        if busy and started:
            details.append(format_elapsed(time.monotonic() - started))
        if model:
            details.append(model)
        if activity:
            details.append(activity)
        if input_tokens or output_tokens:
            details.append(f"down {input_tokens} up {output_tokens}")
        if cost:
            details.append(f"${cost:.4f}")

        fragments: list[tuple[str, str]] = []
        fragments.extend(_gradient_fragments("class:run bold", f"  ◆ {label}"))
        fragments.append(("", "\n"))
        detail_text = " · ".join(details) if details else "ready"
        fragments.append(("class:dim", f"    {detail_text}"))
        return FormattedText(fragments)

    def _footer_fragments(self) -> FormattedText:
        with self._lock:
            model = self.state.model
            cwd = self.state.cwd
        if not model:
            try:
                from core.config import settings

                model = settings.model
            except Exception:
                model = "model"
        home = str(Path.home())
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home) :]
        return FormattedText(
            [
                ("class:run", "  geode"),
                ("class:dim", " · "),
                ("class:footer", model),
                ("class:dim", " · "),
                ("class:cwd", cwd),
            ]
        )

    def _header_fragments(self) -> ANSI:
        try:
            from core.config import settings

            model = settings.model
        except Exception:
            model = ""
        art = geodi_pixel_lines()
        spec = _spec_lines(__version__, model, str(Path.cwd()))
        top = max(0, (len(art) - len(spec)) // 2)
        lines: list[str] = [""]
        for i, row in enumerate(art):
            j = i - top
            side = f"   {spec[j]}" if 0 <= j < len(spec) else ""
            lines.append(f"  {row}{side}")
        return ANSI("\n".join(lines))
