from plugins.benchmark_harness.mcpmark_geode_agent import _route_from_model, register_mcpmark_agent


def test_route_from_geode_model_label() -> None:
    assert _route_from_model("geode-gpt-5.5") == ("gpt-5.5", "openai", "subscription")
    assert _route_from_model("geode-claude-sonnet-4-6") == (
        "claude-sonnet-4-6",
        "anthropic",
        "subscription",
    )
    assert _route_from_model("geode-glm-4-6") == ("glm-4-6", "zhipuai", "api_key")


def test_register_mcpmark_agent() -> None:
    registry: dict[str, object] = {}
    register_mcpmark_agent(registry)
    assert "geode" in registry
