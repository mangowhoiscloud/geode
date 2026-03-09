"""Tests for full 21-tool registration and PolicyChain mode filtering."""

from __future__ import annotations

from pathlib import Path

from geode.runtime import GeodeRuntime, _build_default_policies, _build_default_registry

ALL_TOOL_NAMES = {
    # Analysis (3)
    "run_analyst",
    "run_evaluator",
    "psm_calculate",
    # Data (3)
    "query_monolake",
    "cortex_analyst",
    "cortex_search",
    # Signals (5)
    "youtube_search",
    "reddit_sentiment",
    "twitch_stats",
    "steam_info",
    "google_trends",
    # Memory (7)
    "memory_search",
    "memory_get",
    "memory_save",
    "rule_create",
    "rule_update",
    "rule_delete",
    "rule_list",
    # Output (3)
    "generate_report",
    "export_json",
    "send_notification",
}


class TestFullToolRegistration:
    """Verify all 21 tools are registered in the default registry."""

    def test_registry_contains_21_tools(self) -> None:
        registry = _build_default_registry()
        assert len(registry) == 21

    def test_all_tool_names_present(self) -> None:
        registry = _build_default_registry()
        for name in ALL_TOOL_NAMES:
            assert name in registry, f"Tool '{name}' missing from registry"

    def test_no_extra_tools(self) -> None:
        registry = _build_default_registry()
        registered = set(registry.list_tools())
        assert registered == ALL_TOOL_NAMES

    def test_runtime_registry_count(self, tmp_path: Path) -> None:
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        assert len(runtime.tool_registry) == 21


class TestPolicyChainDryRun:
    """dry_run mode blocks run_analyst, run_evaluator, send_notification."""

    def test_dry_run_blocks_llm_tools(self) -> None:
        chain = _build_default_policies()
        assert chain.is_allowed("run_analyst", mode="dry_run") is False
        assert chain.is_allowed("run_evaluator", mode="dry_run") is False

    def test_dry_run_blocks_notification(self) -> None:
        chain = _build_default_policies()
        assert chain.is_allowed("send_notification", mode="dry_run") is False

    def test_dry_run_allows_data_tools(self) -> None:
        chain = _build_default_policies()
        for tool in ("query_monolake", "cortex_analyst", "cortex_search"):
            assert chain.is_allowed(tool, mode="dry_run") is True

    def test_dry_run_allows_signal_tools(self) -> None:
        chain = _build_default_policies()
        for tool in (
            "youtube_search",
            "reddit_sentiment",
            "twitch_stats",
            "steam_info",
            "google_trends",
        ):
            assert chain.is_allowed(tool, mode="dry_run") is True

    def test_dry_run_allows_memory_tools(self) -> None:
        chain = _build_default_policies()
        for tool in ("memory_search", "memory_get", "memory_save"):
            assert chain.is_allowed(tool, mode="dry_run") is True

    def test_dry_run_filter_count(self) -> None:
        registry = _build_default_registry()
        chain = _build_default_policies()
        available = registry.list_tools(policy=chain, mode="dry_run")
        # 21 total minus 3 blocked (run_analyst, run_evaluator, send_notification)
        assert len(available) == 18


class TestPolicyChainFullPipeline:
    """full_pipeline mode blocks send_notification only."""

    def test_full_pipeline_blocks_notification(self) -> None:
        chain = _build_default_policies()
        assert chain.is_allowed("send_notification", mode="full_pipeline") is False

    def test_full_pipeline_allows_analysis_tools(self) -> None:
        chain = _build_default_policies()
        for tool in ("run_analyst", "run_evaluator", "psm_calculate"):
            assert chain.is_allowed(tool, mode="full_pipeline") is True

    def test_full_pipeline_filter_count(self) -> None:
        registry = _build_default_registry()
        chain = _build_default_policies()
        available = registry.list_tools(policy=chain, mode="full_pipeline")
        # 21 total minus 1 blocked (send_notification)
        assert len(available) == 20

    def test_full_pipeline_allows_memory_tools(self) -> None:
        chain = _build_default_policies()
        for tool in ("memory_search", "memory_get", "memory_save"):
            assert chain.is_allowed(tool, mode="full_pipeline") is True


class TestPolicyFilterIntegration:
    """Integration: registry + policy chain filtering via runtime."""

    def test_runtime_dry_run_filtering(self, tmp_path: Path) -> None:
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        dry_tools = runtime.get_available_tools(mode="dry_run")
        assert "run_analyst" not in dry_tools
        assert "run_evaluator" not in dry_tools
        assert "send_notification" not in dry_tools
        assert "psm_calculate" in dry_tools
        assert "memory_search" in dry_tools
        assert "query_monolake" in dry_tools

    def test_runtime_full_pipeline_filtering(self, tmp_path: Path) -> None:
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        full_tools = runtime.get_available_tools(mode="full_pipeline")
        assert "run_analyst" in full_tools
        assert "send_notification" not in full_tools
        assert len(full_tools) == 20

    def test_unknown_mode_allows_all(self, tmp_path: Path) -> None:
        """Modes with no matching policies allow all tools."""
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        tools = runtime.get_available_tools(mode="custom_mode")
        assert len(tools) == 21

    def test_anthropic_tool_defs_respect_policy(self, tmp_path: Path) -> None:
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        defs = runtime.tool_registry.to_anthropic_tools(
            policy=runtime.policy_chain,
            mode="dry_run",
        )
        names = {d["name"] for d in defs}
        assert "run_analyst" not in names
        assert "send_notification" not in names
        assert "memory_search" in names
