---
title: DESIGN.md · `/seed-generation/<run_id>/timeline/` (Procedure)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/seed-generation/<run_id>/timeline/`

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Phoenix-style nested span list — every procedure each agent followed
during the run, organised by phase. The 9 phases of a
seed-generation run (supervisor → literature_review → generator →
proximity → critic → pilot → ranker → evolver → meta_reviewer)
become `<section>` blocks; each section nests its sub-agent fan-out
+ filtered hook events.

PR-SEEDS-HIRES P2 (2026-05-26). Closes the operator directive: "every
procedure each agent followed".

## 2. Source data

- `transcript.jsonl` — every run-level hook event (`PHASE_STARTED`,
  `PHASE_FINISHED`, `SUBAGENT_STARTED`, `SUBAGENT_COMPLETED`,
  `LLM_CALL_ENDED`, `TOOL_EXEC_STARTED`, etc.).
- `per_phase_costs.json` — `{<phase>: {cost_usd, prompt_tokens,
  completion_tokens, duration_ms, agent_count}}`.
- `sub_agents/<task_id>/session.json` — to bucket sub-agents into
  phases.

All three ship via PR-SEEDS-HIRES P1 (bundle_sync extension).

## 3. URL layout

- `/geode/self-improving/seed-generation/<run_id>/timeline/`

## 4. Layout

Top: one short `<p class="muted">` describing the source files.

Body: a vertical sequence of `<section class="page-sub phase-block">`
per phase. Each section:

- `<h3>` phase name
- `<p class="muted">` with duration + cost + sub-agent count
- `<details><summary>sub-agents (N)</summary>` collapsed `<ul>` of
  links to `/agent/<task_id>/`
- `<details><summary>hook events (M)</summary>` collapsed `<ul>` of
  the first 8 matching transcript events

Phases missing from both `per_phase_costs.json` and `transcript.jsonl`
are skipped (the run never ran that phase).

## 5. Frontier inspiration

- **Phoenix** OTel span tree — vertical nested spans grouped by
  trace; same layout, but rendered as plain HTML `<section>` +
  `<details>` (no JS span library).
- **Langfuse** observations panel — per-phase `<details>` is
  equivalent to a per-observation drawer.

## 6. E2E pin

- `test_pr2_timeline_shows_all_known_phases` — page contains every
  one of the 9 phase names.

## 7. Non-goals

- Span-graph (parent/child links across phases) — current sub-agent
  hierarchy is flat (depth=1 per AgenticLoop design).
- Live tailing — see PR-SEEDS-HIRES P3.
