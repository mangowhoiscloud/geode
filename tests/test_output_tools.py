"""Tests for Output/Export Tools."""

from __future__ import annotations

import json
from pathlib import Path

from core.tools.base import Tool
from core.tools.output_tools import ExportJsonTool, GenerateReportTool, SendNotificationTool


class TestGenerateReportTool:
    def test_satisfies_protocol(self):
        assert isinstance(GenerateReportTool(), Tool)

    def test_name(self):
        assert GenerateReportTool().name == "generate_report"

    def test_execute_basic(self):
        tool = GenerateReportTool()
        result = tool.execute(ip_name="Berserk")
        report = result["result"]
        assert report["title"] == "GEODE Analysis Report: Berserk"
        assert "generated_at" in report
        assert "sections" in report

    def test_execute_with_analysis_data(self):
        tool = GenerateReportTool()
        result = tool.execute(
            ip_name="Cowboy Bebop",
            analysis_data={"tier": "A", "final_score": 76.2, "subscores": {"quality": 82}},
            format="json",
        )
        report = result["result"]
        assert report["format"] == "json"
        assert "76.2" in report["sections"]["executive_summary"]
        assert report["sections"]["tier"] == "A"

    def test_execute_default_format_markdown(self):
        tool = GenerateReportTool()
        result = tool.execute(ip_name="Test")
        assert result["result"]["format"] == "markdown"


class TestExportJsonTool:
    def test_satisfies_protocol(self):
        assert isinstance(ExportJsonTool(), Tool)

    def test_name(self):
        assert ExportJsonTool().name == "export_json"

    def test_execute_writes_file(self, tmp_path: Path):
        tool = ExportJsonTool()
        data = {"ip_name": "Berserk", "score": 82.2}
        result = tool.execute(
            data=data,
            filename="test_export.json",
            output_dir=str(tmp_path),
        )
        assert result["result"]["exported"] is True
        path = Path(result["result"]["path"])
        assert path.exists()
        content = json.loads(path.read_text())
        assert content["ip_name"] == "Berserk"
        assert content["score"] == 82.2

    def test_execute_creates_parent_dirs(self, tmp_path: Path):
        tool = ExportJsonTool()
        nested = tmp_path / "deep" / "nested"
        result = tool.execute(
            data={"test": True},
            filename="deep_export.json",
            output_dir=str(nested),
        )
        assert result["result"]["exported"] is True
        assert Path(result["result"]["path"]).exists()

    def test_execute_default_filename(self, tmp_path: Path):
        tool = ExportJsonTool()
        result = tool.execute(data={"x": 1}, output_dir=str(tmp_path))
        assert result["result"]["exported"] is True
        assert "geode_export_" in result["result"]["path"]


class TestSendNotificationTool:
    def test_satisfies_protocol(self):
        assert isinstance(SendNotificationTool(), Tool)

    def test_name(self):
        assert SendNotificationTool().name == "send_notification"

    def test_execute_slack_no_adapter(self):
        """Without adapter, falls back to stub response."""
        from core.mcp.notification_port import set_notification

        set_notification(None)
        tool = SendNotificationTool()
        result = tool.execute(
            channel="slack",
            message="Pipeline completed for Berserk",
            severity="info",
            recipient="#geode-alerts",
        )
        data = result["result"]
        assert data["sent"] is False
        assert data["channel"] == "slack"
        assert data["severity"] == "info"
        assert data["recipient"] == "#geode-alerts"
        assert "not delivered" in data["note"].lower()

    def test_execute_with_adapter(self):
        """With adapter available, sends via NotificationPort."""
        from unittest.mock import MagicMock

        from core.mcp.notification_port import (
            NotificationResult,
            set_notification,
        )

        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = True
        mock_adapter.send_message.return_value = NotificationResult(
            success=True, channel="slack", message_id="ts_123"
        )
        set_notification(mock_adapter)

        tool = SendNotificationTool()
        result = tool.execute(
            channel="slack",
            message="Test message",
            recipient="#general",
        )
        assert result["result"]["sent"] is True
        assert result["result"]["message_id"] == "ts_123"

        set_notification(None)

    def test_execute_default_severity(self):
        from core.mcp.notification_port import set_notification

        set_notification(None)
        tool = SendNotificationTool()
        result = tool.execute(channel="email", message="Test")
        assert result["result"]["severity"] == "info"

    def test_execute_message_preview_truncated(self):
        from core.mcp.notification_port import set_notification

        set_notification(None)
        tool = SendNotificationTool()
        long_msg = "A" * 200
        result = tool.execute(channel="webhook", message=long_msg)
        assert len(result["result"]["message_preview"]) == 100
