"""StateGraph build + compile for the GEODE pipeline.

Design Decision: Plan-and-Execute over ReAct
    ReAct (Reason+Act) executes tools sequentially without upfront planning,
    limiting parallelism and structured multi-step analysis. GEODE adopts a
    fixed-topology DAG with Send API parallelism (analysts×4, evaluators×3)
    for deterministic execution order. Dynamic Plan-and-Execute for complex
    requests lives in L4 orchestration (see orchestration/plan_mode.py).

Topology: START → router → signals → analyst×4 (Send)
       → evaluator×3 (Send) → scoring → verification → synthesizer → END

Router loads fixture data (ip_info, monolake) and assembles 3-tier memory context.

Feedback Loop (L3): verification → _configured_should_continue
  - confidence >= 0.7 → synthesizer
  - confidence < 0.7 AND iteration < max_iterations → signals (loopback)
  - iteration >= max_iterations → synthesizer (force proceed)

Hook Integration (L4): NODE_ENTER/EXIT/ERROR events triggered at each node.
"""

from __future__ import annotations

import atexit
import logging
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from geode.llm.prompt_assembler import PromptAssembler

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from geode.infrastructure.ports.hook_port import HookSystemPort
from geode.nodes.analysts import analyst_node, make_analyst_sends
from geode.nodes.evaluators import evaluator_node, make_evaluator_sends
from geode.nodes.router import route_after_router, router_node
from geode.nodes.scoring import scoring_node
from geode.nodes.signals import signals_node
from geode.nodes.synthesizer import synthesizer_node
from geode.orchestration.bootstrap import BootstrapManager
from geode.orchestration.hooks import HookEvent
from geode.state import BiasBusterResult, GeodeState, GuardrailResult
from geode.tools.policy import NodeScopePolicy
from geode.verification.biasbuster import run_biasbuster
from geode.verification.calibration import run_calibration_check
from geode.verification.cross_llm import run_cross_llm_check
from geode.verification.guardrails import run_guardrails
from geode.verification.rights_risk import RightsStatus, check_rights_risk

log = logging.getLogger(__name__)

# Confidence threshold for feedback loop (L3)
CONFIDENCE_THRESHOLD = 0.7
DEFAULT_MAX_ITERATIONS = 5

# Nodes eligible for node-level retry on failure (Phase 3-A)
_RETRYABLE_NODES = frozenset({"analyst", "evaluator", "scoring"})
_NODE_MAX_RETRIES = 1

# Node → specific hook event mapping
_NODE_COMPLETION_EVENTS: dict[str, HookEvent] = {
    "analyst": HookEvent.ANALYST_COMPLETE,
    "evaluator": HookEvent.EVALUATOR_COMPLETE,
    "scoring": HookEvent.SCORING_COMPLETE,
}


