"""Agent contracts SoT reader — ADR-012 M2, JSON mutation surface.

Mutator overrides per-agent ``role`` / ``system_prompt`` / ``tools`` on
:class:`core.skills.agents.AgentDefinition` instances. ``model`` field
는 Tier 2 (안전성 invariants 의 root) 이므로 본 surface 에서 명시적
제외 — mutator 가 provider 를 임의로 바꿔 safety guardrail 을 우회하지
못하도록 설계.

**SoT schema** (모든 agent entry optional, 모든 field optional):

.. code-block:: json

    {
      "research_assistant": {
        "role": "Research Specialist (v2)",
        "system_prompt": "...evolved prompt...",
        "tools": ["web_search", "web_fetch", "read_document"]
      },
      "data_analyst": {
        "system_prompt": "...evolved prompt..."
      }
    }

Unknown agent name / 부적합 schema → graceful drop (forward-compat).

**Resolution order** (PR-BACKFILL-SOT 2026-05-21 shared chain):

1. ``GEODE_AGENT_CONTRACTS_OVERRIDE`` env var — explicit override.
   - With ``GEODE_AGENT_CONTRACTS_STRICT=1``: strict.
   - Without strict flag: graceful (no fall-through).
2. ``~/.geode/self-improving-loop/agent-contracts.json`` — operator-local.
3. ``autoresearch/state/policies/agent-contracts.json`` — in-repo.
4. ``None`` — no-op.

**Frontier**: Claude Code 의 ``.claude/agents/*.md`` agent definitions
이 사용자 hand-edit 만 받지만 — mutator 가 자동 진화시키는 것이 M2 의
가치. ``model`` 은 사용자 explicit 선택만 허용 (Tier 2).
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from core.paths import (
    GLOBAL_AGENT_CONTRACTS_PATH,
    OPERATOR_LOCAL_AGENT_CONTRACTS_PATH,
)
from core.self_improving.loop.sot_resolution import resolve_sot

log = logging.getLogger(__name__)

_AGENT_CONTRACTS_OVERRIDE_ENV = "GEODE_AGENT_CONTRACTS_OVERRIDE"

_AGENT_CONTRACTS_SOT_PATH = GLOBAL_AGENT_CONTRACTS_PATH
"""Cross-process in-repo SoT path (M2, 2026-05-21). Module-local alias."""

_OPERATOR_LOCAL_AGENT_CONTRACTS_PATH = OPERATOR_LOCAL_AGENT_CONTRACTS_PATH
"""Operator-local SoT path. Module-local alias for monkey-patch."""


# Mutable field set — ``model`` is intentionally absent (Tier 2 guardrail).
_FIELD_ROLE = "role"
_FIELD_SYSTEM_PROMPT = "system_prompt"
_FIELD_TOOLS = "tools"
_MUTABLE_FIELDS = frozenset({_FIELD_ROLE, _FIELD_SYSTEM_PROMPT, _FIELD_TOOLS})


def _load_agent_contracts_override() -> dict[str, dict[str, Any]] | None:
    """Return the active agent-contracts dict, or ``None`` if no SoT applies."""
    selection = resolve_sot(
        env_var=_AGENT_CONTRACTS_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_AGENT_CONTRACTS_PATH,
        in_repo=_AGENT_CONTRACTS_SOT_PATH,
    )
    if selection is None:
        return None
    if selection.strict:
        return _strict_load(selection.path)
    return _graceful_load(selection.path)


def _strict_load(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"{_AGENT_CONTRACTS_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{_AGENT_CONTRACTS_OVERRIDE_ENV}={path} load failed: {exc}") from exc
    _validate_schema(data, path)
    return _coerce(data)


def _graceful_load(path: Path) -> dict[str, dict[str, Any]] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.warning("agent-contracts SoT at %s is unreadable; ignoring", path)
        return None
    try:
        _validate_schema(data, path)
    except RuntimeError as exc:
        log.warning("agent-contracts SoT at %s schema invalid: %s; ignoring", path, exc)
        return None
    return _coerce(data)


def _validate_schema(data: Any, path: Path) -> None:
    """Top-level ``dict[str, dict[field, value]]``. role/system_prompt = str;
    tools = list[str]. Unknown field 무시 (forward-compat).
    """
    if not isinstance(data, dict):
        raise RuntimeError(f"agent-contracts at {path} must be a dict")
    for agent_name, entry in data.items():
        if not isinstance(agent_name, str):
            type_name = type(agent_name).__name__
            raise RuntimeError(f"agent-contracts at {path} key must be str, got {type_name}")
        if not isinstance(entry, dict):
            type_name = type(entry).__name__
            raise RuntimeError(
                f"agent-contracts at {path}[{agent_name!r}] must be dict, got {type_name}"
            )
        for field in (_FIELD_ROLE, _FIELD_SYSTEM_PROMPT):
            if field in entry and not isinstance(entry[field], str):
                raise RuntimeError(f"agent-contracts at {path}[{agent_name!r}].{field} must be str")
        if _FIELD_TOOLS in entry:
            tools = entry[_FIELD_TOOLS]
            if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
                raise RuntimeError(
                    f"agent-contracts at {path}[{agent_name!r}].tools must be list[str]"
                )


def _coerce(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract known mutable fields per agent. ``model`` etc. dropped
    (Tier 2 guardrail)."""
    result: dict[str, dict[str, Any]] = {}
    for agent_name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        kept: dict[str, Any] = {}
        for field in _MUTABLE_FIELDS:
            if field in entry:
                value = entry[field]
                if field == _FIELD_TOOLS and isinstance(value, list):
                    kept[field] = [t for t in value if isinstance(t, str)]
                elif isinstance(value, str):
                    kept[field] = value
        if kept:
            result[agent_name] = kept
    return result


