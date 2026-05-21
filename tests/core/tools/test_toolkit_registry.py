"""Tests for core.tools.toolkit_registry — TOML parsing + composition + fallback."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from core.tools.toolkit_registry import (
    DEFAULT_TOOLKIT,
    ToolkitCompositionError,
    ToolkitRegistry,
    load_default_registry,
)


class TestFromDict:
    def test_simple_toolkit(self) -> None:
        reg = ToolkitRegistry.from_dict(
            {
                "toolkits": {
                    "kit_a": {
                        "description": "A",
                        "tools": ["read_document", "grep_files"],
                    }
                }
            }
        )
        assert reg.has("kit_a")
        assert reg.resolve("kit_a") == frozenset({"read_document", "grep_files"})

    def test_flat_dict_shape_accepted(self) -> None:
        """Tests can pass a flat dict without the ``toolkits`` wrapper."""
        reg = ToolkitRegistry.from_dict(
            {"kit_b": {"tools": ["read_document"]}}
        )
        assert reg.has("kit_b")
        assert reg.resolve("kit_b") == frozenset({"read_document"})

    def test_empty_body(self) -> None:
        """Toolkit with no ``tools`` and no ``includes`` resolves to empty set."""
        reg = ToolkitRegistry.from_dict({"empty_kit": {}})
        assert reg.resolve("empty_kit") == frozenset()

    def test_malformed_row(self) -> None:
        with pytest.raises(ToolkitCompositionError):
            ToolkitRegistry.from_dict({"toolkits": {"bad": "not_a_table"}})


class TestComposition:
    def test_includes_recursive(self) -> None:
        reg = ToolkitRegistry.from_dict(
            {
                "common_read": {"tools": ["read_document", "grep_files"]},
                "common_write": {"tools": ["write_file"]},
                "compound": {"includes": ["common_read", "common_write"]},
            }
        )
        assert reg.resolve("compound") == frozenset(
            {"read_document", "grep_files", "write_file"}
        )

    def test_nested_includes(self) -> None:
        """Includes chain follows transitively."""
        reg = ToolkitRegistry.from_dict(
            {
                "a": {"tools": ["t_a"]},
                "b": {"tools": ["t_b"], "includes": ["a"]},
                "c": {"tools": ["t_c"], "includes": ["b"]},
            }
        )
        assert reg.resolve("c") == frozenset({"t_a", "t_b", "t_c"})

    def test_cycle_detected(self) -> None:
        reg = ToolkitRegistry.from_dict(
            {
                "a": {"includes": ["b"]},
                "b": {"includes": ["a"]},
            }
        )
        with pytest.raises(ToolkitCompositionError, match="cycle"):
            reg.resolve("a")

    def test_self_cycle_detected(self) -> None:
        reg = ToolkitRegistry.from_dict({"self_ref": {"includes": ["self_ref"]}})
        with pytest.raises(ToolkitCompositionError, match="cycle"):
            reg.resolve("self_ref")

    def test_missing_include_target(self) -> None:
        reg = ToolkitRegistry.from_dict(
            {"a": {"includes": ["nonexistent"]}}
        )
        with pytest.raises(ToolkitCompositionError, match="not declared"):
            reg.resolve("a")

    def test_duplicate_tools_merged(self) -> None:
        """The same tool name across composed kits collapses to one entry."""
        reg = ToolkitRegistry.from_dict(
            {
                "a": {"tools": ["read_document"]},
                "b": {"tools": ["read_document", "grep_files"], "includes": ["a"]},
            }
        )
        assert reg.resolve("b") == frozenset({"read_document", "grep_files"})


class TestFallback:
    def test_unknown_falls_back_to_default(self) -> None:
        reg = ToolkitRegistry.from_dict(
            {
                "_default": {"tools": ["read_document"]},
            }
        )
        # ``typo_name`` is unknown; the registry logs a WARNING (not
        # asserted here) and routes through ``_default``.
        assert reg.resolve_with_fallback("typo_name") == frozenset({"read_document"})

    def test_none_uses_default(self) -> None:
        reg = ToolkitRegistry.from_dict(
            {"_default": {"tools": ["read_document"]}}
        )
        assert reg.resolve_with_fallback(None) == frozenset({"read_document"})

    def test_no_default_returns_empty(self) -> None:
        reg = ToolkitRegistry.from_dict({"kit_only": {"tools": ["read_document"]}})
        assert reg.resolve_with_fallback(None) == frozenset()

    def test_known_takes_precedence(self) -> None:
        reg = ToolkitRegistry.from_dict(
            {
                "_default": {"tools": ["read_document"]},
                "explicit": {"tools": ["write_file"]},
            }
        )
        assert reg.resolve_with_fallback("explicit") == frozenset({"write_file"})


class TestDiskLoad:
    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        reg = ToolkitRegistry.load(tmp_path / "missing.toml")
        assert reg.names() == []

    def test_load_real_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "toolkits.toml"
        p.write_text(
            textwrap.dedent(
                """
                [toolkits.kit_x]
                description = "test"
                tools = ["read_document"]
                """
            ).strip()
        )
        reg = ToolkitRegistry.load(p)
        assert reg.has("kit_x")
        assert reg.resolve("kit_x") == frozenset({"read_document"})


class TestDefaultRegistry:
    def test_bundled_toolkits_load(self) -> None:
        """The bundled ``core/tools/toolkits.toml`` must load + parse cleanly."""
        reg = load_default_registry(force_reload=True)
        assert reg.has(DEFAULT_TOOLKIT), "missing _default in bundled manifest"
        # Spot-check seed_* kits used by .claude/agents/seed_*.md
        for name in (
            "seed_generation",
            "seed_critique",
            "seed_pilot",
            "seed_ranker",
            "seed_evolver",
            "seed_meta_review",
            "seed_proximity",
        ):
            assert reg.has(name), f"bundled toolkit {name!r} missing"
            # Resolution should never raise — guards against accidental
            # cycles or typos in the manifest's ``includes``.
            tools = reg.resolve(name)
            assert isinstance(tools, frozenset)

    def test_bundled_general_toolkits(self) -> None:
        """CSP-1 — general-purpose toolkits available for non-seed agents."""
        reg = load_default_registry(force_reload=True)
        # web_research — search + fetch + common read primitives.
        web = reg.resolve("web_research")
        assert "general_web_search" in web
        assert "web_fetch" in web
        assert "read_document" in web  # via common_read
        # data_analysis — read + search + memory, no write.
        analysis = reg.resolve("data_analysis")
        assert "general_web_search" in analysis
        assert "memory_search" in analysis
        assert "write_file" not in analysis  # read-only
        # general_purpose — broad-surface orchestrator kit.
        general = reg.resolve("general_purpose")
        assert {"general_web_search", "web_fetch", "memory_save",
                "note_save", "read_document", "write_file"} <= general

    def test_default_agents_resolve_their_toolkits(self) -> None:
        """The bundled ``_DEFAULT_AGENTS`` declare toolkits that resolve."""
        from core.skills.agents import AgentRegistry

        registry = AgentRegistry()
        registry.load_defaults()
        reg = load_default_registry(force_reload=True)
        for name in ("research_assistant", "data_analyst", "web_researcher"):
            agent = registry.get(name)
            assert agent is not None
            assert agent.toolkit, f"default agent {name!r} missing toolkit declaration"
            # Toolkit must exist in the bundled manifest.
            assert reg.has(agent.toolkit), (
                f"default agent {name!r} declares toolkit={agent.toolkit!r} "
                f"which is not in toolkits.toml"
            )
