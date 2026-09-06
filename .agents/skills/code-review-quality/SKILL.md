---
name: code-review-quality
description: Python code quality review lens. SOLID principles, dead code, exception handling, resource leaks, thread safety, performance. Triggered by "quality" ("품질"), "SOLID", "dead code" ("데드코드"), "exception", "resource leak", "thread safety" keywords.
---

# Code Review Quality Lens

Review quality issues from 6 perspectives that automated tools miss.

## Check 1: Dead Code Detection

```bash
# Unused imports
uv run ruff check core/ --select F401

# Unused variables
uv run ruff check core/ --select F841

# Residual TODO/FIXME/HACK
grep -rn "TODO\|FIXME\|HACK\|XXX" core/ --include="*.py"

# Empty function bodies (stubs with only pass)
grep -rn "def.*:" core/ --include="*.py" -A1 | grep -B1 "^\s*pass$"
```

## Check 2: Exception Handling Anti-patterns

```bash
# Empty except blocks (swallowing exceptions)
grep -rn "except.*:" core/ --include="*.py" -A1 | grep -B1 "^\s*pass$"

# Catch-all Exception (overly broad except)
grep -rn "except Exception" core/ --include="*.py" | grep -v "# noqa"

# Bare except (except without type)
grep -rn "except:" core/ --include="*.py"
```

Rules:
- Empty except: At minimum log, or wrap and re-raise
- except Exception: Must state legitimate justification
- Bare except: Prohibited — specify at minimum the Exception type

## Check 3: Resource Leak Detection

```bash
# File handles (without with statement)
grep -rn "open(" core/ --include="*.py" | grep -v "with " | grep -v "# noqa"

# subprocess handles not collected
grep -rn "subprocess\.Popen" core/ --include="*.py" | grep -v "with "

# Temporary files not cleaned up
grep -rn "tempfile\.\|NamedTemporaryFile\|mktemp" core/ --include="*.py"
```

Rule: All `Closeable` must be wrapped with `with` statement

## Check 4: Thread Safety

```bash
# Global mutable state
grep -rn "^[A-Z_]*\s*=\s*\[\|^[A-Z_]*\s*=\s*{" core/ --include="*.py" | grep -v "frozenset\|tuple\|Final"

# Shared state modification without Lock
grep -rn "threading\.\|asyncio\.\|concurrent\." core/ --include="*.py"

# ContextVar usage patterns
grep -rn "ContextVar\|contextvars" core/ --include="*.py"
```

GEODE context:
- `core.wiring` composes services through constructors/configuration or typed
  contexts such as `ToolContext`; a service-locator `ContextVar` is not the DI contract.
- Request-local `ContextVar` use does not prove mutable values are isolated or
  that context propagates across every thread/task boundary. Trace the actual
  producer, handoff, mutation, and reset paths.
- For a module-level dict/list, establish whether concurrent mutation exists
  and which owner serializes it before recommending a lock or immutable type.

See [architecture boundaries](../../../docs/architecture/naming-conventions.md#12-process-and-capability-boundaries).

## Check 5: SOLID Principles

| Principle | Discovery candidates, not violations | Detection |
|-----------|-------------------|-----------|
| **SRP** | 500+ line files, classes with 5+ responsibilities | `wc -l core/**/*.py \| sort -rn \| head` |
| **OCP** | if/elif chains with 10+ branches | grep -rn "elif" count |
| **LSP** | NotImplementedError in subclasses | grep -rn "NotImplementedError" |
| **ISP** | Protocol with 10+ methods | Trace actual Protocol consumers |
| **DIP** | Import bypassing a declared package/capability boundary | Check the current import-linter contracts |

These source/size heuristics need caller and failure evidence. Concrete-class
imports are valid when no declared boundary or substitution contract is bypassed.
Use the [field guide](../agent-anti-pattern/references/field-guide.md) before
deleting code/tests or introducing an abstraction.

## Check 6: Performance

```bash
# N+1 pattern (I/O inside loops)
grep -rn "for.*in.*:" core/ --include="*.py" -A5 | grep "\.get\|\.fetch\|\.call\|\.execute"

# Unnecessary list creation (generator possible)
grep -rn "\[.*for.*in.*\]" core/ --include="*.py" | grep -v "test"

# Redundant computation (repeated calls to same function)
# (requires manual review)
```
