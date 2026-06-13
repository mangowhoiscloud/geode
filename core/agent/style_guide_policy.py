"""Response style guide SoT reader — ADR-013 T3, JSON mutation surface.

Mutator picks from a constrained typed enum (vs. wrapper-sections.json's
free-form text mutation) so the loop can explore the small, expressive
style space efficiently. This used to target the ``ux_means`` fitness
axis (``success_rate`` / ``revert_ratio``); that axis was removed in
PR-MARGIN-FITNESS-SCALE (2026-05-30) — fitness is now pure Petri dim
aggregate, so style mutations only move fitness via their effect on the
Petri behaviour dims.

**SoT schema** (모든 entry optional, 각 value 는 enum):

.. code-block:: json

    {
      "tone": "concise",                  // concise | balanced | verbose
      "verbosity_level": "low",           // low | medium | high
      "response_format": "markdown",      // markdown | plain | structured
      "code_style": "show-first"          // show-first | explain-first
    }

빈 정책 / 누락 field → 해당 axis 는 default 동작. Unknown enum value →
WARNING + 해당 axis drop (forward-compat 위해 다른 axes 는 유지).

**Resolution order** (PR-BACKFILL-SOT 2026-05-21 shared chain):

1. ``GEODE_STYLE_GUIDE_OVERRIDE`` env var — explicit override.

   - With ``GEODE_STYLE_GUIDE_STRICT=1`` (audit subprocess): strict.
   - Without strict flag (operator daily): graceful (no fall-through).

2. ``~/.geode/autoresearch/handoff/style-guide.json`` — operator-local, graceful.
3. ``state/autoresearch/policies/style-guide.json`` — in-repo, graceful.
4. ``None`` — no-op.

**Frontier**: OpenAI / Anthropic system prompt guides converge on
**enum-based response constraints** (style, format, length) over
free-form prose — easier to A/B-test and roll back.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.agent.policy_sot import load_policy_sot
from core.paths import GLOBAL_STYLE_GUIDE_PATH, OPERATOR_LOCAL_STYLE_GUIDE_PATH

log = logging.getLogger(__name__)

_STYLE_GUIDE_OVERRIDE_ENV = "GEODE_STYLE_GUIDE_OVERRIDE"

_STYLE_GUIDE_SOT_PATH = GLOBAL_STYLE_GUIDE_PATH
"""Cross-process in-repo SoT path (T3, 2026-05-21). Module-local alias."""

_OPERATOR_LOCAL_STYLE_GUIDE_PATH = OPERATOR_LOCAL_STYLE_GUIDE_PATH
"""Operator-local SoT path. Module-local alias for monkey-patch."""


# Enum field → allowed values + human-readable directive on selection.
_TONE = "tone"
_VERBOSITY = "verbosity_level"
_FORMAT = "response_format"
_CODE_STYLE = "code_style"

_FIELD_ENUMS: dict[str, frozenset[str]] = {
    _TONE: frozenset({"concise", "balanced", "verbose"}),
    _VERBOSITY: frozenset({"low", "medium", "high"}),
    _FORMAT: frozenset({"markdown", "plain", "structured"}),
    _CODE_STYLE: frozenset({"show-first", "explain-first"}),
}

_DIRECTIVES: dict[str, dict[str, str]] = {
    _TONE: {
        "concise": "Keep responses brief; 2-3 sentences for routine answers.",
        "balanced": "Match response length to question complexity.",
        "verbose": "Expand with context and reasoning; longer explanations welcome.",
    },
    _VERBOSITY: {
        "low": "Default to minimum detail; expand only when explicitly asked.",
        "medium": "Include relevant context but skip obvious background.",
        "high": "Provide thorough background and edge cases by default.",
    },
    _FORMAT: {
        "markdown": "Use Markdown — headers, lists, fenced code blocks.",
        "plain": "Use plain prose; avoid Markdown formatting.",
        "structured": "Use explicit sections and bullet lists for every response.",
    },
    _CODE_STYLE: {
        "show-first": "Show working code first, then explain after.",
        "explain-first": "Explain the approach first, then show the code.",
    },
}


def _load_style_guide_override() -> dict[str, str] | None:
    """Return the active style guide dict, or ``None`` if no SoT applies."""
    return load_policy_sot(
        env_var=_STYLE_GUIDE_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_STYLE_GUIDE_PATH,
        in_repo=_STYLE_GUIDE_SOT_PATH,
        label="style-guide",
        validate_strict=_validate_schema,
        validate_graceful=_validate_schema,
        coerce=_coerce,
    )


def _validate_schema(data: Any, path: Path) -> None:
    """Top-level shape — ``dict[str, str]``. Enum value 검증은 `_coerce` 단계.

    Forward-compat: unknown field 는 `_coerce` 에서 drop (raise X)."""
    if not isinstance(data, dict):
        raise RuntimeError(f"style-guide at {path} must be a dict")
    for key, value in data.items():
        if not isinstance(key, str):
            type_name = type(key).__name__
            raise RuntimeError(f"style-guide at {path} key must be str, got {type_name}")
        if not isinstance(value, str):
            type_name = type(value).__name__
            raise RuntimeError(f"style-guide at {path}[{key!r}] must be str, got {type_name}")


def _coerce(data: dict[str, Any]) -> dict[str, str]:
    """Drop unknown fields + unknown enum values (graceful per-axis)."""
    result: dict[str, str] = {}
    for field, allowed in _FIELD_ENUMS.items():
        if field not in data:
            continue
        value = data[field]
        if value in allowed:
            result[field] = value
        else:
            log.warning(
                "style-guide field %r has unknown enum value %r (allowed: %s); dropping",
                field,
                value,
                sorted(allowed),
            )
    return result


def apply_style_guide_policy(
    base_prompt: str,
    policy: dict[str, str] | None,
) -> str:
    """Append a ``<response_style>`` block to ``base_prompt`` per ``policy``.

    Returns ``base_prompt`` unchanged when ``policy`` is empty / None.
    The appended block lives in the **static** (cache-eligible) portion of
    the system prompt — it changes only when the policy SoT changes, which
    is rare enough to amortize the cache miss across many turns.
    """
    if not policy:
        return base_prompt
    lines: list[str] = ["<response_style>"]
    for field in (_TONE, _VERBOSITY, _FORMAT, _CODE_STYLE):
        value = policy.get(field)
        if value is None:
            continue
        directive = _DIRECTIVES[field].get(value)
        if directive is None:
            continue
        lines.append(f"  {field}: {value} — {directive}")
    lines.append("</response_style>")
    if len(lines) == 2:  # no fields rendered
        return base_prompt
    block = "\n".join(lines)
    if base_prompt:
        return f"{base_prompt}\n\n{block}"
    return block


__all__ = ["apply_style_guide_policy"]
