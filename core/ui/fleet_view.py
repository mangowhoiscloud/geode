"""Interactive full-screen fleet view — Stage 2 of the multi-agent fleet view.

Design SOT: ``docs/plans/2026-07-03-fleet-view.md``. Stage 1 built the
:class:`~core.ui.fleet.FleetRegistry` data layer + a one-line turn-time summary;
Stage 1.5 plumbed live per-agent activity. Stage 2 (this module) is the
on-demand interactive picker the operator opens with ``/fleet``: a
``prompt_toolkit`` full-screen :class:`Application` that lists every sub-agent
(running first), moves a selection with ↑/↓, opens a per-agent detail pane on
Enter, and exits back to the REPL on Esc/q.

Data source (honest scope). The :class:`EventRenderer` that owns the live
registry is created *per prompt* in the thin client and discarded at turn end;
``/fleet`` is typed at the REPL **between** turns, where that per-turn registry
is already gone and — because the REPL blocks inside ``send_prompt`` with no
concurrent stdin reader — a full-screen app cannot be opened *during* a turn.
So the view reads a session-scoped last-snapshot holder
(:func:`core.ui.fleet.get_last_fleet_snapshot`) that ``EventRenderer.stop``
writes at the end of every turn that dispatched ≥1 sub-agent. It therefore
shows the most recent turn's fleet with each agent's **final** state (role,
status, elapsed, tokens); ``current_activity`` is ``""`` for a completed agent
(it is cleared on the terminal transition), so the live "Reading …" tool text
from the Stage-1 summary is a during-turn artefact, not a between-turns one.
Live-during-turn interactivity is a deferred follow-up (it needs a concurrent
input surface the blocking REPL does not have).

The row/detail/number formatting are pure functions (:func:`compact_tokens`,
:func:`compact_elapsed`, :func:`build_fleet_rows`, :func:`build_detail_lines`)
so they can be unit-tested without spinning the event loop; the
:class:`_FleetView` wrapper only binds keys + styles on top of them.
"""

from __future__ import annotations

import shutil
import sys
from typing import TYPE_CHECKING, Any

from core.ui import spinner_glyph
from core.ui.console import console

if TYPE_CHECKING:
    from core.ui.fleet import FleetAgent

#: Shown (dim, one line, no app) when no sub-agent has run this session.
EMPTY_MESSAGE = "No sub-agents this session."

#: Terminal-status glyphs. Running reuses the single-source GEODE rose mark
#: (``spinner_glyph.GLYPH``); the rest are the same check/cross the activity
#: region already uses (``✓`` / ``✗``), plus a non-emoji hourglass for
#: timeout. No pictographic emoji (house style).
_STATUS_GLYPH: dict[str, str] = {
    "running": spinner_glyph.GLYPH,  # ◆
    "done": "✓",  # ✓
    "error": "✗",  # ✗
    "timeout": "⧗",  # ⧗
}


def compact_tokens(tokens: int) -> str:
    """Compact ``↓160k`` / ``↓1.2M`` token label, or ``""`` when there are none.

    ``0`` → ``""`` (subscription / CLI-routed calls expose no usage — the count
    is honestly absent, never faked). ``< 1000`` shows the raw count, ``< 1M``
    rounds to ``k``, ``>= 1M`` shows one decimal ``M`` (trailing ``.0`` dropped).
    The ``↓`` mirrors the Claude Code fleet screenshot's received-tokens arrow.
    """
    if tokens <= 0:
        return ""
    if tokens >= 1_000_000:
        value = f"{tokens / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"↓{value}M"
    if tokens >= 1000:
        thousands = round(tokens / 1000)
        if thousands >= 1000:  # 999_500+ rounds up to 1000k — promote to M
            return "↓1M"
        return f"↓{thousands}k"
    return f"↓{tokens}"


def compact_elapsed(seconds: float) -> str:
    """Compact ``4m48s`` / ``2m51s`` / ``9s`` / ``1h04m`` elapsed label.

    Distinct from :func:`spinner_glyph.elapsed` (``1m 05s``, with a space): the
    fleet rows use the space-free ``4m48s`` shape from the reference screenshot.
    """
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _status_glyph(status: str) -> str:
    return _STATUS_GLYPH.get(status, "•")  # • for an unknown status


def _truncate(text: str, width: int) -> str:
    """Truncate ``text`` to ``width`` columns with a trailing ellipsis."""
    if width <= 0 or len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


