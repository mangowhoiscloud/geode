---
name: slop-audit
visibility: public
triggers: slop, dead code, unused, audit, duplicate, todo, noqa, stale
description: 6-lens diagnostic slop audit — unused imports, dead private fns, duplicate signatures, abandoned TODOs, lint bypass markers, stale refs.
---

# Slop Prevention Audit

Recurring 6-lens scan of `core/` / `plugins/` / `scripts/` to catch the patterns that accumulate during long PR
sequences and rot codebase health when nobody is grepping for them.

## When to run

- **Per session, before the final PR merges.** Catches inline duplicates
  and dead-helper candidates introduced during a sprint.
- **After a large refactor / removal PR.** Surfaces stale references
  to the removed feature in unrelated files.
- **Before promotion.** Use it to find review candidates; its counts do not
  decide promotion.

## The 6 lenses

| # | Lens | What it surfaces | Severity tier |
|---|------|------------------|---------------|
| 1 | `unused_imports` | `ruff F401` — module imports never referenced. | warning |
| 2 | `dead_private_functions` | `def _foo(...)` with zero in-file callers. | warning if >10 |
| 3 | `duplicate_signatures` | Same function name defined in ≥3 files (lift-to-helper signal). | info |
| 4 | `abandoned_todos` | `TODO/FIXME/XXX` without owner `(name)` or `YYYY-MM-DD` date. | warning if >5 |
| 5 | `lint_bypass_markers` | `# noqa` + `# type: ignore` count. | info |
| 6 | `stale_references` | Known-removed names that re-appear in source (`BudgetGuard`, `seeds_safe10`, etc.). | error if >0 |

Severity is **diagnostic**. Heuristic absolute counts are not an accepted-debt
floor or promotion contract.

## Reading the output

```bash
uv run python scripts/slop_audit.py
```

Emits a markdown report with the count table + first 5 samples per
lens. Inspect samples for patterns:

- **unused_imports samples in tests/** → leftover after a refactor.
  Auto-fix: `uv run ruff check --fix --select F401`.
- **dead_private_functions in agent files** → same-file textual candidates.
  Check cross-module, registry, entrypoint, and compatibility consumers before
  changing them.
- **duplicate_signatures = "init"/"build"/etc.** → expected framework
  method. Other shared names still require behavior and caller comparison;
  they do not automatically justify a shared helper.
- **abandoned_todos** → add owner `(@handle)` or remove. The convention
  is `# TODO(@user, 2026-05-18): ...`.
- **stale_references = N** for any N > 0 → fix in the same PR as the
  feature removal; allowing it to land merges the rot.

## Workflow

```bash
uv run python scripts/slop_audit.py
```

The original 2026-05-18 absolute-count snapshot is preserved at
`docs/reference/2026-05-18-slop-audit-baseline.md` as historical evidence. It
is not a current pass/fail contract. Ruff, mypy, dependency checks, coverage,
and behavior tests remain the promotion gates.

Treat all six lenses as discovery signals. Before deleting code or tests, use
the deletion gate in `.agents/skills/agent-anti-pattern/references/field-guide.md`.

## Stale-reference list

`scripts/slop_audit.py` maintains `_STALE_REFS` — a tuple of names
that should not re-appear in production code after their removal PR.
Current list:

- `BudgetGuard` (removed PR 1)
- `SUBAGENT_BUDGET_WARNING` (removed PR 1)
- `seeds_safe10` (renamed PR 0)
- `FitnessBaseline` (removed S9)

Add a new entry whenever you remove a public surface. The lens
ignores `docs/` and `CHANGELOG.md` so historical prose stays
documented.
