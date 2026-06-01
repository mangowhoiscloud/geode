"""Skill catalog SoT reader — ADR-013 T2, JSON mutation surface.

Mutator overrides per-skill ``description`` text + ``user_invocable``
visibility for the LLM's skill-routing context block (rendered by
``core.skills.skills.SkillRegistry.get_context_block``).

Selecting the right skill is bandwidth-limited by description quality —
identical to ADR-013 T1 (tool descriptions) but applied to the agent's
*skill catalog* surface (Voyager-style routing — frontier curriculum
agents evolve their own task taxonomy via the same JSON-only loop).

**SoT schema** (모든 entry optional):

.. code-block:: json

    {
      "geode-gitflow": {
        "description": "Curated workflow for branch/PR/merge operations.",
        "user_invocable": true
      },
      "frontier-harness-research": {
        "user_invocable": false
      }
    }

빈 entry / 누락 skill / 부적합 schema → no-op (default SKILL.md metadata
유지). Unknown skill name 은 정책에 있어도 무시 — base registry 가
authoritative.

**Resolution order** (PR-BACKFILL-SOT 2026-05-21 shared chain):

1. ``GEODE_SKILL_CATALOG_OVERRIDE`` env var — explicit override.

   - With ``GEODE_SKILL_CATALOG_STRICT=1`` (audit subprocess): strict.
   - Without strict flag (operator daily): graceful (no fall-through).

2. ``~/.geode/self-improving-loop/skill-catalog.json`` — operator-local,
   graceful.
3. ``autoresearch/state/policies/skill-catalog.json`` — in-repo, graceful.
4. ``None`` — no-op.

**Frontier**: Voyager (Wang et al., 2023) curriculum loop — agent
maintains its own skill library + descriptions, both updated by the loop.
GEODE separates the *description text* (mutable here) from the *skill body*
(SKILL.md, Tier 2, untouched in this surface).
"""

from __future__ import annotations

import json
import logging
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.paths import GLOBAL_SKILL_CATALOG_PATH, OPERATOR_LOCAL_SKILL_CATALOG_PATH
from core.self_improving.loop.sot_resolution import resolve_sot

if TYPE_CHECKING:
    from core.skills.skills import SkillRegistry

log = logging.getLogger(__name__)

_SKILL_CATALOG_OVERRIDE_ENV = "GEODE_SKILL_CATALOG_OVERRIDE"

_SKILL_CATALOG_SOT_PATH = GLOBAL_SKILL_CATALOG_PATH
"""Cross-process in-repo SoT path (T2, 2026-05-21). Module-local alias
for monkey-patch in tests."""

_OPERATOR_LOCAL_SKILL_CATALOG_PATH = OPERATOR_LOCAL_SKILL_CATALOG_PATH
"""Operator-local SoT path. Module-local alias for monkey-patch."""

_FIELD_DESCRIPTION = "description"
_FIELD_USER_INVOCABLE = "user_invocable"
_ALL_FIELDS = frozenset({_FIELD_DESCRIPTION, _FIELD_USER_INVOCABLE})


def _load_skill_catalog_override() -> dict[str, dict[str, Any]] | None:
    """Return active skill-catalog override, or ``None`` if no SoT.

    Resolution order — see module docstring (3-layer chain).
    """
    selection = resolve_sot(
        env_var=_SKILL_CATALOG_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_SKILL_CATALOG_PATH,
        in_repo=_SKILL_CATALOG_SOT_PATH,
    )
    if selection is None:
        return None
    if selection.strict:
        return _strict_load(selection.path)
    return _graceful_load(selection.path)


def _strict_load(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"{_SKILL_CATALOG_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{_SKILL_CATALOG_OVERRIDE_ENV}={path} load failed: {exc}") from exc
    _validate_schema(data, path)
    return _coerce(data)


