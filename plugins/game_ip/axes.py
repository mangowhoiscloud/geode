"""Game IP rubric axes — eager-loaded from evaluator_axes.yaml.

This is the canonical source for game-IP-specific scoring axes. Previously
this data lived in `core/llm/prompts/axes.py`, where its eager YAML load at
import time hard-coupled `core/` to `plugins/game_ip/`. Step 1 of the
domain-free-core refactor (see docs/architecture/domain-free-core-audit.md)
moves the load here so that `core/` can be imported without a game_ip plugin
present (e.g. REODE forks).

Backwards-compatible: `core/llm/prompts/axes.py` re-exports these names
when this plugin is installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_YAML_PATH = Path(__file__).resolve().parent / "config" / "evaluator_axes.yaml"
_data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))

ANALYST_SPECIFIC: dict[str, str] = _data["analyst_specific"]
EVALUATOR_AXES: dict[str, dict[str, Any]] = _data["evaluator_axes"]
PROSPECT_EVALUATOR_AXES: dict[str, dict[str, Any]] = _data["prospect_evaluator_axes"]


def _derive_valid_axes_map() -> dict[str, set[str]]:
    """Derive valid axes keys from EVALUATOR_AXES + PROSPECT_EVALUATOR_AXES."""
    result: dict[str, set[str]] = {}
    for eval_type, spec in {**EVALUATOR_AXES, **PROSPECT_EVALUATOR_AXES}.items():
        result[eval_type] = set(spec["axes"].keys())
    return result


VALID_AXES_MAP: dict[str, set[str]] = _derive_valid_axes_map()
