"""v0.51.1 — IPC output parity tests.

Daemon-side flows that prompt the user (OAuth device-code, billing
errors, /clear confirmation) must surface through the IPC event channel
so thin-client REPLs see them. Pre-v0.51.1 these used native ``print()``
or ``rich.console.Console()`` which only reached daemon stdout.
"""

from __future__ import annotations

from typing import Any

from core.cli.ui import agentic_ui
from core.cli.ui.event_renderer import EventRenderer


class _CapturingWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def send_event(self, event_type: str, **payload: Any) -> None:
        self.events.append({"type": event_type, **payload})


def _swap_writer(writer: _CapturingWriter | None) -> _CapturingWriter | None:
    prior = getattr(agentic_ui._ipc_writer_local, "writer", None)
    if writer is None:
        agentic_ui._ipc_writer_local.writer = None  # type: ignore[attr-defined]
    else:
        agentic_ui._ipc_writer_local.writer = writer  # type: ignore[attr-defined]
    return prior


class TestOAuthIpcEvents:
    def test_started_event_includes_uri_and_code(self) -> None:
        w = _CapturingWriter()
        prior = _swap_writer(w)
        try:
            agentic_ui.emit_oauth_login_started(
                provider="OpenAI Codex",
                verification_uri="https://example.test/device",
                user_code="ABCD-1234",
            )
        finally:
            _swap_writer(prior)
        assert w.events == [
            {
                "type": "oauth_login_started",
                "provider": "OpenAI Codex",
                "verification_uri": "https://example.test/device",
                "user_code": "ABCD-1234",
            }
        ]

    def test_pending_event_carries_elapsed_seconds(self) -> None:
        w = _CapturingWriter()
        prior = _swap_writer(w)
        try:
            agentic_ui.emit_oauth_login_pending("OpenAI Codex", 5)
            agentic_ui.emit_oauth_login_pending("OpenAI Codex", 10)
        finally:
            _swap_writer(prior)
        assert [e["elapsed_s"] for e in w.events] == [5, 10]

    def test_success_event_includes_metadata(self) -> None:
        w = _CapturingWriter()
        prior = _swap_writer(w)
        try:
            agentic_ui.emit_oauth_login_success(
                provider="OpenAI Codex",
                account_id="acct-123",
                email="user@example.test",
                plan_type="plus",
                stored_at="/var/folders/test/auth.toml",
            )
        finally:
            _swap_writer(prior)
        assert w.events[0]["type"] == "oauth_login_success"
        assert w.events[0]["email"] == "user@example.test"
        assert w.events[0]["plan_type"] == "plus"
        assert w.events[0]["stored_at"] == "/var/folders/test/auth.toml"

    def test_failed_event_carries_reason(self) -> None:
        w = _CapturingWriter()
        prior = _swap_writer(w)
        try:
            agentic_ui.emit_oauth_login_failed("OpenAI Codex", "cancelled by user")
        finally:
            _swap_writer(prior)
        assert w.events == [
            {
                "type": "oauth_login_failed",
                "provider": "OpenAI Codex",
                "reason": "cancelled by user",
            }
        ]

    def test_emitters_fall_back_to_console_in_direct_mode(self, capsys) -> None:
        prior = _swap_writer(None)
        try:
            agentic_ui.emit_oauth_login_started(
                "OpenAI Codex", "https://example.test/device", "XYZ-1"
            )
        finally:
            _swap_writer(prior)
        captured = capsys.readouterr()
        # Rich strips ANSI when not attached to a terminal — the URL and
        # code should appear in the captured output.
        assert "OpenAI Codex" in captured.out
        assert "https://example.test/device" in captured.out
        assert "XYZ-1" in captured.out


class TestBillingErrorEvent:
    def test_billing_error_event_carries_message(self) -> None:
        w = _CapturingWriter()
        prior = _swap_writer(w)
        try:
            agentic_ui.emit_billing_error("Insufficient credits")
        finally:
            _swap_writer(prior)
        assert w.events == [{"type": "billing_error", "message": "Insufficient credits"}]


class TestRendererHandlersExist:
    def test_oauth_event_handlers_dispatch(self) -> None:
        # Prove EventRenderer routes the new event types to handlers.
        renderer = EventRenderer()
        for etype in (
            "oauth_login_started",
            "oauth_login_pending",
            "oauth_login_success",
            "oauth_login_failed",
            "billing_error",
        ):
            assert hasattr(renderer, f"_handle_{etype}"), etype


class TestClearForceGate:
    def test_clear_in_ipc_mode_requires_force(self) -> None:
        from unittest.mock import MagicMock, patch

        from core.cli.commands import cmd_clear

        ctx = MagicMock()
        ctx.messages = [{"role": "user", "content": "hi"}]
        ctx.clear = MagicMock()

        # Pretend we are in IPC mode by attaching a writer.
        w = _CapturingWriter()
        prior = _swap_writer(w)
        try:
            with (
                patch("core.cli.commands.get_conversation_context", return_value=ctx),
                patch("core.cli.commands.console") as mock_console,
            ):
                cmd_clear("")
                # Should NOT have cleared messages in IPC mode without --force
                ctx.clear.assert_not_called()
                # Should have surfaced a refusal message
                printed = " ".join(
                    str(call.args[0]) for call in mock_console.print.call_args_list if call.args
                )
                assert "--force" in printed
        finally:
            _swap_writer(prior)

    def test_clear_force_flag_proceeds_in_ipc_mode(self) -> None:
        from unittest.mock import MagicMock, patch

        from core.cli.commands import cmd_clear

        ctx = MagicMock()
        ctx.messages = [{"role": "user", "content": "hi"}]
        ctx.clear = MagicMock()

        w = _CapturingWriter()
        prior = _swap_writer(w)
        try:
            with (
                patch("core.cli.commands.get_conversation_context", return_value=ctx),
                patch("core.cli.commands.console"),
                patch("core.llm.token_tracker.reset_tracker"),
            ):
                cmd_clear("--force")
                ctx.clear.assert_called_once()
        finally:
            _swap_writer(prior)
