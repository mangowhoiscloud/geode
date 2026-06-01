---
title: DESIGN.md · `/geode/self-improving/autoresearch/baseline/` (Baseline Viewer)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/autoresearch/baseline/` (Baseline Viewer)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Renders the current `baseline.json` (schema v2) as a human-readable inspector. Each namespace becomes a section.

## 2. Data sources

| Source | Used for |
|---|---|
| `docs/self-improving/autoresearch/baseline.json` | Main render |
| `docs/self-improving/autoresearch/baseline_archive.jsonl` | "Previous baseline" link (last N=5) |

## 3. Sidebar `.active`

`Autoresearch > Baseline`

## 4. Sections (matches baseline.json v2 namespaces)

1. **Metadata** — schema_version / session_id / gen_tag / commit / ts_utc
2. **raw** — dim_means / dim_stderr / sample_count / rubric_version / eval_archive (+ sha256) / measurement_modality
3. **normalized** — dim_scores / stability_score / missing_dims / stability_axis_n_eligible
4. **axes** — ux_means / admire_means / bench_means
5. **fitness** — value / formula_version / weights / components (critical_min / auxiliary_mean / info_mean / stability_axis)
6. **audit** — audit_seconds / target_model / judge_model / auditor_model + harness chips / seed_limit / dim_set / max_turns / usd_spent
7. **promotion** — promote_rule_fired / margin / N / previous_baseline_ref

## 5. Per-section table treatment

For each namespace, render `<table class="records">` with:

```
key                value
key                value
...
```

`dim_means` / `dim_scores` / etc. are dicts — render as 22-row tables with dim name + value (color-coded by petri convention: high=warm, low=cool).

## 6. Models with chips

The `audit` namespace's auditor_model / target_model / judge_model → harness chips per master DESIGN.md §3.

## 7. Empty state

If `baseline.json` absent: `<em>No live baseline. Run <code>uv run python core/self_improving/train.py --promote</code>.</em>`

If `baseline.json` is the legacy `.outdated-*` artifact: rendered, but page banner warns "This is a stale snapshot."

## 8. Outgoing links

- "Previous baselines (archive)" → `/geode/self-improving/autoresearch/baseline/archive` (separate page from `baseline_archive.jsonl`)
- "Mutation that produced this baseline" → `/geode/self-improving/autoresearch/mutations/<mut_id>` (cross-link via `promotion.previous_baseline_ref`)

## 9. Verification checklist

- [ ] All 7 namespaces render even if some are empty
- [ ] Models carry harness chips
- [ ] Dim means / scores tables show all 22 dims (no truncation)
- [ ] Stale baseline shows warning banner
