---
title: Package classification during runtime/eval/evolve convergence
status: transitional
decision: BND-001 / R1.1, superseded for final placement by BND-009 / R8.5
authority: package-classification
related:
  - docs/architecture/extensibility-roadmap.md
  - docs/architecture/domain-free-core-audit.md
  - site/src/data/geode/architecture-baseline.json
---

# Package classification during runtime/eval/evolve convergence

The architecture roadmap is the authority for status, ordering, and
implementation permission. Its active BND-009 claim replaces the older
`core`/`geode_product` final-boundary decision with this target:

```text
evolve (Crucible and scaffold search)
  -> evals (Petri, benchmarks, seed generation, GEO)
    -> core (GEODE runtime)
```

This document classifies the current checkout while that migration remains
`IN_PROGRESS`; it does not advance the roadmap status.

## Current ownership during implementation

| Surface | Current role | BND-009 target |
|---|---|---|
| `core/` | GEODE runtime | remains `core/` |
| `evals/` | measurement, Petri, benchmark, seed-generation, and GEO implementations | remains `evals/` |
| `evolve/` | Crucible, scaffold search, campaign, promotion, and tracked search state | remains `evolve/` |
| `.agents/skills/` | cross-host development and evaluation scaffolds | remains development-only |
| `.claude/skills/` | Claude-compatible aliases and workflow scaffolds | remains development-only |
| `.geode/skills/` | bundled runtime-discoverable skills | remains runtime-only |

The following surfaces have no independent behavior or supported extension
contract and are absent from the final tree:

- `plugins/`: forwarding-only compatibility modules;
- `core/self_improving/`: forwarding-only module launchers;
- `geode_product/`: mixed runtime/evaluation/evolution ownership;
- `scripts/eval/tau2_geode_agent.py`: wrapper around the canonical module;
- `packaging/homebrew/` and its renderer: unreleased candidate scaffold;
- `docker/computer-use-sandbox/` and its HTTP dispatch/configuration: an
  unverified isolation path.

Git history is the recovery mechanism. No compatibility stub, archive copy,
or experimental replacement is created.

## Behavioral boundary

- User-facing commands, MCP surfaces, runtime skills, and host computer-use
  behavior remain implemented by their current canonical modules.
- Unrestricted Petri audits fail closed by disabling computer-use; there is no
  verified isolated desktop path to fall back to.
- The ten tracked scaffold-search state files live under
  `evolve/scaffold_search/state/`. Eight data/marker payloads retain their
  pre-migration bytes; two README files update only canonical path prose.
- Historical changelog entries, dated plans, audits, and immutable evaluation
  evidence keep the paths that were factual when recorded.

## Non-goals

This package split does not create a second distribution, compatibility alias,
plugin registry, user-data migration, or provider/runtime behavior change.
Roadmap status remains owned by the separate BND-009 reconciliation and
tracking transactions.
