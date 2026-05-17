"""Tests for core tool registration and PolicyChain mode filtering."""

from __future__ import annotations

from pathlib import Path

from core.runtime import GeodeRuntime, _build_default_policies, _build_default_registry

ALL_TOOL_NAMES = {
    # Data (3)
    "cortex_analyst",
    "cortex_search",
    "generate_data",
    # Search (2)
    "web_search",
    "wanted_jobs_search",
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
    # Meta (1)
    "tool_search",
}


class TestFullToolRegistration:
    """Verify core tools are registered in the default registry."""

    def test_registry_contains_core_tools(self) -> None:
        registry = _build_default_registry()
        assert len(registry) == len(ALL_TOOL_NAMES)

    def test_all_tool_names_present(self) -> None:
        registry = _build_default_registry()
        for name in ALL_TOOL_NAMES:
            assert name in registry, f"Tool '{name}' missing from registry"

    def test_no_extra_tools(self) -> None:
        registry = _build_default_registry()
        registered = set(registry.list_tools())
        assert registered == ALL_TOOL_NAMES

    def test_runtime_registry_count(self, tmp_path: Path) -> None:
        runtime = GeodeRuntime.create("Project Atlas", log_dir=tmp_path)
        assert len(runtime.tool_registry) == len(ALL_TOOL_NAMES)


class TestPolicyChainDryRun:
    """dry_run mode blocks notifications."""

    def test_dry_run_blocks_notification(self) -> None:
        chain = _build_default_policies()
        assert chain.is_allowed("send_notification", mode="dry_run") is False

    def test_dry_run_allows_data_tools(self) -> None:
        chain = _build_default_policies()
        for tool in ("cortex_analyst", "cortex_search", "generate_data"):
            assert chain.is_allowed(tool, mode="dry_run") is True

    def test_dry_run_allows_memory_tools(self) -> None:
        chain = _build_default_policies()
        for tool in ("memory_search", "memory_get", "memory_save"):
            assert chain.is_allowed(tool, mode="dry_run") is True

    def test_dry_run_filter_count(self) -> None:
        registry = _build_default_registry()
        chain = _build_default_policies()
        available = registry.list_tools(policy=chain, mode="dry_run")
        assert len(available) == len(ALL_TOOL_NAMES) - 1


class TestPolicyChainFullPipeline:
    """full_pipeline mode blocks send_notification only."""

    def test_full_pipeline_blocks_notification(self) -> None:
        chain = _build_default_policies()
        assert chain.is_allowed("send_notification", mode="full_pipeline") is False

    def test_full_pipeline_filter_count(self) -> None:
        registry = _build_default_registry()
        chain = _build_default_policies()
        available = registry.list_tools(policy=chain, mode="full_pipeline")
        assert len(available) == len(ALL_TOOL_NAMES) - 1

    def test_full_pipeline_allows_memory_tools(self) -> None:
        chain = _build_default_policies()
        for tool in ("memory_search", "memory_get", "memory_save"):
            assert chain.is_allowed(tool, mode="full_pipeline") is True


class TestPolicyFilterIntegration:
    """Integration: registry + policy chain filtering via runtime."""

    def test_runtime_dry_run_filtering(self, tmp_path: Path) -> None:
        runtime = GeodeRuntime.create("Project Atlas", log_dir=tmp_path)
        dry_tools = runtime.get_available_tools(mode="dry_run")
        assert "send_notification" not in dry_tools
        assert "memory_search" in dry_tools
        assert "cortex_search" in dry_tools

    def test_runtime_full_pipeline_filtering(self, tmp_path: Path) -> None:
        runtime = GeodeRuntime.create("Project Atlas", log_dir=tmp_path)
        full_tools = runtime.get_available_tools(mode="full_pipeline")
        assert "send_notification" not in full_tools
        assert len(full_tools) == len(ALL_TOOL_NAMES) - 1

    def test_unknown_mode_allows_all(self, tmp_path: Path) -> None:
        """Modes with no matching policies allow all tools."""
        runtime = GeodeRuntime.create("Project Atlas", log_dir=tmp_path)
        tools = runtime.get_available_tools(mode="custom_mode")
        assert len(tools) == len(ALL_TOOL_NAMES)

    def test_anthropic_tool_defs_respect_policy(self, tmp_path: Path) -> None:
        runtime = GeodeRuntime.create("Project Atlas", log_dir=tmp_path)
        defs = runtime.tool_registry.to_anthropic_tools(
            policy=runtime.policy_chain,
            mode="dry_run",
        )
        names = {d["name"] for d in defs}
        assert "send_notification" not in names
        assert "memory_search" in names
