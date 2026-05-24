"""core.hooks.dispatch — small helpers for firing hooks from any layer.

Eliminates the four near-identical ``_fire_hook`` copies that lived in
``tools/memory_tools.py``, ``llm/router.py``, ``llm/provider_dispatch.py``,
and ``cli/__init__.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from core.hooks.system import HookEvent, HookSystem

log = logging.getLogger(__name__)


def fire_hook(
    hooks: HookSystem | None,
    event: HookEvent | str,
    data: dict[str, Any],
) -> None:
    """Fire a hook event with graceful degradation.

    No-op when ``hooks`` is ``None``. Errors from handlers are logged at
    DEBUG and never raised — hook failures must not break the surrounding
    call (LLM dispatch, tool execution, CLI lifecycle).
    """
    if hooks is None:
        return
    try:
        if isinstance(event, str):
            event = HookEvent(event)
        hooks.trigger(event, data)
    except Exception:
        log.debug("Hook trigger failed: %s", event, exc_info=True)
