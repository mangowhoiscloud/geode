---
title: DESIGN.md · `/geode/self-improving/autoresearch/` (Landing)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/autoresearch/` (Landing)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Landing page for the autoresearch surface — the closed-loop self-improvement engine. Surfaces 4 sub-views (baseline / mutations / results / policies) plus a generation timeline.

**Critical**: autoresearch artifacts are NOT currently mirrored into `docs/petri-bundle/` or `docs/self-improving/`. Phase 6 of the sprint MUST add a publisher (`plugins/autoresearch/bundle_sync.py` or similar) that mirrors:

| Runtime SoT | Bundle mirror destination |
|---|---|
| `state/self_improving/baseline.json` | `docs/self-improving/autoresearch/baseline.json` |
| `state/self_improving/baseline_archive.jsonl` | `docs/self-improving/autoresearch/baseline_archive.jsonl` |
| `state/self_improving/mutations.jsonl` | `docs/self-improving/autoresearch/mutations.jsonl` |
| `state/self_improving/policies/*.json` | `docs/self-improving/autoresearch/policies/*.json` (14 files) |
| `autoresearch/results.tsv` | `docs/self-improving/autoresearch/results.tsv` |
| `autoresearch/results.jsonl` | `docs/self-improving/autoresearch/results.jsonl` |

Publisher trigger: end-of-iteration hook in `core.self_improving_loop.runner` after `_apply_mutation` commits a new baseline.

## 2. Sidebar `.active`

`Autoresearch` (root, no sub highlighted)

## 3. Sections

1. **Status** — current baseline summary + last write timestamps for each artifact
2. **Generation timeline** — recent rows from baseline_archive.jsonl with fitness delta
3. **Sub-views** — 4 cards (no card-lifts) linking to baseline / mutations / results / policies sub-pages

## 4. Status section columns

`<dl class="status-grid">`:

```
current baseline      gen-N (from baseline.json.metadata.gen_tag)
fitness               from baseline.json.fitness.value
last promote          baseline.json.promotion.timestamp
auditor model         baseline.json.audit.auditor_model + harness chip
target model          baseline.json.audit.target_model + harness chip
judge model           baseline.json.audit.judge_model + harness chip
mutations.jsonl       row count + last write timestamp
results.tsv           row count + last write timestamp
policies/             14 files + last touched timestamp
```

If `baseline.json` absent or marked `.outdated`, status block prepends a red banner: `<div class="warning">No live baseline. Latest known: baseline.json.outdated-YYYYMMDD.</div>`

## 5. Generation timeline section

Table from `baseline_archive.jsonl`:

| col | source |
|---|---|
| gen_tag | `row.gen_tag` |
| ts | `row.ts_utc` |
| fitness | `row.fitness.value` |
| Δ fitness | computed vs previous row |
| mut summary | `row.mutation.target_section` (truncated) |
| audit models | `row.audit.{auditor,target,judge}_model` + harness chips |

Sort: newest first. Highlight current baseline row with `.active` styling.

## 6. Sub-view cards

4 rows in a `<table class="records">` (NOT card grid):

| sub-page | rows | link |
|---|---|---|
| Baseline | 1 (current baseline state) | `/geode/self-improving/autoresearch/baseline/` |
| Mutations | N (from mutations.jsonl) | `/geode/self-improving/autoresearch/mutations/` |
| Results | N (from results.tsv) | `/geode/self-improving/autoresearch/results/` |
| Policies | 14 files | `/geode/self-improving/autoresearch/policies/` |

## 7. Empty states

| Scenario | Treatment |
|---|---|
| `baseline.json` missing | Status block reads "no baseline yet — run <code>uv run python core/self_improving/train.py --promote</code>" |
| `baseline_archive.jsonl` 0 rows | timeline section empty table |
| All artifacts missing | landing reads "autoresearch publisher not yet wired — see <code>plugins/autoresearch/bundle_sync.py</code>" |

## 8. Verification checklist

- [ ] Publisher exists and runs on autoresearch iteration completion
- [ ] All 4 sub-pages exist and link from landing
- [ ] Status reflects real baseline.json fields
- [ ] Generation timeline sourced from baseline_archive.jsonl
- [ ] Stale baseline (`.outdated-*`) handled gracefully
- [ ] Models in audit row carry harness chips
