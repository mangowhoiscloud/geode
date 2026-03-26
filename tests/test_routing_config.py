"""Tests for GAP 1: Routing Config (.geode/routing.toml)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from core.config import (
    _PIPELINE_NODE_DEFAULTS,
    ANTHROPIC_PRIMARY,
    RoutingConfig,
    get_node_model,
    load_routing_config,
    reset_routing_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear routing config cache before each test."""
    reset_routing_cache()
    yield  # type: ignore[misc]
    reset_routing_cache()


class TestRoutingConfig:
    """RoutingConfig dataclass behavior."""

    def test_empty_config_returns_none(self) -> None:
        cfg = RoutingConfig()
        assert cfg.nodes.get("analyst") is None
        assert cfg.agentic.get("default") is None

    def test_node_routing(self) -> None:
        cfg = RoutingConfig(
            nodes={"analyst": "claude-opus-4-6", "evaluator": "claude-sonnet-4-6"},
        )
        assert cfg.nodes["analyst"] == "claude-opus-4-6"
        assert cfg.nodes["evaluator"] == "claude-sonnet-4-6"

    def test_agentic_routing(self) -> None:
        cfg = RoutingConfig(
            agentic={"default": "claude-opus-4-6", "sub_agent": "claude-sonnet-4-6"},
        )
        assert cfg.agentic["default"] == "claude-opus-4-6"
        assert cfg.agentic["sub_agent"] == "claude-sonnet-4-6"


class TestLoadRoutingConfig:
    """Loading from TOML file."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        cfg = load_routing_config(tmp_path / "nonexistent.toml")
        assert cfg.nodes == {}
        assert cfg.agentic == {}

    def test_load_full_config(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "routing.toml"
        toml_file.write_text(
            textwrap.dedent("""\
            [nodes]
            analyst = "claude-opus-4-6"
            evaluator = "claude-sonnet-4-6"
            scoring = "claude-haiku-4-5-20251001"
            synthesizer = "claude-opus-4-6"

            [agentic]
            default = "claude-opus-4-6"
            sub_agent = "claude-sonnet-4-6"
            """)
        )
        cfg = load_routing_config(toml_file)
        assert cfg.nodes["analyst"] == "claude-opus-4-6"
        assert cfg.nodes["evaluator"] == "claude-sonnet-4-6"
        assert cfg.nodes["scoring"] == "claude-haiku-4-5-20251001"
        assert cfg.agentic["default"] == "claude-opus-4-6"

    def test_malformed_toml_returns_empty(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "bad.toml"
        toml_file.write_text("{{bad toml}}")
        cfg = load_routing_config(toml_file)
        assert cfg.nodes == {}


class TestGetNodeModel:
    """get_node_model() integration."""

    def test_no_config_returns_pipeline_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pipeline nodes return fixed defaults even without routing.toml."""
        import core.config as cfg

        monkeypatch.setattr(cfg, "ROUTING_CONFIG_PATH", tmp_path / "nope.toml")
        # Pipeline nodes get fixed defaults (never None → never inherit REPL model)
        assert get_node_model("analyst") == ANTHROPIC_PRIMARY
        assert get_node_model("evaluator") == ANTHROPIC_PRIMARY
        assert get_node_model("scoring") == ANTHROPIC_PRIMARY
        assert get_node_model("synthesizer") == ANTHROPIC_PRIMARY
        # Non-pipeline nodes still return None
        assert get_node_model("unknown_node") is None

    def test_configured_node_returns_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import core.config as cfg

        toml_file = tmp_path / "routing.toml"
        toml_file.write_text(
            textwrap.dedent("""\
            [nodes]
            analyst = "claude-sonnet-4-6"
            """)
        )
        monkeypatch.setattr(cfg, "ROUTING_CONFIG_PATH", toml_file)
        assert get_node_model("analyst") == "claude-sonnet-4-6"
        # evaluator not in routing.toml → falls back to pipeline default
        assert get_node_model("evaluator") == ANTHROPIC_PRIMARY

    def test_pipeline_node_defaults_cover_all_nodes(self) -> None:
        """Verify _PIPELINE_NODE_DEFAULTS covers analyst/evaluator/scoring/synthesizer."""
        expected_nodes = {"analyst", "evaluator", "scoring", "synthesizer"}
        assert set(_PIPELINE_NODE_DEFAULTS.keys()) == expected_nodes
        # All defaults must be ANTHROPIC_PRIMARY
        for node, model in _PIPELINE_NODE_DEFAULTS.items():
            assert model == ANTHROPIC_PRIMARY, f"{node} default should be {ANTHROPIC_PRIMARY}"

    def test_routing_toml_overrides_pipeline_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """routing.toml takes priority over _PIPELINE_NODE_DEFAULTS."""
        import core.config as cfg

        toml_file = tmp_path / "routing.toml"
        toml_file.write_text(
            textwrap.dedent("""\
            [nodes]
            analyst = "glm-5"
            """)
        )
        monkeypatch.setattr(cfg, "ROUTING_CONFIG_PATH", toml_file)
        # Explicit routing.toml override takes priority
        assert get_node_model("analyst") == "glm-5"
        # Others still use pipeline defaults
        assert get_node_model("evaluator") == ANTHROPIC_PRIMARY
