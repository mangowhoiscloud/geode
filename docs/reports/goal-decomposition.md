# Goal Decomposition - Implementation Report

## Summary

Autonomous Goal Decomposition feature that automatically breaks down complex, multi-step user requests into structured sub-goal DAGs. Simple requests pass through without overhead.

## Architecture

```
User Input → _is_clearly_simple() → yes → AgenticLoop (normal)
                                   → no  → _has_compound_indicators() → no → AgenticLoop (normal)
                                                                       → yes → GoalDecomposer._llm_decompose()
                                                                              → DecompositionResult
                                                                              → System prompt injection
                                                                              → AgenticLoop (guided execution)
```

### Components

| Component | Path | Role |
|-----------|------|------|
| `GoalDecomposer` | `core/orchestration/goal_decomposer.py` | LLM-based compound request decomposition |
| `SubGoal` | `core/orchestration/goal_decomposer.py` | Pydantic model for individual sub-goals |
| `DecompositionResult` | `core/orchestration/goal_decomposer.py` | Structured output from decomposition |
| `decomposer.md` | `core/llm/prompts/decomposer.md` | System prompt for decomposition LLM |
| `_try_decompose()` | `core/cli/agentic_loop.py` | Integration hook in AgenticLoop |

### Design Decisions

1. **Prompt injection over delegation**: Instead of creating sub-agents for each goal, the decomposition plan is injected into the system prompt. The existing AgenticLoop then executes tools in the suggested order. This reuses the existing multi-tool execution capability without adding orchestration complexity.

2. **Cost-aware model selection**: Uses `ANTHROPIC_BUDGET` (Haiku, $1/$5 per M tokens) for decomposition instead of Opus ($5/$25), keeping the overhead at ~$0.01 per decomposition call.

3. **Two-stage heuristic filter**: Before calling the LLM, two fast checks avoid unnecessary API calls:
   - `_is_clearly_simple()`: Slash commands and inputs < 15 chars
   - `_has_compound_indicators()`: Korean/English connectors and multi-step keywords

4. **TaskGraph reuse**: `build_task_graph_from_goals()` converts decomposition results into the existing `TaskGraph` infrastructure, enabling dependency-aware execution and failure propagation.

5. **Graceful degradation**: LLM failures return None, and the AgenticLoop proceeds normally without decomposition guidance.

## Files Changed

| File | Change |
|------|--------|
| `core/orchestration/goal_decomposer.py` | New: GoalDecomposer class |
| `core/llm/prompts/decomposer.md` | New: Decomposition prompt template |
| `core/cli/agentic_loop.py` | Modified: `_try_decompose()` integration, `enable_goal_decomposition` flag |
| `core/cli/nl_router.py` | Modified: `"decompose"` action added to `_STATIC_VALID_ACTIONS` |
| `tests/test_goal_decomposer.py` | New: 32 tests |
| `tests/test_nl_router.py` | Modified: Updated action count assertions |
| `CHANGELOG.md` | Updated: Added entry |
| `CLAUDE.md` | Updated: Module count, test count, project structure |

## Tests

- 32 new tests in `tests/test_goal_decomposer.py`
- All 2248 existing tests pass (0 regressions)
- Test coverage includes:
  - SubGoal/DecompositionResult model validation
  - Heuristic pre-filter (simple passthrough)
  - Compound indicator detection
  - LLM decomposition with mocked responses
  - LLM error graceful degradation
  - TaskGraph conversion with dependency ordering
  - Parallel goal batching
  - Failure propagation in task graphs
  - AgenticLoop integration (enable/disable, hint generation)

## Quality Gates

| Gate | Status |
|------|--------|
| `uv run ruff check core/ tests/` | Pass |
| `uv run mypy core/` | Pass (132 source files) |
| `uv run pytest tests/ -q` | 2248 passed |