def _make_hooked_node(
    node_fn: Callable[[GeodeState], dict[str, Any]],
    node_name: str,
    hooks: HookSystemPort,
    bootstrap_mgr: BootstrapManager | None = None,
    prompt_assembler: PromptAssembler | None = None,
    node_scope_policy: NodeScopePolicy | None = None,
) -> Callable[[GeodeState], dict[str, Any]]:
    """Wrap a node function with hook triggers and prompt assembly."""

    def _wrapped(state: GeodeState) -> dict[str, Any]:
        hook_data: dict[str, Any] = {"node": node_name, "ip_name": state.get("ip_name", "")}

        # Propagate Send API subtype so TaskGraphHookBridge can resolve task IDs
        if node_name == "analyst" and "_analyst_type" in state:
            hook_data["_analyst_type"] = state["_analyst_type"]
        if node_name == "evaluator" and "_evaluator_type" in state:
            hook_data["_evaluator_type"] = state["_evaluator_type"]

        # NODE_BOOTSTRAP — allow hooks to modify node config before execution
        effective_state: GeodeState = state
        if bootstrap_mgr is not None:
            ip_name = state.get("ip_name", "")
            ctx = bootstrap_mgr.prepare_node(node_name, ip_name, dict(state))
            if ctx.skip:
                log.info("Bootstrap skip: node '%s' skipped for IP '%s'", node_name, ip_name)
                return {}
            effective_state = bootstrap_mgr.apply_context(dict(state), ctx)  # type: ignore[assignment]

        # ADR-007: PromptAssembler injection via state
        if prompt_assembler is not None:
            effective_state = dict(effective_state)  # type: ignore[assignment]
            effective_state["_prompt_assembler"] = prompt_assembler  # type: ignore[typeddict-unknown-key]

        # Phase 2: Node-scoped tool filtering — restrict _tool_definitions per node
        if node_scope_policy is not None:
            es_dict: dict[str, Any] = dict(effective_state)
            raw_defs: Any = es_dict.get("_tool_definitions", [])
            tool_defs: list[dict[str, Any]] = raw_defs if isinstance(raw_defs, list) else []
            if tool_defs:
                tool_names = [t.get("name", "") for t in tool_defs if isinstance(t, dict)]
                allowed_set = set(node_scope_policy.filter(tool_names, node=node_name))
                filtered_defs = [
                    t for t in tool_defs if isinstance(t, dict) and t.get("name", "") in allowed_set
                ]
                es_dict["_tool_definitions"] = filtered_defs
                effective_state = es_dict  # type: ignore[assignment]

        # NODE_ENTER
        hooks.trigger(HookEvent.NODE_ENTER, hook_data)

        # PIPELINE_START (router is the first real node)
        if node_name == "router":
            hooks.trigger(HookEvent.PIPELINE_START, hook_data)

        start_time = time.time()

        # Phase 3-A: node-level retry for retryable nodes
        retries_left = _NODE_MAX_RETRIES if node_name in _RETRYABLE_NODES else 0
        last_exc: Exception | None = None

        while True:
            try:
                # On retry, lower temperature for more deterministic output
                if last_exc is not None and isinstance(effective_state, dict):
                    prev: Any = effective_state.get("_bootstrap_parameters", {})
                    effective_state["_bootstrap_parameters"] = {  # type: ignore[typeddict-unknown-key]
                        **(prev or {}),
                        "temperature": 0.3,
                    }

                result: dict[str, Any] = node_fn(effective_state)

                duration_ms = (time.time() - start_time) * 1000
                hook_data["duration_ms"] = duration_ms
                hook_data["result_keys"] = list(result.keys())
                if last_exc is not None:
                    hook_data["retried"] = True

                # Auto-attach drift scan hint for scoring node
                if node_name == "scoring":
                    score = result.get("final_score", 0.0)
                    if score > 0:
                        hook_data["drift_scan_hint"] = True
                        hook_data["final_score"] = score

                # NODE_EXIT
                hooks.trigger(HookEvent.NODE_EXIT, hook_data)

                # Node-specific completion events
                if node_name in _NODE_COMPLETION_EVENTS:
                    hooks.trigger(_NODE_COMPLETION_EVENTS[node_name], hook_data)

                # Verification pass/fail
                if node_name == "verification":
                    guardrails = result.get("guardrails")
                    biasbuster = result.get("biasbuster")
                    all_ok = (
                        guardrails
                        and guardrails.all_passed
                        and biasbuster
                        and biasbuster.overall_pass
                    )
                    if all_ok:
                        hooks.trigger(HookEvent.VERIFICATION_PASS, hook_data)
                    else:
                        hooks.trigger(HookEvent.VERIFICATION_FAIL, hook_data)

                # PIPELINE_END (synthesizer is the last real node)
                if node_name == "synthesizer":
                    # Enrich hook_data for memory write-back
                    synthesis = result.get("synthesis")
                    if synthesis:
                        hook_data["synthesis_cause"] = getattr(
                            synthesis,
                            "undervaluation_cause",
                            "",
                        )
                        hook_data["synthesis_action"] = getattr(synthesis, "action_type", "")
                    hook_data["final_score"] = effective_state.get("final_score", 0.0)
                    hook_data["tier"] = effective_state.get("tier", "")
                    hook_data["dry_run"] = effective_state.get("dry_run", False)
                    hooks.trigger(HookEvent.PIPELINE_END, hook_data)

                return result

            except Exception as exc:
                if retries_left > 0:
                    retries_left -= 1
                    last_exc = exc
                    log.warning(
                        "Node '%s' failed (%s), retrying (%d left)",
                        node_name,
                        exc,
                        retries_left,
                    )
                    hook_data["retry_reason"] = str(exc)
                    continue
                hook_data["error"] = str(exc)
                hooks.trigger(HookEvent.NODE_ERROR, hook_data)
                hooks.trigger(HookEvent.PIPELINE_ERROR, hook_data)
                raise

    _wrapped.__name__ = f"hooked_{node_name}"

    # Phase 5-B: Wrap with LangSmith traceable for Run Tree hierarchy
    if os.environ.get("LANGSMITH_API_KEY"):
        try:
            from langsmith import traceable

            _wrapped = traceable(
                run_type="chain",
                name=f"node:{node_name}",
            )(_wrapped)
        except ImportError:
            pass

    return _wrapped


