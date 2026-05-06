"""GameIPDomain — DomainPort adapter for game IP evaluation.

Wraps all game-IP-specific configuration (analyst types, evaluator axes,
scoring weights, decision tree, cause/action mappings) into the DomainPort
interface so the pipeline nodes can remain domain-agnostic.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# Paths relative to this adapter file
_ADAPTER_DIR = Path(__file__).resolve().parent
_CONFIG_DIR = _ADAPTER_DIR / "config"
_FIXTURES_DIR = _ADAPTER_DIR / "fixtures"


def _load_axes_yaml() -> dict[str, Any]:
    """Load evaluator_axes.yaml from config directory."""
    path = _CONFIG_DIR / "evaluator_axes.yaml"
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _load_cause_actions_yaml() -> dict[str, Any]:
    """Load cause_actions.yaml from config directory."""
    path = _CONFIG_DIR / "cause_actions.yaml"
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _load_scoring_config() -> dict[str, Any]:
    """Load scoring weights from config, with project-level override.

    Priority: .geode/scoring_weights.yaml > built-in config/scoring_weights.yaml
    """
    # Project override
    project_path = Path(".geode") / "scoring_weights.yaml"
    if project_path.exists():
        try:
            data: dict[str, Any] = yaml.safe_load(project_path.read_text(encoding="utf-8"))
            log.info("Scoring weights loaded from project override: %s", project_path)
            return data
        except Exception:
            log.warning("Failed to load project scoring config, using built-in", exc_info=True)

    # Built-in default
    builtin_path = _CONFIG_DIR / "scoring_weights.yaml"
    data = yaml.safe_load(builtin_path.read_text(encoding="utf-8"))
    return data


class GameIPDomain:
    """DomainPort implementation for game IP evaluation.

    All game-specific configuration is encapsulated here. Pipeline nodes
    call get_domain() to access these values instead of hardcoding them.
    """

    def __init__(self) -> None:
        self._axes_data = _load_axes_yaml()
        self._cause_data = _load_cause_actions_yaml()

    # --- Identity ---

    @property
    def name(self) -> str:
        return "game_ip"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Game IP 평가 도메인 — 저평가 IP의 시장 잠재력 분석"

    # --- Analyst Configuration ---

    def get_analyst_types(self) -> list[str]:
        return list(self._axes_data["analyst_specific"].keys())

    def get_analyst_specific(self) -> dict[str, str]:
        return dict(self._axes_data["analyst_specific"])

    # --- Evaluator Configuration ---

    def get_evaluator_types(self) -> list[str]:
        return list(self._axes_data["evaluator_axes"].keys())

    def get_evaluator_axes(self) -> dict[str, dict[str, Any]]:
        return dict(self._axes_data["evaluator_axes"])

    def get_prospect_evaluator_axes(self) -> dict[str, dict[str, Any]]:
        return dict(self._axes_data.get("prospect_evaluator_axes", {}))

    def get_valid_axes_map(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for eval_type, spec in self._axes_data["evaluator_axes"].items():
            result[eval_type] = set(spec["axes"].keys())
        if "prospect_evaluator_axes" in self._axes_data:
            for eval_type, spec in self._axes_data["prospect_evaluator_axes"].items():
                result[eval_type] = set(spec["axes"].keys())
        return result

    # --- Scoring ---

    def get_scoring_weights(self) -> dict[str, float]:
        from plugins.game_ip.scoring_constants import DEFAULT_WEIGHTS

        cfg = _load_scoring_config()
        weights: dict[str, float] = cfg.get("weights", DEFAULT_WEIGHTS)
        return weights

    def get_confidence_multiplier_params(self) -> tuple[float, float]:
        from plugins.game_ip.scoring_constants import (
            CONFIDENCE_BASE_FACTOR,
            CONFIDENCE_SCALE_FACTOR,
        )

        cfg = _load_scoring_config()
        cm: dict[str, float] = cfg.get("confidence_multiplier", {})
        return (
            cm.get("base_factor", CONFIDENCE_BASE_FACTOR),
            cm.get("scale_factor", CONFIDENCE_SCALE_FACTOR),
        )

    def get_tier_thresholds(self) -> list[tuple[float, str]]:
        cfg = _load_scoring_config()
        tiers: list[dict[str, Any]] = cfg.get("tiers", [])
        if tiers:
            return [(t["threshold"], t["label"]) for t in tiers]
        return [(80.0, "S"), (60.0, "A"), (40.0, "B")]

    def get_tier_fallback(self) -> str:
        cfg = _load_scoring_config()
        return str(cfg.get("fallback_tier", "C"))

    # --- Classification ---

    def get_cause_values(self) -> list[str]:
        return [
            "undermarketed",
            "conversion_failure",
            "monetization_misfit",
            "niche_gem",
            "timing_mismatch",
            "discovery_failure",
        ]

    def get_action_values(self) -> list[str]:
        return [
            "marketing_boost",
            "monetization_pivot",
            "platform_expansion",
            "timing_optimization",
            "community_activation",
        ]

    def get_cause_to_action(self) -> dict[str, str]:
        return dict(self._cause_data["cause_to_action"])

    def get_cause_descriptions(self) -> dict[str, str]:
        return dict(self._cause_data["cause_descriptions"])

    def get_action_descriptions(self) -> dict[str, str]:
        return dict(self._cause_data["action_descriptions"])

    # --- Fixtures ---

    def list_fixtures(self) -> list[str]:
        if not _FIXTURES_DIR.exists():
            return []
        return [p.stem for p in _FIXTURES_DIR.glob("*.json")]

    def get_fixture_path(self) -> str | None:
        if _FIXTURES_DIR.exists():
            return str(_FIXTURES_DIR)
        return None

    # --- Lifecycle hooks (DomainPort v2, step 3) ---
    #
    # All four methods lazy-import their plugin-side dependencies to
    # avoid pulling in the full pipeline at adapter construction time.

    def wire_context_assembler(self, assembler: Any) -> None:
        """Inject ``ContextAssembler`` into the game-IP router node."""
        from plugins.game_ip.wiring import wire_context_assembler

        wire_context_assembler(assembler)

    def build_task_graph(self, memory: Any, subject_id: str) -> Any:
        """Build the game-IP TaskGraph for ``subject_id`` (IP name).

        ``memory`` is accepted for forward compatibility (future domains
        may need session memory to size the graph) but currently unused
        — the game-IP topology is fixed.
        """
        from plugins.game_ip.wiring import build_task_graph

        return build_task_graph(subject_id)

    def build_signal_adapter(self) -> Any:
        """Wire the game-IP signal adapter (Steam MCP + fixture fallback)."""
        from plugins.game_ip.wiring import build_signal_adapter

        build_signal_adapter()
        return None

    def compose_static_prefix(self, model: str) -> str:
        """Return the game-IP-flavored ``ROUTER_SYSTEM`` prefix."""
        from plugins.game_ip.prompt import compose_static_prefix

        return compose_static_prefix(model)

    # --- CLI extension hooks (DomainPort v2, step 4) ---

    def get_rerunnable_nodes(self) -> set[str]:
        """Pipeline nodes that ``/rerun_node`` is allowed to re-invoke."""
        return {"scoring", "verification", "synthesizer"}

    def register_slash_commands(self, command_map: dict[str, str]) -> None:
        """Merge the game-IP slash entries into the generic ``COMMAND_MAP``."""
        from plugins.game_ip.cli.commands import GAME_IP_SLASHES

        command_map.update(GAME_IP_SLASHES)

    def render_help_fragment(self) -> None:
        """Append the game-IP slash block to ``/help`` output."""
        from plugins.game_ip.cli.commands import render_help_fragment

        render_help_fragment()

    def register_tool_handlers(self, handlers: dict[str, Any]) -> None:
        """Merge the game-IP tool handlers (analysis + signals + generate_data)."""
        from plugins.game_ip.cli.tool_handlers import build_game_ip_handlers

        handlers.update(build_game_ip_handlers())

    # --- MCP server extension hook (DomainPort v2, step 6) ---

    def register_mcp_tools(self, server: Any) -> None:
        """Attach the game-IP MCP tools (analyze_ip, quick_score,
        get_ip_signals, list_fixtures) and the ``geode://fixtures``
        resource to ``server``.
        """
        from plugins.game_ip.mcp.tools import register_game_ip_mcp_tools

        register_game_ip_mcp_tools(server)