def _graceful_load(path: Path) -> dict[str, dict[str, Any]] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.warning("skill-catalog SoT at %s is unreadable; ignoring", path)
        return None
    try:
        _validate_schema(data, path)
    except RuntimeError as exc:
        log.warning("skill-catalog SoT at %s schema invalid: %s; ignoring", path, exc)
        return None
    return _coerce(data)


def _validate_schema(data: Any, path: Path) -> None:
    """``data`` 가 ``dict[str, dict[description: str, user_invocable: bool]]`` 모양인지.

    Unknown field 는 무시 (forward-compatible)."""
    if not isinstance(data, dict):
        raise RuntimeError(f"skill-catalog at {path} must be a dict")
    for skill_name, entry in data.items():
        if not isinstance(skill_name, str):
            type_name = type(skill_name).__name__
            raise RuntimeError(f"skill-catalog at {path} key must be str, got {type_name}")
        if not isinstance(entry, dict):
            type_name = type(entry).__name__
            raise RuntimeError(
                f"skill-catalog at {path}[{skill_name!r}] must be dict, got {type_name}"
            )
        if _FIELD_DESCRIPTION in entry and not isinstance(entry[_FIELD_DESCRIPTION], str):
            raise RuntimeError(f"skill-catalog at {path}[{skill_name!r}].description must be str")
        if _FIELD_USER_INVOCABLE in entry and not isinstance(entry[_FIELD_USER_INVOCABLE], bool):
            raise RuntimeError(
                f"skill-catalog at {path}[{skill_name!r}].user_invocable must be bool"
            )


def _coerce(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """알려진 field 만 추출 — entry 별 description / user_invocable 만 보존."""
    result: dict[str, dict[str, Any]] = {}
    for skill_name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        kept: dict[str, Any] = {}
        if _FIELD_DESCRIPTION in entry:
            kept[_FIELD_DESCRIPTION] = entry[_FIELD_DESCRIPTION]
        if _FIELD_USER_INVOCABLE in entry:
            kept[_FIELD_USER_INVOCABLE] = entry[_FIELD_USER_INVOCABLE]
        if kept:
            result[skill_name] = kept
    return result


def apply_skill_catalog_policy(
    registry: SkillRegistry,
    policy: dict[str, dict[str, Any]] | None,
    *,
    max_chars: int = 8000,
) -> str:
    """Render the skill catalog context block with per-skill overrides applied.

    Replaces the registry's ``get_context_block()`` call at the inference
    entry point. When ``policy is None``, delegates to the registry's
    own renderer (no behavior change).

    Otherwise iterates the registry and emits the same XML format
    (``<available_skills>...<skill ...>desc</skill>...</available_skills>``)
    but for each skill checks ``policy.get(skill.name, {})`` and prefers
    override values for ``description`` / ``user_invocable``. Unknown
    skill names in the policy are ignored — base registry is authoritative
    for which skills exist.
    """
    if not policy:
        return registry.get_context_block(max_chars=max_chars)

    skills = sorted(registry._skills.values(), key=lambda s: s.name)
    if not skills:
        return ""

    lines: list[str] = ["<available_skills>"]
    total = 0
    for skill in skills:
        override = policy.get(skill.name, {})
        effective_invocable = override.get(_FIELD_USER_INVOCABLE, skill.user_invocable)
        effective_description = override.get(_FIELD_DESCRIPTION, skill.description)
        attrs = [
            f'name="{escape(skill.name, quote=True)}"',
            f'user_invocable="{str(effective_invocable).lower()}"',
        ]
        if skill.tools:
            attrs.append(f'tools="{escape(", ".join(skill.tools), quote=True)}"')
        if skill.context_fork:
            attrs.append('context="fork"')
        desc = escape(effective_description[:200])
        line = f"  <skill {' '.join(attrs)}>{desc}</skill>"
        if total + len(line) > max_chars:
            remaining = len(skills) - (len(lines) - 1)
            lines.append(f'  <truncated remaining="{remaining}" />')
            break
        lines.append(line)
        total += len(line)
    lines.append("</available_skills>")

    return "\n".join(lines)


__all__ = ["apply_skill_catalog_policy"]
