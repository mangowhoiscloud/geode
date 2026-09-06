---
name: agent-ops-debugging
description: Diagnose agent operational failures through default-policy checks, multi-gap analysis, explicit service ownership, request-context lifetime, and degradation-versus-correctness checks.
---

# Agent Ops Debugging — Autonomous Agent Operational Debugging Patterns

> **Source**: Distilled from GEODE operational debugging sessions (2026-03-14)
> **Philosophy**: "Not crashing" and "working correctly" are different problems.
> **Historical incident**: [ADR-008](../../../docs/adr/ADR-008-subagent-dry-run-bypass.md).
> The referenced Blog 25 (`25-operational-debugging-four-layer-fix.md`) is absent
> from this checkout; it is retained here only as historical provenance.
> **Current contract**: [construction and lifecycle](../../../docs/architecture/naming-conventions.md#33-construction-and-lifecycle).

## 5 Pattern Overview

| # | Pattern | One-line Principle | Applicable Layer |
|---|---------|-------------------|-----------------|
| D1 | Safe Default Anti-pattern | Safe defaults guarantee stability but not correctness | All layers |
| D2 | Multi-gap Root Cause | Individual gaps are harmless but N gaps combined manifest — individual tests cannot catch them | Pipeline |
| D3 | Ownership and Context Lifetime | Compose services explicitly; bind and reset request-local context | Wiring + Runtime |
| D4 | Execution Boundary | Choose explicit snapshots or context propagation according to ownership | Runtime + Concurrency |
| D5 | Degradation ≠ Correctness | Graceful skip/fallback and functional correctness must be verified separately | Verification |

---

## D1. Safe Default Anti-pattern

### Principle

When defaults are set to safe values like `True`, `None`, or `""`, the system does not crash but **returns results different from the intended behavior**. This type of bug does not appear in error logs, so it is discovered late.

### Diagnostic Criteria

```text
Q: If this code path operates with the default value, is the result "normal" or "degraded"?
```

| Default Type | Normal Case | Degraded Case |
|-------------|-------------|---------------|
| `dry_run=True` | Returns fixture when no API key | Returns only fixture even with API key present |
| `return None` | Optional feature not in use | Required feature silently disabled |
| `log.debug(skip)` | Optional external integration skipped | Required integration silent fail |

### Application Pattern

```python
# BAD — always safe but always degraded
dry_run = args.get("dry_run", True)

# GOOD — default determined by system state
dry_run = args.get("dry_run", force_dry_run)  # force_dry_run is readiness-based
```

> Use the owner's declared default and distinguish normal, degraded, and failed
> outcomes. The example above describes the 2026-03-14 incident; credential
> availability alone does not authorize live calls or changing a dry-run request.

---

## D2. Multi-gap Root Cause Analysis

### Principle

The most difficult operational bugs to find are those that **manifest only when N independent gaps exist simultaneously**. Each gap is individually harmless or has separate safeguards, so they are not discovered by unit tests.

### Analysis Framework

```text
1. Symptom definition: "On which path, under which conditions, does the result differ from expectations"
2. Path comparison: "Identify divergence points compared to the normally working path"
3. Gap enumeration: "Verify whether each divergence point has an independent gap"
4. Overlap determination: "Must all gaps exist simultaneously for the bug to manifest?"
```

### Case: Sub-agent dry-run (3-gap)

```text
Gap 1: Handler default = True (hardcoded)
  → Alone: Solvable if LLM passes dry_run=False
Gap 2: dry_run not defined in tool schema
  → Alone: LLM cannot know the parameter
Gap 3: ContextVar thread isolation
  → Alone: Handler cannot query readiness

All 3 present → sub-agent path always runs in dry-run
```

> Fix the smallest root cause, then verify whether the remaining gaps are
> actually harmless. Do not close them from the existence of one fix alone.

---

## D3. Service Ownership and Request Context

### Principle

Current GEODE composes services in `core.wiring` through constructors or existing
typed contexts. Do not restore the historical ContextVar service locator.
ContextVars may hold request identity, diagnostics, or request-local state;
their binding and reset must match the logical request lifetime.

### Entry Point Checklist

```text
Typical entry points for an agent system:
[ ] CLI single command
[ ] REPL interactive loop (e.g., `geode` → interactive)
[ ] Hosted runtime turn
[ ] Sub-agent task, worker thread, or subprocess
[ ] Server or scheduled-job entry point
[ ] Test fixture (e.g., pytest conftest.py)
```

For the affected entry points, trace the service constructor to its consumer
and the request-context binder to its reset, including errors and cancellation.
Reuse the existing composition owner; entry-point count alone does not justify
another bootstrap layer or DI container.

---

## D4. Crossing Task, Thread, and Process Boundaries

### Principle

Check how the actual execution primitive propagates context. A copied context
does not synchronize mutable services, and a captured value can become stale.
Pass services explicitly and choose the lifetime of value snapshots deliberately.

### Historical pattern — ADR-008, 2026-03-14

```python
def make_handler(*, force_dry_run: bool = True):
    """force_dry_run is captured in the closure — same regardless of which thread executes."""
    def handler(task_type: str, args: dict) -> dict:
        dry_run = args.get("dry_run", force_dry_run)
        ...
    return handler

# Historical call site: fix readiness state at handler creation time
readiness = _get_readiness()
handler = make_handler(force_dry_run=readiness.force_dry_run)
```

### Current decision criteria

| Value | Boundary treatment | Verify |
|-------|--------------------|--------|
| Service dependency | Constructor or existing typed context | Correct owner and teardown |
| Immutable per-turn policy | Explicit snapshot at the owning turn boundary | A later config change affects the intended next turn |
| Request identity or diagnostics | Scoped binding or explicit context propagation | Correlation preserved; reset on success/error/cancel |
| Cross-process input | Existing serialized request contract | No assumption that in-process ContextVars cross the boundary |

The historical closure fixed one readiness lookup. It is not a recommendation
to capture mutable credentials or long-lived policy at handler construction.

---

## D5. Degradation ≠ Correctness

### Principle

Graceful degradation is a system **stability** pattern. It must be verified separately from functional **correctness**.

### Verification Matrix

```text
For all external dependencies:

| Dependency | Expected behavior when present | Expected behavior when absent | Actual behavior |
|------------|-------------------------------|-------------------------------|-----------------|
| Provider   | authorized call uses selected source | explicit error or explicitly requested fixture mode | ??? |
| MCP        | tool list loaded              | skip + warning                | ???             |
| Redis      | L1 cache used                 | direct L2 query               | ???             |
```

> Test both columns with offline fakes first. Live verification requires the
> task's authorization; merely finding credentials does not authorize it.

### Distinction Criteria

```text
Stability test: "Does the system not crash when dependency X is absent?"
Correctness test: "Does the system actually use X when dependency X is present?"
```

Verify the declared outcome in both cases. A required dependency may correctly
fail closed instead of returning a successful-looking fallback.

---

## Debugging Workflow

When encountering a symptom of "it works but not correctly" during operations:

```text
1. Symptom → Identify the affected layer (infrastructure/UI/DI/pipeline)
2. Compare with the normal path to find divergence points
3. Check defaults at divergence points — D1 Safe Default applicable?
4. Determine single cause vs Multi-gap — D2 applicable?
5. ContextVar access failure? — D3/D4 applicable?
6. After fix, verify both "when present" + "when absent" — D5
```
