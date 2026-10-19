"""Tests for CLI extracted modules — scheduler_drain, terminal."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestTerminal:
    """Test terminal utility functions."""

    def test_drain_stdin_non_tty(self) -> None:
        from core.cli.terminal import drain_stdin

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            drain_stdin()  # Should return immediately

    def test_restore_terminal_non_tty(self) -> None:
        from core.cli.terminal import restore_terminal

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.fileno.side_effect = ValueError("not a tty")
            restore_terminal()  # Should not raise

    def test_make_sigint_handler(self) -> None:
        from core.cli.terminal import make_sigint_handler

        handler = make_sigint_handler()
        assert callable(handler)


class TestSchedulerDrain:
    """Test scheduler drain function."""

    def test_empty_queue(self) -> None:
        import asyncio
        import queue

        from core.cli.scheduler_drain import drain_scheduler_queue

        q: queue.Queue = queue.Queue()
        result = asyncio.run(
            drain_scheduler_queue(
                action_queue=q,
                services=MagicMock(),
                session_lane=MagicMock(),
                global_lane=MagicMock(),
            )
        )
        assert result == 0