def apply_agent_contracts_policy(
    agent_def: Any,
    policy: dict[str, dict[str, Any]] | None,
) -> Any:
    """Return a (possibly modified) copy of ``agent_def`` with policy
    overrides applied — role / system_prompt / tools only. ``model``
    field is never touched (Tier 2 guardrail).

    ``policy is None`` or agent name absent from policy → original
    ``agent_def`` returned unchanged (no behavior change).
    """
    if not policy:
        return agent_def
    name = getattr(agent_def, "name", None)
    if not isinstance(name, str) or name not in policy:
        return agent_def
    entry = policy[name]
    if not entry:
        return agent_def
    # Pydantic BaseModel.model_copy(update=...) returns a new instance.
    # Filter overrides to mutable fields only — defensive even though
    # ``_coerce`` already drops everything else.
    overrides = {k: v for k, v in entry.items() if k in _MUTABLE_FIELDS}
    if not overrides:
        return agent_def
    # CSP-1 fix-up (Codex MCP MEDIUM #1) — an agent that declares a
    # ``toolkit:`` will have its ``tools`` field shadowed by the
    # toolkit's resolved set inside ``filter_handlers``. A policy entry
    # that mutates ``tools`` on a toolkit-declaring agent therefore
    # silently does nothing. Warn so operators notice rather than
    # debugging a no-op override later.
    agent_toolkit: str = str(getattr(agent_def, "toolkit", "") or "")
    if _FIELD_TOOLS in overrides and agent_toolkit:
        log.warning(
            "agent_contracts_policy: agent %r declares toolkit=%r; "
            "the policy's ``tools`` override is shadowed at spawn time "
            "(toolkit takes precedence in filter_handlers). Either "
            "remove the ``tools`` override or add a ``toolkit`` field "
            "to the policy entry.",
            name,
            agent_toolkit,
        )
    if hasattr(agent_def, "model_copy"):
        return agent_def.model_copy(update=overrides)
    # Fallback for non-BaseModel doubles (test stubs, dicts) —
    # deep-copy + setattr / item-set.
    new_def = copy.deepcopy(agent_def)
    for k, v in overrides.items():
        if isinstance(new_def, dict):
            new_def[k] = v
        else:
            setattr(new_def, k, v)
    return new_def


__all__ = ["apply_agent_contracts_policy"]
