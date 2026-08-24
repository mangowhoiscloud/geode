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

## Current ownership after the removal hotfix

| Surface | Current role | BND-009 target |
|---|---|---|
| `core/` | GEODE runtime | remains `core/` |
| `geode_product/benchmark_harness`, `petri_audit`, `seed_generation` | measurement and evaluation implementations | `evals/` |
| `geode_product/crucible`, `self_improving` | search, campaign, and promotion implementations | `evolve/` |
| remaining `geode_product/` composition | current outer runtime composition | `core/` or removal, per BND-009 |
| `geode_product/self_improving/state/` | byte-preserved tracked state colocated with the current implementation | `evolve/` under BND-009 |
| `.agents/skills/` | cross-host development and evaluation scaffolds | remains development-only |
| `.claude/skills/` | Claude-compatible aliases and workflow scaffolds | remains development-only |
| `.geode/skills/` | bundled runtime-discoverable skills | remains runtime-only |

The following surfaces have no independent behavior or supported extension
contract and are removed before the namespace migration:

- `plugins/`: forwarding-only compatibility modules;
- `core/self_improving/*.py`: forwarding-only module launchers;
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
- The ten tracked self-improving state files move out of `core/` through one
  byte-preserving rename. Eight data/marker payloads retain their final bytes;
  two README files update only their canonical path prose. BND-009 will move
  the state again with its final `evolve/` owner.
- Historical changelog entries, dated plans, audits, and immutable evaluation
  evidence keep the paths that were factual when recorded.

## Non-goals

This hotfix does not create `evals/` or `evolve/`, move `geode_product`, move
tracked state to its final `evolve/` owner, change the BND-009 claim, or perform
a release. Those actions remain owned by
`feature/r8-5-runtime-eval-evolve-migration` after this hotfix reaches `main`
and is synchronized back to `develop`.
