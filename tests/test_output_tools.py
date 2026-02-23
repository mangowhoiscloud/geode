"""Tests for Output/Export Tools."""

from __future__ import annotations

import json
from pathlib import Path

from geode.tools.base import Tool
from geode.tools.output_tools import ExportJsonTool, GenerateReportTool, SendNotificationTool


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

    def test_execute_slack(self):
        tool = SendNotificationTool()
        result = tool.execute(
            channel="slack",
            message="Pipeline completed for Berserk",
            severity="info",
            recipient="#geode-alerts",
        )
        data = result["result"]
        assert data["sent"] is True
        assert data["channel"] == "slack"
        assert data["severity"] == "info"
        assert data["recipient"] == "#geode-alerts"
        assert "stub" in data["note"].lower()

    def test_execute_default_severity(self):
        tool = SendNotificationTool()
        result = tool.execute(channel="email", message="Test")
        assert result["result"]["severity"] == "info"

    def test_execute_message_preview_truncated(self):
        tool = SendNotificationTool()
        long_msg = "A" * 200
        result = tool.execute(channel="webhook", message=long_msg)
        assert len(result["result"]["message_preview"]) == 100