def _verification_node(state: GeodeState) -> dict[str, Any]:
    """Run guardrails + biasbuster + rights risk check."""
    if state.get("skip_verification"):
        log.warning("Verification skipped — results unverified")
        return {
            "guardrails": GuardrailResult(
                details=["WARNING: Verification skipped — results unverified"],
            ),
            "biasbuster": BiasBusterResult(explanation="Skipped"),
        }
    guardrails = run_guardrails(state, signal_data=state.get("signals"))
    biasbuster = run_biasbuster(state)
    cross_llm = run_cross_llm_check(state)

    # Rights risk assessment (GAP-2)
    ip_name = state.get("ip_name", "")
    rights_risk = check_rights_risk(ip_name)

    errors: list[str] = []
    if not guardrails.all_passed:
        errors.append("Guardrails failed — results may be unreliable (demo mode)")
    if not biasbuster.overall_pass:
        errors.append("BiasBuster flagged potential bias in analysis")
    if not cross_llm.get("passed", True):
        errors.append("Cross-LLM agreement below threshold")
    if rights_risk.status in (RightsStatus.RESTRICTED, RightsStatus.UNKNOWN):
        errors.append(
            f"Rights risk warning: {rights_risk.status.value} — {rights_risk.recommendation}"
        )
    # Ground Truth calibration (Layer 5 — Swiss Cheese)
    calibration = run_calibration_check(state)

    result: dict[str, Any] = {
        "guardrails": guardrails,
        "biasbuster": biasbuster,
        "cross_llm": cross_llm,
        "rights_risk": rights_risk,
        "calibration": calibration,
    }
    if not calibration.passed:
        errors.append(f"Calibration check: {calibration.overall_score:.1f}/100 (threshold: 80.0)")
    if errors:
        result["errors"] = errors
    return result


def _gather_node(state: GeodeState) -> dict[str, Any]:
    """Feedback loop gather node — increment iteration, snapshot, and adapt.

    Adaptive behavior (G5): identifies weak areas from the current iteration
    and records them so downstream nodes can focus on low-confidence dimensions.
    """
    iteration = state.get("iteration", 1)
    log.info("Feedback loop: re-entering pipeline (iteration %d → %d)", iteration, iteration + 1)

    # Snapshot current iteration's metrics before re-entering
    confidence = state.get("analyst_confidence", 0.0)
    final_score = state.get("final_score", 0.0)
    tier = state.get("tier", "")

    # Adaptive analysis: identify weak subscores to focus on next iteration
    subscores = state.get("subscores", {})
    weak_areas = [k for k, v in subscores.items() if v < 50.0] if subscores else []

    history_entry: dict[str, Any] = {
        "iteration": iteration,
        "confidence": confidence,
        "final_score": final_score,
        "tier": tier,
        "weak_areas": weak_areas,
    }

    result: dict[str, Any] = {"iteration": iteration + 1, "iteration_history": [history_entry]}

    if weak_areas:
        log.info("Adaptive feedback: weak areas identified — %s", weak_areas)
        # Inject weak_areas into monolake so downstream nodes focus on low-confidence dims
        monolake = dict(state.get("monolake", {}))
        monolake["_weak_areas"] = weak_areas
        result["monolake"] = monolake

    # Return single-element list — Annotated[..., operator.add] reducer handles accumulation
    return result


