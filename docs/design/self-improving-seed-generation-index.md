---
title: DESIGN.md · `/geode/self-improving/seed-generation/` (Index)
geode_version: 0.99.63
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.63"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/seed-generation/` (Index)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Lists every seed-generation run as a row. Cross-cuts the existing per-run JSON published under `docs/self-improving/petri-bundle/seeds/` (relocated). Promote seed-generation to a top-level surface in the hub (sibling to petri-bundle).

## 2. Data sources

| Source | Used for |
|---|---|
| `docs/self-improving/petri-bundle/seeds/listing.json` | Run catalog (kind=seeds, runs[]) |
| Per-run `docs/self-improving/petri-bundle/seeds/<run_id>/state.json` | (lazy-loaded if user expands row) |
| `docs/self-improving/petri-bundle/seeds/<run_id>/meta_review.json` | Same |

## 3. Sidebar `.active`

`Seed Generation > All runs`

## 4. Sections

1. **Runs** — full table of seed-generation runs, sorted newest first
2. **Phases legend** — explainer of the 8 pipeline phases (supervisor → generator → ... → meta_reviewer)
3. **Cost rollup** — total spend across all runs

## 5. Runs table columns

Same schema as Hub's Seed Generation section plus:

| Column | Source field |
|---|---|
| run_id | `runs[].run_id` (anchor → per-run page) |
| gen_tag | `runs[].gen_tag` |
| target_dim | `runs[].target_dim` |
| mutator | `claude-cli/claude-opus-4-7` (current default) — chip + mono |
| draft → surv | `runs[].candidates_drafted` → `runs[].survivors_count` |
| evolved | `runs[].evolved_count` |
| iterations | `runs[].iterations` / `runs[].max_iterations` |
| cost | `runs[].usd_spent` $ |
| phases | count of non-empty phase `.eval` files (cross-ref `logs/listing.json` filter `task` starts with `seed-generation/`) |
| created | best-effort from per-run `state.json.started_at` or file mtime |

## 6. Phases legend section

Static `<dl>`:

| Phase | What it does |
|---|---|
| `supervisor` | Strategic guidance for the gen (target dims, scoping). 1 LLM call. |
| `generator` | Drafts N candidate seeds. N LLM calls in parallel. |
| `proximity` | Dedupes near-duplicates via similarity clustering. No LLM. |
| `critic` | Per-candidate reflection: strengths / weaknesses / discrimination_estimate. N calls. |
| `pilot` | Runs each candidate through a small audit, returning per-dim mean scores. Cost-heavy. |
| `ranker` | Pairwise tournament with judge panel to rank candidates by Elo. |
| `evolver` | Mutates top survivors into new variants. Jaccard guard. |
| `meta_reviewer` | Coverage report + next_gen_priors for the next iteration. 1 call. |

## 7. Cost rollup section

`<dl class="cost-grid">` aggregating across runs:

```
total USD       sum(runs[].usd_spent)
prompt_tokens   sum(runs[].prompt_tokens)
completion_tk   sum(runs[].completion_tokens)
runs            count
```

## 8. Empty state

`<em>No runs published yet. Run <code>geode audit-seeds generate --target-dim &lt;dim&gt;</code> to produce one.</em>`

## 9. Verification checklist

- [ ] Reads real listing.json
- [ ] Phases count column matches actual `.eval` files in logs/
- [ ] Cost rollup math correct (verify against listing.json sums)
- [ ] Each run_id is a `<a>` to per-run detail page
- [ ] Phases legend has 8 entries
