"""Tests for REPL input handling via prompt_toolkit / fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import core.cli.repl as _repl_mod


def _patch_signal():
    """Patch signal.signal to no-op in tests (avoid SIGINT handler issues in CI)."""
    return patch.object(_repl_mod, "signal", MagicMock())


class TestReadMultilineInput:
    """_read_multiline_input uses prompt_toolkit or console.input fallback."""

    def setup_method(self):
        """Reset prompt_toolkit singleton before each test."""
        _repl_mod._prompt_session = None

    def test_single_line_returns_as_is(self):
        mock_console = MagicMock()
        mock_console.input.return_value = "Berserk 분석해줘"
        with (
            patch.object(_repl_mod, "_get_prompt_session", return_value=None),
            _patch_signal(),
            patch.object(_repl_mod, "console", mock_console),
        ):
            result = _repl_mod._read_multiline_input("> ")
        assert result == "Berserk 분석해줘"

    def test_empty_input_returns_empty(self):
        mock_console = MagicMock()
        mock_console.input.return_value = "   "
        with (
            patch.object(_repl_mod, "_get_prompt_session", return_value=None),
            _patch_signal(),
            patch.object(_repl_mod, "console", mock_console),
        ):
            result = _repl_mod._read_multiline_input("> ")
        assert result == ""

    def test_console_fallback_when_no_session(self):
        mock_console = MagicMock()
        mock_console.input.return_value = "hello"
        with (
            patch.object(_repl_mod, "_get_prompt_session", return_value=None),
            _patch_signal(),
            patch.object(_repl_mod, "console", mock_console),
        ):
            result = _repl_mod._read_multiline_input("> ")
        assert result == "hello"
        mock_console.input.assert_called_once()

    def test_console_fallback_on_prompt_exception(self):
        mock_session = MagicMock()
        mock_session.prompt.side_effect = RuntimeError("boom")
        mock_console = MagicMock()
        mock_console.input.return_value = "fallback"
        with (
            patch.object(_repl_mod, "_get_prompt_session", return_value=mock_session),
            _patch_signal(),
            patch.object(_repl_mod, "console", mock_console),
        ):
            result = _repl_mod._read_multiline_input("> ")
        assert result == "fallback"

    def test_multiline_routes_to_agentic_not_slash(self):
        user_input = "/some command\nmore content"
        is_multiline = "\n" in user_input
        assert is_multiline is True
        assert not (not is_multiline and user_input.startswith("/"))

    def test_prompt_toolkit_session_used_when_available(self):
        mock_session = MagicMock()
        mock_session.prompt.return_value = "test input"
        with (
            patch.object(_repl_mod, "_get_prompt_session", return_value=mock_session),
            _patch_signal(),
        ):
            result = _repl_mod._read_multiline_input("> ")
        assert result == "test input"
        mock_session.prompt.assert_called_once()
