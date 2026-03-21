"""Tests for HITL level (Feature 2) and session-level tool approval (Feature 1).

Feature 1: Session-level tool approval (A=Always)
  - _prompt_with_always returns 'y', 'n', or 'a'
  - "A" response adds category to _always_approved_categories
  - Subsequent calls auto-approve when category is in set

Feature 2: HITL level (0/1/2)
  - hitl_level=0: skip all prompts (autonomous)
  - hitl_level=1: skip bash/MCP, prompt only for writes
  - hitl_level=2: prompt for everything (default)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.cli.tool_executor import ToolExecutor

# ---------------------------------------------------------------------------
# Feature 1: Session-level tool approval (A=Always)
# ---------------------------------------------------------------------------


class TestAlwaysApproval:
    """Test the A=Always session-level approval feature."""

    def test_always_approved_categories_initialized_empty(self) -> None:
        executor = ToolExecutor()
        assert executor._always_approved_categories == set()
        assert executor._always_approved_tools == set()

    def test_prompt_with_always_returns_y(self) -> None:
        executor = ToolExecutor()
        with patch("core.cli.tool_executor.console") as mock_console:
            mock_console.input.return_value = "y"
            with patch("core.cli.tool_executor._restore_terminal", create=True):
                result = executor._prompt_with_always("Allow?", "test detail")
        assert result == "y"

    def test_prompt_with_always_returns_n(self) -> None:
        executor = ToolExecutor()
        with patch("core.cli.tool_executor.console") as mock_console:
            mock_console.input.return_value = "n"
            with patch("core.cli.tool_executor._restore_terminal", create=True):
                result = executor._prompt_with_always("Allow?", "test detail")
        assert result == "n"

    def test_prompt_with_always_returns_a(self) -> None:
        executor = ToolExecutor()
        with patch("core.cli.tool_executor.console") as mock_console:
            mock_console.input.return_value = "a"
            with patch("core.cli.tool_executor._restore_terminal", create=True):
                result = executor._prompt_with_always("Allow?", "test detail")
        assert result == "a"

    def test_prompt_with_always_accepts_always_word(self) -> None:
        executor = ToolExecutor()
        with patch("core.cli.tool_executor.console") as mock_console:
            mock_console.input.return_value = "always"
            with patch("core.cli.tool_executor._restore_terminal", create=True):
                result = executor._prompt_with_always("Allow?", "test detail")
        assert result == "a"

    def test_prompt_with_always_empty_is_yes(self) -> None:
        executor = ToolExecutor()
        with patch("core.cli.tool_executor.console") as mock_console:
            mock_console.input.return_value = ""
            with patch("core.cli.tool_executor._restore_terminal", create=True):
                result = executor._prompt_with_always("Allow?", "test detail")
        assert result == "y"

    def test_prompt_with_always_keyboard_interrupt_is_no(self) -> None:
        executor = ToolExecutor()
        with patch("core.cli.tool_executor.console") as mock_console:
            mock_console.input.side_effect = KeyboardInterrupt
            with patch("core.cli.tool_executor._restore_terminal", create=True):
                result = executor._prompt_with_always("Allow?", "test detail")
        assert result == "n"

    def test_bash_always_adds_category(self) -> None:
        """When user responds 'a' to bash approval, 'bash' category is added."""
        executor = ToolExecutor()
        with patch.object(executor, "_prompt_with_always", return_value="a"):
            approved = executor._request_approval("npm install foo", "test")
        assert approved is True
        assert "bash" in executor._always_approved_categories

    def test_bash_always_skips_subsequent_approval(self) -> None:
        """After 'A' for bash, subsequent bash commands skip approval."""
        executor = ToolExecutor()
        executor._always_approved_categories.add("bash")
        # Non-safe bash command should be auto-approved
        with patch.object(executor, "_prompt_with_always") as mock_prompt:
            executor.execute("run_bash", {"command": "npm install foo", "reason": "test"})
            mock_prompt.assert_not_called()

    def test_write_always_adds_category(self) -> None:
        """When user responds 'a' to write approval, 'write' category is added."""
        executor = ToolExecutor()
        with (
            patch.object(executor, "_prompt_with_always", return_value="a"),
            patch("core.cli.tool_executor.console"),
        ):
            approved = executor._confirm_write("memory_save", {"content": "test"})
        assert approved is True
        assert "write" in executor._always_approved_categories

    def test_write_always_skips_subsequent_approval(self) -> None:
        """After 'A' for write, subsequent writes auto-approve."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"memory_save": handler})
        executor._always_approved_categories.add("write")
        with patch.object(executor, "_prompt_with_always") as mock_prompt:
            result = executor.execute("memory_save", {"content": "data"})
            mock_prompt.assert_not_called()
        assert result["status"] == "ok"

    def test_cost_always_adds_category(self) -> None:
        """When user responds 'a' to cost approval, 'cost' category is added."""
        executor = ToolExecutor()
        with (
            patch.object(executor, "_prompt_with_always", return_value="a"),
            patch("core.cli.tool_executor.console"),
        ):
            approved = executor._confirm_cost("analyze_ip", 1.50)
        assert approved is True
        assert "cost" in executor._always_approved_categories

    def test_cost_always_skips_subsequent_approval(self) -> None:
        """After 'A' for cost, subsequent expensive tools auto-approve."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"analyze_ip": handler})
        executor._always_approved_categories.add("cost")
        with patch.object(executor, "_prompt_with_always") as mock_prompt:
            result = executor.execute("analyze_ip", {"ip_name": "test"})
            mock_prompt.assert_not_called()
        assert result["status"] == "ok"

    def test_mcp_always_adds_server_category(self) -> None:
        """When user responds 'a' to MCP approval, 'mcp:<server>' is added."""
        executor = ToolExecutor()
        with (
            patch.object(executor, "_prompt_with_always", return_value="a"),
            patch("core.cli.tool_executor.console"),
        ):
            approved = executor._confirm_mcp("custom-server", "some_tool")
        assert approved is True
        assert "mcp:custom-server" in executor._always_approved_categories


# ---------------------------------------------------------------------------
# Feature 2: HITL level (0/1/2)
# ---------------------------------------------------------------------------


class TestHITLLevel:
    """Test HITL level gating (0=autonomous, 1=write-only, 2=all)."""

    def test_default_hitl_level_is_2(self) -> None:
        executor = ToolExecutor()
        assert executor._hitl_level == 2

    def test_hitl_level_0_skips_bash_approval(self) -> None:
        """hitl_level=0 auto-approves all bash commands."""
        executor = ToolExecutor(hitl_level=0)
        with patch.object(executor, "_prompt_with_always") as mock_prompt:
            executor.execute("run_bash", {"command": "npm install foo", "reason": "test"})
            mock_prompt.assert_not_called()

    def test_hitl_level_1_skips_bash_approval(self) -> None:
        """hitl_level=1 auto-approves bash commands."""
        executor = ToolExecutor(hitl_level=1)
        with patch.object(executor, "_prompt_with_always") as mock_prompt:
            executor.execute("run_bash", {"command": "npm install foo", "reason": "test"})
            mock_prompt.assert_not_called()

    def test_hitl_level_2_requires_bash_approval(self) -> None:
        """hitl_level=2 requires approval for non-safe bash commands."""
        executor = ToolExecutor(hitl_level=2)
        with (
            patch.object(executor, "_prompt_with_always", return_value="y") as mock_prompt,
            patch("core.cli.tool_executor.console"),
        ):
            executor.execute("run_bash", {"command": "npm install foo", "reason": "test"})
            mock_prompt.assert_called_once()

    def test_hitl_level_0_skips_write_approval(self) -> None:
        """hitl_level=0 auto-approves write operations."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"memory_save": handler}, hitl_level=0)
        with patch.object(executor, "_prompt_with_always") as mock_prompt:
            result = executor.execute("memory_save", {"content": "data"})
            mock_prompt.assert_not_called()
        assert result["status"] == "ok"

    def test_hitl_level_1_requires_write_approval(self) -> None:
        """hitl_level=1 still requires approval for write operations."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"memory_save": handler}, hitl_level=1)
        with (
            patch.object(executor, "_prompt_with_always", return_value="y"),
            patch("core.cli.tool_executor.console"),
        ):
            executor.execute("memory_save", {"content": "data"})
            # Write tools at hitl_level=1 should still prompt (write-only)

    def test_hitl_level_0_skips_cost_approval(self) -> None:
        """hitl_level=0 auto-approves expensive operations."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"analyze_ip": handler}, hitl_level=0)
        with patch.object(executor, "_prompt_with_always") as mock_prompt:
            result = executor.execute("analyze_ip", {"ip_name": "test"})
            mock_prompt.assert_not_called()
        assert result["status"] == "ok"

    def test_hitl_level_0_skips_mcp_approval(self) -> None:
        """hitl_level=0 auto-approves MCP tools."""
        mock_mcp = MagicMock()
        mock_mcp.find_server_for_tool.return_value = "custom-server"
        mock_mcp.call_tool.return_value = {"result": "ok"}
        executor = ToolExecutor(mcp_manager=mock_mcp, hitl_level=0)
        with patch.object(executor, "_confirm_mcp") as mock_confirm:
            result = executor.execute("unknown_mcp_tool", {"arg": "value"})
            mock_confirm.assert_not_called()
        assert result["result"] == "ok"

    def test_hitl_level_1_skips_mcp_approval(self) -> None:
        """hitl_level=1 auto-approves MCP tools."""
        mock_mcp = MagicMock()
        mock_mcp.find_server_for_tool.return_value = "custom-server"
        mock_mcp.call_tool.return_value = {"result": "ok"}
        executor = ToolExecutor(mcp_manager=mock_mcp, hitl_level=1)
        with patch.object(executor, "_confirm_mcp") as mock_confirm:
            result = executor.execute("unknown_mcp_tool", {"arg": "value"})
            mock_confirm.assert_not_called()
        assert result["result"] == "ok"

    def test_hitl_level_from_config(self) -> None:
        """hitl_level field exists in Settings with default 2."""
        from core.config import Settings

        s = Settings()
        assert s.hitl_level == 2
