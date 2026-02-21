# GEODE Pipeline Topology Reference

> SOT: `architecture-v6.md` §4 (Agentic Core Layer)

## Full Graph Definition

```python
def build_graph() -> StateGraph:
    graph = StateGraph(GeodeState)

    # 8 nodes
    graph.add_node("router", router_node)
    graph.add_node("cortex", cortex_node)
    graph.add_node("signals", signals_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("evaluators", evaluators_node)
    graph.add_node("scoring", scoring_node)
    graph.add_node("verification", _verification_node)
    graph.add_node("synthesizer", synthesizer_node)

    # Edges
    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", route_after_router,
        {"cortex": "cortex", "evaluators": "evaluators", "scoring": "scoring"})
    graph.add_edge("cortex", "signals")
    graph.add_conditional_edges("signals", make_analyst_sends, ["analyst"])
    graph.add_edge("analyst", "evaluators")
    graph.add_edge("evaluators", "scoring")
    graph.add_edge("scoring", "verification")
    graph.add_conditional_edges("verification", _should_synthesize,
        {"synthesizer": "synthesizer"})
    graph.add_edge("synthesizer", END)

    return graph
```

## Router Modes (6 → 3 destinations)

| Mode | Destination | Description |
|------|-------------|-------------|
| `full_pipeline` | cortex | 전체 분석 |
| `cortex_only` | cortex | Cortex 데이터만 |
| `discovery` | cortex | 발굴 모드 |
| `analysis` | cortex | 분석 모드 |
| `evaluation` | evaluators | 평가만 재실행 |
| `scoring` | scoring | 점수만 재계산 |

## Send API Detail

```python
def make_analyst_sends(state: GeodeState) -> list[Send]:
    types = ["game_mechanics", "player_experience", "growth_potential", "discovery"]
    base = {k: v for k, v in state.items() if k not in ("analyses", "_analyst_type")}
    return [Send("analyst", {**base, "_analyst_type": t}) for t in types]
```

Private state per analyst:
- Receives: `ip_info`, `monolake`, `signals`, `_analyst_type`
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

## Planned Enhancement: Feedback Loop (GAP-1)

```
VERIFY → [confidence >= 0.7] → SYNTHESIZER
       → [confidence < 0.7 AND iteration < 3] → CORTEX (loop back)
       → [iteration >= 3] → SYNTHESIZER (partial)
```

Requires: `iteration: int`, `max_iterations: int` in GeodeState.
