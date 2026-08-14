"""Tool policy SoT reader — ADR-012 S0a, dead slot 살리기.

Applies an optional tool policy while the agent builds its candidate tool set.

**SoT schema** (모든 필드 optional):

.. code-block:: json

    {
      "allowed_tools": ["bash", "read"],    # whitelist (선언되면 다른 도구 제외)
      "forbidden_tools": ["write"],          # blacklist (선언되면 그 도구 제외)
      "priority_order": ["bash", "read"]    # 호출 우선순위 (앞쪽이 먼저, 없는 것은 뒤)
    }

빈 정책 / 누락 / 부적합 schema → no-op (현재 행동 유지). 정책이 ALIVE
신호를 내려면 셋 중 하나라도 비어 있지 않아야 한다.

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

# Schema field 이름들 — 외부 정책 파일과 1:1 mapping.
_FIELD_ALLOWED = "allowed_tools"
_FIELD_FORBIDDEN = "forbidden_tools"
_FIELD_PRIORITY = "priority_order"
_ALL_FIELDS = frozenset({_FIELD_ALLOWED, _FIELD_FORBIDDEN, _FIELD_PRIORITY})


def _load_tool_policy_override(
    *,
    sources: PolicySourcePaths | None = None,
) -> dict[str, list[str]] | None:
    """Return the active tool policy dict, or ``None`` when no SoT applies.

    Resolution order — see module docstring (3-layer chain).
    """
    return load_policy_source(
        sources=sources,
        label="tool policy",
        validate_strict=lambda data, path: _validate_schema(data, path, strict=True),
        validate_graceful=lambda data, path: _validate_schema(data, path, strict=False),
        coerce=_coerce,
    )


def _validate_schema(data: Any, path: Path, *, strict: bool) -> None:
    """``data`` 가 ``dict`` 모양인지 + 알려진 field 가 ``list[str]`` 또는
    ``str`` (comma/newline-separated) 인지 확인.

    Product writers may serialize ``dict[str, str]`` rather than lists.
    Therefore the reader also accepts comma/newline-separated strings and
    normalizes them to lists. Unknown fields remain forward-compatible."""
    if not isinstance(data, dict):
        raise RuntimeError(f"tool policy at {path} must be a dict")
    for key in _ALL_FIELDS:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, list):
            if not all(isinstance(x, str) for x in value):
                raise RuntimeError(
                    f"tool policy at {path} field {key!r} list must contain only str"
                )
        elif not isinstance(value, str):
            got = type(value).__name__
            raise RuntimeError(
                f"tool policy at {path} field {key!r} must be list[str] or str; got {got}"
            )


def _coerce(data: dict[str, Any]) -> dict[str, list[str]]:
    """알려진 3 field 만 추출 + string payload 는 comma/newline split.

    Returns ``dict[str, list[str]]`` 정규화된 형태 — ``apply_tool_policy``
    의 입력 contract 일치."""
    result: dict[str, list[str]] = {}
    for key in _ALL_FIELDS:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, list):
            result[key] = list(value)
        elif isinstance(value, str):
            # comma 또는 newline separator. mutation 의 string payload 정규화.
            items = [s.strip() for s in value.replace("\n", ",").split(",") if s.strip()]
            result[key] = items
    return result


def apply_tool_policy(
    tools: list[dict[str, Any]],
    policy: dict[str, list[str]] | None,
) -> list[dict[str, Any]]:
    """Apply ``policy`` to ``tools``. ``policy is None`` → ``tools`` 그대로.

    Order of application:

    1. **forbidden_tools** — 정책에 등장하는 이름의 도구 제외.
    2. **allowed_tools** — 선언됐다면, 그 안에 등장하는 이름만 유지
       (whitelist). 빈 list 면 모든 도구 제외 (의도된 동작 — 정책으로
       완전 차단 가능).
    3. **priority_order** — 정책에 등장하는 순서대로 재정렬. 정책에
       없는 도구는 그 뒤에 원래 상대 순서 유지.

    각 도구 dict 은 ``"name"`` 키를 갖는다는 contract (Anthropic Tool
    Use schema). 이름이 없는 도구는 정책 영향을 받지 않고 그대로 통과.
    """
    if policy is None:
        return tools
    forbidden = set(policy.get(_FIELD_FORBIDDEN, []))
    allowed: list[str] | None = policy.get(_FIELD_ALLOWED) if _FIELD_ALLOWED in policy else None
    priority = policy.get(_FIELD_PRIORITY, [])

    filtered: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str):
            filtered.append(tool)
            continue
        if name in forbidden:
            continue
        if allowed is not None and name not in allowed:
            continue
        filtered.append(tool)

    # Self-lock guard (Codex MCP catch, 2026-05-21) — 정책이 모든 도구를
    # 제거하면 에이전트가 응답을 만들 수 있는 수단이 없음. 의도된 동작
    # (정책으로 완전 차단) 일 수도 있으나 운영자가 실수로 빈 list 를
    # 입력하면 silent failure. WARNING 으로 알림.
    if tools and not filtered:
        log.warning(
            "tool policy filtered out all %d tools — agent has zero tools available. "
            "이는 의도된 동작 (정책으로 완전 차단) 일 수 있으나, 실수로 "
            "빈 allowed_tools 를 설정한 경우라면 정책을 확인하세요.",
            len(tools),
        )

    if not priority:
        return filtered

    priority_index = {name: i for i, name in enumerate(priority)}
    last = len(priority_index)

    def _sort_key(tool: dict[str, Any]) -> int:
        name = tool.get("name")
        if not isinstance(name, str):
            return last
        return priority_index.get(name, last)

    return sorted(filtered, key=_sort_key)


__all__ = ["apply_tool_policy"]
