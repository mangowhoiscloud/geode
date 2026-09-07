---
name: kent-beck-review
description: Code review from the Kent Beck Simple Design 4 Rules perspective. God Object splitting, SRP, duplication removal, naming, cyclomatic complexity. Triggered by "kent beck", "simple design", "simplify", "refactoring" ("리팩토링"), "refactor", "god object", "SRP" keywords.
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

File size identifies inspection candidates, not a split requirement. Trace
responsibilities, callers, and reasons to change before proposing extraction.
Do not carry a dated file-size snapshot forward as current implementation status.

### Method Size & Complexity

Inspect the actual function and its callers. Function length, nesting, and
branch counts do not by themselves justify a Strategy, dispatch table, or new
module. Prefer an early return or an existing helper when it resolves the
identified failure without obscuring domain behavior.

### Reveals Intention

| Anti-pattern | Improvement |
|-------------|-------------|
| `def process(data)` | `def score_analyst_response(response)` |
| `result = fn(x, y, z)` | Use meaningful variable names |
| `# This function does X` | Reveal through function name, remove comment |
| `magic number 0.7` | `CONFIDENCE_THRESHOLD = 0.7` |

### No Duplication

Detect idea-level duplication (not just copy-paste but missing abstractions):

Trace repeated decisions through their shared owner. Unify behavior that must
change together; keep similar-looking paths separate when their contracts differ.
Neither repetition count nor structural similarity alone requires a factory,
Protocol, or generic abstraction.

### Fewest Elements

| Unnecessary Element | Criteria |
|--------------------|----------|
| Unused parameters | Wrappers that only pass `**kwargs` |
| ABC with single implementation | Check the substitution contract; a concrete class may be sufficient |
| Empty `__init__.py` | Check package, distribution, discovery, and import contracts before removal |
| Unused imports | Auto-detected by ruff F401 |

## Scope and Verification

A review does not authorize refactoring. Follow the
[workflow](../../../docs/workflow.md) for requested changes and the
[deletion gate](../agent-anti-pattern/references/field-guide.md#deletion-gate)
before removing code, tests, or package files. Use
[verification gates](../geode-workflow/references/verification-gates.md) for
targeted checks and evidence reuse. Report concrete findings with current
file/line evidence; no finding is preferable to a speculative simplification.
