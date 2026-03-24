"""Tests for post-HITL-approval spinner in ToolExecutor.

Verifies that _tool_spinner is invoked after user approves at each
HITL gate (bash, MCP, write, expensive) and NOT invoked when approval
is denied or for safe/standard tools.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.cli.tool_executor import ToolExecutor, _tool_spinner

# ---------------------------------------------------------------------------
# _tool_spinner context manager unit tests
# ---------------------------------------------------------------------------


class TestToolSpinner:
    """Test the _tool_spinner context manager itself."""

    @patch("core.agent.tool_executor.console")
    def test_spinner_starts_and_stops(self, mock_console: MagicMock) -> None:
        """Spinner calls status.start() on enter and status.stop() on exit."""
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with _tool_spinner("Testing..."):
            mock_console.status.assert_called_once()
            mock_status.start.assert_called_once()
            mock_status.stop.assert_not_called()

        mock_status.stop.assert_called_once()

    @patch("core.agent.tool_executor.console")
    def test_spinner_stops_on_exception(self, mock_console: MagicMock) -> None:
        """Spinner stops even if the wrapped block raises."""
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with pytest.raises(RuntimeError), _tool_spinner("Will fail"):
            raise RuntimeError("boom")

        mock_status.stop.assert_called_once()

    @patch("core.agent.tool_executor.console")
    def test_spinner_label_in_status(self, mock_console: MagicMock) -> None:
        """Spinner label is passed to console.status()."""
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with _tool_spinner("Calling server/tool..."):
            pass

        call_args = mock_console.status.call_args
        assert "Calling server/tool..." in call_args[0][0]


# ---------------------------------------------------------------------------
# ToolExecutor integration: bash spinner
# ---------------------------------------------------------------------------


class TestBashSpinner:
    """Test spinner activation during bash command execution."""

    @patch("core.agent.tool_executor._tool_spinner")
    @patch("core.agent.tool_executor.console")
    def test_bash_spinner_after_approval(
        self, mock_console: MagicMock, mock_spinner: MagicMock
    ) -> None:
        """After bash approval, spinner wraps command execution."""
        mock_console.input.return_value = "y"
        mock_spinner.return_value.__enter__ = MagicMock(return_value=None)
        mock_spinner.return_value.__exit__ = MagicMock(return_value=False)

        executor = ToolExecutor()
        executor.execute("run_bash", {"command": "echo hello", "reason": "test"})

        mock_spinner.assert_called_once()
        label = mock_spinner.call_args[0][0]
        assert "echo hello" in label

    @patch("core.agent.tool_executor._tool_spinner")
    @patch("core.agent.tool_executor.console")
    def test_bash_no_spinner_when_denied(
        self, mock_console: MagicMock, mock_spinner: MagicMock
    ) -> None:
        """When user denies non-safe bash command, no spinner is shown."""
        mock_console.input.return_value = "n"

        result = ToolExecutor().execute(
            "run_bash", {"command": "npm install foo", "reason": "test"}
        )

        mock_spinner.assert_not_called()
        assert result.get("denied") is True


# ---------------------------------------------------------------------------
# ToolExecutor integration: MCP spinner
# ---------------------------------------------------------------------------


class TestMcpSpinner:
    """Test spinner activation during MCP tool execution."""

    @patch("core.agent.tool_executor._tool_spinner")
    @patch("core.agent.tool_executor.console")
    def test_mcp_spinner_after_approval(
        self, mock_console: MagicMock, mock_spinner: MagicMock
    ) -> None:
        """After MCP approval, spinner wraps call_tool execution."""
        mock_console.input.return_value = "y"
        mock_spinner.return_value.__enter__ = MagicMock(return_value=None)
        mock_spinner.return_value.__exit__ = MagicMock(return_value=False)

        mcp = MagicMock()
        mcp.find_server_for_tool.return_value = "my-server"
        mcp.call_tool.return_value = {"result": "ok"}

        executor = ToolExecutor(mcp_manager=mcp)
        executor.execute("mcp_tool_x", {"arg": "val"})

        mock_spinner.assert_called_once()
        label = mock_spinner.call_args[0][0]
        assert "my-server" in label
        assert "mcp_tool_x" in label

    @patch("core.agent.tool_executor._tool_spinner")
    @patch("core.agent.tool_executor.console")
    def test_mcp_no_spinner_when_denied(
        self, mock_console: MagicMock, mock_spinner: MagicMock
    ) -> None:
        """When user denies MCP tool, no spinner is shown."""
        mock_console.input.return_value = "n"

        mcp = MagicMock()
        mcp.find_server_for_tool.return_value = "my-server"

        result = ToolExecutor(mcp_manager=mcp).execute("mcp_tool_x", {"arg": "val"})

        mock_spinner.assert_not_called()
        assert result.get("denied") is True

    @patch("core.agent.tool_executor._tool_spinner")
    def test_mcp_no_spinner_when_auto_approved(self, mock_spinner: MagicMock) -> None:
        """When auto_approve is True, spinner wraps execution without HITL prompt."""
        mock_spinner.return_value.__enter__ = MagicMock(return_value=None)
        mock_spinner.return_value.__exit__ = MagicMock(return_value=False)

        mcp = MagicMock()
        mcp.find_server_for_tool.return_value = "srv"
        mcp.call_tool.return_value = {"ok": True}

        executor = ToolExecutor(auto_approve=True, mcp_manager=mcp)
        executor.execute("mcp_auto", {"x": 1})

        # auto_approve skips HITL but still uses spinner
        mock_spinner.assert_called_once()


# ---------------------------------------------------------------------------
# ToolExecutor integration: write tool spinner
# ---------------------------------------------------------------------------


class TestWriteToolSpinner:
    """Test spinner activation during write tool execution."""

    @patch("core.agent.tool_executor._tool_spinner")
    @patch("core.agent.tool_executor.console")
    def test_write_spinner_after_approval(
        self, mock_console: MagicMock, mock_spinner: MagicMock
    ) -> None:
        """After write approval, spinner wraps handler execution."""
        mock_console.input.return_value = "y"
        mock_spinner.return_value.__enter__ = MagicMock(return_value=None)
        mock_spinner.return_value.__exit__ = MagicMock(return_value=False)

        handler = MagicMock(return_value={"saved": True})
        executor = ToolExecutor(action_handlers={"memory_save": handler})
        executor.execute("memory_save", {"content": "test data"})

        mock_spinner.assert_called_once()
        label = mock_spinner.call_args[0][0]
        assert "memory_save" in label

    @patch("core.agent.tool_executor._tool_spinner")
    @patch("core.agent.tool_executor.console")
    def test_write_no_spinner_when_denied(
        self, mock_console: MagicMock, mock_spinner: MagicMock
    ) -> None:
        """When user denies write operation, no spinner is shown."""
        mock_console.input.return_value = "n"

        handler = MagicMock(return_value={"saved": True})
        executor = ToolExecutor(action_handlers={"memory_save": handler})
        result = executor.execute("memory_save", {"content": "test data"})

        mock_spinner.assert_not_called()
        assert result.get("denied") is True
        handler.assert_not_called()


# ---------------------------------------------------------------------------
# ToolExecutor integration: expensive tool spinner
# ---------------------------------------------------------------------------


class TestExpensiveToolSpinner:
    """Test spinner activation during expensive tool execution."""

    @patch("core.agent.tool_executor._tool_spinner")
    @patch("core.agent.tool_executor.console")
    def test_expensive_spinner_after_approval(
        self, mock_console: MagicMock, mock_spinner: MagicMock
    ) -> None:
        """After cost approval, spinner wraps handler execution."""
        mock_console.input.return_value = "y"
        mock_spinner.return_value.__enter__ = MagicMock(return_value=None)
        mock_spinner.return_value.__exit__ = MagicMock(return_value=False)

        handler = MagicMock(return_value={"tier": "S", "score": 85.0})
        executor = ToolExecutor(action_handlers={"analyze_ip": handler})
        executor.execute("analyze_ip", {"ip_name": "Berserk"})

        mock_spinner.assert_called_once()
        label = mock_spinner.call_args[0][0]
        assert "analyze_ip" in label

    @patch("core.agent.tool_executor._tool_spinner")
    @patch("core.agent.tool_executor.console")
    def test_expensive_no_spinner_when_denied(
        self, mock_console: MagicMock, mock_spinner: MagicMock
    ) -> None:
        """When user denies cost, no spinner is shown."""
        mock_console.input.return_value = "n"

        handler = MagicMock(return_value={"tier": "S"})
        executor = ToolExecutor(action_handlers={"analyze_ip": handler})
        result = executor.execute("analyze_ip", {"ip_name": "Berserk"})

        mock_spinner.assert_not_called()
        assert result.get("denied") is True
        handler.assert_not_called()

    @patch("core.agent.tool_executor._tool_spinner")
    def test_expensive_no_spinner_when_auto_approved(self, mock_spinner: MagicMock) -> None:
        """When auto_approve is True, expensive tools skip HITL and spinner."""
        handler = MagicMock(return_value={"tier": "A"})
        executor = ToolExecutor(auto_approve=True, action_handlers={"analyze_ip": handler})
        executor.execute("analyze_ip", {"ip_name": "Test"})

        # auto_approve skips the cost gate entirely, so approved_via_hitl stays False
        mock_spinner.assert_not_called()
        handler.assert_called_once()


# ---------------------------------------------------------------------------
# ToolExecutor: safe/standard tools should NOT show spinner
# ---------------------------------------------------------------------------


class TestNoSpinnerForSafeTools:
    """Safe and standard tools should not show a post-HITL spinner."""

    @patch("core.agent.tool_executor._tool_spinner")
    def test_safe_tool_no_spinner(self, mock_spinner: MagicMock) -> None:
        """Safe tools execute without any spinner."""
        handler = MagicMock(return_value={"ips": []})
        executor = ToolExecutor(action_handlers={"list_ips": handler})
        executor.execute("list_ips", {})

        mock_spinner.assert_not_called()
        handler.assert_called_once()

    @patch("core.agent.tool_executor._tool_spinner")
    def test_standard_tool_no_spinner(self, mock_spinner: MagicMock) -> None:
        """Standard (non-gated) tools execute without spinner."""
        handler = MagicMock(return_value={"report": "done"})
        executor = ToolExecutor(action_handlers={"generate_report": handler})
        executor.execute("generate_report", {"topic": "test"})

        mock_spinner.assert_not_called()
        handler.assert_called_once()
