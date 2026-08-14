"""Decomposition policy SoT reader — ADR-012 S0c, dead slot 살리기.

Applies an optional decomposition policy immediately before
``core.agent.plan.decompose_async`` sends its LLM request.

**SoT schema** (모든 field optional, string):

.. code-block:: json

    {
      "system_prompt": "...",      # load_prompt("decomposer","system") override
      "prefix": "...",             # default system_prompt 앞에 prefix 추가
      "suffix": "..."              # default system_prompt 뒤에 suffix 추가
    }

빈 정책 / 누락 / 부적합 schema → no-op (load_prompt 결과 그대로 사용).
``system_prompt`` 가 있으면 다른 두 field 는 무시 (override 우선).

Candidate paths are supplied by product composition. Selection is explicit
override → operator-local → packaged default → no-op; an explicit override is
authoritative and may request strict loading.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.config.policy_source import PolicySourcePaths, load_policy_source

log = logging.getLogger(__name__)

_FIELD_SYSTEM_PROMPT = "system_prompt"
_FIELD_PREFIX = "prefix"
_FIELD_SUFFIX = "suffix"
_ALL_FIELDS = frozenset({_FIELD_SYSTEM_PROMPT, _FIELD_PREFIX, _FIELD_SUFFIX})


def _load_decomposition_policy_override(
    *,
    sources: PolicySourcePaths | None = None,
) -> dict[str, str] | None:
    """Return active decomposition policy, or ``None`` when no SoT applies.

    Resolution order — see module docstring (3-layer chain).
    """
    return load_policy_source(
        sources=sources,
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
