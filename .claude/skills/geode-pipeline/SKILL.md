---
name: geode-pipeline
description: GEODE LangGraph StateGraph 파이프라인 구축 가이드. 7-node topology, Send API 병렬 분석, Conditional Edges, Reducer 패턴, graph.stream() 진행 추적. "pipeline", "graph", "topology", "node", "send api", "langgraph", "stategraph" 키워드로 트리거.
---

# GEODE Pipeline (LangGraph StateGraph)

## Topology

```
START → router → signals → analyst×4 (Send API)
     → evaluators → scoring → verification → synthesizer → END
```

Router loads fixture data (ip_info, monolake) + assembles 3-tier memory context.

## State Schema

`GeodeState(TypedDict, total=False)` in `geode/state.py`:

- `ip_name`, `pipeline_mode`, `session_id` — Input
- `ip_info`, `monolake`, `memory_context` — Layer 1 (Router)
- `signals` — Layer 2
- `analyses: Annotated[list[AnalysisResult], operator.add]` — Reducer (Send API)
- `evaluations: dict[str, EvaluatorResult]` — Layer 3
- `psm_result`, `subscores`, `final_score`, `tier` — Layer 4
- `synthesis` — Layer 5
- `guardrails`, `biasbuster` — Verification
- `errors: Annotated[list[str], operator.add]` — Reducer

## Key Patterns

### 1. Send API (Clean Context)

4 Analysts in parallel. Each gets isolated state (without `analyses`) to prevent anchoring.

```python
def make_analyst_sends(state: GeodeState) -> list[Send]:
    types = ["game_mechanics", "player_experience", "growth_potential", "discovery"]
    base = {k: v for k, v in state.items() if k not in ("analyses", "_analyst_type")}
    return [Send("analyst", {**base, "_analyst_type": t}) for t in types]
```

Wiring: `graph.add_conditional_edges("signals", make_analyst_sends, ["analyst"])`

### 2. Router (6 modes → 3 destinations)

```python
def route_after_router(state: GeodeState) -> str:
    mode = state.get("pipeline_mode", "full_pipeline")
    if mode in ("full_pipeline", "cortex_only", "discovery", "analysis"):
        return "signals"
    elif mode == "evaluation":
        return "evaluators"
    return "scoring"
```

### 3. graph.stream() Progress

`cli.py` uses `graph.stream()` with manual state accumulation for reducer fields (`analyses`, `errors`).

### 4. Verification Conditional Edge

```python
graph.add_conditional_edges("verification", _should_synthesize, {"synthesizer": "synthesizer"})
```

## Node Contract

Each node: `(state: GeodeState) -> dict` — returns only updated fields.

| Node | Output Keys |
|------|-------------|
| `router` | `pipeline_mode`, `ip_info`, `monolake`, `session_id`, `memory_context` |
| `signals` | `signals` |
| `analyst` | `analyses` (list, reducer) |
| `evaluators` | `evaluations` |
| `scoring` | `psm_result`, `subscores`, `final_score`, `tier` |
| `verification` | `guardrails`, `biasbuster`, `errors` |
| `synthesizer` | `synthesis` |

## Key Files

| File | Role |
|------|------|
| `geode/graph.py` | StateGraph build + compile |
| `geode/state.py` | GeodeState + Pydantic models + Ports |
| `geode/cli.py` | graph.stream() + Rich UI |
| `geode/nodes/*.py` | 7 node implementations |

## References

- **Full topology details**: See [topology.md](./references/topology.md)
- **SOT**: `docs/architecture-v6.md` §4 (Agentic Core)
