# `core/self_improving/state/_archive/` — baseline-epoch snapshots

Epoch-boundary snapshot location for the self-improving loop.
Content-addressed by the baseline **epoch label** `be-NNN` (assigned by
`core/self_improving/loop/baseline_epoch.py` — `resolve_epoch_label`,
keyed on the `sha256` of the full baseline production + measurement spec:
`margin_rule` + fitness/margin logic version + the 4 roles' model/source +
rubric/dim-set + bench + seed-pool identity).

## Convention

When a spec change opens a **new** baseline epoch
(`resolve_epoch_label(...)` returns `is_new=True`), the PRIOR epoch's full
production surface is frozen here as an immutable record:

```
core/self_improving/state/_archive/<prior-be-NNN>/
  policies/            # the 5+ mutation-target SoT JSONs at the epoch boundary
  baseline.json        # the promoted fitness baseline (the epoch's final state)
  pool-identity.txt    # the seed-pool content hash the epoch was measured on
```

A new epoch means the fitness/margin numbers are no longer comparable to the
prior epoch's (the ruler changed), so the prior epoch's surface is frozen
rather than overwritten — mirroring the seed-generation `gen-*` series.

## Status (PR-STATE-SELF-IMPROVING-RENAME, 2026-06-01)

The convention is **documented**; the auto-snapshot-on-epoch-change is
**deferred** (TODO marked at `core/self_improving/train.py`, in the
`if _epoch_is_new:` branch). Rationale: adding snapshot I/O inside the promote
write path risks the promote itself — a copy failure must not abort a
gate-approved promote. The snapshot should run as a separate, post-promote
step (campaign driver or operator command) so the promote write stays
single-responsibility.

## Git tracking

This `_archive/` dir lives under the in-repo TRACKED SoT
(`core/self_improving/state/`), so post PR-STATE-SOT-RUNTIME-SPLIT no
`.gitignore` negation dance is needed. Epoch snapshots are immutable VERSIONED
records of the production surface at each ruler change — when the deferred
auto-snapshot lands, `_archive/<be-NNN>/` payloads are git-tracked alongside the
`baseline_archive.jsonl` history they index (the runtime LATEST `baseline.json`
stays out-of-repo under `~/.geode/self-improving/`).
