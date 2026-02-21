"""StateGraph build + compile for the GEODE pipeline.

Topology: START → router → cortex → signals → analyst×4 (Send)
       → evaluators → scoring → verification → synthesizer → END
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from geode.nodes.analysts import analyst_node, make_analyst_sends
from geode.nodes.cortex import cortex_node
from geode.nodes.evaluators import evaluators_node
from geode.nodes.router import route_after_router, router_node
from geode.nodes.scoring import scoring_node
from geode.nodes.signals import signals_node
from geode.nodes.synthesizer import synthesizer_node
from geode.state import GeodeState
from geode.verification.biasbuster import run_biasbuster
from geode.verification.guardrails import run_guardrails

log = logging.getLogger(__name__)


def _verification_node(state: GeodeState) -> dict:
    """Run guardrails + biasbuster."""
    if state.get("skip_verification"):
        from geode.state import BiasBusterResult, GuardrailResult

        return {
            "guardrails": GuardrailResult(details=["Skipped by --skip-verification"]),
            "biasbuster": BiasBusterResult(explanation="Skipped"),
        }
    guardrails = run_guardrails(state)
    biasbuster = run_biasbuster(state)
    errors: list[str] = []
    if not guardrails.all_passed:
        errors.append("Guardrails failed — results may be unreliable (demo mode)")
    if not biasbuster.overall_pass:
        errors.append("BiasBuster flagged potential bias in analysis")
    result: dict = {
        "guardrails": guardrails,
        "biasbuster": biasbuster,
    }
    if errors:
        result["errors"] = errors
    return result


def _should_synthesize(state: GeodeState) -> str:
    """Conditional edge: proceed to synthesizer or abort."""
    guardrails = state.get("guardrails")
    if guardrails and not guardrails.all_passed:
        log.warning("Guardrails failed — proceeding in demo mode")
    return "synthesizer"


def build_graph() -> StateGraph:
    """Build the GEODE LangGraph StateGraph."""
    graph = StateGraph(GeodeState)

    # Add nodes
    graph.add_node("router", router_node)
    graph.add_node("cortex", cortex_node)
    graph.add_node("signals", signals_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("evaluators", evaluators_node)
    graph.add_node("scoring", scoring_node)
    graph.add_node("verification", _verification_node)
    graph.add_node("synthesizer", synthesizer_node)

    # Edges: START → router
    graph.add_edge(START, "router")

    # Router conditional edges (§langgraph-flow: 6 modes → 3 destinations)
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {"cortex": "cortex", "evaluators": "evaluators", "scoring": "scoring"},
    )

    # Sequential: cortex → signals
    graph.add_edge("cortex", "signals")

    # Send API: signals → 4 analysts in parallel (Clean Context)
    graph.add_conditional_edges("signals", make_analyst_sends, ["analyst"])

    # Sequential: analysts → evaluators → scoring → verification → synthesizer → END
    graph.add_edge("analyst", "evaluators")
    graph.add_edge("evaluators", "scoring")
    graph.add_edge("scoring", "verification")
    graph.add_conditional_edges(
        "verification",
        _should_synthesize,
        {"synthesizer": "synthesizer"},
    )
    graph.add_edge("synthesizer", END)

    return graph


def compile_graph():
    """Compile the graph for execution."""
    graph = build_graph()
    return graph.compile()
