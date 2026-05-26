---
title: DESIGN.md · `/seed-generation/<run_id>/lineage/` (Candidate journey)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/seed-generation/<run_id>/lineage/`

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Render each candidate's journey across the 9 phases as a vertical
station list — generator body → critic reflection → debate transcript
→ pilot dim_means → ranker matches → evolver rewrite + body diff. The
operator can trace why any single survivor (or evolved variant) ended
up with its final Elo.

PR-SEEDS-HIRES P3 (2026-05-26). Closes the operator directive: "각
시나리오가 절차순으로 어떻게 변화했는지".

## 2. Source data

All per-candidate data lives in `state.json` + the per-run bundle dir:

| Station | Field |
|---------|-------|
| supervisor | `state.json:supervisor_guidance` (run-wide) |
| generator | `candidates/<cand_id>.md` (body) |
| proximity | `state.json:removed_duplicates[]` (only when this cand was dropped) |
| critic | `state.json:reflections[cand_id]` + `state.json:debate_transcripts[cand_id]` |
| pilot | `state.json:pilot_scores[cand_id]` |
| ranker | `tournament.json:matches[]` filtered by cand_id |
| evolver | `state.json:evolved_candidates[]` where parent_id == cand_id + diff between `<cand>.md` and `<evolved>.md` |

## 3. URL layout

- `/geode/self-improving/seed-generation/<run_id>/lineage/` — index
  table of candidates with chip-list of stations visited.
- `/geode/self-improving/seed-generation/<run_id>/lineage/<cand_id>/` —
  per-candidate detail.

## 4. Per-candidate layout

Top header: `<dl>` with candidate id + station count + back-link to
lineage index.

Body: vertical sequence of `<section class="page-sub
lineage-station">`. Each station has an `<h3>` phase name + body
appropriate to that phase (`<pre>` for raw bodies, `<dl>` for
key/value summaries, `<table>` for pilot scores + ranker matches).

The evolver station carries a unified diff between the parent
candidate body and the evolved variant body, rendered in
`<pre class="diff">`. Uses Python's `difflib.unified_diff` — no
external dep.

## 5. Index layout

Dense table: candidate id link / list of station chips / station count.

## 6. Cotton discipline

- Zero new color tokens. Reuses `--bucket-seedgen` + paper / rule
  tokens; the diff uses `--paper-tint` + `--rule-soft`.
- No JS — diff is pre-rendered at build time.

## 7. Frontier inspiration

- **Inspect_ai sample diff** — the per-sample view shows
  before/after; lineage applies the same pattern to candidate text.
- **PromptLayer / Helicone** prompt diff — same unified-diff
  rendering for "what changed between v1 and v2".

## 8. E2E pins

- `test_pr3_lineage_index_lists_candidates` — original + evolved
  both surface.
- `test_pr3_lineage_detail_renders_stations_and_diff` — ≥4 stations
  + a `<pre class="diff">` block for evolved variants.

## 9. Non-goals

- Cross-run lineage (candidate A in run X → carryover into run Y) —
  carryover surface is owned by the autoresearch outer-loop (PR
  follow-up); the per-run lineage page intentionally stops at one run.
- Interactive station filtering — operator uses Cmd+F.
