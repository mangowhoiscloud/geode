---
title: DESIGN.md · `/geode/self-improving/autoresearch/mutations/` (Mutations Ledger)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/autoresearch/mutations/` (Mutations Ledger)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Renders the full `mutations.jsonl` as a table. Each row = one mutation proposed + applied. Schema W4 (2026-05-25): ApplyRecord with attribution rows.

## 2. Data sources

| Source | Used for |
|---|---|
| `docs/self-improving/autoresearch/mutations.jsonl` | Main render (line-per-row) |

## 3. Sidebar `.active`

`Autoresearch > Mutations`

## 4. Sections

1. **Filter strip** — by gen_tag / target_section / verdict (`applied` / `reverted`)
2. **Mutations table** — all rows, newest first
3. **Per-row drill-down** (HTML `<details>`) — full payload as `<pre>` JSON

## 5. Mutations table columns

| col | source field | notes |
|---|---|---|
| ts_utc | `row.ts_utc` | ISO short |
| gen_tag | `row.gen_tag` | mono |
| mut_id | `row.mutation_id` | mono, anchor for `<details>` |
| target_section | `row.mutation.target_section` | e.g. `wrapper-sections.json::sycophancy_guardrail` |
| kind | `row.mutation.kind` | one of: rewrite / append / delete / etc. |
| mutator model | `row.mutator.model` | harness chip + mono |
| verdict | `row.verdict` | applied (green) / reverted (red) / pending (muted) |
| Δfitness | `row.fitness_delta` | ±N.NN (color-coded ±) |
| audit ref | `row.attribution.audit_eval_id` | link to SPA task viewer |

## 6. Per-row `<details>` content

When expanded:

```
Mutation payload:        full JSON dict
Audit attribution:       audit_eval_id + auditor/target/judge chips + dim deltas
Cost:                    cost_judge_tokens + cost_target_tokens + cost_seconds
```

## 7. Empty state

`<em>No mutations recorded. Run <code>uv run python core/self_improving/train.py</code>.</em>`

## 8. Verification checklist

- [ ] Renders every line of mutations.jsonl
- [ ] Audit ref links resolve in SPA viewer
- [ ] Δfitness color-coding (positive green, negative red, noise muted)
- [ ] Mutator model carries harness chip
- [ ] Filter strip works (or is documented as Phase-2 feature)
