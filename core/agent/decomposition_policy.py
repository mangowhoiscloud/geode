"""Decomposition policy SoT reader — ADR-012 S0c, dead slot 살리기.

5축 mutation 의 ``decomposition`` slot 은 PR-6 시점부터 SoT 파일
(`autoresearch/decomposition.json`) 만 정의되고 인퍼런스 reader 가 부재였다.
``core/agent/plan.py:decompose_async`` (PR-CL-A1-followup, 2026-05-23 — 이전
``core/orchestration/goal_decomposer.py:_llm_decompose`` 가 호출) 의
``load_prompt("decomposer", "system")`` 는 별도 prompt SoT 에서 system
prompt 를 로드하지만 ``decomposition.json`` 과는 미연결 (PR-AUDIT-5SLOT
2026-05-21 진단).

이 모듈은 S0a/S0b 의 패턴을 그대로 차용해 ``decomposition.json`` 의
정책을 ``decompose_async`` 의 LLM 호출 직전에 적용한다.

**SoT schema** (모든 field optional, string):

.. code-block:: json

    {
      "system_prompt": "...",      # load_prompt("decomposer","system") override
      "prefix": "...",             # default system_prompt 앞에 prefix 추가
      "suffix": "..."              # default system_prompt 뒤에 suffix 추가
    }

빈 정책 / 누락 / 부적합 schema → no-op (load_prompt 결과 그대로 사용).
``system_prompt`` 가 있으면 다른 두 field 는 무시 (override 우선).

**Resolution order** (PR-BACKFILL-SOT 2026-05-21, shared
:mod:`core.self_improving.loop.mutate.sot_resolution`):

1. ``GEODE_DECOMPOSITION_POLICY_OVERRIDE`` env var — explicit override.

   - With ``GEODE_DECOMPOSITION_POLICY_STRICT=1`` (audit subprocess): strict.
   - Without strict flag (operator daily): graceful (no fall-through).

2. ``~/.geode/autoresearch/handoff/decomposition.json`` — operator-local, graceful.
3. ``state/autoresearch/policies/decomposition.json`` — in-repo, graceful.
4. ``None`` — no-op.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.agent.policy_sot import load_policy_sot
from core.paths import (
    GLOBAL_DECOMPOSITION_POLICY_PATH,
    OPERATOR_LOCAL_DECOMPOSITION_POLICY_PATH,
)

log = logging.getLogger(__name__)

_DECOMPOSITION_POLICY_OVERRIDE_ENV = "GEODE_DECOMPOSITION_POLICY_OVERRIDE"

_DECOMPOSITION_POLICY_SOT_PATH = GLOBAL_DECOMPOSITION_POLICY_PATH
"""Cross-process in-repo SoT path (S0c, 2026-05-21). module-local alias 로
테스트가 monkeypatch 가능 (path-literal guard contract)."""

_OPERATOR_LOCAL_DECOMPOSITION_POLICY_PATH = OPERATOR_LOCAL_DECOMPOSITION_POLICY_PATH
"""Operator-local SoT path (PR-BACKFILL-SOT, 2026-05-21). Module-local
alias kept for monkeypatch in tests."""


_FIELD_SYSTEM_PROMPT = "system_prompt"
_FIELD_PREFIX = "prefix"
_FIELD_SUFFIX = "suffix"
_ALL_FIELDS = frozenset({_FIELD_SYSTEM_PROMPT, _FIELD_PREFIX, _FIELD_SUFFIX})


def _load_decomposition_policy_override() -> dict[str, str] | None:
    """Return active decomposition policy, or ``None`` when no SoT applies.

    Resolution order — see module docstring (3-layer chain).
    """
    return load_policy_sot(
        env_var=_DECOMPOSITION_POLICY_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_DECOMPOSITION_POLICY_PATH,
        in_repo=_DECOMPOSITION_POLICY_SOT_PATH,
        label="decomposition policy",
        validate_strict=_validate_schema,
        validate_graceful=_validate_schema,
        coerce=_coerce,
    )


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
