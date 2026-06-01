"""Reflection policy SoT reader — ADR-012 S0b, dead slot 살리기.

5축 mutation 의 ``reflection`` slot 은 PR-6 시점부터 SoT 파일
(`autoresearch/reflection.json`) 만 정의되고 인퍼런스 reader 가 부재였다.
``core/agent/loop/_reflection.py`` 의 ``_REFLECTION_TOOL`` schema 와
``_SYSTEM_PROMPT`` 가 module-level constant 로 hardcoded — `reflection.json`
미연결 (PR-AUDIT-5SLOT 2026-05-21 진단).

이 모듈은 S0a (`tool_policy.py`) 의 패턴을 그대로 차용해 ``reflection.json``
의 정책을 reflection LLM 호출 직전에 적용한다.

**SoT schema** (두 field 모두 optional):

.. code-block:: json

    {
      "description": "...",      # _REFLECTION_TOOL["description"] override
      "system_prompt": "..."     # _SYSTEM_PROMPT override
    }

빈 정책 / 누락 / 부적합 schema → no-op (현재 행동 유지). ``input_schema``
는 mutate 대상이 아님 — record_reflection 의 typed payload contract 는
유지 (`hypotheses` / `confidence` / `next_action_hint`).

**Resolution order** (PR-BACKFILL-SOT 2026-05-21, shared
:mod:`core.self_improving.loop.sot_resolution`):

1. ``GEODE_REFLECTION_POLICY_OVERRIDE`` env var — explicit override.

   - With ``GEODE_REFLECTION_POLICY_STRICT=1`` (audit subprocess): strict.
   - Without strict flag (operator daily): graceful (no fall-through).

2. ``~/.geode/autoresearch/handoff/reflection.json`` — operator-local, graceful.
3. ``state/autoresearch/policies/reflection.json`` — in-repo, graceful.
4. ``None`` — no-op.

**Read-Write parity** (S0a Codex MCP lesson): ``write_policy()`` 가
``dict[str, str]`` 만 직렬화하므로 reader 는 string payload 그대로 수용.
S0a 와 달리 reflection 의 두 field 는 본질적으로 string 이라 split
정규화는 불필요.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_REFLECTION_POLICY_PATH, OPERATOR_LOCAL_REFLECTION_POLICY_PATH
from core.self_improving.loop.sot_resolution import resolve_sot

log = logging.getLogger(__name__)

_REFLECTION_POLICY_OVERRIDE_ENV = "GEODE_REFLECTION_POLICY_OVERRIDE"

_REFLECTION_POLICY_SOT_PATH = GLOBAL_REFLECTION_POLICY_PATH
"""Cross-process in-repo SoT path (S0b, 2026-05-21). module-local alias 로
테스트가 monkeypatch 가능 (path-literal guard contract)."""

_OPERATOR_LOCAL_REFLECTION_POLICY_PATH = OPERATOR_LOCAL_REFLECTION_POLICY_PATH
"""Operator-local SoT path (PR-BACKFILL-SOT, 2026-05-21). Module-local
alias kept for monkeypatch in tests."""


_FIELD_DESCRIPTION = "description"
_FIELD_SYSTEM_PROMPT = "system_prompt"
_ALL_FIELDS = frozenset({_FIELD_DESCRIPTION, _FIELD_SYSTEM_PROMPT})


def _load_reflection_policy_override() -> dict[str, str] | None:
    """Return active reflection policy, or ``None`` when no SoT applies.

    Resolution order — see module docstring (3-layer chain).
    """
    selection = resolve_sot(
        env_var=_REFLECTION_POLICY_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_REFLECTION_POLICY_PATH,
        in_repo=_REFLECTION_POLICY_SOT_PATH,
    )
    if selection is None:
        return None
    if selection.strict:
        return _strict_load(selection.path)
    return _graceful_load(selection.path)


def _strict_load(path: Path) -> dict[str, str]:
    """Audit-subprocess path: schema 실패 시 ``RuntimeError`` (fail-fast)."""
    if not path.is_file():
        raise RuntimeError(f"{_REFLECTION_POLICY_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{_REFLECTION_POLICY_OVERRIDE_ENV}={path} load failed: {exc}") from exc
    _validate_schema(data, path)
    return _coerce(data)


def _graceful_load(path: Path) -> dict[str, str] | None:
    """Daily-run path: schema 실패 시 WARNING + ``None``."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.warning("reflection policy SoT at %s is unreadable; ignoring", path)
        return None
    try:
        _validate_schema(data, path)
    except RuntimeError as exc:
        log.warning("reflection policy SoT at %s schema invalid: %s; ignoring", path, exc)
        return None
    return _coerce(data)


def _validate_schema(data: Any, path: Path) -> None:
    """``data`` 가 ``dict`` 모양 + 알려진 field 는 모두 ``str`` 이어야 함.

    Unknown field 는 무시 (forward-compatible)."""
    if not isinstance(data, dict):
        raise RuntimeError(f"reflection policy at {path} must be a dict")
    for key in _ALL_FIELDS:
        if key in data and not isinstance(data[key], str):
            got = type(data[key]).__name__
            raise RuntimeError(f"reflection policy at {path} field {key!r} must be str; got {got}")


def _coerce(data: dict[str, Any]) -> dict[str, str]:
    """알려진 2 field 만 추출. 빈 string 은 ``None`` 처럼 취급되도록 제외."""
    return {key: data[key] for key in _ALL_FIELDS if data.get(key)}


def apply_reflection_policy(
    tool: dict[str, Any],
    system_prompt: str,
    policy: dict[str, str] | None,
) -> tuple[dict[str, Any], str]:
    """Apply ``policy`` to the reflection tool definition and system prompt.

    Returns the (possibly overridden) ``(tool, system_prompt)`` tuple.
    ``policy is None`` → 입력 그대로.

    - ``description`` field 가 정책에 있으면 tool["description"] override.
    - ``system_prompt`` field 가 정책에 있으면 system_prompt override.
    - ``input_schema`` 와 ``name`` 은 mutate 대상이 아님 — record_reflection
      의 typed payload contract 보존.

    Tool dict 은 deep-copy 후 mutate 해서 caller 의 module-level constant
    가 오염되지 않도록 함.
    """
    if policy is None:
        return tool, system_prompt
    new_description = policy.get(_FIELD_DESCRIPTION)
    new_system_prompt = policy.get(_FIELD_SYSTEM_PROMPT)
    if not new_description and not new_system_prompt:
        return tool, system_prompt
    new_tool = copy.deepcopy(tool)
    if new_description:
        new_tool["description"] = new_description
    final_system = new_system_prompt if new_system_prompt else system_prompt
    return new_tool, final_system


__all__ = ["apply_reflection_policy"]