def build_graph(
    *,
    hooks: HookSystemPort | None = None,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    bootstrap_mgr: BootstrapManager | None = None,
    prompt_assembler: PromptAssembler | None = None,
    node_scope_policy: NodeScopePolicy | None = None,
) -> StateGraph[GeodeState]:
    """Build the GEODE LangGraph StateGraph.

    Args:
        hooks: Optional HookSystem for event-driven extensions.
            If provided, all nodes are wrapped with hook triggers.
        confidence_threshold: Override the feedback loop confidence threshold.
        max_iterations: Override maximum feedback loop iterations.
        bootstrap_mgr: Optional BootstrapManager for pre-execution node
            configuration. If provided, NODE_BOOTSTRAP fires before each
            node, allowing hooks to modify prompts/parameters per-IP.
    """
    graph = StateGraph(GeodeState)

    # Optionally wrap nodes with hook triggers
    def _node(
        fn: Callable[[GeodeState], dict[str, Any]],
        name: str,
    ) -> Callable[[GeodeState], dict[str, Any]]:
        if hooks is not None:
            return _make_hooked_node(
                fn,
                name,
                hooks,
                bootstrap_mgr,
                prompt_assembler,
                node_scope_policy,
            )
        return fn

    # Add nodes (type: ignore needed — LangGraph type stubs don't match runtime)
    graph.add_node("router", _node(router_node, "router"))  # type: ignore[call-overload]
    graph.add_node("signals", _node(signals_node, "signals"))  # type: ignore[call-overload]
    graph.add_node("analyst", _node(analyst_node, "analyst"))  # type: ignore[call-overload]
    graph.add_node("evaluator", _node(evaluator_node, "evaluator"))  # type: ignore[call-overload]
    graph.add_node("scoring", _node(scoring_node, "scoring"))  # type: ignore[call-overload]
    graph.add_node("verification", _node(_verification_node, "verification"))  # type: ignore[call-overload]
    graph.add_node("synthesizer", _node(synthesizer_node, "synthesizer"))  # type: ignore[call-overload]
    graph.add_node("gather", _node(_gather_node, "gather"))  # type: ignore[call-overload]

    # Edges: START → router
    graph.add_edge(START, "router")

    # Router conditional edges (§langgraph-flow: 6 modes → 3 destinations)
    # Note: route_after_router returns "evaluators" (plural) for evaluation mode,
    # which maps to the "evaluator" node (singular, Send API pattern).
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {"signals": "signals", "evaluators": "evaluator", "scoring": "scoring"},
    )

    # Send API: signals → 4 analysts in parallel (Clean Context)
    graph.add_conditional_edges("signals", make_analyst_sends, ["analyst"])

    # Send API: analysts → 3 evaluators in parallel (Clean Context)
    graph.add_conditional_edges("analyst", make_evaluator_sends, ["evaluator"])

    # Sequential: evaluators → scoring → verification
    graph.add_edge("evaluator", "scoring")
    graph.add_edge("scoring", "verification")

    # Feedback Loop: verification → _configured_should_continue → synthesizer or gather → signals
    # Use injected thresholds via closure for configurability
    def _configured_should_continue(state: GeodeState) -> str:
        guardrails = state.get("guardrails")
        if guardrails and not guardrails.all_passed:
            log.warning("Guardrails failed — proceeding in demo mode")

        confidence = state.get("analyst_confidence", 0.0)
        iteration = state.get("iteration", 1)
        max_iter = state.get("max_iterations", max_iterations)

        conf_normalized = confidence / 100.0 if confidence > 1.0 else confidence

        if conf_normalized >= confidence_threshold:
            log.info("Confidence %.2f >= %.2f — synthesizer", conf_normalized, confidence_threshold)
            return "synthesizer"

        if iteration >= max_iter:
            log.warning(
                "Confidence %.2f < %.2f but max iterations (%d) reached — force proceeding",
                conf_normalized,
                confidence_threshold,
                max_iter,
            )
            return "synthesizer"

        log.info(
            "Confidence %.2f < %.2f — looping back (iteration %d/%d)",
            conf_normalized,
            confidence_threshold,
            iteration,
            max_iter,
        )
        return "gather"

    graph.add_conditional_edges(
        "verification",
        _configured_should_continue,
        {"synthesizer": "synthesizer", "gather": "gather"},
    )
    graph.add_edge("gather", "signals")

    graph.add_edge("synthesizer", END)

    return graph


