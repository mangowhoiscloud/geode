"""StateGraph build + compile for the GEODE pipeline.

Design Decision: Plan-and-Execute over ReAct
    ReAct (Reason+Act) executes tools sequentially without upfront planning,
    limiting parallelism and structured multi-step analysis. GEODE adopts a
    fixed-topology DAG with Send API parallelism (analysts×4, evaluators×3)
    for deterministic execution order. Dynamic Plan-and-Execute for complex
    requests lives in L4 orchestration (see orchestration/plan_mode.py).

Topology: START → router → signals → analyst×4 (Send)
       → evaluator×3 (Send) → scoring → [skip?] → verification → synthesizer → END

Dynamic Graph: nodes can be skipped based on state.skip_nodes.
  - Router sets skip_nodes (e.g. dry_run → skip verification)
  - Scoring sets skip_nodes (e.g. extreme scores → skip verification)
  - Scoring sets enrichment_needed (mid-range → lower confidence threshold)
  - Skipped nodes are recorded in state.skipped_nodes for audit trail

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
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm.prompt_assembler import PromptAssembler

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from core.config import settings
from core.domains.game_ip.nodes.analysts import analyst_node, make_analyst_sends
from core.domains.game_ip.nodes.evaluators import evaluator_node, make_evaluator_sends
from core.domains.game_ip.nodes.router import route_after_router, router_node
from core.domains.game_ip.nodes.scoring import scoring_node
from core.domains.game_ip.nodes.signals import signals_node
from core.domains.game_ip.nodes.synthesizer import synthesizer_node
from core.hooks import HookEvent, HookSystem
from core.orchestration.bootstrap import BootstrapManager
from core.state import (
    BiasBusterResult,
    GeodeState,
    GuardrailResult,
    ensure_analysis_results,
    ensure_evaluator_results,
)
from core.tools.policy import NodeScopePolicy
from core.verification.biasbuster import run_biasbuster
from core.verification.calibration import run_calibration_check
from core.verification.cross_llm import run_cross_llm_check
from core.verification.guardrails import run_guardrails
from core.verification.rights_risk import RightsStatus, check_rights_risk

log = logging.getLogger(__name__)

# Confidence threshold for feedback loop (L3)
CONFIDENCE_THRESHOLD = 0.7
DEFAULT_MAX_ITERATIONS = 5

# Nodes eligible for node-level retry on failure (Phase 3-A)
_RETRYABLE_NODES = frozenset({"analyst", "evaluator", "scoring", "gather"})
_NODE_MAX_RETRIES = 1

# Nodes that return degraded results instead of crashing the pipeline (B1)
_DEGRADABLE_NODES = frozenset({"analyst", "evaluator", "scoring"})

# Node → specific hook event mapping
_NODE_COMPLETION_EVENTS: dict[str, HookEvent] = {
    "analyst": HookEvent.ANALYST_COMPLETE,
    "evaluator": HookEvent.EVALUATOR_COMPLETE,
    "scoring": HookEvent.SCORING_COMPLETE,
}


def _make_degraded_result(node_name: str, exc: Exception, state: Any) -> dict[str, Any]:
    """B1: Return degraded fallback instead of crashing the pipeline.

    Reuses existing degraded patterns from analysts.py / evaluators.py.
    """
    from core.state import AnalysisResult, EvaluatorResult

    err_msg = f"{node_name}: {type(exc).__name__}: {exc}"

    if node_name == "analyst":
        atype = state.get("_analyst_type", "unknown") if isinstance(state, dict) else "unknown"
        return {
            "analyses": [
                AnalysisResult(
                    analyst_type=atype,
                    score=1.0,
                    key_finding="[DEGRADED] Node retry exhausted",
                    reasoning=str(exc),
                    evidence=["retry_exhausted"],
                    confidence=0.0,
                    is_degraded=True,
                )
            ],
            "errors": [err_msg],
        }

    if node_name == "evaluator":
        etype = state.get("_evaluator_type", "unknown") if isinstance(state, dict) else "unknown"
        _NEUTRAL = 3.0
        _default_axes: dict[str, dict[str, float]] = {
            "quality_judge": dict.fromkeys(
                (
                    "a_score",
                    "b_score",
                    "c_score",
                    "b1_score",
                    "c1_score",
                    "c2_score",
                    "m_score",
                    "n_score",
                ),
                _NEUTRAL,
            ),
            "community_momentum": {
                "j_score": _NEUTRAL,
                "k_score": _NEUTRAL,
                "l_score": _NEUTRAL,
            },
        }
        _hidden = {"d_score": _NEUTRAL, "e_score": _NEUTRAL, "f_score": _NEUTRAL}
        return {
            "evaluations": {
                etype: EvaluatorResult(
                    evaluator_type=etype,
                    axes=_default_axes.get(etype, _hidden),
                    composite_score=0.0,
                    rationale="[DEGRADED] Node retry exhausted",
                    is_degraded=True,
                )
            },
            "errors": [err_msg],
        }

    if node_name == "scoring":
        return {
            "final_score": 0.0,
            "tier": "C",
            "analyst_confidence": 0.0,
            "subscores": {},
            "errors": [err_msg],
        }

    return {"errors": [err_msg]}


def _make_hooked_node(
    node_fn: Callable[[GeodeState], dict[str, Any]],
    node_name: str,
    hooks: HookSystem,
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

                # Rehydrate Pydantic models that LangGraph may have
                # deserialized to dicts during Send API state merging.
                if isinstance(effective_state, dict):
                    raw_a: Any = effective_state.get("analyses")
                    if raw_a and isinstance(raw_a, list) and isinstance(raw_a[0], dict):
                        effective_state["analyses"] = ensure_analysis_results(raw_a)
                    raw_e: Any = effective_state.get("evaluations")
                    if raw_e and isinstance(raw_e, dict):
                        first_val = next(iter(raw_e.values()), None)
                        if isinstance(first_val, dict):
                            effective_state["evaluations"] = ensure_evaluator_results(raw_e)

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

                # B1: degradable nodes return degraded results instead of crashing
                if node_name in _DEGRADABLE_NODES:
                    log.warning(
                        "Node '%s' retry exhausted — returning degraded result",
                        node_name,
                    )
                    return _make_degraded_result(node_name, exc, effective_state)

                hooks.trigger(HookEvent.PIPELINE_ERROR, hook_data)
                raise

    _wrapped.__name__ = f"hooked_{node_name}"

    # Phase 5-B: Wrap with LangSmith traceable for Run Tree hierarchy
    from core.llm.router import is_langsmith_enabled

    if is_langsmith_enabled():
        try:
            from langsmith import traceable

            _wrapped = traceable(
                run_type="chain",
                name=f"node:{node_name}",
            )(_wrapped)
        except ImportError:
            pass

    return _wrapped


def _skip_check_node(state: GeodeState) -> dict[str, Any]:
    """Dynamic Graph: passthrough node that records skip decisions.

    This node runs before verification. If verification is in skip_nodes,
    it records the skip in skipped_nodes for audit trail and returns
    minimal placeholder results so downstream nodes have valid state.
    """
    skip_nodes = state.get("skip_nodes", [])
    if "verification" in skip_nodes:
        from core.cli.ui.agentic_ui import emit_node_skipped

        emit_node_skipped("verification", "Dynamic Graph skip_nodes")
        log.info("Dynamic Graph: verification skipped (in skip_nodes)")
        return {
            "skipped_nodes": ["verification"],
            "guardrails": GuardrailResult(
                details=["Verification skipped by Dynamic Graph (skip_nodes)"],
            ),
            "biasbuster": BiasBusterResult(explanation="Skipped (Dynamic Graph)"),
        }
    return {}


def _route_after_skip_check(state: GeodeState) -> str:
    """Conditional edge: skip verification or proceed normally."""
    skip_nodes = state.get("skip_nodes", [])
    if "verification" in skip_nodes:
        return "synthesizer"
    return "verification"


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
    cross_llm = run_cross_llm_check(state, agreement_threshold=settings.agreement_threshold)

    # Rights risk assessment (GAP-2)
    ip_name = state.get("ip_name", "")
    rights_risk = check_rights_risk(ip_name)

    errors: list[str] = []
    if not guardrails.all_passed:
        errors.append("Guardrails failed — results may be unreliable (demo mode)")
    if not biasbuster.overall_pass:
        errors.append("BiasBuster flagged potential bias in analysis")
    if not cross_llm.get("passed", False):
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
    hooks: HookSystem | None = None,
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
    graph.add_node("skip_check", _node(_skip_check_node, "skip_check"))  # type: ignore[call-overload]
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

    # Sequential: evaluators → scoring → skip_check
    # Dynamic Graph: skip_check decides whether to run verification or skip to synthesizer
    graph.add_edge("evaluator", "scoring")
    graph.add_edge("scoring", "skip_check")
    graph.add_conditional_edges(
        "skip_check",
        _route_after_skip_check,
        {"verification": "verification", "synthesizer": "synthesizer"},
    )

    # Feedback Loop: verification → _configured_should_continue → synthesizer or gather → signals
    # Use injected thresholds via closure for configurability
    def _configured_should_continue(state: GeodeState) -> str:
        guardrails = state.get("guardrails")
        biasbuster = state.get("biasbuster")

        confidence = state.get("analyst_confidence", 0.0)
        iteration = state.get("iteration", 1)
        max_iter = state.get("max_iterations", max_iterations)

        conf_normalized = confidence / 100.0 if confidence > 1.0 else confidence

        # B5: verification failure triggers enrichment loop (before confidence check)
        verification_failed = (guardrails and not guardrails.all_passed) or (
            biasbuster and not biasbuster.overall_pass
        )
        if verification_failed and iteration < max_iter:
            log.warning(
                "Verification failed (guardrails=%s, biasbuster=%s)"
                " — looping back (iteration %d/%d)",
                getattr(guardrails, "all_passed", None),
                getattr(biasbuster, "overall_pass", None),
                iteration,
                max_iter,
            )
            from core.cli.ui.agentic_ui import emit_feedback_loop

            emit_feedback_loop(iteration, conf_normalized * 100, confidence_threshold * 100)
            return "gather"

        # Dynamic Graph: enrichment_needed lowers confidence threshold
        # to encourage at least one feedback loop for mid-range scores
        effective_threshold = confidence_threshold
        if state.get("enrichment_needed") and iteration <= 1:
            # First iteration with enrichment needed: require higher confidence
            # to proceed, effectively forcing a re-evaluation loop
            effective_threshold = min(confidence_threshold + 0.1, 0.95)
            log.info(
                "Dynamic Graph: enrichment_needed → raised threshold to %.2f",
                effective_threshold,
            )

        if conf_normalized >= effective_threshold:
            log.info(
                "Confidence %.2f >= %.2f — synthesizer",
                conf_normalized,
                effective_threshold,
            )
            return "synthesizer"

        if iteration >= max_iter:
            log.warning(
                "Confidence %.2f < %.2f but max iterations (%d) reached — force proceeding",
                conf_normalized,
                effective_threshold,
                max_iter,
            )
            return "synthesizer"

        from core.cli.ui.agentic_ui import emit_feedback_loop

        emit_feedback_loop(iteration, conf_normalized * 100, effective_threshold * 100)
        log.info(
            "Confidence %.2f < %.2f — looping back (iteration %d/%d)",
            conf_normalized,
            effective_threshold,
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


def _register_drift_scan_hook(hooks: HookSystem) -> None:
    """Register a SCORING_COMPLETE handler that triggers CUSUM drift scan.

    When the scoring node completes, this hook checks the drift_scan_hint
    and emits a DRIFT_DETECTED event if the final_score suggests monitoring
    is needed. In production, this would feed into FeedbackOrchestrator.
    """
    from core.automation.drift import CUSUMDetector

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
    hooks: HookSystem | None = None,
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

    # Register Pydantic models for checkpoint (de)serialization.
    # allowed_json_modules covers both JSON and msgpack paths internally
    # (langgraph-checkpoint >=4.0.1 warns on unregistered types).
    _allowed_modules: list[tuple[str, ...]] = [
        ("core.state", "AnalysisResult"),
        ("core.state", "EvaluatorResult"),
        ("core.state", "PSMResult"),
        ("core.state", "SynthesisResult"),
        ("core.state", "GuardrailResult"),
        ("core.state", "BiasBusterResult"),
        ("core.state", "CalibrationResult"),
        ("core.state", "RightsStatus"),
        ("core.state", "RightsRiskResult"),
        ("core.state", "LicenseInfo"),
    ]
    _serde = JsonPlusSerializer(
        allowed_json_modules=_allowed_modules,
        allowed_msgpack_modules=_allowed_modules,
    )

    if checkpoint_db is not None:
        db_path = Path(checkpoint_db)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        atexit.register(conn.close)
        compile_kwargs["checkpointer"] = SqliteSaver(conn, serde=_serde)
    elif memory_fallback:
        compile_kwargs["checkpointer"] = MemorySaver(serde=_serde)

    if interrupt_before:
        compile_kwargs["interrupt_before"] = interrupt_before

    # CLI integration note: the returned CompiledStateGraph supports
    # .stream(state, config) for node-by-node progress reporting,
    # yielding intermediate state dicts after each node execution.
    # Use graph.stream() in CLI/UI layers for real-time progress bars.
    return graph.compile(**compile_kwargs)


class PipelineTimeoutError(Exception):
    """B3: Pipeline execution exceeded configured timeout."""


def invoke_with_timeout(
    graph: CompiledStateGraph[Any, None, Any, Any],
    state: dict[str, Any],
    config: Any | None = None,
    timeout_s: float = 0.0,
    hooks: HookSystem | None = None,
) -> Any:
    """B3: Invoke graph with optional timeout guard.

    Args:
        timeout_s: Max seconds (0 = use settings.pipeline_timeout_s, negative = no timeout).
    Returns:
        Final state dict. On timeout, raises PipelineTimeoutError.
    """
    import concurrent.futures
    import contextvars

    if timeout_s == 0.0:
        timeout_s = settings.pipeline_timeout_s
    if timeout_s <= 0:
        return graph.invoke(state, config=config)

    # Snapshot ContextVars so the worker thread inherits memory/profile/domain
    # adapters set during bootstrap. Python contextvars do not auto-propagate
    # across threads — without this, graph nodes see None for all injected state.
    ctx = contextvars.copy_context()

    def _run() -> Any:
        return graph.invoke(state, config=config)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(ctx.run, _run)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            log.error("Pipeline timeout after %.0fs", timeout_s)
            if hooks:
                hooks.trigger(HookEvent.PIPELINE_TIMEOUT, {"timeout_s": timeout_s})
            raise PipelineTimeoutError(
                f"Pipeline execution exceeded {timeout_s}s timeout"
            ) from None
