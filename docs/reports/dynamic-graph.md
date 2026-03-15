# Dynamic Graph — Implementation Report

## Summary

Dynamic Graph enables GEODE's StateGraph to skip nodes or inject enrichment paths based on analysis results. Previously, every pipeline run followed the identical fixed topology regardless of context. Now, the graph dynamically adapts based on state conditions.

## Changes

### New State Fields (`core/state.py`)

| Field | Type | Purpose |
|-------|------|---------|
| `skip_nodes` | `list[str]` | Nodes to skip in current execution |
| `skipped_nodes` | `Annotated[list[str], operator.add]` | Audit log of actually skipped nodes (accumulates) |
| `enrichment_needed` | `bool` | Whether mid-range scores require additional evaluation |

### New Graph Node: `skip_check` (`core/graph.py`)

Inserted between `scoring` and `verification` in the topology:

```
scoring → skip_check → [verification or synthesizer]
```

- `_skip_check_node`: Passthrough that records skip decisions and provides placeholder results
- `_route_after_skip_check`: Conditional edge routing based on `skip_nodes`

### Router Changes (`core/nodes/router.py`)

- `dry_run` mode automatically adds `"verification"` to `skip_nodes`
- Merges caller-provided `skip_nodes` with router-determined skips

### Scoring Changes (`core/nodes/scoring.py`)

- **Extreme scores** (final >= 90 or final <= 20): adds `"verification"` to `skip_nodes` (high confidence in result)
- **Mid-range scores** (40 <= final <= 80): sets `enrichment_needed=True`
- Scores in the [20, 40) and [80, 90) ranges proceed normally

### Confidence Gate Enhancement (`core/graph.py`)

When `enrichment_needed=True` and on the first iteration, the confidence threshold is raised by 0.1 (capped at 0.95). This encourages the feedback loop to run at least once for ambiguous mid-range scores.

## Topology

```
Before:
  scoring → verification → [confidence gate] → synthesizer

After:
  scoring → skip_check → verification → [confidence gate] → synthesizer
                        ↘ synthesizer (when verification skipped)
```

## Audit Trail

All skip decisions are recorded in `state.skipped_nodes` (accumulative via `operator.add` reducer). This enables:
- Post-analysis audit: which nodes were actually executed
- Debugging: understand why certain verification results are placeholders
- Monitoring: track skip frequency across pipeline runs

## Test Results

| Gate | Result |
|------|--------|
| `ruff check core/ tests/` | 0 errors |
| `mypy core/` | 0 errors (132 files) |
| `pytest tests/` | 2250 passed, 19 deselected |

### Fixture Preservation

All 3 core IP fixtures produce unchanged tier/cause results:
- Berserk: **S** (81.3) -- conversion_failure
- Cowboy Bebop: **A** (68.4) -- undermarketed
- Ghost in the Shell: **B** (51.6) -- discovery_failure

### New Tests (22)

| Test Class | Count | Coverage |
|------------|-------|----------|
| `TestSkipCheckNode` | 4 | Unit tests for skip_check node logic |
| `TestRouteAfterSkipCheck` | 3 | Conditional edge routing |
| `TestDryRunSkip` | 3 | dry_run verification skip |
| `TestExplicitSkipNodes` | 2 | Caller-provided skip_nodes |
| `TestEnrichmentNeeded` | 3 | Scoring enrichment flag |
| `TestDynamicGraphBuild` | 2 | Graph construction |
| `TestAuditTrail` | 2 | Skip audit recording |
| `TestFixturePreservation` | 3 | Existing fixture regression |

## Design Decisions

1. **skip_check as separate node** (not inline in scoring): Keeps the skip decision visible in the graph topology and LangSmith traces. Each node has a single responsibility.

2. **Placeholder results when skipping**: When verification is skipped, `GuardrailResult(all_passed=True)` is returned. This ensures downstream nodes (synthesizer) that may reference guardrails don't encounter missing state.

3. **enrichment_needed raises threshold** (not force-loops): Instead of unconditionally forcing a feedback loop for mid-range scores, we raise the confidence threshold. If confidence is already very high, we still proceed. This respects the existing max_iterations cap.

4. **Confidence Gate loopback preserved**: The max 5 iteration limit remains unchanged. Dynamic Graph only affects which nodes run within each iteration and the effective confidence threshold.
