"""Structured scoring axes and rubric data for evaluators and analysts.

Loads configuration from core/config/evaluator_axes.yaml.
Prompt templates live in .md files loaded by the prompts package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_YAML_PATH = Path(__file__).resolve().parents[2] / "config" / "evaluator_axes.yaml"
_data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))

ANALYST_SPECIFIC: dict[str, str] = _data["analyst_specific"]

EVALUATOR_AXES: dict[str, dict[str, Any]] = _data["evaluator_axes"]

PROSPECT_EVALUATOR_AXES: dict[str, dict[str, Any]] = _data["prospect_evaluator_axes"]


def _derive_valid_axes_map() -> dict[str, set[str]]:
    """Derive valid axes keys from EVALUATOR_AXES + PROSPECT_EVALUATOR_AXES (SSOT)."""
    result: dict[str, set[str]] = {}
    for eval_type, spec in {**EVALUATOR_AXES, **PROSPECT_EVALUATOR_AXES}.items():
        result[eval_type] = set(spec["axes"].keys())
    return result


VALID_AXES_MAP: dict[str, set[str]] = _derive_valid_axes_map()
