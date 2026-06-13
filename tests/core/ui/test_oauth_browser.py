"""Tests for ``core.ui.oauth_browser`` + Press-Enter wiring on both
``emit_oauth_login_started`` render paths (IPC + direct fallback)."""

from __future__ import annotations

import io
from unittest.mock import patch


class TestStartOauthBrowserWatcher:
    """Module-level helper that spawns the daemon stdin watcher."""

    def test_skips_when_stdin_not_a_tty(self) -> None:
        """Non-interactive stdin (piped / CI) → no thread spawned."""
        from core.ui.oauth_browser import start_oauth_browser_watcher

        with (
            patch("core.ui.oauth_browser.sys.stdin") as fake_stdin,
            patch("core.ui.oauth_browser.threading.Thread") as fake_thread,
        ):
            fake_stdin.isatty.return_value = False
            start_oauth_browser_watcher("https://example.test/device")
            fake_thread.assert_not_called()

    def test_spawns_daemon_thread_when_tty(self) -> None:
        """Interactive stdin → daemon thread targeting the inner watcher."""
        from core.ui.oauth_browser import start_oauth_browser_watcher

        with (
            patch("core.ui.oauth_browser.sys.stdin") as fake_stdin,
            patch("core.ui.oauth_browser.threading.Thread") as fake_thread,
        ):
            fake_stdin.isatty.return_value = True
            start_oauth_browser_watcher("https://example.test/device")
            assert fake_thread.called
            _, kwargs = fake_thread.call_args
            assert kwargs["daemon"] is True
            assert kwargs["name"] == "oauth-browser-watcher"
            fake_thread.return_value.start.assert_called_once()


class TestEmitOauthLoginStartedFallback:
    """Direct (no-IPC-writer) path must include the Press-[Enter] prompt and
    spawn the browser watcher — wiring regression for the thin-CLI flow."""

    def test_fallback_prints_press_enter_prompt(self, monkeypatch, capsys) -> None:
        """`/login openai` runs THIN; emit must render the Enter
        prompt and invoke the watcher even without an IPC writer."""
        from core.ui import agentic_ui
        from core.ui.agentic_ui import events
        from core.ui.agentic_ui._state import _ipc_writer_local

        # Ensure no IPC writer is bound — force the fallback branch.
        if hasattr(_ipc_writer_local, "writer"):
            monkeypatch.delattr(_ipc_writer_local, "writer", raising=False)

        # Route console output to a buffer we can assert on.
        from rich.console import Console

        buf = io.StringIO()
        monkeypatch.setattr(agentic_ui, "console", Console(file=buf, force_terminal=False))

        watcher_calls: list[str] = []

        def _fake_watcher(uri: str) -> None:
            watcher_calls.append(uri)

        monkeypatch.setattr("core.ui.oauth_browser.start_oauth_browser_watcher", _fake_watcher)

        events.emit_oauth_login_started(
            provider="OpenAI ChatGPT",
            verification_uri="https://example.test/device",
            user_code="ABCD-1234",
        )

        rendered = buf.getvalue()
        assert "OpenAI ChatGPT OAuth Login" in rendered
        assert "https://example.test/device" in rendered
        assert "ABCD-1234" in rendered
        assert "Press [Enter]" in rendered
        assert "Waiting for sign-in" in rendered
        assert watcher_calls == ["https://example.test/device"]

    def test_ipc_path_skips_fallback(self, monkeypatch) -> None:
        """When the IPC writer is bound, fallback console output must NOT
        fire — event must be sent through the writer instead."""
        from core.ui.agentic_ui import events
        from core.ui.agentic_ui._state import _ipc_writer_local

        sent_events: list[tuple[str, dict[str, object]]] = []

        class _FakeWriter:
            def send_event(self, name: str, **kwargs: object) -> None:
                sent_events.append((name, dict(kwargs)))

        watcher_calls: list[str] = []

        def _fake_watcher(uri: str) -> None:
            watcher_calls.append(uri)

        monkeypatch.setattr("core.ui.oauth_browser.start_oauth_browser_watcher", _fake_watcher)

        # `threading.local()` doesn't pre-create `.writer`; assign directly +
        # try/finally to clear so the attribute doesn't leak to other tests.
        _ipc_writer_local.writer = _FakeWriter()
        try:
            events.emit_oauth_login_started(
                provider="OpenAI ChatGPT",
                verification_uri="https://example.test/device",
                user_code="ABCD-1234",
            )
        finally:
            if hasattr(_ipc_writer_local, "writer"):
                del _ipc_writer_local.writer

        assert len(sent_events) == 1
        assert sent_events[0][0] == "oauth_login_started"
        assert sent_events[0][1]["verification_uri"] == "https://example.test/device"
        # Fallback watcher must NOT be invoked here — the EventRenderer side
        # spawns it on receipt.
        assert watcher_calls == []
