"""StateGraph build + compile for the GEODE pipeline.

Topology: START → router → cortex → signals → analyst×4 (Send)
       → evaluator×3 (Send) → scoring → verification → synthesizer → END

Feedback Loop (L3): verification → _configured_should_continue
  - confidence >= 0.7 → synthesizer
  - confidence < 0.7 AND iteration < max_iterations → cortex (loopback)
  - iteration >= max_iterations → synthesizer (force proceed)

Hook Integration (L4): NODE_ENTER/EXIT/ERROR events triggered at each node.
"""

from __future__ import annotations

import atexit
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from geode.nodes.analysts import analyst_node, make_analyst_sends
from geode.nodes.cortex import cortex_node
from geode.nodes.evaluators import evaluator_node, make_evaluator_sends
from geode.nodes.router import route_after_router, router_node
from geode.nodes.scoring import scoring_node
from geode.nodes.signals import signals_node
from geode.nodes.synthesizer import synthesizer_node
from geode.orchestration.hooks import HookEvent, HookSystem
from geode.state import BiasBusterResult, GeodeState, GuardrailResult
from geode.verification.biasbuster import run_biasbuster
from geode.verification.cross_llm import run_cross_llm_check
from geode.verification.guardrails import run_guardrails

log = logging.getLogger(__name__)

# Confidence threshold for feedback loop (L3)
CONFIDENCE_THRESHOLD = 0.7
DEFAULT_MAX_ITERATIONS = 3

# Node → specific hook event mapping
_NODE_COMPLETION_EVENTS: dict[str, HookEvent] = {
    "analyst": HookEvent.ANALYST_COMPLETE,
    "evaluator": HookEvent.EVALUATOR_COMPLETE,
    "scoring": HookEvent.SCORING_COMPLETE,
}


def _make_hooked_node(
    node_fn,
    node_name: str,
    hooks: HookSystem,
):
    """Wrap a node function with hook triggers."""

    def _wrapped(state: GeodeState) -> dict[str, Any]:
        hook_data: dict[str, Any] = {"node": node_name, "ip_name": state.get("ip_name", "")}

        # NODE_ENTER
        hooks.trigger(HookEvent.NODE_ENTER, hook_data)

        # PIPELINE_START (router is the first real node)
        if node_name == "router":
            hooks.trigger(HookEvent.PIPELINE_START, hook_data)

        start_time = time.time()
        try:
            result: dict[str, Any] = node_fn(state)

            duration_ms = (time.time() - start_time) * 1000
            hook_data["duration_ms"] = duration_ms
            hook_data["result_keys"] = list(result.keys())

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
                if guardrails and guardrails.all_passed and biasbuster and biasbuster.overall_pass:
                    hooks.trigger(HookEvent.VERIFICATION_PASS, hook_data)
                else:
                    hooks.trigger(HookEvent.VERIFICATION_FAIL, hook_data)

            # PIPELINE_END (synthesizer is the last real node)
            if node_name == "synthesizer":
                hooks.trigger(HookEvent.PIPELINE_END, hook_data)

            return result

        except Exception as exc:
            hook_data["error"] = str(exc)
            hooks.trigger(HookEvent.NODE_ERROR, hook_data)
            hooks.trigger(HookEvent.PIPELINE_ERROR, hook_data)
            raise

    _wrapped.__name__ = f"hooked_{node_name}"
    return _wrapped


def _verification_node(state: GeodeState) -> dict[str, Any]:
    """Run guardrails + biasbuster."""
    if state.get("skip_verification"):
        return {
            "guardrails": GuardrailResult(details=["Skipped by --skip-verification"]),
            "biasbuster": BiasBusterResult(explanation="Skipped"),
        }
    guardrails = run_guardrails(state)
    biasbuster = run_biasbuster(state)
    cross_llm = run_cross_llm_check(state)
    errors: list[str] = []
    if not guardrails.all_passed:
        errors.append("Guardrails failed — results may be unreliable (demo mode)")
    if not biasbuster.overall_pass:
        errors.append("BiasBuster flagged potential bias in analysis")
    if not cross_llm.get("passed", True):
        errors.append("Cross-LLM agreement below threshold")
    result: dict = {
        "guardrails": guardrails,
        "biasbuster": biasbuster,
        "cross_llm": cross_llm,
    }
    if errors:
        result["errors"] = errors
    return result


