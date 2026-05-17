"""Shared utilities used by multiple tool-handler groups."""

from __future__ import annotations

from typing import Any

from core.async_runtime import run_process_coroutine


def _clarify(
    tool: str,
    missing: list[str],
    hint: str,
    **extra: Any,
) -> dict[str, Any]:
    """Standard clarification response for missing required params."""
    return {
        "error": f"{tool} requires: {', '.join(missing)}",
        "clarification_needed": True,
        "missing": missing,
        "hint": hint,
        **extra,
    }


def _safe_delegate(tool_class: type, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Wrap delegated tool execution -- catch KeyError as clarification."""
    try:
        tool = tool_class()
        aexecute = getattr(tool, "aexecute", None)
        if not callable(aexecute):
            raise TypeError(f"{tool_class.__name__} must implement aexecute()")
        result: dict[str, Any] = run_process_coroutine(aexecute(**kwargs))
        return result
    except (KeyError, TypeError) as exc:
        param = str(exc).strip("'\"")
        return _clarify(
            tool_class.__name__,
            [param],
            f"'{param}' 값을 알려주세요.",
        )
