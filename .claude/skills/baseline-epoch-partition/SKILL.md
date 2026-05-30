---
name: baseline-epoch-partition
description: Content-addressed baseline-archive epoch partitioning. Partition baseline_archive.jsonl + the self-improving hub's baseline serving by a HASH of the full baseline-production+measurement spec — when the spec (margin_rule, fitness/margin logic version, the 4 roles' model+source, rubric/dim-set, bench, seed-pool identity) changes, the hash changes → a new epoch series (like seed-gen gen-*). Triggered by "baseline epoch", "baseline 아카이빙", "epoch partition", "spec hash", "content-addressed", "margin_rule namespace", "production logic 구분", "baseline 하위 서빙" keywords.
user-invocable: false
---

# Baseline Epoch Partition — Content-Addressed Baseline Archiving

> **Source**: operator design 2026-05-30 ([[project_baseline_archive_partition_plan]] · [[project_per_mutator_partition_plan]]).
> **Philosophy**: baselines produced under different production logic are **not comparable** — partition them, never average across the boundary. The boundary is the *spec*, and the spec is *content-addressed* so the discriminator can't drift.
> **Builds on**: the v0.99.89 registry (`autoresearch/train.py:_append_baseline_registry_row`, `baseline_archive.jsonl`) which already records `margin_rule` + `role_provenance`.

## When this applies

Every promote appends a `kind="baseline"` row to the git-tracked
`autoresearch/state/baseline_archive.jsonl`. Those rows must be partitioned into
**epochs** — like seed-generation's `gen-*` series — keyed by the production
logic, and the self-improving hub serves them **under a `baseline` section,
grouped by epoch**. This skill specifies how the epoch discriminator is computed
and recorded, so a future baseline lands in the right partition automatically and
deterministically (no LLM, no manual epoch bump).

## Core principle — the epoch IS a hash of the spec

```
epoch_hash = sha256(canonical_json(baseline_spec))[:12]
```

`baseline_spec` is the **production + measurement surface** that determines
comparability. When any field changes, the hash changes → a new epoch begins on
its own. Same spec → same hash, always (deterministic, reproducible, cross-machine
stable). The discriminator is derived from the spec, so it can never lie about
what produced the baseline.

## The spec field-set (what is hashed)