def _gather_node(state: GeodeState) -> dict:
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

    if weak_areas:
        log.info("Adaptive feedback: weak areas identified — %s", weak_areas)

    # Return single-element list — Annotated[..., operator.add] reducer handles accumulation
    return {"iteration": iteration + 1, "iteration_history": [history_entry]}


def build_graph(
    *,
    hooks: HookSystem | None = None,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> StateGraph:
    """Build the GEODE LangGraph StateGraph.

    Args:
        hooks: Optional HookSystem for event-driven extensions.
            If provided, all nodes are wrapped with hook triggers.
        confidence_threshold: Override the feedback loop confidence threshold.
        max_iterations: Override maximum feedback loop iterations.
    """
    graph = StateGraph(GeodeState)

    # Optionally wrap nodes with hook triggers
    def _node(fn, name: str):
        if hooks is not None:
            return _make_hooked_node(fn, name, hooks)
        return fn

    # Add nodes
    graph.add_node("router", _node(router_node, "router"))
    graph.add_node("cortex", _node(cortex_node, "cortex"))
    graph.add_node("signals", _node(signals_node, "signals"))
    graph.add_node("analyst", analyst_node)  # Send API — not wrapped (runs in parallel)
    graph.add_node("evaluator", evaluator_node)  # Send API — parallel evaluators
    graph.add_node("scoring", _node(scoring_node, "scoring"))
    graph.add_node("verification", _node(_verification_node, "verification"))
    graph.add_node("synthesizer", _node(synthesizer_node, "synthesizer"))
    graph.add_node("gather", _node(_gather_node, "gather"))

    # Edges: START → router
    graph.add_edge(START, "router")

    # Router conditional edges (§langgraph-flow: 6 modes → 3 destinations)
    # Note: route_after_router returns "evaluators" (plural) for evaluation mode,
    # which maps to the "evaluator" node (singular, Send API pattern).
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {"cortex": "cortex", "evaluators": "evaluator", "scoring": "scoring"},
    )

    # Sequential: cortex → signals
    graph.add_edge("cortex", "signals")

    # Send API: signals → 4 analysts in parallel (Clean Context)
    graph.add_conditional_edges("signals", make_analyst_sends, ["analyst"])

    # Send API: analysts → 3 evaluators in parallel (Clean Context)
    graph.add_conditional_edges("analyst", make_evaluator_sends, ["evaluator"])

    # Sequential: evaluators → scoring → verification
    graph.add_edge("evaluator", "scoring")
    graph.add_edge("scoring", "verification")

    # Feedback Loop: verification → _configured_should_continue → synthesizer or gather → cortex
    # Use injected thresholds via closure for configurability
    def _configured_should_continue(state: GeodeState) -> str:
        guardrails = state.get("guardrails")
        if guardrails and not guardrails.all_passed:
            log.warning("Guardrails failed — proceeding in demo mode")

        confidence = state.get("analyst_confidence", 100.0)
        iteration = state.get("iteration", 1)
        max_iter = state.get("max_iterations", max_iterations)

        conf_normalized = confidence / 100.0 if confidence > 1.0 else confidence

        if conf_normalized >= confidence_threshold:
            log.info("Confidence %.2f >= %.2f — synthesizer", conf_normalized, confidence_threshold)
            return "synthesizer"

        if iteration >= max_iter:
            log.warning(
                "Confidence %.2f < %.2f but max iterations (%d) reached — force proceeding",
                conf_normalized, confidence_threshold, max_iter,
            )
            return "synthesizer"

        log.info(
            "Confidence %.2f < %.2f — looping back (iteration %d/%d)",
            conf_normalized, confidence_threshold, iteration, max_iter,
        )
        return "gather"

    graph.add_conditional_edges(
        "verification",
        _configured_should_continue,
        {"synthesizer": "synthesizer", "gather": "gather"},
    )
    graph.add_edge("gather", "cortex")

    graph.add_edge("synthesizer", END)

    return graph


def compile_graph(
    *,
    checkpoint_db: str | None = None,
    hooks: HookSystem | None = None,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    interrupt_before: list[str] | None = None,
):
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
    """
    graph = build_graph(
        hooks=hooks,
        confidence_threshold=confidence_threshold,
        max_iterations=max_iterations,
    )

    compile_kwargs: dict[str, Any] = {}

    if checkpoint_db is not None:
        db_path = Path(checkpoint_db)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        atexit.register(conn.close)
        compile_kwargs["checkpointer"] = SqliteSaver(conn)

    if interrupt_before:
        compile_kwargs["interrupt_before"] = interrupt_before

    return graph.compile(**compile_kwargs)
