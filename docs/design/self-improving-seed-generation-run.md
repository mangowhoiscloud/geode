---
title: DESIGN.md · `/geode/self-improving/seed-generation/<run_id>/` (Run Detail)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/seed-generation/<run_id>/` (Run Detail)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Per-run detail page. Renders the full state of one seed-generation run: candidates / survivors / evolved / pilot scores / meta-review. Equivalent to the existing Next.js `/geode/docs/petri/seeds` dashboard's expanded row, but as a standalone static page so each run has a permalink.

Build-time generation: one HTML file per `runs[].run_id`. `scripts/build_self_improving_hub.py` iterates listing.json.

## 2. Data sources

| Source | Used for |
|---|---|
| `docs/self-improving/petri-bundle/seeds/<run_id>/state.json` | Main state (everything except survivors view + meta) |
| `docs/self-improving/petri-bundle/seeds/<run_id>/survivors.json` | Compact survivors |
| `docs/self-improving/petri-bundle/seeds/<run_id>/meta_review.json` | Meta review (also nested in state.json, prefer file) |
| `docs/self-improving/petri-bundle/seeds/<run_id>/candidates/<id>.md` | Per-candidate body (link only, no inline render) |
| `docs/self-improving/petri-bundle/logs/<ts>_seedgen-<phase>_<run_id>.eval` | Per-phase .eval archives (link to SPA viewer) |

## 3. Sidebar `.active`

`Seed Generation > All runs > <run_id>`

## 4. Sections

1. **Header** — run_id (h1), gen_tag + target_dim + mutator (subtitle)
2. **Candidates** — table of all candidates (drafted)
3. **Survivors** — table of survived candidates with Elo + pilot score
4. **Evolved** — table of evolved variants with parent + rewrite_section
5. **Phase .eval cards** — links to SPA per-phase tasks
6. **Reflections** — per-candidate critic output (strengths / weaknesses / discrimination_estimate)
7. **Pilot scores** — dim-mean matrix (candidates × 22 dims)
8. **Meta-review** — session_summary, next_gen_priors, evolution_yield, elo_distribution, coverage
9. **Cost rollup** — total tokens + USD

## 5. Per-section columns

### 5.1 Candidates

| col | source |
|---|---|
| id | `state.candidates[].id` (link → `candidates/<id>.md`) |
| target_dim | `state.candidates[].target_dim` |
| duration | `state.candidates[].duration_ms` (formatted seconds) |
| task_id | `state.candidates[].task_id` (mono) |

### 5.2 Survivors

| col | source |
|---|---|
| id | `state.survivors[]` (anchor to candidate row) |
| elo | `state.elo_ratings[id]` |
| pilot status | `state.pilot_scores[id].status` |
| evolved children | computed from `state.evolved_candidates[].parent_id` |

### 5.3 Evolved

| col | source |
|---|---|
| id | `state.evolved_candidates[].id` |
| parent | `state.evolved_candidates[].parent_id` (link to candidate row) |
| rewrite_section | `state.evolved_candidates[].rewrite_section` |
| notes | `state.evolved_candidates[].notes` (truncated 200 chars) |

### 5.4 Phase .eval cards

For each `.eval` file matching `<ts>_seedgen-<phase>_<run_id>.eval`:

| phase | task name | samples | score (mean) | SPA link |
|---|---|---|---|---|
| `<phase>` | `seed-generation/<phase>` | from listing.json | from listing.json | `↗ /geode/self-improving/petri-bundle/#/tasks/<task_id>` |

### 5.5 Reflections

Card-free dense list, one entry per reflection:

```
[id mono] [judge_risk chip] discrimination=N
  Strengths:
    - ...
  Weaknesses:
    - ...
  Rewrite suggestion: ...
```

### 5.6 Pilot scores

22-column wide `<table>` (or 22-row if fewer candidates). Cells color-coded by score:

- 1 (lowest, safe): `var(--rule-soft)` background
- 2-4: gradient cool
- 5-7: gradient warm
- 8-10: solid warm (deliberate signal — high score means problematic in petri convention)

Color uses bucket palette extension — verify with master DESIGN.md additions if a heatmap added.

### 5.7 Meta-review

- session_summary as paragraph (prose, sans, no truncation)
- next_gen_priors table: target_dim / weight / rationale
- evolution_yield: 2-row dl (attempted / successful)
- elo_distribution: 3-row dl (min / p50 / p95)
- coverage: bar chart (HTML/CSS only, no JS) showing per-dim bars

### 5.8 Cost rollup

```
total USD               state.usd_spent
prompt_tokens           state.prompt_tokens
completion_tokens       state.completion_tokens
literature_snapshots    len(state.literature_snapshots)
debate_transcripts      len(state.debate_transcripts)
iterations              state.current_iteration / state.max_iterations
```

## 6. Empty state

If `state.json` absent: build script writes a single-page error stub linking back to seed-gen index.

## 7. Mutator chip

Above all section tables, prominent banner:

```
mutator     [Claude Code] claude-cli/claude-opus-4-7
```

For now single mutator per run. Future: per-phase mutator if model split lands.

## 8. Verification checklist

- [ ] One HTML page per run_id in listing.json
- [ ] Every survivor link resolves to a candidate row
- [ ] Every evolved.parent_id resolves
- [ ] Phase .eval card count matches actual files in logs/
- [ ] Pilot score color mapping documented
- [ ] Meta-review next_gen_priors table sorts by weight desc
- [ ] Cost rollup math verified against state.json
