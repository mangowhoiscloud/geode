"""Tests for L5 Analysis Tools (RunAnalystTool, RunEvaluatorTool, PSMCalculateTool)."""

from __future__ import annotations

from core.tools.analysis import PSMCalculateTool, RunAnalystTool, RunEvaluatorTool
from core.tools.base import Tool
from core.tools.registry import ToolRegistry


class TestRunAnalystTool:
    def test_satisfies_protocol(self):
        tool = RunAnalystTool()
        assert isinstance(tool, Tool)

    def test_name(self):
        assert RunAnalystTool().name == "run_analyst"

    def test_parameters_schema(self):
        params = RunAnalystTool().parameters
        assert "analyst_type" in params["properties"]
        assert "ip_name" in params["properties"]
        assert params["properties"]["analyst_type"]["enum"] == [
            "game_mechanics",
            "player_experience",
            "growth_potential",
            "discovery",
        ]

    def test_execute_berserk(self):
        tool = RunAnalystTool()
        result = tool.execute(analyst_type="game_mechanics", ip_name="Berserk")
        assert "result" in result
        assert result["result"]["analyst_type"] == "game_mechanics"
        assert result["result"]["score"] == 4.8

    def test_execute_cowboy_bebop(self):
        tool = RunAnalystTool()
        result = tool.execute(analyst_type="growth_potential", ip_name="Cowboy Bebop")
        assert result["result"]["score"] == 4.5

    def test_execute_unknown_analyst_type(self):
        tool = RunAnalystTool()
        result = tool.execute(analyst_type="invalid", ip_name="Berserk")
        assert "error" in result


class TestRunEvaluatorTool:
    def test_satisfies_protocol(self):
        tool = RunEvaluatorTool()
        assert isinstance(tool, Tool)

    def test_name(self):
        assert RunEvaluatorTool().name == "run_evaluator"

    def test_execute_quality_judge(self):
        tool = RunEvaluatorTool()
        result = tool.execute(evaluator_type="quality_judge", ip_name="Berserk")
        assert "result" in result
        assert result["result"]["evaluator_type"] == "quality_judge"

    def test_execute_hidden_value(self):
        tool = RunEvaluatorTool()
        result = tool.execute(evaluator_type="hidden_value", ip_name="Cowboy Bebop")
        assert "result" in result

    def test_execute_community_momentum(self):
        tool = RunEvaluatorTool()
        result = tool.execute(evaluator_type="community_momentum", ip_name="Berserk")
        assert "result" in result

    def test_execute_unknown_ip(self):
        tool = RunEvaluatorTool()
        result = tool.execute(evaluator_type="quality_judge", ip_name="Unknown IP")
        assert "error" in result

    def test_execute_unknown_evaluator(self):
        tool = RunEvaluatorTool()
        result = tool.execute(evaluator_type="invalid", ip_name="Berserk")
        assert "error" in result


class TestPSMCalculateTool:
    def test_satisfies_protocol(self):
        tool = PSMCalculateTool()
        assert isinstance(tool, Tool)

    def test_name(self):
        assert PSMCalculateTool().name == "psm_calculate"

    def test_execute_berserk(self):
        tool = PSMCalculateTool()
        result = tool.execute(ip_name="Berserk")
        assert "result" in result
        psm = result["result"]
        assert "att_pct" in psm
        assert "z_value" in psm
        assert "psm_valid" in psm
        assert psm["psm_valid"] is True

    def test_execute_cowboy_bebop(self):
        tool = PSMCalculateTool()
        result = tool.execute(ip_name="Cowboy Bebop")
        assert result["result"]["psm_valid"] is True

    def test_execute_unknown_ip(self):
        tool = PSMCalculateTool()
        result = tool.execute(ip_name="Unknown IP XYZ")
        # Falls back to default values, not an error
        assert "result" in result


class TestAnalysisToolsRegistry:
    def test_register_all_three(self):
        registry = ToolRegistry()
        registry.register(RunAnalystTool())
        registry.register(RunEvaluatorTool())
        registry.register(PSMCalculateTool())

        assert len(registry) == 3
        assert "run_analyst" in registry
        assert "run_evaluator" in registry
        assert "psm_calculate" in registry

    def test_anthropic_format(self):
        registry = ToolRegistry()
        registry.register(RunAnalystTool())
        registry.register(RunEvaluatorTool())
        registry.register(PSMCalculateTool())

        tools = registry.to_anthropic_tools()
        assert len(tools) == 3
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "input_schema" in t
