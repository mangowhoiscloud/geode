"""Game IP plugin wiring — signal adapter, context assembler, task graph.

Step 3 (domain-free-core) relocated three plugin-bound wiring helpers out
of ``core/lifecycle/`` into the plugin so ``core/`` no longer reaches
into ``plugins.game_ip.nodes`` directly. ``core/lifecycle/adapters.py``
and ``core/lifecycle/bootstrap.py`` now go through the DomainPort v2
methods instead, which delegate here for the game-IP domain.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory.context import ContextAssembler
    from core.orchestration.task_system import TaskGraph

log = logging.getLogger(__name__)


def build_signal_adapter() -> None:
    """Build and inject CompositeSignalAdapter with MCP-backed signal sources.

    Chains MCP signal adapters into CompositeSignalAdapter, then injects
    into ``signals_node`` via contextvars. If no MCP servers are
    configured or available, the adapter reports ``is_available()=False``
    and ``signals_node`` falls back to fixtures.

    Relocated from ``core.wiring.adapters.build_signal_adapter`` in
    step 3 because it is plugin-specific (Steam adapter, ``signals_node``
    setter live under ``plugins/game_ip/``).
    """
    from core.mcp.composite_signal import CompositeSignalAdapter
    from core.mcp.manager import get_mcp_manager
    from core.mcp.steam_adapter import SteamMCPSignalAdapter

    from plugins.game_ip.nodes.signals import set_signal_adapter

    manager = get_mcp_manager()
    server_count = manager.load_config()

    if server_count == 0:
        log.debug("No MCP servers configured — signal adapter skipped (fixture fallback)")
        set_signal_adapter(None)
        return

    # Build individual MCP signal adapters
    adapters: list[SteamMCPSignalAdapter] = []

    steam_adapter = SteamMCPSignalAdapter(manager=manager, server_name="steam")
    adapters.append(steam_adapter)

    composite = CompositeSignalAdapter(adapters)  # type: ignore[arg-type]

    if composite.is_available():
        log.info(
            "Signal liveification enabled: %d MCP adapters wired",
            len(adapters),
        )
    else:
        log.debug("MCP servers configured but none available — fixture fallback active")

    set_signal_adapter(composite)


def wire_context_assembler(assembler: ContextAssembler | None) -> None:
    """Inject a ContextAssembler into the game-IP router node.

    Thin wrapper over ``plugins.game_ip.nodes.router.set_context_assembler``
    so the call site in ``core/lifecycle/bootstrap.py`` can route
    through ``DomainPort.wire_context_assembler`` instead of importing
    the plugin directly.
    """
    from plugins.game_ip.nodes.router import set_context_assembler

    set_context_assembler(assembler)


def build_task_graph(subject_id: str) -> TaskGraph:
    """Build the game-IP TaskGraph for the given IP name.

    Lazy-imports ``create_geode_task_graph`` so plugin import does not
    pull in the full orchestration stack at module load time. The
    function itself still lives in ``core/orchestration/task_system.py``
    for now; later refactor steps may move it under ``plugins/`` once
    other call sites are decoupled.
    """
    from core.orchestration.task_system import create_geode_task_graph

    return create_geode_task_graph(subject_id)
