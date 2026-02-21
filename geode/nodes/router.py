"""Layer 0: Router — Pipeline mode selection."""

from __future__ import annotations

from geode.state import GeodeState


def router_node(state: GeodeState) -> dict:
    """Set pipeline mode (defaults to full_pipeline)."""
    mode = state.get("pipeline_mode", "full_pipeline")
    return {"pipeline_mode": mode}


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
        return "cortex"
