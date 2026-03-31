# GEODE Orchestration Layer — Design Decision

> **English** | [한국어](orchestration-decision.md)

> **Conclusion**: LangGraph StateGraph itself is the orchestration layer. No separate layer needed.

## Systems Investigated

| System | Pattern | GEODE Applicability |
|--------|---------|---------------------|
| **OpenClaw** | Hub-and-spoke Gateway, Lane Queue, Skills | Not suitable — designed for personal assistant automation, serial-first design |
| **Claude Code** | Master loop (while tool_calls), Sub-agent Task tool, Context compressor | Not suitable — designed for conversational tool-use agents, differs from structured pipelines |
| **LangGraph** | StateGraph, Send API, Conditional Edges, Checkpoint | **Currently in use — optimal** |

## Why LangGraph Is Optimal

1. **Typed State**: `GeodeState(TypedDict)` + Pydantic BaseModel → type safety
2. **Send API**: 4 Analysts parallel execution + Clean Context (anchoring prevention)
3. **Conditional Edges**: Router 6-mode branching, conditional Synthesizer after Verification
4. **Reducer Pattern**: `Annotated[list[AnalysisResult], operator.add]` → automatic parallel result merging
5. **Checkpoint**: SqliteSaver support (recovery for long-running executions)

## Patterns Borrowed from OpenClaw

| OpenClaw Pattern | GEODE Application |
|------------------|-------------------|
| Progressive Disclosure (Skills) | `--verbose`, `--dry-run` flags |
| Session Isolation | Send API Clean Context (score isolation between Analysts) |
| Gateway routing | Router node + `route_after_router` conditional edges |

## Patterns Borrowed from Claude Code

| Claude Code Pattern | GEODE Application |
|---------------------|-------------------|
| Sub-agent isolated context | Send API: each Analyst runs with independent state |
| Step-by-step progress | `graph.stream()`-based progress indicator |
| Effective Harnesses | Fixture-based dry-run (full pipeline verification without LLM) |

## Architecture Comparison

```
OpenClaw:  Gateway → Lane Queue → Skill → Agent (serial by default)
Claude:    while(tool_calls) { execute(tool) } (conversation loop)
GEODE:     StateGraph: START → Route → Gather → Send(Analyst×4) → Evaluate → Score → Verify → Synthesize → END
```

GEODE is a **structured analysis pipeline**, fundamentally different in topology from conversational agents (OpenClaw/Claude).
Since LangGraph's StateGraph maps 1:1 to this pattern, no separate orchestration layer is needed.
