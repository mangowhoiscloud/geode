"""Layer 1: Cortex — MonoLake data retrieval (fixture-based).

Supports optional ContextAssembler injection for 3-tier memory merge.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from geode.fixtures import FIXTURE_MAP, load_fixture
from geode.state import GeodeState

if TYPE_CHECKING:
    from geode.memory.context import ContextAssembler

log = logging.getLogger(__name__)

# Re-export for CLI /list command
_FIXTURE_MAP = FIXTURE_MAP

# Module-level context assembler (set by runtime wiring)
_context_assembler: ContextAssembler | None = None


def set_context_assembler(assembler: ContextAssembler | None) -> None:
    """Inject a ContextAssembler for 3-tier memory merge in cortex node."""
    global _context_assembler  # noqa: PLW0603
    _context_assembler = assembler


def cortex_node(state: GeodeState) -> dict:
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

        # 3-tier memory context assembly (if available)
        if _context_assembler:
            session_id = state.get("session_id", "")
            if session_id:
                memory_context = _context_assembler.assemble(session_id, ip_name)
                _context_assembler.mark_assembled(memory_context.get("_assembled_at"))
                result["memory_context"] = memory_context

        return result
    except Exception as exc:
        log.error("Node cortex failed: %s", exc)
        return {"errors": [f"cortex: {exc}"]}
