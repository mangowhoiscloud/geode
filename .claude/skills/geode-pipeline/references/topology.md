# GEODE Pipeline Topology Reference

> SOT: `architecture-v6.md` §4 (Agentic Core Layer)

## Full Graph Definition

```python
def build_graph() -> StateGraph:
    graph = StateGraph(GeodeState)

    # 7 nodes (router handles data loading + memory assembly)
    graph.add_node("router", router_node)
    graph.add_node("signals", signals_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("evaluators", evaluators_node)
    graph.add_node("scoring", scoring_node)
    graph.add_node("verification", _verification_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("gather", _gather_node)

    # Edges
    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", route_after_router,
        {"signals": "signals", "evaluators": "evaluators", "scoring": "scoring"})
    graph.add_conditional_edges("signals", make_analyst_sends, ["analyst"])
    graph.add_conditional_edges("analyst", make_evaluator_sends, ["evaluator"])
    graph.add_edge("evaluator", "scoring")
    graph.add_edge("scoring", "verification")
    graph.add_conditional_edges("verification", _configured_should_continue,
        {"synthesizer": "synthesizer", "gather": "gather"})
    graph.add_edge("gather", "signals")
    graph.add_edge("synthesizer", END)

    return graph
```

## Router Modes (6 → 3 destinations)

| Mode | Destination | Description |
|------|-------------|-------------|
| `full_pipeline` | signals | Full analysis |
| `cortex_only` | signals | Full analysis after data load |
| `discovery` | signals | Discovery mode |
| `analysis` | signals | Analysis mode |
| `evaluation` | evaluators | Re-run evaluation only |
| `scoring` | scoring | Recalculate scoring only |

## Send API Detail

```python
def make_analyst_sends(state: GeodeState) -> list[Send]:
    types = ["game_mechanics", "player_experience", "growth_potential", "discovery"]
    base = {k: v for k, v in state.items() if k not in ("analyses", "_analyst_type")}
    return [Send("analyst", {**base, "_analyst_type": t}) for t in types]
```

Private state per analyst:
- Receives: `ip_info`, `monolake`, `signals`, `memory_context`, `_analyst_type`
- Does NOT receive: `analyses` (Clean Context)
- Output merged via: `Annotated[list[AnalysisResult], operator.add]`

## graph.stream() State Accumulation

```python
for event in graph.stream(initial_state):
    for node_name, output in event.items():
        for k, v in output.items():
            if k in ("analyses", "errors"):  # Reducer fields
                lst = v if isinstance(v, list) else [v]
                final_state.setdefault(k, []).extend(lst)
            else:
                final_state[k] = v
```

## Feedback Loop (L3)

```
VERIFY → [confidence >= 0.7] → SYNTHESIZER
       → [confidence < 0.7 AND iteration < max_iter] → GATHER → SIGNALS (loop back)
       → [iteration >= max_iter] → SYNTHESIZER (force proceed)
```

Gather node injects `_weak_areas` into monolake for adaptive focus.
