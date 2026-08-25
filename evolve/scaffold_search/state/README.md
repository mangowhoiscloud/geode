# `evolve/scaffold_search/state/` — tracked self-improving SoT (PR-STATE-SOT-RUNTIME-SPLIT, 2026-06-14)

In a GEODE checkout, this directory is the **git-tracked Source of Truth** for
the self-improving (autoresearch) loop: the versioned inputs and ledgers a
reviewer must see across runs. A wheel contains only read-only reference policy
inputs; rolling ledgers are not package data, and mutation/promotion requires a
writable checkout selected by `GEODE_EVOLVE_WORKSPACE`.

The companion **RUNTIME scratch** (per-run execution traces, the LATEST baseline,
handoff pointers, logs) lives OUT of the repo under `~/.geode/self-improving/`
(machine-local, never in git) so a clone/worktree never scatters runtime files
into history nor loses them on `git clean`.

## What lives here (tracked, in-repo)

```
evolve/scaffold_search/state/
├── README.md                  (this file)
├── mutations.jsonl            mutation audit ledger (git-as-optimiser trail)
├── baseline_archive.jsonl     promoted baseline-history registry
├── baseline_epochs.json       epoch_hash → be-NNN label map
├── results.tsv                rolling 12-column run results (S10 + P1a)
├── results.jsonl              rolling raw 18-dim per-row results
├── policies/                  mutation-target SoT JSONs (wrapper-sections, tool-policy, …)
├── seed_pools/                repo-pinned LOCATION for campaign INPUT pools
│                              (cycle-input/ + held-out/ assembled by
│                              scripts/assemble_seed_pool.py; committed when pinned)
└── _archive/README.md         epoch-boundary archive convention doc
```

## What lives at `~/.geode/self-improving/` (runtime, out-of-repo)

```
~/.geode/self-improving/                 (= core.paths.RUNTIME_ROOT)
├── baseline.json              the LATEST promoted baseline (vs the tracked archive)
├── run.log                    captured train.py stdout
├── wrapper-override.json      per-run wrapper-prompt override dump
├── campaign/
│   ├── gen-0-snapshot/        matched-reset frozen baseline snapshot
│   └── runs/<run_id>.json     S4 resume checkpoints
├── handoff/
│   ├── latest_pointer.json    forward pointer to the freshest survivor pool
│   └── sessions.jsonl         cross-run registry, append-only
└── seed_generation/<run_id>/  per-run seed-gen artefacts (candidates, survivors, elo_log, …)
```

## The two roots in `core.paths`

| Constant | Lifecycle | Default |
|----------|-----------|---------|
| `SELF_IMPROVING_SOT_DIR` / `AUTORESEARCH_STATE_DIR` | TRACKED/read-only in a wheel | `$GEODE_EVOLVE_WORKSPACE/evolve/scaffold_search/state/`, or bundled reference inputs for reads only |
| `SEED_POOLS_DIR` | TRACKED (always repo-pinned) | `evolve/scaffold_search/state/seed_pools/` |
| `RUNTIME_ROOT` | RUNTIME | `~/.geode/self-improving/` |
| `BASELINE_JSON_PATH` | RUNTIME | `~/.geode/self-improving/baseline.json` |

## `GEODE_STATE_ROOT` — worker isolation

When `GEODE_STATE_ROOT` is set (a campaign fans path-independent workers out as
isolated `train.py` subprocesses), BOTH the tracked SoT and the runtime root
collapse to `$GEODE_STATE_ROOT/autoresearch/` so each worker's reads/writes land
in its own seeded tree (`campaign._seed_isolated_state_root` lays out
`<root>/autoresearch/{policies/, baseline.json}` to match). Seed pools are the one
exception — ALWAYS repo-pinned, so an isolated worker still reads the real
tracked input pools. With the env unset (orchestrator / serve / CLI) the in-repo
↔ `~/.geode` split above applies.

The `core.paths` module reads `GEODE_STATE_ROOT` / `GEODE_HOME` once at import.
