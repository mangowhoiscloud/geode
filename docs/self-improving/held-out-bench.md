# Held-out bench — version-frozen fixed ruler for the cross-generation curve (E2)

Reproducibility record for the **version-frozen held-out bench** the
self-improving loop scores against EVERY cycle to capture a fitness-vs-generation
curve on a FIXED ruler. The bench directory itself (`state/seed-pools/held-out/`)
is a gitignored runtime artefact (`.gitignore` `state/*`); this file is the
git-tracked record that makes it reproducible — its content identity, the runs it
was assembled from, and the launch wiring the operator uses.

## Why a held-out bench

The cycle-input pool (`docs/self-improving/cycle-input-pool.md`) supplies
**selection pressure** and **co-evolves** — the seed-generation co-scientist
grows/replaces adversarial seeds alongside the agent, so the fitness it produces
is a *moving ruler*: useful for ranking candidates WITHIN a generation (the
`(1+1)` accept/revert decision), NOT for comparing fitness ACROSS generations.

The held-out bench is the complement: a directory of frozen seeds the mutator /
seed-generation loop NEVER touches. Scoring the agent on this fixed set every
cycle yields a `held_out_fitness` whose values ARE comparable across generations
— the only curve that counts as evidence of real improvement. It is assembled
from runs **disjoint** from the cycle-input pool so the held-out seeds never
leaked into the selection signal.

## 1. Frozen bench identity

| Field | Value |
|-------|-------|
| Content hash | `pool-c16d186178e1` |
| Total survivors | 16 (5 + 5 + 2 + 4) |
| Selection mode | `explicit` (`manifest.json` `selection_mode`) |
| Selected runs | `gen-2605-1-redundant_tool_invocation`, `gen-2605-2-redundant_tool_invocation`, `gen1-redundant_tool_invocation`, `gen1-broken_tool_use` |
| Seeds root | `docs/self-improving/petri-bundle/seeds` (git-tracked SoT) |
| Schema version | 1 (`manifest.json` `schema_version`) |

**Disjointness** — the cycle-input pool is `gen-2605-4` + `gen-2605-3`; the
held-out bench is `gen-2605-1` + `gen-2605-2` + both `gen1-*` runs. The two sets
share **zero** survivor bodies, so the fixed ruler is uncontaminated by the seeds
that drive selection.

### Survivor ids (16)

`gen-2605-2-redundant_tool_invocation` (`gen-2605-2`) — 5 survivors:
`gen-2605-2-000-3eccf591`, `gen-2605-2-003-ac89a36e`, `gen-2605-2-005-451e6063`,
`gen-2605-2-006-e869ae30`, `gen-2605-2-008-ff906419`.

`gen-2605-1-redundant_tool_invocation` (`gen-2605-1`) — 5 survivors:
`gen-2605-1-001-b0a469ea`, `gen-2605-1-002-3f2cef5b`, `gen-2605-1-006-21d2c52b`,
`gen-2605-1-008-fa28b643`, `gen-2605-1-011-00818a03`.

`gen1-redundant_tool_invocation` (`gen1`) — 2 survivors:
`gen1-000-83b2299b`, `gen1-001-56634935`.

`gen1-broken_tool_use` (`gen1`) — 4 survivors:
`gen1-000-a047886e`, `gen1-001-d4b78b3d`, `gen1-003-dbbfc17c`, `gen1-004-46ce8bd3`.

Each survivor body is copied into the bench as `<survivor_id>.md`. The source
bodies are git-tracked under
`docs/self-improving/petri-bundle/seeds/<run_id>/candidates/` (or
`candidates_evolved/`), so the bench is reproducible from a clean clone.

## 2. Reproduce the bench

Run from the repository root. `--select-runs` pins the EXACT run set (explicit
mode — `--runs` is ignored). `--now` only stamps the manifest's `generated_at`;
it does not affect the content hash (the deterministic core never reads the
clock). `--force` wipes a pre-existing dir so the copy is a clean snapshot.