Hash a **fixed, enumerated** field-set — the *surface* (how a baseline is made),
NEVER the *instance* (the baseline's measured values):

```jsonc
baseline_spec = {
  "spec_schema_version": "1",          // the field-set version itself (see A)
  "margin_rule": "fitness-stderr"|"dim-stderr",
  "margin_logic_version": "<tag>",     // bumped when _should_promote margin math changes
  "fitness_formula_version": "<tag>",  // bumped when compute_fitness semantics change
  "rubric_version": "<PETRI_RUBRIC_VERSION>",
  "dim_set": "<name>",
  "bench": false,
  "roles": {                            // model + source per role (lane is derived, not hashed)
    "auditor": {"model": ..., "source": ...},
    "target":  {"model": ..., "source": ...},
    "judge":   {"model": ..., "source": ...},
    "mutator": {"model": ..., "source": ...}
  },
  "seed_pool_id": "<pool content-hash>" // decision B — the pool IDENTITY, not bodies
}
```

**EXCLUDED (instance, not spec)** — never hash these: `dim_means`, `fitness`,
`fitness_stderr`, the specific seed bodies, `ts_utc`, `session_id`, `commit`,
`seed_count`. They vary per run; including them would make every run its own
epoch and destroy the partition.

## Four robustness rules (do not skip)

1. **Spec vs instance.** Hash the surface (logic versions + config + role
   bindings + pool identity), not the results. The registry row still stores the
   instance fields separately; only the spec sub-object is hashed.
2. **Version-tags, not source-hash, for code.** Fitness formula + margin logic
   are code — hashing their source churns the epoch on a comment edit. Instead
   carry deliberate constants (`FITNESS_FORMULA_VERSION`, `MARGIN_LOGIC_VERSION`)
   bumped on *semantic* change, and a guard test that FAILS if the logic changed
   without a version bump (under-sensitivity defense — pin a golden fitness value
   per version).
3. **Canonical serialization.** `json.dumps(spec, sort_keys=True,
   separators=(",", ":"))` → `sha256` → first 12 hex. Order/format must not move
   the hash.
4. **Hash + human label.** The raw hash is the SoT discriminator; it is not
   readable on the hub. Assign a human `epoch_label` (`be-001`, `be-002`, … in
   hash-first-seen order, persisted in an epoch-label map) for display, like
   `gen-2605-*`. Store both on the row.

## Resolved sub-decisions

- **(A) Write-time frozen hash + schema version — no retroactive recompute.**
  Each row stores its `epoch_hash` computed *at write time* plus the `baseline_spec`
  it was computed from plus `spec_schema_version`. The hash is **immutable per
  row** — never recomputed. Adding a field to the spec field-set is a deliberate
  `spec_schema_version` bump; because `spec_schema_version` is itself hashed, old
  rows (schema 1) and new rows (schema 2) fall into different epochs naturally
  (correct — the *definition* of a baseline changed). No migration churns old
  hashes. Rationale: immutable content-addressing; a stored row is self-verifying
  (recompute hash from its stored spec → must equal stored `epoch_hash`).
- **(B) Seed-pool identity is in the spec.** Different seeds → different measured
  dims → non-comparable, so the seed pool is part of the measurement surface.
  Include `seed_pool_id` = the pool's **content-hash** (a stable identity of the
  survivor set), NOT the raw bodies. A seed-pool change ⇒ new epoch. Ties to the
  deterministic seed-pool assembly (which emits the pool content-hash).

## What each registry row records

Augment `_append_baseline_registry_row` to add: `baseline_spec` (the hashed
sub-object), `spec_schema_version`, `epoch_hash`, `epoch_label`. The existing
`margin_rule` + `role_provenance` are folded INTO `baseline_spec` (no
duplication — keep them top-level too for back-compat readers, but the canonical
comparability key is `epoch_hash`).

## Hub serving (Phase 2-4)

Serve baselines under a top-level **`baseline`** section, grouped by `epoch_hash`,
each epoch rendered as a sub-series (like a `gen-*` run): `epoch_label` as the
series name + a one-line spec summary (margin_rule · models · pool) + a dense
table of that epoch's baselines (`baseline-id · ts · fitness · fitness_stderr ·
verdict`). Mirror `scripts/build_self_improving_hub.py:_render_seedgen_index_rows`
(dense table + sidebar, NO card-grid / accent-bar slop — [[feedback_no_box_ui_no_emoji]]).
Never render two epochs in one comparison table (the whole point is they are not
comparable).

## Determinism + guards (must ship with the impl)

- `test_epoch_hash_deterministic` — same spec dict → same hash across calls.
- `test_epoch_hash_changes_on_each_surface_field` — flipping any spec field
  changes the hash; flipping an instance field (dim_means/fitness) does NOT.
- `test_logic_version_guard` — a golden fitness value per `FITNESS_FORMULA_VERSION`
  (and margin behavior per `MARGIN_LOGIC_VERSION`); fails if the code changed
  without the version bump.
- `test_row_self_verifies` — recompute `epoch_hash` from the row's stored
  `baseline_spec` → equals stored `epoch_hash`.
- `test_canonical_serialization` — key order / whitespace does not move the hash.

## The general pattern (reuse)

This is content-addressed epoch partitioning: **partition a ledger by a hash of
the spec that defines comparability, store hash + label, serve grouped by hash.**
It generalizes to per-mutator partitioning ([[project_per_mutator_partition_plan]])
and mirrors seed-generation's `gen-*` series. Apply the same four robustness rules
whenever a ledger needs logic-keyed partitions.
