from __future__ import annotations

import io
from typing import Any

from core.ui.event_renderer import EventRenderer, _ThinkingRegion


def _renderer() -> EventRenderer:
    renderer = EventRenderer()
    renderer._out = io.StringIO()
    renderer._tty = True
    return renderer


def _line(text: str) -> str:
    return f"  \033[90m∙ thinking · {text}\033[0m\n"


def test_collapse_writes_cursor_up_clear_and_header(monkeypatch: Any) -> None:
    renderer = _renderer()
    region = _ThinkingRegion(
        start_ts=100.0,
        items=[_line("one"), _line("two")],
        visible_lines=[_line("one"), _line("two")],
    )
    monkeypatch.setattr("core.ui.event_renderer.time.monotonic", lambda: 105.0)

    renderer._collapse_thinking_region_locked(region, still_running=False)

    out = renderer._out.getvalue()
    assert "\r\033[2K\033[2A" in out
    assert out.count("\r\033[2K") >= 3
    assert "✦ Thought for 5s · 2 items" in out
    assert region.is_collapsed is True


def test_reasoning_summary_while_collapsed_buffers_without_emitting() -> None:
    renderer = _renderer()
    region = _ThinkingRegion(start_ts=100.0, is_collapsed=True)
    renderer._thinking_region = region

    renderer._handle_reasoning_summary({"text": "hidden while collapsed"})

    assert region.items == [_line("hidden while collapsed")]
    assert renderer._out.getvalue() == ""


def test_toggle_round_trip_collapses_then_replays_buffer(monkeypatch: Any) -> None:
    renderer = _renderer()
    items = [_line("one"), _line("two")]
    region = _ThinkingRegion(start_ts=100.0, items=list(items), visible_lines=list(items))
    renderer._thinking_region = region
    monkeypatch.setattr("core.ui.event_renderer.time.monotonic", lambda: 109.0)

    renderer._toggle_thinking_collapse()
    assert region.is_collapsed is True
    assert "still running" in renderer._out.getvalue()

    renderer._out = io.StringIO()
    renderer._toggle_thinking_collapse()

    assert region.is_collapsed is False
    assert renderer._out.getvalue().endswith("".join(items))
    assert region.visible_lines == items


def test_thinking_end_collapses_to_final_header(monkeypatch: Any) -> None:
    renderer = _renderer()
    items = [_line(str(i)) for i in range(5)]
    renderer._thinking_region = _ThinkingRegion(
        start_ts=200.0,
        items=list(items),
        visible_lines=list(items),
    )
    monkeypatch.setattr("core.ui.event_renderer.time.monotonic", lambda: 212.0)

    renderer._handle_thinking_end({})

    out = renderer._out.getvalue()
    assert "✦ Thought for 12s · 5 items" in out
    assert "still running" not in out
    assert renderer._thinking_region is not None
    assert renderer._thinking_region.ended is True


def test_non_tty_keeps_existing_reasoning_lines_without_header() -> None:
    renderer = _renderer()
    renderer._tty = False
    renderer._thinking_region = _ThinkingRegion(start_ts=100.0)

    renderer._handle_reasoning_summary({"text": "plain fallback"})
    renderer._handle_thinking_end({})

    out = renderer._out.getvalue()
    assert "∙ thinking · plain fallback" in out
    assert "Thought for" not in out
    assert "\033[1A" not in out
