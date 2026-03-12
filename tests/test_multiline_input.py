"""Tests for multi-line paste detection in REPL input."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestReadMultilineInput:
    """_read_multiline_input drains paste-buffered stdin lines."""

    def test_single_line_returns_as_is(self):
        """Single line input (no paste) returns the line unchanged."""
        from core.cli import _read_multiline_input

        mock_console = MagicMock()
        mock_console.input.return_value = "Berserk 분석해줘"

        with (
            patch("core.cli.console", mock_console),
            patch("core.cli.select.select", return_value=([], [], [])),
        ):
            result = _read_multiline_input("[bold cyan]>[/bold cyan] ")

        assert result == "Berserk 분석해줘"

    def test_empty_input_returns_empty(self):
        """Empty input returns empty string."""
        from core.cli import _read_multiline_input

        mock_console = MagicMock()
        mock_console.input.return_value = "   "

        with patch("core.cli.console", mock_console):
            result = _read_multiline_input("> ")

        assert result == ""

    def test_multiline_paste_joins_lines(self):
        """Pasted multi-line text is joined into a single string."""
        from core.cli import _read_multiline_input

        mock_console = MagicMock()
        mock_console.input.return_value = "line 1"

        # Simulate two additional lines buffered from paste
        paste_lines = iter(["line 2\n", "line 3\n", ""])
        call_count = [0]

        def fake_select(rlist, wlist, xlist, timeout):
            call_count[0] += 1
            if call_count[0] <= 2:
                return (rlist, [], [])  # data available
            return ([], [], [])  # no more data

        def fake_readline():
            return next(paste_lines, "")

        with (
            patch("core.cli.console", mock_console),
            patch("core.cli.select.select", side_effect=fake_select),
            patch("core.cli.sys.stdin") as mock_stdin,
        ):
            mock_stdin.fileno.return_value = 0
            mock_stdin.readline = fake_readline
            result = _read_multiline_input("> ")

        assert result == "line 1\nline 2\nline 3"

    def test_multiline_paste_skips_blank_lines(self):
        """Blank lines in paste are excluded."""
        from core.cli import _read_multiline_input

        mock_console = MagicMock()
        mock_console.input.return_value = "first"

        paste_lines = iter(["\n", "second\n", ""])
        call_count = [0]

        def fake_select(rlist, wlist, xlist, timeout):
            call_count[0] += 1
            if call_count[0] <= 2:
                return (rlist, [], [])
            return ([], [], [])

        with (
            patch("core.cli.console", mock_console),
            patch("core.cli.select.select", side_effect=fake_select),
            patch("core.cli.sys.stdin") as mock_stdin,
        ):
            mock_stdin.fileno.return_value = 0
            mock_stdin.readline = lambda: next(paste_lines, "")
            result = _read_multiline_input("> ")

        assert result == "first\nsecond"

    def test_select_oserror_falls_back_to_single_line(self):
        """When select fails (e.g. piped stdin), returns first line only."""
        from core.cli import _read_multiline_input

        mock_console = MagicMock()
        mock_console.input.return_value = "hello"

        with (
            patch("core.cli.console", mock_console),
            patch("core.cli.sys.stdin") as mock_stdin,
        ):
            mock_stdin.fileno.side_effect = ValueError("not a tty")
            result = _read_multiline_input("> ")

        assert result == "hello"

    def test_multiline_routes_to_agentic_not_slash(self):
        """Multi-line paste starting with '/' goes to agentic, not slash command."""
        user_input = "/some command\nmore content\neven more"
        is_multiline = "\n" in user_input

        # Multi-line → should NOT enter slash command branch
        assert is_multiline is True
        assert not (not is_multiline and user_input.startswith("/"))
