# Baseline schema history (archive)

Lossless record of every baseline-related schema GEODE's self-improving loop
has used, so a baseline measured under an older schema is never silently
mis-read and the design provenance of the current schema is preserved.

The **active anchor** is `state/self_improving/baseline.json` (the most recently
promoted baseline). The **registry** is `state/self_improving/baseline_archive.jsonl`
(one append-only `kind="baseline"` row per promotion — the hub's baseline index
reads it). The two are separate SoTs: the anchor answers "what does the loop
compare against right now"; the registry answers "what baselines have existed,
under what measurement criteria".

---

## 1. `baseline.json` — active anchor

### v1 (flat, legacy — pre 2026-05-23)
```
{ "dim_means": {dim: float},
  "dim_stderr": {dim: float},
  "ux_means":     {field: float},   # SUPERSEDED — removed 2026-05-30
  "admire_means": {field: float},
  "bench_means":  {field: float} }
```
Read by `_load_baseline` (still consumed for backward-compat; a stale flat
`ux_means` is ignored).

### v2 (namespace-split, current — PR-2 of petri-schema-v2, 2026-05-23)
```
{ "schema_version": 2, "session_id": ..., "commit": ..., "ts_utc": ...,
  "raw": {
    "dim_means": {dim: float}, "dim_stderr": {dim: float},
    "sample_count": {dim: int}, "measurement_modality": {dim: str},
    "fitness_stderr": float,          # ADDED PR-MARGIN-FITNESS-SCALE (2026-05-30)
    "eval_archive": "<path>"|null, "rubric_version": "v3-22dim-PR0" },
  "axes": {
    "admire_means": {field: float}|null,
    "bench_means":  {field: float}|null }   # ux_means axis REMOVED 2026-05-30
  # optional: manual_promote / promoted_by / promoted_at (operator override stamp) }
```

**Removed axis — `ux_means`** (PR-MARGIN-FITNESS-SCALE, 2026-05-30): the behaviour
metric axis (success_rate / token_cost_norm / revert_ratio_norm / latency_norm)
gave the promote gate no usable signal (collector returned `{}` on cycle 0) and
complicated the margin redesign. Fitness reverted to a pure Petri dim aggregate
plus the reserved `admire_means` / `bench_means` axes.

---

## 2. `baseline_archive.jsonl` — registry rows

### Phase 1 row (`feature/baseline-registry @69b9d95f`, SUPERSEDED — never merged)
```
{ "kind": "baseline", "id": "baseline-<YYMM>-<seq>", "ts_utc": ..., "commit": ...,
  "session_id": ..., "promoted_by": ...,
  "fitness": float,                 # intrinsic (baseline_means=None), computed WITH ux_means
  "seed_select": ..., "seed_count": int,
  "auditor_model"/"target_model"/"judge_model"/"mutator_model"/"mutator_source": ...,
  "eval_archive": ..., "dim_means": {dim: float} }
```
Superseded because it (a) carried the now-removed `ux_means` into its intrinsic
fitness, and (b) had **no `margin_rule` / `fitness_stderr` fields** — so two
baselines measured under different promote-gate rules (the dim-stderr margin bug
vs the fitness-stderr fix) could not be told apart, which is exactly the
distinction the registry exists to serve. Its pareto-sibling-row coupling is
also dead (group/Pareto sampling was dropped from develop, 2026-05-29).

### Current row (margin-aware — this PR)
```
{ "kind": "baseline", "id": "baseline-<YYMM>-<seq>", "ts_utc": ..., "commit": ...,
  "session_id": ..., "promoted_by": "gate"|"operator"|"backfill",
  "fitness": float,                 # intrinsic (baseline_means=None), pure Petri dim aggregate
  "fitness_stderr": float|null,     # the audit's fitness-scale σ (bootstrap or MC)
  "margin_rule": "fitness-stderr"|"dim-stderr",   # promote-gate rule in effect — the
                                                  # vanilla(buggy) ↔ margin-fixed discriminator
  "bench": bool,                    # bench axis active (Path C; currently false)
  "seed_select": ..., "seed_count": int,
  # per-role {model, source, lane} for auditor/target/judge/mutator. The
  # credential LANE (PAYG | Subscription | CLI) is load-bearing — the same model
  # id behaves differently per lane — so model + source + lane are all recorded.
  # Shared SoT (core.self_improving_loop.role_provenance) with mutations.jsonl,
  # so the two git-tracked ledgers never drift. Display id: GEODE/{model}/{lane}.
  "role_provenance": { "auditor": {"model": str, "source": str, "lane": str},
                       "target":  {...}, "judge": {...}, "mutator": {...} },
  "eval_archive": "<basename>.eval"|null,   # basename only — the file is git-tracked
  "dim_means": {dim: float} }
```

`source`→`lane`: `api_key`→`PAYG`, `openai-codex`→`Subscription`,
`claude-cli`→`CLI`, `auto`→`Auto`. The **same `role_provenance` block** is
written to every `mutations.jsonl` apply row (every cycle — promote OR reject),
so the credential lane each role ran under is observable without parsing the
`.eval`.

`margin_rule` is the key field: it lets the hub serve the pre-fix `vanilla`
baseline (`margin_rule="dim-stderr"`, the ~75×-too-large margin that produced
the 0-approve run) and the post-fix baseline (`margin_rule="fitness-stderr"`)
side-by-side as a controlled comparison — same seeds/models, only the gate
changed. Live promotes stamp `"fitness-stderr"` (the current code's rule); the
pre-fix vanilla baseline is a one-off backfill stamped `"dim-stderr"`.

---

## References
- ux removal: PR-MARGIN-FITNESS-SCALE (v0.99.88), `docs/adr/ADR-012-self-improvement-surface-tiers.md` §Decision.2 (2026-05-30 amendment).
- v2 namespace: `docs/plans/2026-05-23-petri-schema-v2.md`.
- Phase 1 archived code: `feature/baseline-registry` branch (kept as git archive).
