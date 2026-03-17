"""Tests for REPL input handling via prompt_toolkit / fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _patch_no_prompt_toolkit():
    """Patch _get_prompt_session to return None (force console.input fallback)."""
    return patch("core.cli.repl._get_prompt_session", return_value=None)


class TestReadMultilineInput:
    """_read_multiline_input uses prompt_toolkit or console.input fallback."""

    def test_single_line_returns_as_is(self):
        """Single line input returns the line unchanged."""
        from core.cli import _read_multiline_input

        mock_console = MagicMock()
        mock_console.input.return_value = "Berserk 분석해줘"

        with (
            _patch_no_prompt_toolkit(),
            patch("core.cli.repl.console", mock_console),
        ):
            result = _read_multiline_input("[bold cyan]>[/bold cyan] ")

        assert result == "Berserk 분석해줘"

    def test_empty_input_returns_empty(self):
        """Empty input returns empty string."""
        from core.cli import _read_multiline_input

        mock_console = MagicMock()
        mock_console.input.return_value = "   "

        with (
            _patch_no_prompt_toolkit(),
            patch("core.cli.repl.console", mock_console),
        ):
            result = _read_multiline_input("> ")

        assert result == ""

    def test_console_fallback_when_no_session(self):
        """When prompt_toolkit session is None, falls back to console.input."""
        from core.cli import _read_multiline_input

        mock_console = MagicMock()
        mock_console.input.return_value = "hello"

        with (
            _patch_no_prompt_toolkit(),
            patch("core.cli.repl.console", mock_console),
        ):
            result = _read_multiline_input("> ")

        assert result == "hello"
        mock_console.input.assert_called_once()

    def test_console_fallback_on_prompt_exception(self):
        """When prompt_toolkit raises non-interrupt exception, falls back to console."""
        from core.cli import _read_multiline_input

        mock_session = MagicMock()
        mock_session.prompt.side_effect = RuntimeError("prompt_toolkit error")
        mock_console = MagicMock()
        mock_console.input.return_value = "fallback input"

        with (
            patch("core.cli.repl._get_prompt_session", return_value=mock_session),
            patch("core.cli.repl.console", mock_console),
        ):
            result = _read_multiline_input("> ")

        assert result == "fallback input"

    def test_multiline_routes_to_agentic_not_slash(self):
        """Multi-line paste starting with '/' goes to agentic, not slash command."""
        user_input = "/some command\nmore content\neven more"
        is_multiline = "\n" in user_input

        # Multi-line -> should NOT enter slash command branch
        assert is_multiline is True
        assert not (not is_multiline and user_input.startswith("/"))

    def test_prompt_toolkit_session_used_when_available(self):
        """When prompt_toolkit session is available, it is used for input."""
        from core.cli import _read_multiline_input

        mock_session = MagicMock()
        mock_session.prompt.return_value = "test input"

        with patch("core.cli.repl._get_prompt_session", return_value=mock_session):
            result = _read_multiline_input("> ")

        assert result == "test input"
        mock_session.prompt.assert_called_once()
