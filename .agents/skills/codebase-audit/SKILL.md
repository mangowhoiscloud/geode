---
name: codebase-audit
description: Codebase audit + refactoring workflow. Dead code detection, God Object splitting, duplicate function removal, design flaw identification, frontier comparison verification. Triggered by "audit" ("감사"), "dead code" ("데드코드"), "refactor" ("리팩토링"), "god object", "duplication" ("중복"), "design flaw" ("설계 결함") keywords.
---

# Codebase Audit & Refactoring Workflow

A systematic workflow for auditing and improving the entire codebase.
Proven in the GEODE v0.24.0 session (3,205 lines reduced, __init__.py -57%).

## Workflow

```text
1. Audit
   → Dead code + duplicates + God Object + Parameter Bloat detection
2. Triage
   → Verdict: candidate / refactoring / defer, backed by caller evidence
3. Scope and plan
   → Record keep/change/delete decisions; tracking updates only when requested
4. Workspace Isolation
   → Worktree isolation
5. Implementation + Verification
   → Delete/extract/convert then lint + test
6. Docs-sync + authorized integration
   → CHANGELOG for functional changes; tracking docs follow their main-owned workflow
```

An audit alone does not authorize implementation, merge, global reinstall, or
runtime restart. Use the [canonical workflow](../../../docs/workflow.md) for
the requested scope; deploy or restart only when separately in scope.

## Phase 1: Audit

### Dead Code Detection

```bash
# Check import status per module
for f in $(find core/ -name "*.py" -not -name "__init__.py" -not -path "*__pycache__*"); do
    basename=$(basename $f .py)
    # Check using actual import path (basename match alone causes false positives)
    module_path=$(echo $f | sed 's/\.py$//' | tr '/' '.')
    count=$(grep -rn "from ${module_path}\|import ${module_path}" core/ --include="*.py" | grep -v "$f" | wc -l)
    if [ "$count" -eq 0 ]; then
        echo "CANDIDATE: $f ($(wc -l < $f) lines; no matching textual imports)"
    fi
done
```

Note: Search by **full module path**, not basename, to reduce false positives.
This core-only text scan misses relative imports, outer-package callers,
entrypoints, registries, public exports, and dynamic loading. Apply the deletion
gate below before deciding that a module is unused.

### Duplicate Function Detection

```bash
grep -rn "^def " core/ --include="*.py" | awk -F: '{split($NF,a," "); print a[2]}' | sort | uniq -c | sort -rn | head -10
```

Repeated names are discovery candidates, not proof of duplication. Trace full
call paths and compare behavior; protocol methods and local helpers commonly
share names legitimately.

### God Object Detection (Kent Beck criteria)

```bash
find core/ -name "*.py" -not -path "*__pycache__*" -exec wc -l {} + | sort -rn | head -10
```

- Large files are candidates for responsibility tracing, not automatic splits.
- `grep -c "^def " FILE` counts top-level function declarations, not responsibilities.
  Trace callers, state ownership, and reasons to change before proposing a split.

### Parameter Bloat Detection

```bash
grep -rn "def __init__" core/ --include="*.py" -A20 | grep -B1 "def __init__" | head -20
# Review call-site cohesion; parameter count alone is not a finding.
```

## Phase 2: Triage

| Classification | Criteria | Action |
|----------------|----------|--------|
| **Deletion candidate** | No textual imports found | Apply the agent anti-pattern deletion gate |
| **Refactoring** | Multiple proven responsibilities or drift paths | Use the smallest extraction that removes the failure |
| **Defer** | Planned for future use, or requires large-scale changes | Kanban Backlog |

## Phase 3: Module Extraction Patterns

### Circular Import Prevention

Trace dependency direction before extraction. A deferred back-import can hide
the cycle rather than remove it; do not bypass a package boundary that way.
Use [naming conventions §1 and §6](../../../docs/architecture/naming-conventions.md)
for ownership and the limited reasons to defer an import.

### Thin Wrapper (Delegation Function)

Keep a wrapper only for a named compatibility consumer and one canonical
implementation. If only symbol identity must be preserved, prefer the existing
explicit re-export pattern instead of introducing another function.

### re-export (ruff F401 prevention)

```python
from core.cli.tool_handlers import _build_tool_handlers as _build_tool_handlers
```

## Phase 4: Verification

Preserve a surviving check for every affected behavior or invariant after
deletion. Follow the [verification reference](../geode-workflow/references/verification-gates.md)
for scope and evidence reuse; do not run a full suite merely to report an audit.
Use `scripts/preflight.sh` when broad checks are warranted and report all skips.

## GEODE Proven Results

| Task | Lines Reduced |
|------|---------------|
| Inline handler deletion (dead code) | -898 lines |
| 6 dead modules deleted | -1,243 lines |
| 5 dead tests deleted | -1,064 lines |
| God Object splitting (pipeline_executor + report_renderer) | -786 lines |
| **Total** | **-3,991 lines** |

## Anti-patterns

1. **Searching imports by basename** → false positives (e.g., "repl" matching the string "REPL")
2. **Treating shared names as duplicate behavior** → trace callers before changing either implementation
3. **Not deleting originals after refactoring** → the most dangerous pattern; old version called from serve, leading to lengthy debugging
4. **Reinstalling or restarting as an audit side effect** → require an in-scope deployment request and verify the installation/process owner first

For dead-code or test-deletion decisions, follow
`.agents/skills/agent-anti-pattern/references/field-guide.md`. Zero textual
imports, file size, parameter count, and test-only callers are insufficient on
their own; check entrypoints, registries, public exports, persisted state, and
compatibility contracts first.
