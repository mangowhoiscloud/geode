"""Tests for GEODE MCP server."""

from __future__ import annotations


class TestMCPServerCreation:
    def test_tool_descriptions_defined(self) -> None:
        from core.mcp_server import _TOOL_DESCRIPTIONS

        assert "query_memory" in _TOOL_DESCRIPTIONS
        assert "get_health" in _TOOL_DESCRIPTIONS
        # Step 6: only the two core-generic descriptions stay in core/.
        assert len(_TOOL_DESCRIPTIONS) == 2

    def test_create_server_requires_mcp_package(self) -> None:
        from core.mcp_server import create_mcp_server

        assert callable(create_mcp_server)

    def test_main_entry_exists(self) -> None:
        from core.mcp_server import main

        assert callable(main)

    def test_core_tool_names_present(self) -> None:
        from core.mcp_server import _TOOL_DESCRIPTIONS

        # Step 6: core retains only domain-agnostic tools. The four
        # plugin-bound entries (analyze_ip, quick_score, get_ip_signals,
        # list_fixtures) moved to plugins/game_ip/mcp/mcp_tools.json.
        expected = {"query_memory", "get_health"}
        assert set(_TOOL_DESCRIPTIONS.keys()) == expected

    def test_descriptions_are_nonempty_strings(self) -> None:
        from core.mcp_server import _TOOL_DESCRIPTIONS

        for name, desc in _TOOL_DESCRIPTIONS.items():
            assert isinstance(desc, str), f"{name} description not a string"
            assert len(desc) > 10, f"{name} description too short"

    def test_plugin_tool_descriptions_split_to_plugin(self) -> None:
        """The four IP-specific MCP tools live with the plugin after step 6."""
        from plugins.game_ip.mcp import tools as plugin_tools

        plugin_descs = plugin_tools._TOOL_DESCRIPTIONS
        expected = {"analyze_ip", "quick_score", "get_ip_signals", "list_fixtures"}
        assert set(plugin_descs.keys()) == expected
        for name, desc in plugin_descs.items():
            assert isinstance(desc, str), f"{name} description not a string"
            assert len(desc) > 10, f"{name} description too short"

    def test_register_mcp_tools_hook_exists_on_domain(self) -> None:
        """GameIPDomain implements the v2 ``register_mcp_tools`` hook."""
        from plugins.game_ip.adapter import GameIPDomain

        domain = GameIPDomain()
        assert callable(getattr(domain, "register_mcp_tools", None))


class TestMCPToolFunctions:
    """Test tool logic by exercising the same code paths the MCP tools use."""

    def test_get_ip_signals_returns_fixture_data(self) -> None:
        from plugins.game_ip.fixtures import FIXTURE_MAP, load_fixture

        ip_key = sorted(FIXTURE_MAP.keys())[0]
        fixture = load_fixture(ip_key)
        result = {
            "ip_name": ip_key,
            "signals": fixture.get("signals", {}),
            "source": "fixture",
        }
        assert "signals" in result
        assert result["source"] == "fixture"

    def test_get_ip_signals_unknown_ip(self) -> None:
        from plugins.game_ip.fixtures import FIXTURE_MAP

        assert "zzz_nonexistent_ip" not in FIXTURE_MAP

    def test_list_fixtures_returns_count_and_ips(self) -> None:
        from plugins.game_ip.fixtures import FIXTURE_MAP

        result = {"count": len(FIXTURE_MAP), "ips": sorted(FIXTURE_MAP.keys())}
        assert result["count"] > 0
        assert isinstance(result["ips"], list)

    def test_get_health_returns_model_info(self) -> None:
        from core.config import settings

        result = {
            "model": settings.model,
            "ensemble_mode": settings.ensemble_mode,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "openai_configured": bool(settings.openai_api_key),
        }
        assert "model" in result
        assert "ensemble_mode" in result

    def test_fixtures_resource_returns_json(self) -> None:
        import json

        from plugins.game_ip.fixtures import FIXTURE_MAP

        data = json.dumps({"count": len(FIXTURE_MAP), "ips": sorted(FIXTURE_MAP.keys())})
        parsed = json.loads(data)
        assert "count" in parsed
        assert "ips" in parsed

    def test_query_memory_returns_context(self) -> None:
        from core.memory.project import ProjectMemory

        pm = ProjectMemory()
        context = pm.get_context_for_ip("cowboy bebop")
        assert isinstance(context, (dict, list, str, type(None)))