def _register_drift_scan_hook(hooks: HookSystemPort) -> None:
    """Register a SCORING_COMPLETE handler that triggers CUSUM drift scan.

    When the scoring node completes, this hook checks the drift_scan_hint
    and emits a DRIFT_DETECTED event if the final_score suggests monitoring
    is needed. In production, this would feed into FeedbackOrchestrator.
    """
    from geode.automation.drift import CUSUMDetector

    detector = CUSUMDetector()

    def _on_scoring_complete(event: HookEvent, data: dict[str, Any]) -> None:
        if not data.get("drift_scan_hint"):
            return
        score = data.get("final_score", 0.0)
        if score <= 0:
            return
        alerts = detector.scan_all({"final_score": score})
        if alerts:
            hooks.trigger(
                HookEvent.DRIFT_DETECTED,
                {
                    "source": "scoring_complete_hook",
                    "final_score": score,
                    "alerts": [a.to_dict() for a in alerts],
                },
            )

    hooks.register(
        HookEvent.SCORING_COMPLETE,
        _on_scoring_complete,
        name="drift_scan_on_scoring",
        priority=50,
    )


def compile_graph(
    *,
    checkpoint_db: str | None = None,
    hooks: HookSystemPort | None = None,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    interrupt_before: list[str] | None = None,
    memory_fallback: bool = False,
    enable_drift_scan: bool = False,
    bootstrap_mgr: BootstrapManager | None = None,
    prompt_assembler: PromptAssembler | None = None,
    node_scope_policy: NodeScopePolicy | None = None,
) -> CompiledStateGraph[Any, None, Any, Any]:
    """Compile the graph for execution.

    Args:
        checkpoint_db: Path to SQLite database for LangGraph checkpointing.
            If provided, enables SqliteSaver for state persistence/recovery.
            If None, runs without checkpointing (default).
        hooks: Optional HookSystem for event-driven extensions.
        confidence_threshold: Override feedback loop confidence threshold.
        max_iterations: Override maximum feedback loop iterations.
        interrupt_before: Optional list of node names to pause before for
            human-in-the-loop support. E.g. ["verification"].
        memory_fallback: If True and checkpoint_db is None, use MemorySaver
            as an in-memory checkpointer (requires thread_id in config).
        enable_drift_scan: If True and hooks provided, register CUSUM drift
            scan handler on SCORING_COMPLETE events.
        bootstrap_mgr: Optional BootstrapManager for pre-execution node
            configuration via NODE_BOOTSTRAP hooks.
    """
    # Register drift scan hook before building graph (GAP-7)
    if enable_drift_scan and hooks is not None:
        _register_drift_scan_hook(hooks)

    graph = build_graph(
        hooks=hooks,
        confidence_threshold=confidence_threshold,
        max_iterations=max_iterations,
        bootstrap_mgr=bootstrap_mgr,
        prompt_assembler=prompt_assembler,
        node_scope_policy=node_scope_policy,
    )

    compile_kwargs: dict[str, Any] = {}

    if checkpoint_db is not None:
        db_path = Path(checkpoint_db)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        atexit.register(conn.close)
        compile_kwargs["checkpointer"] = SqliteSaver(conn)
    elif memory_fallback:
        compile_kwargs["checkpointer"] = MemorySaver()

    if interrupt_before:
        compile_kwargs["interrupt_before"] = interrupt_before

    # CLI integration note: the returned CompiledStateGraph supports
    # .stream(state, config) for node-by-node progress reporting,
    # yielding intermediate state dicts after each node execution.
    # Use graph.stream() in CLI/UI layers for real-time progress bars.
    return graph.compile(**compile_kwargs)
