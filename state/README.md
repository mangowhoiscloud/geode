# `state/` — autoresearch + seed_generation cross-run state (CSP-7, 2026-05-22)

Machine-portable replacement for the pre-CSP-7
`~/.geode/self-improving-loop/` + `~/.geode/seed-generation/`
directories. The path layout ships with the repository so a clone on a
fresh host immediately knows where artefacts live; runtime artefacts
themselves stay `.gitignore`-d under `state/*` and never enter git
history.

## Layout

PR-STATE-AUTORESEARCH-RENAME (2026-06-01, Scheme A) — the autoresearch
optimization loop's state (ledgers + policies) lives under
`state/autoresearch/`, with the cross-run handoff NESTED at
`state/autoresearch/handoff/` (was the separate top-level
`state/self-improving-loop/`, an underscore/hyphen near-synonym twin
with the `state/self_improving/` ledger dir of #1955 — both folded into
one root here). `seed-generation/` is renamed to `seed_generation/` to
match the plugin package `plugins/seed_generation/`.

```
state/
├── .gitkeep                          (directory marker)
├── README.md                         (this file)
├── autoresearch/                     self-improving (autoresearch) loop state
│   ├── mutations.jsonl               git-tracked mutation audit ledger
│   ├── baseline_archive.jsonl        git-tracked baseline-history registry
│   ├── baseline_epochs.json          epoch_hash → be-NNN label map
│   ├── policies/                     git-tracked mutation-target SoT JSONs
│   ├── _archive/README.md            epoch-boundary archive convention doc
│   └── handoff/                      CSP-7 cross-run handoff (machine-local)
│       ├── latest_pointer.json       forward pointer (replaces latest_seed_pool
│       │                             + latest_meta_review.json symlinks)
│       └── sessions.jsonl            run-level registry, append-only
└── seed_generation/
    └── <run_id>/                     per-run artefacts
        ├── state.json                Pipeline.run() offload snapshot
        ├── candidates/*.md           Generator output
        ├── candidates_evolved/*.md   Evolver output
        ├── survivors/*.md            Ranker top-K (file copies — was
        │                              pre-CSP-7 symlinks)
        ├── survivors.json            survivor metadata (Elo + pilot)
        ├── meta_review.json          standalone copy of state.meta_review
        ├── elo_log.tsv               per-match Elo history
        └── proximity_log.tsv         (when proximity phase ran)
```

## Pointer file (`autoresearch/handoff/latest_pointer.json`)

Stamped at the end of every `geode audit-seeds generate` run by
`plugins.seed_generation.orchestrator.Pipeline._write_latest_pointer`.
Read by:

- `autoresearch.train._resolve_seed_select` — auto-picks the freshest
  survivor pool for the next audit.
- `plugins.seed_generation.baseline_reader._default_latest_meta_review_path`
  — loads previous run's `next_gen_priors` for the next generator.

Schema:

```json
{
  "version": 1,
  "run_id": "gen2-broken_tool_use",
  "gen_tag": "gen2",
  "updated_at": "2026-05-22T01:00:00Z",
  "seed_pool":   "seed_generation/gen2-broken_tool_use/survivors",
  "meta_review": "seed_generation/gen2-broken_tool_use/meta_review.json"
}
```

Paths are `STATE_ROOT`-relative so the same JSON file works under any
machine's `GEODE_STATE_ROOT` (default: `<repo_root>/state`).

## Overriding the location (CI / limited workspace)

Set `GEODE_STATE_ROOT` to redirect everything under this directory:

```bash
GEODE_STATE_ROOT=/scratch/geode-state geode audit-seeds generate ...
```

The `core.paths` module reads the env var once at import time.

## Why not git-track runtime artefacts?

Runtime artefacts (candidate `.md` bodies, Elo logs, pointer files)
are *machine-local execution traces*. Committing them would:

- Bloat git history (kilobytes per candidate × hundreds of candidates × N runs).
- Create merge conflicts on `latest_pointer.json` between branches.
- Mask the actual source-level diff during reviews.

The path *convention* lives in the repo (this README + `core.paths`
constants); the *content* belongs to whichever machine ran the
pipeline. Operators that want to archive a specific run still can —
just `tar -czf` the `state/seed_generation/<run_id>/` directory.
