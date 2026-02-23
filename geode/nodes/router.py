"""Layer 0: Router — Pipeline mode selection."""

from __future__ import annotations

import logging
from typing import Any

from geode.state import GeodeState

log = logging.getLogger(__name__)


def router_node(state: GeodeState) -> dict[str, Any]:
    """Set pipeline mode (defaults to full_pipeline)."""
    try:
        mode = state.get("pipeline_mode", "full_pipeline")
        return {"pipeline_mode": mode}
    except Exception as exc:
        log.error("Node router failed: %s", exc)
        return {"errors": [f"router: {exc}"]}


def route_after_router(state: GeodeState) -> str:
    """Conditional edge: decide next node based on pipeline mode."""
    mode = state.get("pipeline_mode", "full_pipeline")
    if mode in ("cortex_only", "discovery", "analysis", "full_pipeline"):
        return "cortex"
    elif mode == "evaluation":
        return "evaluators"
    elif mode == "scoring":
        return "scoring"
    else:
        log.warning("Unknown pipeline_mode '%s', defaulting to cortex", mode)
        return "cortex"
