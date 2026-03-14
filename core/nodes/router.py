"""Layer 0: Router — Pipeline mode selection + data loading.

Combines routing with fixture loading and 3-tier memory assembly.
Formerly split across router (mode) and cortex (data), now unified
for simpler topology: router → signals → analysts → ...
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from core.fixtures import load_fixture
from core.state import GeodeState

if TYPE_CHECKING:
    from core.memory.context import ContextAssembler

log = logging.getLogger(__name__)

# Thread-safe context assembler via contextvars (set by runtime wiring)
_context_assembler_ctx: ContextVar[Any] = ContextVar("context_assembler", default=None)


def set_context_assembler(assembler: ContextAssembler | None) -> None:
    """Inject a ContextAssembler for 3-tier memory merge."""
    _context_assembler_ctx.set(assembler)


def router_node(state: GeodeState) -> dict[str, Any]:
    """Route pipeline mode + load fixture data + assemble memory context.

    1. Determine pipeline_mode (prospect override for non-gamified IPs)
    2. Load IP fixture data (ip_info, monolake) from JSON fixtures
    3. Generate session_id and assemble 3-tier memory context if wired
    """
    try:
        mode = state.get("pipeline_mode", "full_pipeline")
        ip_name = state["ip_name"]
        ip_type = state.get("ip_type", "gamified")

        # Route 2: prospect IPs use 9-axis evaluation
        if ip_type == "prospect" and mode == "full_pipeline":
            mode = "prospect"

        # Load fixture data (graceful degradation for unknown IPs)
        try:
            fixture = load_fixture(ip_name)
            ip_info = fixture["ip_info"]
            monolake = fixture["monolake"]
            is_external = False
        except ValueError:
            log.info("No fixture for '%s' — using external data mode", ip_name)
            ip_info = {
                "ip_name": ip_name,
                "media_type": "unknown",
                "release_year": 0,
                "studio": "unknown",
                "genre": "unknown",
                "synopsis": "",
                "proof_of_game": "none",
                "franchise_size": 0,
                "ip_age_years": 0,
            }
            monolake = {}
            is_external = True

        result: dict[str, Any] = {
            "pipeline_mode": mode,
            "ip_info": ip_info,
            "monolake": monolake,
        }

        # External IPs: cap feedback loop to 1 iteration.
        # Re-running with the same web search data won't improve confidence.
        if is_external:
            result["max_iterations"] = 1

        # Generate session_id for memory context (fixes GAP-005)
        session_id = state.get("session_id", "")
        if not session_id:
            normalized = ip_name.lower().replace(" ", "_")
            session_id = f"entity:{normalized}:{uuid.uuid4().hex[:8]}"
            result["session_id"] = session_id

        # 3-tier memory context assembly (if ContextAssembler is wired)
        assembler = _context_assembler_ctx.get()
        if assembler and session_id:
            memory_context = assembler.assemble(session_id, ip_name)
            assembler.mark_assembled(memory_context.get("_assembled_at"))
            result["memory_context"] = memory_context

        return result
    except Exception as exc:
        log.error("Node router failed: %s", exc)
        return {"errors": [f"router: {exc}"]}


def route_after_router(state: GeodeState) -> str:
    """Conditional edge: decide next node based on pipeline mode."""
    mode = state.get("pipeline_mode", "full_pipeline")
    if mode in ("cortex_only", "discovery", "analysis", "full_pipeline", "prospect"):
        return "signals"
    if mode == "evaluation":
        return "evaluators"
    if mode == "scoring":
        return "scoring"
    log.warning("Unknown pipeline_mode '%s', defaulting to signals", mode)
    return "signals"
