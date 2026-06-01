---
title: DESIGN.md · `/geode/self-improving/autoresearch/evidence/` (Evidence)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-30
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/autoresearch/evidence/` (Evidence)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

ONE honest evidence page — methods + results + power — that a skeptical reader uses
to judge a single question: **does scaffold-selection actually improve safety
fitness?** This is EVIDENCE, not presentation. `0 promotions` is a
TRUST-INCREASING result (a loop that promotes nothing on null evidence is behaving
correctly) and the page states it plainly. Where a matched campaign has not run
yet, the page renders an honest "awaiting" / "no evidence yet" state — never a
fabricated curve, never a placeholder number (CLAUDE.md: measured values only).

This is the hub-SERVING synthesis endpoint for the evidence track. The interactive
per-cycle held-out curve still renders on the Mutations page (E2-wire's
`_render_held_out_curve`); this page is the comprehensive synthesis.

## 2. Data sources (recorded ledgers only)

| Source | Used for |
|---|---|
| `state/self_improving/mutations.jsonl` (attribution rows) | per-cycle `held_out_fitness` curve PER ARM (`promote_policy`), `gain_ci_excludes_zero` / `gain_verdict` / `gain_ci_low` / `gain_ci_high` verdicts, `within_mutation_stderr` + `between_seed_stderr` for the power σ |
| `state/self_improving/baseline_archive.jsonl` (`kind="baseline"` rows) | promotion count PER ARM (`promote_policy`), per-promote gain verdict |

Pre-E1 mixed-scale rows (`fitness_before > 1.0`) are excluded from aggregates
(reuses the E1b heuristic). The held-out fields are read directly (they are already
on the canonical 0-1 fitness scale).

## 3. Sidebar `.active`

`Autoresearch > Evidence`

## 4. Sections

1. **Methods** — the experimental design, honestly: the FROZEN held-out ruler (E2,
   `held_out_bench_id`) vs the pinned SELECTION pool (B2, `pool-68dc6f0c9745`); the
   3 ARMS (E3: gate / random / never); per-mutation REPLICATE + the ci-excludes-0
   rule (E4); REPRODUCIBILITY pins (E5: prompt_hash / applied_diff / sampling_params
   / rng_seed); content-addressed EPOCH partition (A). Explains WHY (the
   co-evolving-ruler problem — only the held-out curve is evidence; cross-arm
   comparison isolates selection from drift / judge-noise).
2. **Results** — the per-cycle `held_out_fitness` curve PER ARM, the 3-arm
   comparison on the fixed ruler (mean held-out fitness + promotion count per arm),
   and the per-cycle / per-campaign `gain_ci_excludes_zero` verdict. Dense tables.
   Honest empty state per arm when no cycle recorded.
3. **Power** — the required `N_seed × M_replicate` line computed from the recorded
   σ (`√(within²+between²)`) at δ=0.02, α=0.05, 80% power (the formula mirrors
   `core/self_improving_loop/statistical_power.py::required_samples`) + the honest
   verdict ("no evidence yet" when the gain CI includes 0; "indeterminate" when σ is
   unrecorded — never a fabricated N).

## 5. Renderer

`scripts/build_self_improving_hub.py::render_autoresearch_evidence` →
`docs/self-improving/autoresearch/evidence/index.html`. Section bodies:
`_render_evidence_methods` / `_render_evidence_methods_arms` /
`_render_evidence_results` / `_render_evidence_verdict` / `_render_evidence_power`.
The stdlib power-formula mirror `_required_n_seed` + the arm map `_EVIDENCE_ARMS`
are kept in lockstep with core by drift-guard tests.

## 6. No-slop

Dense `<table class="records">` + `<dl class="status-grid">` only. No card grid, no
colored `border-left` accent bar, no emoji, no `XXXX` placeholder. Verified by
`tests/test_self_improving_hub_e2e.py::test_evidence_page_no_slop`.
