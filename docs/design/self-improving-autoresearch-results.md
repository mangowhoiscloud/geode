---
title: DESIGN.md · `/geode/self-improving/autoresearch/results/` (Results)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/autoresearch/results/` (Results)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Renders `results.tsv` (12-col header per `RESULTS_TSV_HEADER` in `core/self_improving/train.py:1284`) and `results.jsonl` (full per-dim signal). One row per generation/iteration.

## 2. Data sources

| Source | Used for |
|---|---|
| `docs/self-improving/autoresearch/results.tsv` | Main table |
| `docs/self-improving/autoresearch/results.jsonl` | Per-row drill-down (full dim breakdown) |

## 3. Sidebar `.active`

`Autoresearch > Results`

## 4. Sections

1. **Summary** — total iterations, last fitness, last promote
2. **Results table** — all rows of `results.tsv`
3. **Per-row drill-down** (HTML `<details>`) — full dim-by-dim score breakdown from corresponding `results.jsonl` line

## 5. Results table

12 columns from `RESULTS_TSV_HEADER`. Need to grep actual list from `train.py:1284`. Likely:

```
gen_tag, ts_utc, fitness, critical_min, auxiliary_mean, info_mean,
stability_axis, ux_part, admire_part, bench_part, dim_part, verdict
```

(Verify against code before implementing.)

Column treatment:
- numeric cols right-aligned
- gen_tag bolded
- verdict color-coded
- fitness col gets sparkline `▁▂▃▄▅▆▇█` showing Δ vs previous row

## 6. Drill-down

For each row, expand to:
- `dim_means` from results.jsonl (22-row table)
- `dim_stderr` (22-row)
- `measurement_modality` (judge_llm / token_count / tool_log per dim)

## 7. Empty state

`<em>No iterations recorded yet.</em>`

## 8. Verification checklist

- [ ] Real column count matches actual `RESULTS_TSV_HEADER` (12 — confirm)
- [ ] results.jsonl row count == results.tsv row count
- [ ] Numeric formatting (4 decimal places for fitness, 2 for parts)
- [ ] Sparkline renders via Unicode block chars (no SVG)
