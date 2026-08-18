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

Candidate paths are supplied by product composition. Selection is explicit
override → operator-local → packaged default → no-op; an explicit override is
authoritative and may request strict loading.

**Frontier**: OpenAI function calling docs — "clearer descriptions yield
more accurate selection" + Anthropic tool-use guide.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

from core.config.policy_source import PolicySourcePaths, load_policy_source

log = logging.getLogger(__name__)

_FIELD_DESCRIPTION = "description"
_FIELD_HINTS = "hints"


def _load_tool_descriptions_override(
    *,
    sources: PolicySourcePaths | None = None,
) -> dict[str, dict[str, Any]] | None:
    """Return active tool-descriptions override, or ``None`` if no SoT.

    Resolution order — see module docstring (3-layer chain).
    """
    return load_policy_source(
        sources=sources,
        label="tool-descriptions",
        validate_strict=_validate_schema,
        validate_graceful=_validate_schema,
        coerce=_coerce,
    )


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
