# Cycle-input seed pool — frozen selection for the upcoming 10-cycle (B2)

Reproducibility record for the **frozen selection pool** the upcoming
self-improving 10-cycle audits against. The pool directory itself
(`state/seed-pools/cycle-input/`) is a gitignored runtime artefact
(`.gitignore` `state/*`); this file is the git-tracked record that makes that
pool reproducible — its content identity, the runs it was assembled from, and
the launch wiring the operator uses.

The pool is **not** an LLM output and carries no randomness:
`scripts/assemble_seed_pool.py` selects runs by a stable `gen_tag` sort key (not
filesystem mtime) and copies git-tracked survivor bodies into a flat dir, so
re-running the exact invocation below on the same seeds tree always reproduces
the same pool with the same content hash.

---

## 1. Frozen pool identity

| Field | Value |
|-------|-------|
| Content hash | `pool-68dc6f0c9745` |
| Total survivors | 10 (5 + 5) |
| Selected runs | `gen-2605-4-unfaithful_thinking` (`gen-2605-4`), `gen-2605-3-broken_tool_use` (`gen-2605-3`) |
| Seeds root | `docs/self-improving/petri-bundle/seeds` (git-tracked SoT) |
| Schema version | 1 (`manifest.json` `schema_version`) |

The two runs are the two most-recent by descending `gen_tag` sort key
`(stamp, counter)`: `(2605, 4)` then `(2605, 3)`. Selection order is preserved
in the pool's copy order and in the survivor lists below.

### Survivor ids (10)

`gen-2605-4-unfaithful_thinking` (target dim: unfaithful_thinking) — 5 survivors:

- `gen-2605-4-003-e2b9759a`
- `gen-2605-4-004-c4e5770b`
- `gen-2605-4-005-29c3f084`
- `gen-2605-4-009-1ceb75e0`
- `gen-2605-4-010-91e734c9`

`gen-2605-3-broken_tool_use` (target dim: broken_tool_use) — 5 survivors:

- `gen-2605-3-002-59743f9d`
- `gen-2605-3-003-8ddb31d0`
- `gen-2605-3-005-0ce25ac8`
- `gen-2605-3-006-6ecf2412`
- `gen-2605-3-013-fd6b0d2b`

Each survivor body is copied into the pool as `<survivor_id>.md`. The source
bodies live under `docs/self-improving/petri-bundle/seeds/<run_id>/candidates/`
(or `candidates_evolved/`) and are git-tracked, so the pool is reproducible from
a clean clone.

---

## 2. Reproduce the pool

Run from the repository root. `--now` only stamps the manifest's
`generated_at`; it does not affect the content hash (the deterministic core
never reads the clock). `--force` wipes a pre-existing pool dir so the copy is a
clean snapshot.

```bash
uv run python scripts/assemble_seed_pool.py \
  --runs 2 \
  --out state/seed-pools/cycle-input \
  --now 2026-05-30T00:00:00+00:00 \
  --force
```

Expected stdout:

```
Assembled seed pool: state/seed-pools/cycle-input
  content hash : pool-68dc6f0c9745
  total seeds  : 10
  generated_at : 2026-05-30T00:00:00+00:00
  runs         :
    - gen-2605-4-unfaithful_thinking (gen-2605-4): 5 survivors
    - gen-2605-3-broken_tool_use (gen-2605-3): 5 survivors
```

If the printed `content hash` is **not** `pool-68dc6f0c9745`, the survivor set
changed (a run was added/pruned, or survivor bodies edited) — STOP and
re-pin a new hash before launching, rather than auditing against a drifted pool.

---

## 3. Launch wiring — `AUTORESEARCH_SEED_SELECT`

The 10-cycle is wired to this pool via the `AUTORESEARCH_SEED_SELECT` env
export, which is **tier-1 precedence** in `core/self_improving/train.py`
`_resolve_seed_select` (it beats the `latest_pointer.json` auto-pick, the
`config.toml` `[self_improving_loop.autoresearch] seed_select`, and the
`SEED_SELECT` module constant). The env export wins unconditionally, so the
operator pins this exact pool for the run without editing
`core/config/self_improving_loop.py`.

`_resolve_seed_select` returns the env value verbatim as the seed-select argv,
so it must be an **absolute** path (the autoresearch run process may have a
different CWD than the repo root). Export it relative to the repo root via
`${HOME}` (no hardcoded user home is committed here):

```bash
# Repo root on this machine, e.g. ${HOME}/workspace/geode
export GEODE_REPO="${HOME}/workspace/geode"
export AUTORESEARCH_SEED_SELECT="${GEODE_REPO}/state/seed-pools/cycle-input"
```

The repo-relative pool path is always:

```
<repo-root>/state/seed-pools/cycle-input
```

Substitute `<repo-root>` for wherever the GEODE checkout lives on the launch
machine. Confirm the pool exists (and matches the hash) before launching:

```bash
ls "$AUTORESEARCH_SEED_SELECT"/manifest.json
```

> Wiring note: this record deliberately does **not** touch
> `core/config/self_improving_loop.py` — a committed config pointer would
> conflict with parallel held-out-bench work on that file and is also
> unnecessary, since `AUTORESEARCH_SEED_SELECT` is the highest-precedence
> override and is the documented per-run handoff used by the seed-generation
> cross-loop.
