"""Construction-time values for :class:`AgenticLoop`.

Runtime services stay explicit constructor dependencies.  This record groups
only scalar/session policy that is snapshotted when one loop is created.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.agent.error_recovery import ErrorRecoveryStrategy
from core.agent.tool_executor import ToolCallProcessor
from core.ui.agentic_ui import OperationLogger


@dataclass(slots=True)
class AgenticLoopConfig:
    """Caller-selected policy for one loop instance."""

    max_rounds: int = 0
    max_tokens: int = 32768
    thinking_budget: int = 0
    effort: str = "high"
    time_budget_s: float = 0.0
    cost_budget: float = 0.0
    parent_session_key: str = ""
    parent_session_id: str = ""
    system_suffix: str = ""
    system_prompt_override: str | None = None
    disable_settings_drift: bool = False
    allowed_tool_names: set[str] | None = None
    force_include_allowed_tools: bool = False
    source: str = ""
    session_id: str = ""
    response_schema: dict[str, Any] | None = None
    allow_actionable_partial_on_empty: bool = False
    yield_after_tool_round: bool = False


def initialize_runtime(
    loop: Any,
    tool_executor: Any,
    hooks: Any,
    config: AgenticLoopConfig,
    *,
    quiet: bool,
) -> None:
    """Build the route, tool surface, persistence, and execution state."""
    source = config.source
    loop._source_explicit = bool(source)
    if not source:
        from core.llm.adapters._source_inference import infer_source

        source = infer_source(loop._provider)
    loop._source = source
    loop._allowed_tool_names = config.allowed_tool_names
    loop._force_include_allowed_tools = config.force_include_allowed_tools

    mcp_manager = loop._mcp_manager
    mcp_tools = mcp_manager.get_all_tools() if mcp_manager is not None else None
    transient_names = loop._transient_tool_names(mcp_tools)
    loop._mcp_epoch = mcp_manager.connection_epoch if mcp_manager is not None else 0

    from ._tool_factory import get_agentic_tools

    runtime_tools = get_agentic_tools(
        loop._tool_registry,
        mcp_tools=mcp_tools,
        force_include=(config.allowed_tool_names if config.force_include_allowed_tools else None),
        provider=loop._provider,
        source=loop._source,
        policy_sources=loop._policy_sources,
    )
    if config.allowed_tool_names is not None:
        runtime_tools = [
            tool for tool in runtime_tools if tool.get("name") in config.allowed_tool_names
        ]
    loop._transient_tools = ()
    loop._transient_deferred_tool_names = ()
    if loop._bound_tool_plan is not None:
        loop._apply_bound_tool_plan(runtime_tools, transient_tool_names=transient_names)
    else:
        loop._tools = runtime_tools

    loop._capability_graph = None
    loop._task_preflight = None
    loop._preflight_hint = ""
    loop._usage_snapshot = None
    loop._capability_graph_digest = ""
    loop._last_llm_error = None
    loop._response_schema = config.response_schema

    from core.llm.adapters import resolve_for
    from core.llm.adapters.registry import (
        AdapterNotFoundError,
        get_adapter,
        normalize_registry_provider,
    )

    registry_provider = normalize_registry_provider(loop._provider)
    try:
        loop._new_adapter = get_adapter(loop._source)
    except AdapterNotFoundError:
        loop._new_adapter = resolve_for(registry_provider, loop._source)
    loop._last_emitted_session_id = ""
    loop._op_logger = OperationLogger(quiet=quiet)
    loop._error_recovery = ErrorRecoveryStrategy(tool_executor)

    loop._timeline = None
    loop._session_id = ""
    loop._goal_store = None
    try:
        import uuid

        from core.memory.goals import GoalStore
        from core.observability.session_timeline import SessionTimeline

        loop._session_id = config.session_id or f"s-{uuid.uuid4().hex[:12]}"
        loop._timeline = SessionTimeline(loop._session_id)
        loop._goal_store = GoalStore(loop._timeline.db_path)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Session timeline init failed", exc_info=True)

    import time

    from core.observability.session_metrics import SessionMetrics, current_session_metrics

    ambient_metrics = current_session_metrics()
    loop._session_metrics = (
        ambient_metrics
        if ambient_metrics.session_id == loop._session_id or ambient_metrics.gen_tag
        else SessionMetrics(
            session_id=loop._session_id,
            component="agentic_loop",
            started_at=time.time(),
        )
    )

    try:
        from core.agent.capability_graph import build_capability_graph
        from core.agent.evidence_ledger import EvidenceLedger
        from core.llm.providers.anthropic import is_computer_use_enabled

        loop._capability_graph = build_capability_graph(
            model=loop.model,
            provider=loop._provider,
            source=loop._source,
            visible_tool_names={
                str(tool.get("name", "")) for tool in loop._tools if tool.get("name")
            },
            computer_use_enabled=is_computer_use_enabled(),
        )
        loop._evidence_ledger = EvidenceLedger.for_session(
            loop._session_id,
            turn_id_provider=lambda: loop._turn_id,
        )
        attach_ledger = getattr(tool_executor, "attach_evidence_ledger", None)
        if callable(attach_ledger):
            attach_ledger(loop._evidence_ledger)
    except Exception:
        import logging

        loop._capability_graph = None
        loop._evidence_ledger = None
        logging.getLogger(__name__).debug(
            "Capability graph/evidence ledger init failed",
            exc_info=True,
        )

    loop._tool_processor = ToolCallProcessor(
        executor=tool_executor,
        op_logger=loop._op_logger,
        error_recovery=loop._error_recovery,
        hooks=hooks,
        mcp_manager=mcp_manager,
        timeline=loop._timeline,
        model=loop.model,
        provider=getattr(loop._new_adapter, "provider", loop._provider),
        source=getattr(loop._new_adapter, "source", loop._source),
        adapter_name=getattr(loop._new_adapter, "name", ""),
    )
    loop._consecutive_llm_failures = 0
    loop._LLM_RETRY_CAP = 5
    loop._pre_execution_retry_errors = []

    from core.agent.context_manager import ContextWindowManager

    loop._ctx_mgr = ContextWindowManager(
        hooks=hooks,
        hook_registry=loop._hook_registry,
        quiet=quiet,
        session_id_provider=lambda: loop._session_id or None,
    )

    from core.agent.convergence import ConvergenceDetector

    loop._convergence = ConvergenceDetector()
    loop._consecutive_tool_tracker = []
    loop._checkpoint = None
    try:
        from core.memory.session_checkpoint import SessionCheckpoint

        loop._checkpoint = SessionCheckpoint()
    except Exception:
        import logging

        logging.getLogger(__name__).warning("SessionCheckpoint init failed", exc_info=True)

    from core.agent.cognitive_state import CognitiveState

    loop.cognitive_state = CognitiveState()


__all__ = ["AgenticLoopConfig", "initialize_runtime"]
