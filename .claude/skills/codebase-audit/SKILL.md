---
name: codebase-audit
description: Codebase audit + refactoring workflow. Dead code detection, God Object splitting, duplicate function removal, design flaw identification, frontier comparison verification. Triggered by "audit" ("감사"), "dead code" ("데드코드"), "refactor" ("리팩토링"), "god object", "duplication" ("중복"), "design flaw" ("설계 결함") keywords.
user-invocable: false
---

# Codebase Audit & Refactoring Workflow

A systematic workflow for auditing and improving the entire codebase.
Proven in the GEODE v0.24.0 session (3,205 lines reduced, __init__.py -57%).

## Workflow

```
1. Audit
   → Dead code + duplicates + God Object + Parameter Bloat detection
2. Triage
   → Verdict: immediate deletion / refactoring / defer
3. Kanban Registration
   → Register in Backlog by priority
4. Workspace Isolation
   → Worktree isolation
5. Implementation + Verification
   → Delete/extract/convert then lint + test
6. Docs-sync + main
   → CHANGELOG, progress.md, global reinstall
```

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
        echo "DEAD: $f ($(wc -l < $f) lines)"
    fi
done
```

Note: Search by **full module path**, not basename, to prevent false positives.

### Duplicate Function Detection

```bash
grep -rn "^def " core/ --include="*.py" | awk -F: '{split($NF,a," "); print a[2]}' | sort | uniq -c | sort -rn | head -10
```

If identically named functions exist in 2+ locations, **it is impossible to know which one is called until runtime** — a design flaw.

### God Object Detection (Kent Beck criteria)

```bash
find core/ -name "*.py" -not -path "*__pycache__*" -exec wc -l {} + | sort -rn | head -10
```

- 500+ lines: Consider splitting
- 1000+ lines: Split immediately
- `grep -c "^def " FILE` to determine the number of responsibilities

### Parameter Bloat Detection

```bash
grep -rn "def __init__" core/ --include="*.py" -A20 | grep -B1 "def __init__" | head -20
# 7+ parameters = refactoring candidate
```

## Phase 2: Triage

| Classification | Criteria | Action |
|----------------|----------|--------|
| **Immediate deletion** | 0 imports, only tests exist | Delete file + tests |
| **Refactoring** | 500+ lines, 3+ responsibilities | Module extraction |
| **Defer** | Planned for future use, or requires large-scale changes | Kanban Backlog |

## Phase 3: Module Extraction Patterns

### Circular Import Prevention

```python
# When the new module references a function from the original module → deferred import
def extracted_function():
    from core.cli import _original_helper  # lazy import inside function
    return _original_helper()
```

### Thin Wrapper (Delegation Function)

When the original module must continue exporting the extracted function:

```python
# core/cli/__init__.py
def _build_tool_handlers(**kwargs):
    """Delegate to tool_handlers (single source)."""
    from core.cli.tool_handlers import _build_tool_handlers as _build
    return _build(**kwargs)
```

### re-export (ruff F401 prevention)

```python
from core.cli.pipeline_executor import _run_analysis as _run_analysis  # explicit re-export
```

## Phase 4: Verification

```bash
# 1. Lint
uv run ruff check core/

# 2. Type check (changed files only)
uv run mypy core/cli/__init__.py core/cli/new_module.py

# 3. Full test suite
uv run pytest tests/ -m "not live" -q

# 4. Tests for deleted modules → import error → delete those tests too
```

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
2. **Leaving duplicate functions** → impossible to know which is called until runtime
3. **Not deleting originals after refactoring** → the most dangerous pattern; old version called from serve, leading to lengthy debugging
4. **Assuming `uv tool install . --force` is sufficient** → `--reinstall` may be required in some cases
