---
name: agent-ops-debugging
description: Autonomous agent system operational debugging patterns. Safe Default Anti-pattern, Multi-gap root cause analysis, ContextVar DI lifecycle, closure capture pattern, Graceful Degradation vs Correctness distinction. Triggered by "debugging" ("디버깅"), "safe default", "contextvar", "dry-run", "operations" ("운영"), "degradation", "multi-gap", "closure capture" ("클로저 캡처") keywords.
user-invocable: false
---

# Agent Ops Debugging — Autonomous Agent Operational Debugging Patterns

> **Source**: Distilled from GEODE operational debugging sessions (2026-03-14)
> **Philosophy**: "Not crashing" and "working correctly" are different problems.
> **Details**: [Blog 25](docs/blogs/25-operational-debugging-four-layer-fix.md) · [ADR-008](docs/plans/ADR-008-subagent-dry-run-bypass.md)

## 5 Pattern Overview

| # | Pattern | One-line Principle | Applicable Layer |
|---|---------|-------------------|-----------------|
| D1 | Safe Default Anti-pattern | Safe defaults guarantee stability but not correctness | All layers |
| D2 | Multi-gap Root Cause | Individual gaps are harmless but N gaps combined manifest — individual tests cannot catch them | Pipeline |
| D3 | ContextVar Lifecycle | ContextVar DI must be initialized at every entry point | DI layer |
| D4 | Closure Capture Bypass | Thread-isolated ContextVars are bypassed via closure capture | DI + Concurrency |
| D5 | Degradation ≠ Correctness | Graceful skip/fallback and functional correctness must be verified separately | Verification |

---

## D1. Safe Default Anti-pattern

### Principle

When defaults are set to safe values like `True`, `None`, or `""`, the system does not crash but **returns results different from the intended behavior**. This type of bug does not appear in error logs, so it is discovered late.

### Diagnostic Criteria

```
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

> Do not hardcode defaults — derive them from system state (readiness, config, env).

---

## D2. Multi-gap Root Cause Analysis

### Principle

The most difficult operational bugs to find are those that **manifest only when N independent gaps exist simultaneously**. Each gap is individually harmless or has separate safeguards, so they are not discovered by unit tests.

### Analysis Framework

```
1. Symptom definition: "On which path, under which conditions, does the result differ from expectations"
2. Path comparison: "Identify divergence points compared to the normally working path"
3. Gap enumeration: "Verify whether each divergence point has an independent gap"
4. Overlap determination: "Must all gaps exist simultaneously for the bug to manifest?"
```

### Case: Sub-agent dry-run (3-gap)

```
Gap 1: Handler default = True (hardcoded)
  → Alone: Solvable if LLM passes dry_run=False
Gap 2: dry_run not defined in tool schema
  → Alone: LLM cannot know the parameter
Gap 3: ContextVar thread isolation
  → Alone: Handler cannot query readiness

All 3 present → sub-agent path always runs in dry-run
```

> Multi-gap bug fix strategy: **Resolve the most fundamental single gap** and the remaining gaps become harmless. No need to fix all 3.

---

## D3. ContextVar DI Lifecycle

### Principle

When using Python `contextvars.ContextVar` as a DI container, it must be initialized at **every entry point**. If set at only one entry point, other entry points return `None`.

### Entry Point Checklist

```
Typical entry points for an agent system:
[ ] CLI single command (e.g., `geode analyze "Berserk"`)
[ ] REPL interactive loop (e.g., `geode` → interactive)
[ ] Pipeline internal (e.g., GeodeRuntime.run())
[ ] Sub-agent thread (e.g., delegate_task → separate thread)
[ ] HTTP endpoint (e.g., trigger_endpoint)
[ ] Test fixture (e.g., pytest conftest.py)
```

### Safe Pattern

```python
# Method 1: Explicit initialization at each entry point
def _interactive_loop():
    set_project_memory(ProjectMemory())
    set_org_memory(MonoLakeOrganizationMemory())
    ...

# Method 2: Batch initialization in Bootstrap layer (recommended as scale grows)
class Bootstrap:
    def init_all_contextvars(self):
        set_project_memory(ProjectMemory())
        set_org_memory(MonoLakeOrganizationMemory())
        set_readiness(ReadinessReport(...))
```

> If there are 3 or more entry points, introduce a Bootstrap layer to eliminate initialization logic duplication.

---

## D4. Closure Capture Bypass

### Principle

ContextVar is **only valid within the thread/task where it was set**. If a handler running in a separate thread needs to access a ContextVar, **capture it via closure at handler creation time**.

### Pattern

```python
def make_handler(*, force_dry_run: bool = True):
    """force_dry_run is captured in the closure — same regardless of which thread executes."""
    def handler(task_type: str, args: dict) -> dict:
        dry_run = args.get("dry_run", force_dry_run)
        ...
    return handler

# Call site: fix readiness state at creation time
readiness = _get_readiness()
handler = make_handler(force_dry_run=readiness.force_dry_run)
```

### Alternative Comparison

| Method | Complexity | Thread-safe | Testability |
|--------|-----------|-------------|-------------|
| Closure capture | Low | Safe (immutable value) | Injectable as parameter |
| `contextvars.copy_context()` | Medium | Safe (context copy) | Requires setup |
| Global variable | Low | Unsafe (race condition) | Breaks test isolation |
| Thread-local | Medium | Safe | Incompatible with asyncio |

> If the value does not change after handler creation, closure capture is the best option. If the value can change at runtime, use `copy_context()`.

---

## D5. Degradation ≠ Correctness

### Principle

Graceful degradation is a system **stability** pattern. It must be verified separately from functional **correctness**.

### Verification Matrix

```
For all external dependencies:

| Dependency | Expected behavior when present | Expected behavior when absent | Actual behavior |
|------------|-------------------------------|-------------------------------|-----------------|
| API key    | live LLM call                 | fixture return                | ???             |
| MCP        | tool list loaded              | skip + warning                | ???             |
| Redis      | L1 cache used                 | direct L2 query               | ???             |
```

> Do not only test the "when absent" column. Separately verify that the "when present" column truly takes the live path.

### Distinction Criteria

```
Stability test: "Does the system not crash when dependency X is absent?"
Correctness test: "Does the system actually use X when dependency X is present?"
```

Both questions must be answered "yes" for the system to be healthy.

---

## Debugging Workflow

When encountering a symptom of "it works but not correctly" during operations:

```
1. Symptom → Identify the affected layer (infrastructure/UI/DI/pipeline)
2. Compare with the normal path to find divergence points
3. Check defaults at divergence points — D1 Safe Default applicable?
4. Determine single cause vs Multi-gap — D2 applicable?
5. ContextVar access failure? — D3/D4 applicable?
6. After fix, verify both "when present" + "when absent" — D5
```
