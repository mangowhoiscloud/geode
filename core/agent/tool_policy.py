"""Tool policy SoT reader — ADR-012 S0a, dead slot 살리기.

5축 mutation 의 ``tool_policy`` slot 은 PR-6 시점부터 SoT 파일
(`autoresearch/tool-policy.json`) 만 정의되고 인퍼런스 reader 가 부재였다
(PR-AUDIT-5SLOT 2026-05-21 진단). 이 모듈은 ``wrapper-sections.json``
reader 의 패턴을 그대로 차용해 ``tool-policy.json`` 의 정책을 도구 후보
필터링 단계에서 적용한다.

**SoT schema** (모든 필드 optional):

.. code-block:: json

    {
      "allowed_tools": ["bash", "read"],    # whitelist (선언되면 다른 도구 제외)
      "forbidden_tools": ["write"],          # blacklist (선언되면 그 도구 제외)
      "priority_order": ["bash", "read"]    # 호출 우선순위 (앞쪽이 먼저, 없는 것은 뒤)
    }

빈 정책 / 누락 / 부적합 schema → no-op (현재 행동 유지). 정책이 ALIVE
신호를 내려면 셋 중 하나라도 비어 있지 않아야 한다.

**Resolution order** (PR-BACKFILL-SOT 2026-05-21, shared
:mod:`core.self_improving_loop.sot_resolution`):

1. ``GEODE_TOOL_POLICY_OVERRIDE`` env var — explicit override.

   - With ``GEODE_TOOL_POLICY_STRICT=1`` (audit subprocess): strict load,
     RuntimeError on missing/unparseable (fail-fast for mutation audit).
   - Without strict flag (operator daily): graceful load, returns ``None``
     on issue (no fall-through to lower layers; env is authoritative).

2. ``~/.geode/self-improving-loop/tool-policy.json`` — operator-local SoT,
   graceful load (per-machine override outside the in-repo ratchet).
3. ``autoresearch/state/policies/tool-policy.json`` — in-repo,
   ratchet-tracked, graceful load (default policy site).
4. ``None`` — no-op (도구 목록 그대로).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_TOOL_POLICY_PATH, OPERATOR_LOCAL_TOOL_POLICY_PATH
from core.self_improving_loop.sot_resolution import resolve_sot

log = logging.getLogger(__name__)

_TOOL_POLICY_OVERRIDE_ENV = "GEODE_TOOL_POLICY_OVERRIDE"

_TOOL_POLICY_SOT_PATH = GLOBAL_TOOL_POLICY_PATH
"""Cross-process in-repo SoT path shared with :mod:`autoresearch.train`
(S0a, 2026-05-21). Module-local alias kept for monkeypatch in tests."""

_OPERATOR_LOCAL_TOOL_POLICY_PATH = OPERATOR_LOCAL_TOOL_POLICY_PATH
"""Operator-local SoT path (PR-BACKFILL-SOT, 2026-05-21). Module-local
alias kept for monkeypatch in tests."""


# Schema field 이름들 — 외부 정책 파일과 1:1 mapping.
_FIELD_ALLOWED = "allowed_tools"
_FIELD_FORBIDDEN = "forbidden_tools"
_FIELD_PRIORITY = "priority_order"
_ALL_FIELDS = frozenset({_FIELD_ALLOWED, _FIELD_FORBIDDEN, _FIELD_PRIORITY})


def _load_tool_policy_override() -> dict[str, list[str]] | None:
    """Return the active tool policy dict, or ``None`` when no SoT applies.

    Resolution order — see module docstring (3-layer chain).
    """
    selection = resolve_sot(
        env_var=_TOOL_POLICY_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_TOOL_POLICY_PATH,
        in_repo=_TOOL_POLICY_SOT_PATH,
    )
    if selection is None:
        return None
    if selection.strict:
        return _strict_load(selection.path)
    return _graceful_load(selection.path)


def _strict_load(path: Path) -> dict[str, list[str]]:
    """Audit-subprocess path: schema 실패 시 ``RuntimeError`` (fail-fast)."""
    if not path.is_file():
        raise RuntimeError(f"{_TOOL_POLICY_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{_TOOL_POLICY_OVERRIDE_ENV}={path} load failed: {exc}") from exc
    _validate_schema(data, path, strict=True)
    return _coerce(data)


def _graceful_load(path: Path) -> dict[str, list[str]] | None:
    """Daily-run path: schema 실패 시 WARNING + ``None`` (graceful degrade).

    Asymmetric handling vs ``_strict_load`` is intentional — 동일 사유
    (``wrapper-sections.json`` reader 의 docstring 참조): 일상 ``geode``
    호출이 손상된 self-improving-loop artifact 때문에 hard-fail 하면 안 됨."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.warning("tool policy SoT at %s is unreadable; ignoring", path)
        return None
    try:
        _validate_schema(data, path, strict=False)
    except RuntimeError as exc:
        log.warning("tool policy SoT at %s schema invalid: %s; ignoring", path, exc)
        return None
    return _coerce(data)


def _validate_schema(data: Any, path: Path, *, strict: bool) -> None:
    """``data`` 가 ``dict`` 모양인지 + 알려진 field 가 ``list[str]`` 또는
    ``str`` (comma/newline-separated) 인지 확인.

    Read-write parity (Codex MCP catch, 2026-05-21) — ``write_policy()``
    (`core/self_improving_loop/policies.py:194`) 는 SoT 파일을
    ``dict[str, str]`` 로만 직렬화한다 (mutation 의 ``new_value`` 가
    string). 따라서 reader 는 ``list[str]`` 뿐 아니라 **mutation 으로
    쓰인 string payload 도 수용** 해야 한다 — comma 또는 newline 으로
    split 해서 list 로 정규화. Unknown field 는 무시 (forward-compatible)."""
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
