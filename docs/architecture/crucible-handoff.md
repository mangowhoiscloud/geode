# Crucible historical handoff tombstone

> Superseded on 2026-07-10 by
> [`crucible-kernel.md`](crucible-kernel.md). This file is intentionally not an
> execution checklist or source of truth.

The former handoff described the July G0-G7 campaign, temporary branches,
account windows, candidate-specific tau2 switches, and local artifact paths.
Those details became stale and encouraged three experimental errors:

- runtime candidate ladders accumulated inside the harness;
- rows from different candidate revisions were combined;
- exposed task failures were repaired and reused as if they remained held out.

The associated telecom workflow variants, retail projectors, prompt guards,
post-hoc surrogate gates, and sequential-gate scripts have been removed from
the active implementation. Their code and detailed run history remain
recoverable through git and archived artifacts when incident reconstruction is
needed.

Current work starts only from the frozen kernel:

```text
search head SHA
  -> standalone candidate producer
  -> one candidate manifest
  -> trusted paired evaluator
  -> KEEP / REJECT / INVALID
  -> append-only supervisor ledger
```

The adaptive loop lives in `plugins.crucible.supervisor` and has no import
connection to `core/self_improving`. Train `KEEP` advances only the loop-local
search head. Core promotion authority remains closed.

The historical campaign provides train counterexamples and infrastructure
incidents. It provides no sealed-test authority and no evidence that any
current candidate should be promoted to core.
