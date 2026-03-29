---
name: explore-reason-act
description: Mandatory 3-phase explore-reason-act workflow before code modification. Enforces read-before-write, root cause hypothesis formulation, minimal change application. Triggered by "explore" ("탐색"), "reason" ("추론"), "read before write", "root cause" ("근본 원인") keywords.
user-invocable: false
---

# Explore-Reason-Act Methodology

Before modifying code, always follow the **Explore -> Reason -> Act** cycle.
Modifying without exploration is the #1 cause of incorrect fixes and repeated failures.

## Phase 1: Explore (Read Before Write)

Mandatory exploration patterns before code changes:

```bash
# 1. Understand error context (failing file + surrounding lines)
grep -rn "ERROR_SYMBOL" core/ tests/ --include="*.py" -l

# 2. Find all usage sites of the target symbol
grep -rn "ClassName\|function_name" core/ tests/ --include="*.py"

# 3. Check the dependency chain
grep -rn "from.*import.*ClassName" core/ --include="*.py"

# 4. Check test expectations
grep -rn "ClassName\|function_name" tests/ --include="*.py"
```

Rules:
- Do not edit a file you have not read
- Do not assume a symbol exists without grep verification
- Read the entire function/class, not just the error line
- Check at least 2 levels of callers/callees
- If 10+ files have the same error, find the common root cause

## Phase 2: Reason (Hypothesis Formulation)

State the following before writing fix code:

1. **Observation**: "I confirmed X in files A, B, C"
2. **Hypothesis**: "The root cause is Y. Evidence: Z"
3. **Prediction**: "Fixing Y will simultaneously resolve errors in A, B, C"
4. **Impact scope**: "This change affects N files / M call sites"

Prohibited patterns:
- Fixing compiler errors individually when a common root cause exists
- Guessing API signatures without reading source or documentation
- Assuming dependency versions without checking pyproject.toml/config

## Phase 3: Act (Apply Minimal Changes)

1. Apply only the minimal change for the root cause
2. Run build/test immediately after the change
3. If new errors occur, return to Phase 1 (no stacking fixes)
4. Escalate if unresolved after 3 iterations

## Output Contract

Every fix attempt must include:
- `exploration_summary`: What was read and what was discovered
- `hypothesis`: Evidence-based root cause hypothesis
- `change_description`: What was changed and why
- `verification`: Build/test results after the change

## GEODE Application

| Scenario | Explore | Reason | Act |
|----------|---------|--------|-----|
| Pipeline node modification | Read `graph.py` + node file + state.py entirely | Reducer conflict hypothesis | Modify only 1 node, stream test |
| Tool addition | Read `definitions.json` + `tool_handlers.py` + `tool_executor.py` | Analyze existing tool patterns | Implement following the pattern, unit test |
| Memory change | Read `context.py` + session/project/org hierarchy | Verify 4-tier assembly order | Modify only the relevant tier, assembly test |