def build_fleet_rows(
    agents: list[FleetAgent],
    *,
    selected_index: int = -1,
    width: int | None = None,
) -> list[str]:
    """Build one plain-text row per agent (caller supplies snapshot order).

    Each row is ``<pointer><glyph> <role> · <activity> · <elapsed> · <↓tokens>``,
    dot-joined (house style), width-truncated. The selected row carries a ``❯``
    pointer; empty segments (no live activity, no tokens) are dropped rather
    than rendered as blanks. Agents are rendered in the given order — pass a
    :meth:`~core.ui.fleet.FleetRegistry.snapshot` (already running-first) so the
    rows are running-first. Returns ``[]`` for no agents (the caller prints
    :data:`EMPTY_MESSAGE` instead of an empty list surface).
    """
    if not agents:
        return []
    if width is None:
        width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)
    rows: list[str] = []
    for index, agent in enumerate(agents):
        pointer = "❯ " if index == selected_index else "  "
        label = agent.role or _truncate(agent.description, 30) or agent.task_id
        segments = [f"{_status_glyph(agent.status)} {label}"]
        if agent.current_activity:
            segments.append(agent.current_activity)
        segments.append(compact_elapsed(agent.elapsed_s))
        tokens = compact_tokens(agent.tokens)
        if tokens:
            segments.append(tokens)
        rows.append(_truncate(pointer + " · ".join(segments), width))
    return rows


def build_detail_lines(agent: FleetAgent) -> list[str]:
    """Build the per-agent detail pane as dense key/value plain-text lines."""
    return [
        f"task_id    {agent.task_id}",
        f"role       {agent.role or '(none)'}",
        f"status     {agent.status}",
        f"elapsed    {compact_elapsed(agent.elapsed_s)}",
        f"tokens     {compact_tokens(agent.tokens) or '(none)'}",
        f"activity   {agent.current_activity or '(none)'}",
        "",
        "description",
        f"  {agent.description or '(none)'}",
    ]


class _FleetView:
    """Full-screen ``prompt_toolkit`` picker over a fleet snapshot.

    Two modes: ``list`` (↑/↓ select, Enter → detail) and ``detail`` (Enter/Esc
    → list). Esc/q from the list exits the app back to the REPL. Rendering is
    delegated to the pure :func:`build_fleet_rows` / :func:`build_detail_lines`;
    this class only maps state → styled fragments and binds the keys.
    """

    def __init__(self, agents: list[FleetAgent]) -> None:
        self._agents = agents
        self._selected = 0
        self._mode = "list"  # "list" | "detail"
        self._app = self._build_app()

    def _header_fragments(self) -> list[tuple[str, str]]:
        running = sum(1 for agent in self._agents if agent.is_running)
        return [("class:header", f"Fleet · {len(self._agents)} agents · {running} running\n")]

    def _body_fragments(self) -> list[tuple[str, str]]:
        if self._mode == "detail":
            lines = build_detail_lines(self._agents[self._selected])
            return [("", "\n".join(lines))]
        rows = build_fleet_rows(self._agents, selected_index=self._selected)
        fragments: list[tuple[str, str]] = []
        for index, (agent, row) in enumerate(zip(self._agents, rows, strict=True)):
            if index == self._selected:
                style = "class:selected"
            elif agent.is_running:
                style = "class:running"
            else:
                style = "class:done"
            fragments.append((style, row + "\n"))
        return fragments

    def _footer_fragments(self) -> list[tuple[str, str]]:
        hint = (
            "Enter/Esc back · q quit"
            if self._mode == "detail"
            else "↑/↓ select · Enter view · q quit"
        )
        return [("class:footer", hint)]

    def _build_app(self) -> Any:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.layout import Layout
        from prompt_toolkit.styles import Style

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(_event: Any) -> None:
            if self._mode == "list":
                self._selected = (self._selected - 1) % len(self._agents)

        @kb.add("down")
        @kb.add("j")
        def _down(_event: Any) -> None:
            if self._mode == "list":
                self._selected = (self._selected + 1) % len(self._agents)

        @kb.add("enter")
        def _enter(_event: Any) -> None:
            self._mode = "detail" if self._mode == "list" else "list"

        @kb.add("escape")
        @kb.add("q")
        @kb.add("c-c")
        def _back_or_quit(event: Any) -> None:
            if self._mode == "detail":
                self._mode = "list"
            else:
                event.app.exit()

        layout = Layout(
            HSplit(
                [
                    Window(FormattedTextControl(self._header_fragments), height=1),
                    Window(FormattedTextControl(self._body_fragments), wrap_lines=False),
                    Window(FormattedTextControl(self._footer_fragments), height=1),
                ]
            )
        )
        style = Style.from_dict(
            {
                "header": "bold",
                "selected": f"reverse fg:{spinner_glyph.ROSE_HEX}",
                "running": spinner_glyph.ROSE_HEX,
                "done": "#808080",
                "footer": "#808080",
            }
        )
        return Application(layout=layout, key_bindings=kb, style=style, full_screen=True)

    def run(self) -> None:
        self._app.run()


def run_fleet_view(agents: list[FleetAgent]) -> None:
    """Open the interactive fleet view over ``agents`` (a fleet snapshot).

    Prints :data:`EMPTY_MESSAGE` and returns without spinning a full-screen app
    when the snapshot is empty (no sub-agent has run this session). Under a
    non-interactive stdout (piped / headless) a full-screen prompt_toolkit
    Application cannot run, so fall back to a plain printed list (Codex).
    """
    if not agents:
        console.print(f"  [muted]{EMPTY_MESSAGE}[/muted]")
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        for row in build_fleet_rows(agents, selected_index=-1):
            console.print(f"  {row}")
        return
    _FleetView(agents).run()
