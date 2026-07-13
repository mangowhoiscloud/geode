---
name: slop-audit
visibility: public
triggers: slop, dead code, unused, audit, duplicate, todo, noqa, stale
description: 6-lens slop prevention audit — unused imports, dead private fns, duplicate signatures, abandoned TODOs, lint bypass markers, stale refs. Baseline-gated growth check.
---

# Slop Prevention Audit

Recurring 6-lens scan of `core/` / `plugins/` / `scripts/` to catch the patterns that accumulate during long PR
sequences and rot codebase health when nobody is grepping for them.

## When to run

- **Per session, before the final PR merges.** Catches inline duplicates
  + dead helpers introduced during a sprint.
- **After a large refactor / removal PR.** Surfaces stale references
  to the removed feature in unrelated files.
- **CI advisory mode.** `python scripts/slop_audit.py --check` against
  the committed baseline emits a non-zero exit when any lens count
  grew; informational, not gating.

## The 6 lenses

| # | Lens | What it surfaces | Severity tier |
|---|------|------------------|---------------|
| 1 | `unused_imports` | `ruff F401` — module imports never referenced. | warning |
| 2 | `dead_private_functions` | `def _foo(...)` with zero in-file callers. | warning if >10 |
| 3 | `duplicate_signatures` | Same function name defined in ≥3 files (lift-to-helper signal). | info |
| 4 | `abandoned_todos` | `TODO/FIXME/XXX` without owner `(name)` or `YYYY-MM-DD` date. | warning if >5 |
| 5 | `lint_bypass_markers` | `# noqa` + `# type: ignore` count (ratchet against baseline). | info |
| 6 | `stale_references` | Known-removed names that re-appear in source (`BudgetGuard`, `seeds_safe10`, etc.). | error if >0 |

Severity is **diagnostic** — the script's `--check` mode only compares
counts against the baseline, so growth of any tier-info metric is
still surfaced as a CI failure.

## Reading the output

```bash
uv run python scripts/slop_audit.py
```

Emits a markdown report with the count table + first 5 samples per
lens. Inspect samples for patterns:

- **unused_imports samples in tests/** → leftover after a refactor.
  Auto-fix: `uv run ruff check --fix --select F401`.
- **dead_private_functions in agent files** → a helper that was
  extracted but never called. Either inline at the one caller or
  remove.
- **duplicate_signatures = "init"/"build"/etc.** → expected
  framework method. duplicate_signatures = "parse_critique" with 4
  copies → lift to `agents/base.py`.
- **abandoned_todos** → add owner `(@handle)` or remove. The convention
  is `# TODO(@user, 2026-05-18): ...`.
- **stale_references = N** for any N > 0 → fix in the same PR as the
  feature removal; allowing it to land merges the rot.

## Workflow

```bash
# First run (after PR 0/1/2 land) — generates the canonical baseline
uv run python scripts/slop_audit.py --baseline-out scripts/slop_audit_baseline.md

# Subsequent CI advisory checks
uv run python scripts/slop_audit.py --check
```

The baseline file is checked into `docs/audits/`. Refresh the
baseline (and the timestamp in the filename) whenever an
intentional cleanup PR reduces a count — the goal is **monotone
non-growth**, not zero (some lint_bypass markers, e.g. the bandit
SHA1 nosec, are intentional and stay forever).

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