```bash
uv run python scripts/assemble_seed_pool.py \
  --select-runs gen-2605-1-redundant_tool_invocation,gen-2605-2-redundant_tool_invocation,gen1-broken_tool_use,gen1-redundant_tool_invocation \
  --out state/seed-pools/held-out \
  --now 2026-05-30T00:00:00+00:00 \
  --force
```

Expected stdout:

```
Assembled seed pool: state/seed-pools/held-out
  content hash : pool-c16d186178e1
  total seeds  : 16
  selection    : explicit
  generated_at : 2026-05-30T00:00:00+00:00
  runs         :
    - gen-2605-2-redundant_tool_invocation (gen-2605-2): 5 survivors
    - gen-2605-1-redundant_tool_invocation (gen-2605-1): 5 survivors
    - gen1-redundant_tool_invocation (gen1): 2 survivors
    - gen1-broken_tool_use (gen1): 4 survivors
```

If the printed `content hash` is **not** `pool-c16d186178e1`, the frozen survivor
set changed (a run was added/pruned, or survivor bodies edited) — STOP and
re-pin a new hash, rather than scoring against a drifted "frozen" ruler. The
`held_out_bench_id` recorded in every cycle row IS this content hash, computed by
`seed_pool_content_hash` on the live bench dir: it hashes ONLY the seed `.md`
bodies (the assembler's `manifest.json` — and its `generated_at` timestamp — is
excluded), so the recorded id equals this pin even though the live dir also holds
`manifest.json`, and re-assembling the same survivor bodies always reproduces it
regardless of the manifest timestamp. A silent body edit thus surfaces as an id
change in the curve.

## 3. Launch wiring — `GEODE_HELD_OUT_BENCH`

The held-out bench is resolved by `core/self_improving/train.py` `_resolve_held_out_bench`
with this precedence (mirroring `_resolve_seed_select` **minus** the
`latest_pointer.json` auto-pick tier — the held-out ruler must never move):

1. `GEODE_HELD_OUT_BENCH` env var (per-run override; wins unconditionally).
2. `AUTORESEARCH_HELD_OUT_BENCH` env var (alias).
3. `[self_improving_loop.autoresearch] held_out_bench` in `config.toml`.
4. `None` → no held-out bench configured → per-cycle scoring is skipped entirely
   (zero overhead, backward-compatible).

The resolver returns the value verbatim as the bench path, so it must be an
**absolute** path (the autoresearch run process may have a different CWD than the
repo root). Export it relative to the repo root via `${HOME}` (no hardcoded user
home is committed here):

```bash
# Repo root on this machine, e.g. ${HOME}/workspace/geode
export GEODE_REPO="${HOME}/workspace/geode"
export GEODE_HELD_OUT_BENCH="${GEODE_REPO}/state/seed-pools/held-out"
```

The repo-relative bench path is always `<repo-root>/state/seed-pools/held-out`.
Confirm the bench exists (and matches the hash) before launching:

```bash
ls "$GEODE_HELD_OUT_BENCH"/manifest.json
```

## 4. What gets recorded, and where

When a bench is configured, EVERY cycle (not just promotes) runs a second audit
on the frozen bench and records the result:

- **`core/self_improving/state/mutations.jsonl`** — the per-cycle `kind="attribution"`
  row gains `held_out_fitness` (canonical 0-1 `compute_fitness`, HIGHER-is-better)
  and `held_out_bench_id`. Ordered by `ts`, these rows ARE the cross-generation
  curve. This is the curve SoT the hub renders.
- **`core/self_improving/state/baseline_archive.jsonl`** — on a promote, the
  `kind="baseline"` row also carries `held_out_fitness` + `held_out_bench_id` so
  the promoted baseline records its fixed-ruler fitness.

Both fields are omitted from every row when no bench is configured, so the
no-bench path is byte-for-byte the legacy shape.

> Cost note: each scored cycle runs a SECOND full audit (the frozen bench is a
> different seed set), so it spends additional audit quota. The `None` default is
> the zero-cost path; configure the bench only when the cross-generation curve is
> worth the per-cycle second audit.
