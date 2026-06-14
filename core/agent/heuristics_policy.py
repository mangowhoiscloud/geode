"""Heuristic indicators SoT reader — ADR-013 T6, JSON mutation surface.

Mutator evolves keyword/phrase lists that prime the LLM's task-triage
heuristics — complexity / risk / time-pressure markers injected into the
system prompt's static block. Promptbreeder-식 evolution: agent uses
indicator phrases to classify the current request and pick a strategy
(careful-mode vs fast-mode, confirm-first vs proceed, etc.).

Different from T3 (style guide enums) — T3 picks a *fixed style*; T6
exposes *concrete phrase libraries* the LLM consults at parse-time.

**SoT schema** (모든 indicator group optional):

.. code-block:: json

    {
      "complexity_indicators": ["multi-step", "if and only if", "compare and contrast"],
      "high_risk_indicators": ["delete all", "drop table", "rm -rf", "force push"],
      "time_pressure_indicators": ["asap", "urgent", "deadline"]
    }

빈 정책 / 누락 group → 해당 group skip (no-op). Unknown group / 부적합
schema → graceful drop (forward-compat).

**Resolution order** (PR-BACKFILL-SOT 2026-05-21 shared chain):

1. ``GEODE_HEURISTICS_OVERRIDE`` env var — explicit override.
   - With ``GEODE_HEURISTICS_STRICT=1`` (audit subprocess): strict.
   - Without strict flag (operator daily): graceful (no fall-through).
2. ``~/.geode/autoresearch/handoff/heuristics.json`` — operator-local, graceful.
3. ``core/self_improving/state/policies/heuristics.json`` — in-repo, graceful.
4. ``None`` — no-op.

**Frontier**: Promptbreeder (Fernando et al., 2023) — self-referential
self-improvement of mutation operators + thinking styles, JSON-driven
phrase evolution.
"""

from __future__ import annotations

import logging
from html import escape
from pathlib import Path
from typing import Any

from core.agent.policy_sot import load_policy_sot
from core.paths import AUTORESEARCH_HEURISTICS_PATH, OPERATOR_LOCAL_HEURISTICS_PATH

log = logging.getLogger(__name__)

_HEURISTICS_OVERRIDE_ENV = "GEODE_HEURISTICS_OVERRIDE"

_HEURISTICS_SOT_PATH = AUTORESEARCH_HEURISTICS_PATH
"""Cross-process in-repo SoT path (T6, 2026-05-21). Module-local alias."""

_OPERATOR_LOCAL_HEURISTICS_PATH = OPERATOR_LOCAL_HEURISTICS_PATH
"""Operator-local SoT path. Module-local alias for monkey-patch."""

# Known indicator groups + their human-readable labels in the rendered block.
_GROUP_COMPLEXITY = "complexity_indicators"
_GROUP_HIGH_RISK = "high_risk_indicators"
_GROUP_TIME_PRESSURE = "time_pressure_indicators"

_GROUP_LABELS: dict[str, str] = {
    _GROUP_COMPLEXITY: "complexity",
    _GROUP_HIGH_RISK: "high_risk",
    _GROUP_TIME_PRESSURE: "time_pressure",
}


def _load_heuristics_override() -> dict[str, list[str]] | None:
    """Return the active heuristics dict, or ``None`` if no SoT applies."""
    return load_policy_sot(
        env_var=_HEURISTICS_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_HEURISTICS_PATH,
        in_repo=_HEURISTICS_SOT_PATH,
        label="heuristics",
        validate_strict=_validate_schema,
        validate_graceful=_validate_schema,
        coerce=_coerce,
    )


def _validate_schema(data: Any, path: Path) -> None:
    """Top-level dict; each group value must be ``list[str]`` if present."""
    if not isinstance(data, dict):
        raise RuntimeError(f"heuristics at {path} must be a dict")
    for group, value in data.items():
        if not isinstance(group, str):
            type_name = type(group).__name__
            raise RuntimeError(f"heuristics at {path} key must be str, got {type_name}")
        if not isinstance(value, list):
            type_name = type(value).__name__
            raise RuntimeError(f"heuristics at {path}[{group!r}] must be list, got {type_name}")
        if not all(isinstance(p, str) for p in value):
            raise RuntimeError(f"heuristics at {path}[{group!r}] must be list[str]")


def _coerce(data: dict[str, Any]) -> dict[str, list[str]]:
    """Extract known groups + drop empty strings / dedupe / preserve order."""
    result: dict[str, list[str]] = {}
    for group in _GROUP_LABELS:
        if group not in data:
            continue
        phrases = data[group]
        if not isinstance(phrases, list):
            continue
        seen: set[str] = set()
        normalized: list[str] = []
        for p in phrases:
            if isinstance(p, str) and p and p not in seen:
                seen.add(p)
                normalized.append(p)
        if normalized:
            result[group] = normalized
    return result


def apply_heuristics_policy(
    base_prompt: str,
    policy: dict[str, list[str]] | None,
) -> str:
    """Append a ``<heuristic_indicators>`` block to ``base_prompt``.

    Block renders each non-empty group as ``<group label="...">phrase1,
    phrase2, ...</group>``. Cache-friendly (lives in static section).

    ``policy is None`` / 빈 dict → ``base_prompt`` unchanged (no behavior
    change).
    """
    if not policy:
        return base_prompt
    lines: list[str] = ["<heuristic_indicators>"]
    rendered_any = False
    for group, label in _GROUP_LABELS.items():
        phrases = policy.get(group)
        if not phrases:
            continue
        safe_phrases = ", ".join(escape(p, quote=False) for p in phrases)
        lines.append(f'  <group label="{escape(label, quote=True)}">{safe_phrases}</group>')
        rendered_any = True
    lines.append("</heuristic_indicators>")
    if not rendered_any:
        return base_prompt
    block = "\n".join(lines)
    if base_prompt:
        return f"{base_prompt}\n\n{block}"
    return block


__all__ = ["apply_heuristics_policy"]
