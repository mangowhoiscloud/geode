"""Tests for CLI extracted modules — memory_handler, scheduler_drain, terminal."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestTerminal:
    """Test terminal utility functions."""

    def test_suppress_noisy_warnings(self) -> None:
        from core.cli.terminal import suppress_noisy_warnings

        # Should not raise
        suppress_noisy_warnings()

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


class TestMemoryHandler:
    """Test memory action handler."""

    def test_unrecognized_action(self, capsys: object) -> None:
        from core.cli.memory_handler import handle_memory_action

        handle_memory_action(
            {"query": None, "key": None, "content": None, "rule_action": None}, "", False
        )
        # Should print help text without raising

    def test_rule_list_empty(self) -> None:
        from core.cli.memory_handler import handle_memory_action

        with patch("core.memory.project.ProjectMemory") as mock_pm:
            mock_pm.return_value.list_rules.return_value = []
            handle_memory_action({"rule_action": "list"}, "", False)


class TestSchedulerDrain:
    """Test scheduler drain function."""

    def test_empty_queue(self) -> None:
        import queue

        from core.cli.scheduler_drain import drain_scheduler_queue

        q: queue.Queue = queue.Queue()
        result = drain_scheduler_queue(
            action_queue=q,
            services=MagicMock(),
            runner=MagicMock(),
            session_lane=MagicMock(),
            global_lane=MagicMock(),
        )
        assert result == 0
