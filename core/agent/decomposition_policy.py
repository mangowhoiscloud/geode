"""Decomposition policy SoT reader — ADR-012 S0c, dead slot 살리기.

5축 mutation 의 ``decomposition`` slot 은 PR-6 시점부터 SoT 파일
(`autoresearch/decomposition.json`) 만 정의되고 인퍼런스 reader 가 부재였다.
``core/orchestration/goal_decomposer.py:_llm_decompose:241`` 의
``load_prompt("decomposer", "system")`` 는 별도 prompt SoT 에서 system
prompt 를 로드하지만 ``decomposition.json`` 과는 미연결 (PR-AUDIT-5SLOT
2026-05-21 진단).

이 모듈은 S0a/S0b 의 패턴을 그대로 차용해 ``decomposition.json`` 의
정책을 GoalDecomposer 의 LLM 호출 직전에 적용한다.

**SoT schema** (모든 field optional, string):

.. code-block:: json

    {
      "system_prompt": "...",      # load_prompt("decomposer","system") override
      "prefix": "...",             # default system_prompt 앞에 prefix 추가
      "suffix": "..."              # default system_prompt 뒤에 suffix 추가
    }

빈 정책 / 누락 / 부적합 schema → no-op (load_prompt 결과 그대로 사용).
``system_prompt`` 가 있으면 다른 두 field 는 무시 (override 우선).

**Resolution order** (S0a/S0b 와 동일):

1. ``GEODE_DECOMPOSITION_POLICY_OVERRIDE`` env var — audit subprocess, strict.
2. ``~/.geode/self-improving-loop/decomposition.json`` — daily-run, graceful.
3. ``None`` — no-op.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_DECOMPOSITION_POLICY_PATH

log = logging.getLogger(__name__)

_DECOMPOSITION_POLICY_OVERRIDE_ENV = "GEODE_DECOMPOSITION_POLICY_OVERRIDE"

_DECOMPOSITION_POLICY_SOT_PATH = GLOBAL_DECOMPOSITION_POLICY_PATH
"""Cross-process SoT path (S0c, 2026-05-21). module-local alias 로 테스트
가 monkeypatch 가능 (path-literal guard contract)."""


_FIELD_SYSTEM_PROMPT = "system_prompt"
_FIELD_PREFIX = "prefix"
_FIELD_SUFFIX = "suffix"
_ALL_FIELDS = frozenset({_FIELD_SYSTEM_PROMPT, _FIELD_PREFIX, _FIELD_SUFFIX})


def _load_decomposition_policy_override() -> dict[str, str] | None:
    """Return active decomposition policy, or ``None`` when no override applies.

    Resolution order:

    1. ``GEODE_DECOMPOSITION_POLICY_OVERRIDE`` env var (audit subprocess) — strict.
    2. ``~/.geode/self-improving-loop/decomposition.json`` (daily run) — graceful.
    3. ``None`` — no policy.
    """
    override_path = os.environ.get(_DECOMPOSITION_POLICY_OVERRIDE_ENV)
    if override_path:
        return _strict_load(Path(override_path))
    if _DECOMPOSITION_POLICY_SOT_PATH.is_file():
        return _graceful_load(_DECOMPOSITION_POLICY_SOT_PATH)
    return None


def _strict_load(path: Path) -> dict[str, str]:
    """Audit-subprocess path: schema 실패 시 ``RuntimeError`` (fail-fast)."""
    if not path.is_file():
        raise RuntimeError(f"{_DECOMPOSITION_POLICY_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{_DECOMPOSITION_POLICY_OVERRIDE_ENV}={path} load failed: {exc}"
        ) from exc
    _validate_schema(data, path)
    return _coerce(data)


def _graceful_load(path: Path) -> dict[str, str] | None:
    """Daily-run path: schema 실패 시 WARNING + ``None``."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.warning("decomposition policy SoT at %s is unreadable; ignoring", path)
        return None
    try:
        _validate_schema(data, path)
    except RuntimeError as exc:
        log.warning("decomposition policy SoT at %s schema invalid: %s; ignoring", path, exc)
        return None
    return _coerce(data)


def _validate_schema(data: Any, path: Path) -> None:
    """``data`` 가 ``dict`` + 알려진 field 는 모두 ``str``.

    Unknown field 는 무시 (forward-compatible)."""
    if not isinstance(data, dict):
        raise RuntimeError(f"decomposition policy at {path} must be a dict")
    for key in _ALL_FIELDS:
        if key in data and not isinstance(data[key], str):
            got = type(data[key]).__name__
            raise RuntimeError(
                f"decomposition policy at {path} field {key!r} must be str; got {got}"
            )


def _coerce(data: dict[str, Any]) -> dict[str, str]:
    """알려진 3 field 만 추출. 빈 string 은 drop."""
    return {key: data[key] for key in _ALL_FIELDS if data.get(key)}


def apply_decomposition_policy(
    system_prompt: str,
    policy: dict[str, str] | None,
) -> str:
    """Apply ``policy`` to the decomposer's system prompt.

    ``policy is None`` → 입력 그대로.

    - ``system_prompt`` field 가 정책에 있으면 그것으로 전체 override
      (prefix/suffix 무시 — override 우선).
    - 그렇지 않고 ``prefix`` 가 있으면 default 의 앞에 추가.
    - 그렇지 않고 ``suffix`` 가 있으면 default 의 뒤에 추가.
    - 둘 다 있으면 ``{prefix}\\n\\n{default}\\n\\n{suffix}``.
    """
    if policy is None:
        return system_prompt
    override = policy.get(_FIELD_SYSTEM_PROMPT)
    if override:
        return override
    prefix = policy.get(_FIELD_PREFIX, "")
    suffix = policy.get(_FIELD_SUFFIX, "")
    if not prefix and not suffix:
        return system_prompt
    parts = [p for p in (prefix, system_prompt, suffix) if p]
    return "\n\n".join(parts)


__all__ = ["apply_decomposition_policy"]
