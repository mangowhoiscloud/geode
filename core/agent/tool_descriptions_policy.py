"""Tool descriptions SoT reader — ADR-013 T1, JSON mutation surface.

ADR-012 의 S0a 검증된 패턴 (JSON SoT + reader + dispatcher) 을 그대로
적용한 첫 ADR-013 표면. mutator 가 ``tool-descriptions.json`` 의
``{tool_name: {description: str, hints: [str]}}`` 를 mutate → 도구 후보
선택 정확도 ↑ → Petri 17-dim 의 ``broken_tool_use`` (유일한 양의 압력
dim) 직접 영향.

**SoT schema** (모든 entry optional):

.. code-block:: json

    {
      "bash": {
        "description": "Execute bash commands with timeout + sandbox.",
        "hints": ["Quote file paths with spaces", "Avoid -i flag"]
      },
      "read": {
        "description": "Read file from local filesystem.",
        "hints": ["Use offset+limit for large files"]
      }
    }

빈 entry / 누락 tool / 부적합 schema → no-op (default description 유지).

**Resolution order** (PR-BACKFILL-SOT 2026-05-21, shared
:mod:`core.self_improving.loop.sot_resolution`):

1. ``GEODE_TOOL_DESCRIPTIONS_OVERRIDE`` env var — explicit override.

   - With ``GEODE_TOOL_DESCRIPTIONS_STRICT=1`` (audit subprocess): strict.
   - Without strict flag (operator daily): graceful (no fall-through).

2. ``~/.geode/autoresearch/handoff/tool-descriptions.json`` — operator-local, graceful.
3. ``state/autoresearch/policies/tool-descriptions.json`` — in-repo, graceful.
4. ``None`` — no-op (default description 사용).

**Frontier**: OpenAI function calling docs — "clearer descriptions yield
more accurate selection" + Anthropic tool-use guide.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_TOOL_DESCRIPTIONS_PATH, OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH
from core.self_improving.loop.sot_resolution import resolve_sot

log = logging.getLogger(__name__)

_TOOL_DESCRIPTIONS_OVERRIDE_ENV = "GEODE_TOOL_DESCRIPTIONS_OVERRIDE"

_TOOL_DESCRIPTIONS_SOT_PATH = GLOBAL_TOOL_DESCRIPTIONS_PATH
"""Cross-process in-repo SoT path (T1, 2026-05-21). module-local alias."""

_OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH = OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH
"""Operator-local SoT path (PR-BACKFILL-SOT, 2026-05-21). Module-local
alias kept for monkeypatch in tests."""


_FIELD_DESCRIPTION = "description"
_FIELD_HINTS = "hints"


def _load_tool_descriptions_override() -> dict[str, dict[str, Any]] | None:
    """Return active tool-descriptions override, or ``None`` if no SoT.

    Resolution order — see module docstring (3-layer chain).
    """
    selection = resolve_sot(
        env_var=_TOOL_DESCRIPTIONS_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH,
        in_repo=_TOOL_DESCRIPTIONS_SOT_PATH,
    )
    if selection is None:
        return None
    if selection.strict:
        return _strict_load(selection.path)
    return _graceful_load(selection.path)


def _strict_load(path: Path) -> dict[str, dict[str, Any]]:
    """Audit-subprocess path: schema 실패 시 ``RuntimeError`` (fail-fast)."""
    if not path.is_file():
        raise RuntimeError(f"{_TOOL_DESCRIPTIONS_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{_TOOL_DESCRIPTIONS_OVERRIDE_ENV}={path} load failed: {exc}") from exc
    _validate_schema(data, path)
    return _coerce(data)


def _graceful_load(path: Path) -> dict[str, dict[str, Any]] | None:
    """Daily-run path: schema 실패 시 WARNING + ``None``."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.warning("tool-descriptions SoT at %s is unreadable; ignoring", path)
        return None
    try:
        _validate_schema(data, path)
    except RuntimeError as exc:
        log.warning("tool-descriptions SoT at %s schema invalid: %s; ignoring", path, exc)
        return None
    return _coerce(data)


def _validate_schema(data: Any, path: Path) -> None:
    """``data`` 가 ``dict[str, dict[str, str|list[str]]]`` 모양인지.

    Per-tool entry 는 ``description`` (str) 또는 ``hints`` (list[str]) 만
    포함. Unknown field 무시 (forward-compatible).
    """
    if not isinstance(data, dict):
        raise RuntimeError(f"tool-descriptions at {path} must be a dict")
    for tool_name, entry in data.items():
        if not isinstance(tool_name, str):
            type_name = type(tool_name).__name__
            raise RuntimeError(f"tool-descriptions at {path} key must be str, got {type_name}")
        if not isinstance(entry, dict):
            type_name = type(entry).__name__
            raise RuntimeError(
                f"tool-descriptions at {path}[{tool_name!r}] must be dict, got {type_name}"
            )
        if _FIELD_DESCRIPTION in entry and not isinstance(entry[_FIELD_DESCRIPTION], str):
            raise RuntimeError(
                f"tool-descriptions at {path}[{tool_name!r}].description must be str"
            )
        if _FIELD_HINTS in entry:
            hints = entry[_FIELD_HINTS]
            if not isinstance(hints, list) or not all(isinstance(h, str) for h in hints):
                raise RuntimeError(
                    f"tool-descriptions at {path}[{tool_name!r}].hints must be list[str]"
                )


def _coerce(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """알려진 field 만 추출 — entry 별 description / hints 만 보존."""
    result: dict[str, dict[str, Any]] = {}
    for tool_name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        kept: dict[str, Any] = {}
        if _FIELD_DESCRIPTION in entry:
            kept[_FIELD_DESCRIPTION] = entry[_FIELD_DESCRIPTION]
        if _FIELD_HINTS in entry:
            kept[_FIELD_HINTS] = list(entry[_FIELD_HINTS])
        if kept:
            result[tool_name] = kept
    return result


def apply_tool_descriptions_policy(
    tools: list[dict[str, Any]],
    policy: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Apply ``policy`` to ``tools`` — override description text + append hints.

    ``policy is None`` → ``tools`` 그대로. 각 tool 의 ``description`` 이
    policy 에 있으면 교체. ``hints`` 가 있으면 description 끝에 줄바꿈
    뒤에 append (``Hints:\\n- hint1\\n- hint2``).

    Tools dict 은 deep-copy 후 mutate — caller 의 module-level constant
    오염 방지 (S0b 패턴).
    """
    if policy is None:
        return tools
    out: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or name not in policy:
            out.append(tool)
            continue
        new_tool = copy.deepcopy(tool)
        entry = policy[name]
        if _FIELD_DESCRIPTION in entry:
            new_tool["description"] = entry[_FIELD_DESCRIPTION]
        if _FIELD_HINTS in entry:
            hints = entry[_FIELD_HINTS]
            if hints:
                hint_block = "\n\nHints:\n" + "\n".join(f"- {h}" for h in hints)
                base = new_tool.get("description", "")
                new_tool["description"] = f"{base}{hint_block}" if base else hint_block.lstrip()
        out.append(new_tool)
    return out


__all__ = ["apply_tool_descriptions_policy"]
