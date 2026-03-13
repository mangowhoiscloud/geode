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
_CONFIG_DIR = _ADAPTER_DIR.parents[1] / "config"
_FIXTURES_DIR = _ADAPTER_DIR.parents[1] / "fixtures"


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
        return "저평가 게임 IP 평가 도메인 — 게임화 IP의 시장 잠재력 분석"

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
        return {
            "exposure_lift": 0.25,
            "quality": 0.20,
            "recovery": 0.18,
            "growth": 0.12,
            "momentum": 0.20,
            "developer": 0.05,
        }

    def get_confidence_multiplier_params(self) -> tuple[float, float]:
        # final = base_score * (0.7 + 0.3 * confidence/100)
        return (0.7, 0.3)

    def get_tier_thresholds(self) -> list[tuple[float, str]]:
        return [(80.0, "S"), (60.0, "A"), (40.0, "B")]

    def get_tier_fallback(self) -> str:
        return "C"

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
