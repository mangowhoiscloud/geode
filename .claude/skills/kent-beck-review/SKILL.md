---
name: kent-beck-review
description: Code review from the Kent Beck Simple Design 4 Rules perspective. God Object splitting, SRP, duplication removal, naming, cyclomatic complexity. Triggered by "kent beck", "simple design", "simplify", "refactoring" ("리팩토링"), "refactor", "god object", "SRP" keywords.
user-invocable: false
---

# Kent Beck Code Review Lens

> "Make the change easy, then make the easy change."

## Four Rules of Simple Design (in priority order)

1. **Passes tests** — Tests pass
2. **Reveals intention** — Names and structure reveal intent
3. **No duplication** — Eliminate idea-level duplication
4. **Fewest elements** — Minimal components

## Review Checklist

### File Size

```bash
# Detect 500+ line files (God Object candidates)
find core/ -name "*.py" -exec wc -l {} + | sort -rn | head -20
```

Criteria:
- 500+ lines: Consider splitting
- 1000+ lines: Immediate splitting required
- GEODE status: `cli/__init__.py` (2800+ lines) splitting already in progress

### Method Size & Complexity

```bash
# Detect 50+ line functions
grep -n "def " core/ -r --include="*.py" | while read line; do
  echo "$line"
done

# Detect nesting depth 4+
grep -rn "if\|for\|while\|with\|try" core/ --include="*.py" | grep -c "        " # 4 indent levels
```

Criteria:
- Function 50+ lines: Consider extraction
- Nesting 4+ levels: Early return or extraction
- 10+ branches: Strategy pattern or dispatch table

### Reveals Intention

| Anti-pattern | Improvement |
|-------------|-------------|
| `def process(data)` | `def score_analyst_response(response)` |
| `result = fn(x, y, z)` | Use meaningful variable names |
| `# This function does X` | Reveal through function name, remove comment |
| `magic number 0.7` | `CONFIDENCE_THRESHOLD = 0.7` |

### No Duplication

Detect idea-level duplication (not just copy-paste but missing abstractions):

```bash
# Repeated similar patterns
grep -rn "def _call_llm_" core/ --include="*.py"  # 3 similar functions per provider
grep -rn "def _build_" core/runtime.py  # 10+ similar builder patterns
```

Criteria:
- 3+ repetitions: Consider extraction
- Structural similarity: Consider unification via Protocol/generics

### Fewest Elements

| Unnecessary Element | Criteria |
|--------------------|----------|
| Unused parameters | Wrappers that only pass `**kwargs` |
| ABC with single implementation | Protocol is sufficient |
| Empty `__init__.py` | Remove if no re-exports |
| Unused imports | Auto-detected by ruff F401 |

## GEODE Codebase Existing Findings

| Item | File | Status |
|------|------|--------|
| `cli/__init__.py` 2800+ lines | L0 | Splitting in progress (repl.py, commands.py extracted) |
| `agentic_loop.py` 1400+ lines | L0 | `_process_tool_calls` 88 lines — extraction candidate |
| `runtime.py` 1400+ lines | DI | 10+ `_build_*` builders — pattern unification candidate |
| `policy.py` 430 lines | L4 | Within acceptable range |
