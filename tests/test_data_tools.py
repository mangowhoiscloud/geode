"""Tests for Data Retrieval Tools (QueryMonoLake, CortexAnalyst, CortexSearch)."""

from __future__ import annotations

from core.tools.base import Tool
from core.tools.data_tools import CortexAnalystTool, CortexSearchTool, QueryMonoLakeTool
from core.tools.registry import ToolRegistry


class TestQueryMonoLakeTool:
    def test_satisfies_protocol(self):
        tool = QueryMonoLakeTool()
        assert isinstance(tool, Tool)

    def test_name(self):
        assert QueryMonoLakeTool().name == "query_monolake"

    def test_parameters_schema(self):
        params = QueryMonoLakeTool().parameters
        assert "ip_name" in params["properties"]
        assert params["required"] == ["ip_name"]

    def test_execute_berserk_returns_data(self):
        tool = QueryMonoLakeTool()
        result = tool.execute(ip_name="Berserk")
        assert "result" in result
        data = result["result"]
        assert "ip_info" in data
        assert "monolake" in data
        assert data["ip_info"]["ip_name"] == "Berserk"

    def test_execute_with_fields_filter(self):
        tool = QueryMonoLakeTool()
        result = tool.execute(ip_name="Cowboy Bebop", fields=["ip_name", "dau_peak"])
        assert "result" in result
        data = result["result"]
        assert "ip_name" in data
        assert "dau_peak" in data
        # Filtered result should not contain full nested structure
        assert "ip_info" not in data

    def test_execute_unknown_ip(self):
        tool = QueryMonoLakeTool()
        result = tool.execute(ip_name="Unknown IP XYZ")
        assert "error" in result
        assert "available_ips" in result


class TestCortexAnalystTool:
    def test_satisfies_protocol(self):
        assert isinstance(CortexAnalystTool(), Tool)

    def test_name(self):
        assert CortexAnalystTool().name == "cortex_analyst"

    def test_execute_returns_stub(self):
        tool = CortexAnalystTool()
        result = tool.execute(question="What is the top revenue IP?")
        assert "result" in result
        assert result["result"]["status"] == "stub"
        assert "rows" in result["result"]


class TestCortexSearchTool:
    def test_satisfies_protocol(self):
        assert isinstance(CortexSearchTool(), Tool)

    def test_name(self):
        assert CortexSearchTool().name == "cortex_search"

    def test_execute_returns_stub(self):
        tool = CortexSearchTool()
        result = tool.execute(query="dark fantasy anime IPs", top_k=3)
        assert "result" in result
        assert result["result"]["status"] == "stub"
        assert "documents" in result["result"]


class TestDataToolsRegistry:
    def test_register_all_data_tools(self):
        registry = ToolRegistry()
        registry.register(QueryMonoLakeTool())
        registry.register(CortexAnalystTool())
        registry.register(CortexSearchTool())

        assert len(registry) == 3
        assert "query_monolake" in registry
        assert "cortex_analyst" in registry
        assert "cortex_search" in registry

    def test_anthropic_format(self):
        registry = ToolRegistry()
        registry.register(QueryMonoLakeTool())
        tools = registry.to_anthropic_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "query_monolake"
        assert "input_schema" in tools[0]
