"""Shared utilities used by multiple tool-handler groups."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


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
        result: dict[str, Any] = tool_class().execute(**kwargs)
        return result
    except (KeyError, TypeError) as exc:
        param = str(exc).strip("'\"")
        return _clarify(
            tool_class.__name__,
            [param],
            f"'{param}' 값을 알려주세요.",
        )


def install_domain_tool_handlers(handlers: dict[str, Any]) -> None:
    """Merge the active domain's tool handlers into ``handlers``.

    Domains implement ``DomainPort.register_tool_handlers(handlers)`` (v2,
    optional). When absent or no domain is registered, this is a no-op.
    """
    try:
        from core.domains.port import get_domain_or_none

        domain = get_domain_or_none()
        if domain is None:
            return
        register = getattr(domain, "register_tool_handlers", None)
        if callable(register):
            register(handlers)
    except Exception:
        log.debug("Domain tool-handler registration skipped", exc_info=True)
