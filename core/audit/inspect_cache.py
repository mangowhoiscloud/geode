"""Best-effort access to inspect_ai's generate cache."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def purge_inspect_cache() -> bool:
    """Clear inspect_ai's generate cache when the optional extra is installed."""
    try:
        from inspect_ai.model import cache_clear, cache_path
    except ImportError:
        log.warning("inspect_ai is not installed; skipping cache purge")
        return False
    try:
        target = cache_path()
        cleared = cache_clear()
    except Exception as exc:  # pragma: no cover - inspect_ai internals
        log.warning("inspect_ai cache purge failed: %s", exc)
        return False
    log.info("cleared inspect_ai generate cache at %s (cache_clear=%s)", target, cleared)
    return True
