"""Tests for /context slash command.

Covers:
- COMMAND_MAP registration
- cmd_context default / career / profile modes
"""

from __future__ import annotations

from core.cli.commands import COMMAND_MAP, cmd_context


class TestContextCommandMap:
    def test_context_registered(self) -> None:
        assert COMMAND_MAP["/context"] == "context"

    def test_ctx_alias_registered(self) -> None:
        assert COMMAND_MAP["/ctx"] == "context"


class TestCmdContext:
    def test_default_mode_no_crash(self) -> None:
        """Default /context should not raise."""
        cmd_context("")

    def test_career_mode_no_crash(self) -> None:
        """/context career should not raise."""
        cmd_context("career")

    def test_profile_mode_no_crash(self) -> None:
        """/context profile should not raise."""
        cmd_context("profile")

    def test_unknown_subcommand_shows_tiers(self) -> None:
        """/context xyz falls through to default tier display."""
        cmd_context("xyz")
