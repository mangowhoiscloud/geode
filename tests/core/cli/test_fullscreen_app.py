from __future__ import annotations

import threading
from unittest.mock import patch

from core.cli.fullscreen_app import (
    FullscreenThinCli,
    _materialize_transcript_lines,
    _wrap_plain_line,
)
from prompt_toolkit.data_structures import Point
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType


class _Client:
    def send_command(self, cmd: str, args: str = "") -> dict[str, object]:
        return {"type": "command_result", "output": f"{cmd} {args}".strip()}

    def send_prompt(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {"type": "result", "text": "ok"}

    def send_command_streaming(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {"type": "result", "text": "streamed"}


def test_cache_tokens_accumulate_render_and_reset_each_turn() -> None:
    app = FullscreenThinCli(_Client())
    app.state.status = "Working"
    app._on_event(
        {
            "type": "tokens",
            "model": "gpt-5.5",
            "input": 2000,
            "output": 100,
            "cache_read_tokens": 1200,
            "cache_write_tokens": 30,
            "cost": 0.1234,
        }
    )
    app._on_event({"type": "tokens", "input": 100, "output": 10, "cache_read_tokens": 50})
    # Older token events remain accepted and do not erase collected cache data.
    app._on_event({"type": "tokens", "input": 100, "output": 10})
    assert app.state.cache_read_tokens == 1250
    assert app.state.cache_write_tokens == 30
    status = "".join(text for _style, text in app._status_fragments())
    assert status.splitlines()[2] == "    cache read 1,250 / write 30 tok"
    assert app.status_control.create_content(width=80, height=3).line_count == 3
    status_window = app._build_root().children[4]
    assert status_window.preferred_height(80, 24).preferred == 3
    for rendered in (status, app._done_line()):
        assert "cache read 1,250 / write 30 tok" in rendered
        assert "est. API $0.1234" in rendered
        assert "down 2200 up 120" in rendered
    with patch("core.cli.fullscreen_app.threading.Thread"):
        app._submit_text("next task")
    assert app.state.cache_read_tokens == 0
    assert app.state.cache_write_tokens == 0
    assert "cache read" not in app._done_line()
    # prompt_toolkit caches fragments for one render counter; a live app
    # increments it on redraw. Simulate that next frame without running a UI.
    with patch("prompt_toolkit.layout.controls.get_app") as prompt_app:
        prompt_app.return_value.render_counter = 1
        assert app.status_control.create_content(width=80, height=3).line_count == 2
        assert status_window.preferred_height(80, 24).preferred == 2


def test_geo_slash_input_uses_streaming_command_path() -> None:
    from core.cli.routing import compose_command_registry
    from evals.slash_commands import EVAL_COMMAND_SPECS

    calls: list[tuple[str, str]] = []

    class Client(_Client):
        def send_command_streaming(
            self, cmd: str, args: str = "", **_callbacks: object
        ) -> dict[str, object]:
            calls.append((cmd, args))
            return {"type": "result", "text": "GEO audit"}

    app = FullscreenThinCli(
        Client(),
        command_registry=compose_command_registry(EVAL_COMMAND_SPECS),
    )
    app._run_text("/geo audit the public docs")

    assert calls == [("/geo", "audit the public docs")]
    assert "GEO audit" in app.state.transcript


def test_progress_plan_updates_fixed_plan_pane() -> None:
    app = FullscreenThinCli(_Client())

    app._on_event(
        {
            "type": "progress_plan",
            "plan": [
                {"step": "Inspect", "status": "completed"},
                {"step": "Patch", "status": "in_progress"},
            ],
        }
    )

    rendered = "".join(text for _style, text in app._plan_fragments())
    assert "Tasks · 1/2 done" in rendered
    assert "✓ Inspect" in rendered
    assert "◆ Patch" in rendered


def test_empty_plan_pane_stays_hidden() -> None:
    app = FullscreenThinCli(_Client())

    rendered = "".join(text for _style, text in app._plan_fragments())

    assert rendered == ""


def test_goal_decomposition_populates_plan_pane() -> None:
    app = FullscreenThinCli(_Client())

    app._on_event(
        {
            "type": "goal_decomposition",
            "steps": ["Inspect", "Patch", "Verify"],
        }
    )

    rendered = "".join(text for _style, text in app._plan_fragments())
    assert "Tasks · 0/3 done · 3 steps" in rendered
    assert "◆ Inspect" in rendered
    assert "○ Patch" in rendered


def test_plan_step_event_updates_existing_plan() -> None:
    app = FullscreenThinCli(_Client())
    app._on_event({"type": "goal_decomposition", "steps": ["Inspect", "Patch", "Verify"]})

    app._on_event(
        {
            "type": "plan_step",
            "current": 2,
            "total": 3,
            "description": "Patch CLI",
            "revision": 1,
        }
    )

    rendered = "".join(text for _style, text in app._plan_fragments())
    assert "Tasks · 1/3 done · step 2/3 · rev 1" in rendered
    assert "✓ Inspect" in rendered
    assert "◆ Patch CLI" in rendered


def test_progress_plan_windows_around_active_step() -> None:
    app = FullscreenThinCli(_Client())

    app._on_event(
        {
            "type": "progress_plan",
            "plan": [
                {"step": f"step {i}", "status": "in_progress" if i == 6 else "pending"}
                for i in range(1, 9)
            ],
        }
    )

    rendered = "".join(text for _style, text in app._plan_fragments())
    assert "… 3 earlier" in rendered
    assert "◆ step 6" in rendered
    assert "step 3" not in rendered


def test_tool_events_update_activity_pane_and_status() -> None:
    app = FullscreenThinCli(_Client())

    app._on_event({"type": "tool_start", "name": "grep_files"})
    assert app.state.status == "Running"
    assert app.state.activity == "tool: grep_files"
    assert app.state.transcript == []

    app._on_event(
        {
            "type": "tool_end",
            "name": "grep_files",
            "summary": "ok",
            "duration_s": 0.1,
        }
    )

    rendered = "".join(text for _style, text in app._activity_fragments())
    assert "Activity · 1 tool calls" in rendered
    assert "✓ grep_files" in rendered
    assert "→ ok" in rendered
    assert app.state.status == "Working"


def test_status_uses_classic_working_marker() -> None:
    app = FullscreenThinCli(_Client())

    app._set_status("Working")

    rendered = "".join(text for _style, text in app._status_fragments())
    assert "◆ Working.." in rendered
    assert "\n" in rendered


def test_footer_shows_geode_model_and_cwd() -> None:
    app = FullscreenThinCli(_Client())
    app.state.model = "gpt-5.5"

    rendered = "".join(text for _style, text in app._footer_fragments())

    assert rendered.startswith("  geode · gpt-5.5 · ")


def test_transcript_rows_are_bottom_aligned() -> None:
    app = FullscreenThinCli(_Client())
    app._append("> hello")
    app._append("• Running read_file")

    content = app.transcript_control.create_content(width=80, height=5)
    rendered_rows = ["".join(text for _style, text in content.get_line(i)) for i in range(5)]

    assert rendered_rows[:3] == ["", "", ""]
    assert rendered_rows[-2:] == ["> hello", "• Running read_file"]


def test_user_transcript_line_uses_default_text_color() -> None:
    app = FullscreenThinCli(_Client())
    app._append("> hello")

    content = app.transcript_control.create_content(width=80, height=1)

    assert content.get_line(0) == [("class:transcript", "> hello")]


def test_reasoning_summary_updates_activity_pane_without_raw_transcript() -> None:
    app = FullscreenThinCli(_Client())

    app._on_event({"type": "reasoning_summary", "text": "**Planning** first step"})

    rendered = "".join(text for _style, text in app._activity_fragments())
    assert "Activity · updated" in rendered
    assert "Thought: **Planning** first step" in rendered
    assert app.state.transcript == []


def test_plan_update_changes_fixed_plan_pane_without_transcript_copy() -> None:
    app = FullscreenThinCli(_Client())
    app._on_event(
        {
            "type": "progress_plan",
            "plan": [
                {"step": "Inspect", "status": "in_progress"},
                {"step": "Patch", "status": "pending"},
            ],
        }
    )
    app._on_event(
        {
            "type": "progress_plan",
            "plan": [
                {"step": "Inspect", "status": "completed"},
                {"step": "Patch", "status": "in_progress"},
            ],
        }
    )

    rendered = "".join(text for _style, text in app._plan_fragments())
    assert "Tasks · 1/2 done" in rendered
    assert "✓ Inspect" in rendered
    assert "◆ Patch" in rendered
    assert app.state.transcript == []


def test_update_plan_tool_is_hidden_from_activity_and_transcript() -> None:
    app = FullscreenThinCli(_Client())

    app._on_event({"type": "tool_start", "name": "update_plan"})
    app._on_event({"type": "tool_end", "name": "update_plan", "summary": "ok"})
    app._on_event(
        {
            "type": "progress_plan",
            "plan": [{"step": "Inspect", "status": "in_progress"}],
        }
    )

    activity = "".join(text for _style, text in app._activity_fragments())
    plan = "".join(text for _style, text in app._plan_fragments())
    assert "update_plan" not in activity
    assert app.state.transcript == []
    assert "Tasks · 0/1 done" in plan


def test_ctrl_o_collapses_and_expands_progress_surfaces() -> None:
    app = FullscreenThinCli(_Client())
    app._on_event(
        {
            "type": "progress_plan",
            "plan": [
                {"step": "Inspect", "status": "completed"},
                {"step": "Patch renderer", "status": "in_progress"},
                {"step": "Verify", "status": "pending"},
            ],
        }
    )
    app._on_event(
        {
            "type": "tool_end",
            "name": "grep_files",
            "summary": "ok",
            "duration_s": 0.1,
        }
    )

    app._toggle_progress_details()

    collapsed_plan = "".join(text for _style, text in app._plan_fragments())
    collapsed_activity = "".join(text for _style, text in app._activity_fragments())
    assert "Patch renderer · Ctrl+O expand" in collapsed_plan
    assert "Verify" not in collapsed_plan
    assert "Activity · 1 tool calls" in collapsed_activity
    assert "collapsed · Ctrl+O expand" in collapsed_activity
    assert "→ ok" not in collapsed_activity

    app._toggle_progress_details()

    expanded_plan = "".join(text for _style, text in app._plan_fragments())
    expanded_activity = "".join(text for _style, text in app._activity_fragments())
    assert "○ Verify" in expanded_plan
    assert "→ ok" in expanded_activity


def test_markdown_transcript_is_rendered_before_display() -> None:
    rows = _materialize_transcript_lines(
        [
            "### Hardware",
            "",
            "- 긴 decode에서 HBM bandwidth가 충분한가?",
            "- **token/sec**가 아니라 `cost/task`를 보는가?",
        ],
        80,
    )

    rendered = "\n".join(rows)
    assert "###" not in rendered
    assert "**" not in rendered
    assert "`cost/task`" not in rendered
    assert "Hardware" in rendered
    assert "긴 decode" in rendered


def test_page_scroll_changes_transcript_viewport() -> None:
    app = FullscreenThinCli(_Client())
    for index in range(30):
        app._append(f"line {index}")

    tail_content = app.transcript_control.create_content(width=80, height=5)
    tail_rows = ["".join(text for _style, text in tail_content.get_line(i)) for i in range(5)]
    assert tail_rows[-1] == "line 29"

    app._scroll_transcript(10)
    scrolled_content = app.transcript_control.create_content(width=80, height=5)
    scrolled_rows = [
        "".join(text for _style, text in scrolled_content.get_line(i)) for i in range(5)
    ]
    assert scrolled_rows[-1] == "line 19"

    app._scroll_transcript(-10_000)
    bottom_content = app.transcript_control.create_content(width=80, height=5)
    bottom_rows = ["".join(text for _style, text in bottom_content.get_line(i)) for i in range(5)]
    assert bottom_rows[-1] == "line 29"


def test_mouse_wheel_scrolls_transcript() -> None:
    app = FullscreenThinCli(_Client())
    for index in range(20):
        app._append(f"line {index}")
    app.transcript_control.create_content(width=80, height=5)

    app.transcript_control.mouse_handler(
        MouseEvent(
            position=Point(x=1, y=1),
            event_type=MouseEventType.SCROLL_UP,
            button=MouseButton.NONE,
            modifiers=frozenset(),
        )
    )

    assert app.state.transcript_scroll == 4


def test_scroll_offset_is_clamped_to_available_history() -> None:
    app = FullscreenThinCli(_Client())
    for index in range(3):
        app._append(f"line {index}")
    app._scroll_transcript(999)

    app.transcript_control.create_content(width=80, height=5)

    assert app.state.transcript_scroll == 0


def test_plan_update_appends_codex_style_transcript_cell_once() -> None:
    app = FullscreenThinCli(_Client())
    event = {
        "type": "progress_plan",
        "plan": [
            {"step": "Inspect", "status": "completed"},
            {"step": "Patch", "status": "in_progress"},
        ],
    }

    app._on_event(event)
    app._on_event(event)

    transcript = "\n".join(app.state.transcript)
    assert "• Updated Plan" not in transcript


def test_wrapped_event_lines_keep_codex_style_continuation_prefix() -> None:
    wrapped = _wrap_plain_line("• Ran a very long command with many words", 16)

    assert wrapped == ["• Ran a very", "  │ long command", "  │ with many", "  │ words"]


def test_input_uses_geode_border_frame() -> None:
    app = FullscreenThinCli(_Client())

    assert app.input_frame.body is app.input_window


def test_status_ticker_lifecycle() -> None:
    app = FullscreenThinCli(_Client())

    app.state.busy = True
    app._set_status("Working")
    app._ensure_status_ticker()

    assert app._status_tick_thread is not None
    assert app._status_tick_thread.is_alive()

    app.state.busy = False
    app._set_status("")
    app._stop_status_ticker()

    assert app._status_tick_thread is None


def test_approval_request_resolves_from_key_decision() -> None:
    app = FullscreenThinCli(_Client())
    result: dict[str, str] = {}

    def wait_for_decision() -> None:
        result["decision"] = app._on_approval_request({"tool_name": "computer", "detail": "click"})

    thread = threading.Thread(target=wait_for_decision)
    thread.start()
    assert app._approval_event is not None
    app._resolve_approval("y")
    thread.join(timeout=2)

    assert result["decision"] == "y"
    assert app.state.approval_pending is False


def test_local_model_picker_suspends_fullscreen_terminal(monkeypatch) -> None:
    import asyncio

    from prompt_toolkit.application.current import get_app
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    seen = []
    app = FullscreenThinCli(_Client())

    def collect(client, cmd, args, **kwargs):
        seen.append((client is app.client, cmd, args, get_app()._running_in_terminal))

    monkeypatch.setattr("core.cli.routing.run_thin_command", collect)

    async def run():
        with create_pipe_input() as terminal_input:
            app.app.input = terminal_input
            app.app.output = DummyOutput()
            app.app.renderer.output = app.app.output
            task = asyncio.create_task(app.app.run_async())
            try:
                while not app.app.is_running:
                    await asyncio.sleep(0)
                await asyncio.wait_for(asyncio.to_thread(app._run_text, "/model"), 3)
            finally:
                if app.app.is_running:
                    app.app.exit()
                await task

    asyncio.run(run())
    assert seen == [(True, "/model", "", True)]
    assert not app.state.busy
