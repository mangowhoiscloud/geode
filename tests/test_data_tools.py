"""Tests for generic data tools."""

from __future__ import annotations

import asyncio

from core.tools.base import Tool
from core.tools.data_tools import GenerateDataTool


class TestGenerateDataTool:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(GenerateDataTool(), Tool)

    def test_aexecute_generates_deterministic_records(self) -> None:
        result = asyncio.run(GenerateDataTool().aexecute(count=2, genre="demo"))

        payload = result["result"]
        assert payload["status"] == "ok"
        assert payload["count"] == 2
        assert payload["records"] == [
            {"id": "sample-001", "label": "demo-1", "genre": "demo", "score": 100.0},
            {"id": "sample-002", "label": "demo-2", "genre": "demo", "score": 96.3},
        ]

    def test_aexecute_clamps_count(self) -> None:
        result = asyncio.run(GenerateDataTool().aexecute(count=50))

        assert result["result"]["count"] == 20
        assert len(result["result"]["records"]) == 20

    def test_aexecute_rejects_invalid_count(self) -> None:
        result = asyncio.run(GenerateDataTool().aexecute(count="many"))

        assert result["status"] == "failure"
        assert "count" in result["error"]
