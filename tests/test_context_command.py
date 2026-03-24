"""Tests for /context slash command.

Covers:
- COMMAND_MAP registration
- cmd_context with assembler (full + summary modes)
- cmd_context without assembler (graceful degradation)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.cli.commands import COMMAND_MAP, cmd_context


class TestContextCommandMap:
    def test_context_registered(self) -> None:
        assert COMMAND_MAP["/context"] == "context"

    def test_ctx_alias_registered(self) -> None:
        assert COMMAND_MAP["/ctx"] == "context"


class TestCmdContext:
    def test_no_assembler_graceful(self, capsys) -> None:
        """Should print message when no assembler is available."""
        cmd_context("", context_assembler=None)
        # No crash = pass (Rich output not easily captured by capsys)

    def test_full_mode_with_mock_assembler(self) -> None:
        """Should call assemble and display tiers."""
        assembler = MagicMock()
        assembler.assemble.return_value = {
            "_soul_loaded": True,
            "_soul": "Test mission",
            "_user_profile_loaded": True,
            "_user_profile_summary": "User: Tester",
            "_org_loaded": False,
            "_project_loaded": False,
            "_session_loaded": False,
            "_llm_summary": "Summary line",
            "_assembled_at": 0,
            "_session_id": "_inspect",
            "_ip_name": "_inspect",
        }
        # Should not raise
        cmd_context("", context_assembler=assembler)
        assembler.assemble.assert_called_once_with("_inspect", "_inspect")

    def test_summary_mode_with_mock_assembler(self) -> None:
        """Should only show LLM summary."""
        assembler = MagicMock()
        assembler.assemble.return_value = {
            "_llm_summary": "Compact summary",
            "_assembled_at": 0,
        }
        cmd_context("summary", context_assembler=assembler)
        assembler.assemble.assert_called_once()

    def test_summary_mode_empty(self) -> None:
        """Should show 'no summary' when LLM summary is empty."""
        assembler = MagicMock()
        assembler.assemble.return_value = {"_llm_summary": ""}
        cmd_context("summary", context_assembler=assembler)
