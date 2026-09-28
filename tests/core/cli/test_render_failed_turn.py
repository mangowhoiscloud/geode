"""A failed turn's diagnostic reaches the thin CLI user, not just its code."""

from __future__ import annotations

from unittest.mock import patch

from core.cli.interactive_loop import _render_ipc_response


def test_failed_turn_shows_its_diagnostic() -> None:
    response = {
        "type": "result",
        "status": "error",
        "error": "model_action_required",
        "termination": "model_action_required",
        "text": "! API rate limited.\n\n  error_type : rate_limit",
    }
    with patch("core.cli.interactive_loop.console") as console:
        _render_ipc_response(response)
    printed = " ".join(str(call.args[0]) for call in console.print.call_args_list)
    assert "API rate limited" in printed and "rate_limit" in printed


def test_transport_error_still_shows_its_message() -> None:
    with patch("core.cli.interactive_loop.console") as console:
        _render_ipc_response({"type": "error", "message": "Connection lost"})
    assert "Connection lost" in str(console.print.call_args.args[0])
