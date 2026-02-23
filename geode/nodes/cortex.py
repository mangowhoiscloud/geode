"""Layer 1: Cortex — MonoLake data retrieval (fixture-based).

Supports optional ContextAssembler injection for 3-tier memory merge.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from geode.fixtures import FIXTURE_MAP, load_fixture
from geode.state import GeodeState

if TYPE_CHECKING:
    from geode.memory.context import ContextAssembler

log = logging.getLogger(__name__)

# Re-export for CLI /list command
_FIXTURE_MAP = FIXTURE_MAP

# Thread-safe context assembler via contextvars (set by runtime wiring)
_context_assembler_ctx: ContextVar[Any] = ContextVar("context_assembler", default=None)


def set_context_assembler(assembler: ContextAssembler | None) -> None:
    """Inject a ContextAssembler for 3-tier memory merge in cortex node."""
    _context_assembler_ctx.set(assembler)


def cortex_node(state: GeodeState) -> dict[str, Any]:
    """Load IP info and MonoLake data from fixtures.

    If a ContextAssembler is configured, also merges 3-tier memory context
    (Organization → Project → Session) into the pipeline state.
    """
    try:
        ip_name = state["ip_name"]
        fixture = load_fixture(ip_name)

        result: dict[str, Any] = {
            "ip_info": fixture["ip_info"],
            "monolake": fixture["monolake"],
        }

        # Adaptive feedback: propagate weak_areas from previous iterations
        # so downstream analysts/evaluators can focus on low-confidence dims
        iteration_history = state.get("iteration_history", [])
        if iteration_history:
            latest = iteration_history[-1]
            weak_areas = latest.get("weak_areas", [])
            if weak_areas:
                log.info("Cortex: previous iteration weak areas — %s", weak_areas)
                result.setdefault("monolake", {})["_weak_areas"] = weak_areas

        # 3-tier memory context assembly (if available)
        assembler = _context_assembler_ctx.get()
        if assembler:
            session_id = state.get("session_id", "")
            if session_id:
                memory_context = assembler.assemble(session_id, ip_name)
                assembler.mark_assembled(memory_context.get("_assembled_at"))
                result["memory_context"] = memory_context

        return result
    except Exception as exc:
        log.error("Node cortex failed: %s", exc)
        return {"errors": [f"cortex: {exc}"]}
