---
title: Package classification and product-shell migration
status: accepted
decision: BND-001 / R1.1
authority: package-classification
related:
  - docs/architecture/extensibility-roadmap.md
  - docs/architecture/domain-free-core-audit.md
  - site/src/data/geode/architecture-baseline.json
---

# Package classification and product-shell migration

This decision classifies the packages that ship with GEODE and fixes their
future dependency ring. The architecture roadmap remains the authority for
status, package ordering, and implementation permission.

## Context

The base `geode-agent` distribution ships the closed `core` kernel and the
first-party `geode_product` shell together. The temporary `plugins` package
contains only compatibility facades for the four moved bundled features;
the self-improving control plane still lives under `core/self_improving`.
The generated architecture baseline owns the live kernel-to-product import
inventory and requires it to remain empty.

Those facts do not describe an external plugin system. An external extension
must be independently discoverable, enableable, removable, installable, and
testable. None of the five packages classified here meets that test today.

R1.1 is a boundary decision only. It moves no module, import, entry point,
state root, package data, registration, or writer.

## Decision

GEODE uses three dependency rings:

```text
third-party extensions
        │
        ▼
geode_product + bundled features
        │
        ▼
core (closed kernel)
```

- `core` is the closed agent kernel. Product composition and opt-in product
  workflows leave it through later roadmap packages.
- `geode_product` is the canonical first-party product-shell namespace. It
  will own CLI/server composition and bundled product features after their
  registered moves.
- Skills, filesystem hooks, MCP servers, and explicitly supported external
  Python entry points are extension surfaces. Bundled features do not become
  an extension SDK merely because they move outside `core`.
- The base distribution continues to ship the kernel and bundled product
  ring together. This classification does not create separate wheels.

`geode_product` is chosen instead of preserving the misleading `plugins`
name: the latter implies independently managed extensions that do not exist.
The old package roots are compatibility projections after their move owner
lands; canonical implementation and package data live only in `geode_product`.

### Exhaustive current classification

| Current source | Classification | Canonical target | Move owner |
|---|---|---|---|
| `plugins.benchmark_harness` | bundled product feature | `geode_product.benchmark_harness` | BND-002 |
| `plugins.crucible` | bundled product feature | `geode_product.crucible` | BND-002 |
| `plugins.petri_audit` | bundled product feature | `geode_product.petri_audit` | BND-002 |
| `plugins.seed_generation` | bundled product feature | `geode_product.seed_generation` | BND-002 |
| `core.self_improving` | bundled product feature in the wrong ring | `geode_product.self_improving` | BND-005, then BND-006 |

There is no independently removable external extension, misplaced kernel
concern, or compatibility-only package among these current source packages.
An old path becomes a compatibility facade only after its canonical code has
moved.

Petri, seed generation, and self-improving remain cohesive sibling features.
Benchmark harness and Crucible remain sibling evaluation features. They are
not folded into one generic feature package.

## Migration map

Every migration preserves the current public and operator-visible surfaces
until its registered compatibility gate permits removal.

The table below is exhaustive for compatibility. Package roots, listed
launchers, entry points, commands, tools, and explicitly named module surfaces
are preserved; arbitrary internal deep-module paths are not a public API.
Legacy package-resource lookup resolves the canonical package bytes, so data is
not duplicated under two physical writers.

| Source | Existing surfaces to preserve | State and package data | Test owner | Migration and rollback |
|---|---|---|---|---|
| `plugins.benchmark_harness` | Root exports and public adapters; `python -m plugins.benchmark_harness.{cli,run_mcpmark,run_mcpmark_pair,tau2_geode_agent}`; `scripts/eval` wrappers | Plugin manifest, Tau2 policy, and pinned MCPMark patch remain package data; external harnesses, native results, and run evidence keep their caller-owned `artifacts/eval` paths | `tests/plugins/benchmark_harness` plus Crucible harness-boundary, Tau2, and triad tests | BND-002 preserves adapter/module strings and package-data identity; it moves this reciprocal-import cluster with Crucible together or lands cold-import-safe forwarders before either switch; rollback changes routing without touching evidence |
| `plugins.crucible` | Root exports; `python -m plugins.crucible`; replay producer and `scripts/eval` wrappers | Campaign/attempt evidence, row caches, sealed state under the Git common directory, and `refs/crucible/**` keep their existing authorities | `tests/plugins/crucible` plus the benchmark Tau2 adapter tests | BND-002 preserves command/import/object identity and cold imports; the retired Codex CLI candidate producer has no facade; it shares a migration cluster with the benchmark harness; rollback changes routing without moving state, refs, or immutable evidence |
| `plugins.petri_audit` | Import root and registration side effects; `geode audit`, `petri-archive`, and `audit-agreement`; `/audit` and `/petri`; native audit tools; Inspect model entry points; internal MCP bridge module | `~/.geode/petri/logs`, operator configuration, agreement and seed-staging data, usage diagnostics, and tracked publication bundles keep their owners | `tests/plugins/petri_audit` plus existing CLI, config, LLM, self-improving, and tool integration tests | BND-002 preserves lazy optional-extra registration, command/tool names, string-based entry points, and old module identity; rollback restores registration imports without moving logs or config |
| `plugins.seed_generation` | Import root and exported symbols; `geode audit-seeds`, `/audit-seeds`; native seed tools | `STATE_SEED_GENERATION_DIR`, unified config, the legacy override file, handoff/checkpoint data, Petri inputs, and publication bundles keep their current owners | `tests/plugins/seed_generation` plus existing CLI, tool, self-improving, and Petri integration tests | BND-002 preserves the CLI/slash/tool surfaces, exported-object identity, and sibling Petri dependency; rollback changes routing only |
| `core.self_improving` | Import root; four documented `python -m core.self_improving.*` launchers; `/self-improving`, `/sil`, `geode campaign`; scheduler, hook, and MCP consumers | Tracked `core/self_improving/state`, runtime `~/.geode/self-improving`, handoff roots, and `GEODE_STATE_ROOT` semantics do not move with code | `tests/core/self_improving` plus existing agent, CLI, config, hook, LLM, observability, orchestration, Petri, and seed integration tests | BND-005 extracts neutral seams; BND-006 moves one implementation and keeps launcher forwarders; BND-007 may remove forwarders only after REL-002 and STORE-003; rollback restores composition without dual writers |

The four `plugins.*` paths have no registered retirement package. Their
removal is forbidden until a later roadmap transaction defines a public
compatibility gate. `core.self_improving` retirement is already bounded by
BND-007, REL-002, and STORE-003.

Test ownership follows behavior, not directory renames: feature-unit tests may
move with their implementation, kernel-contract tests stay with the kernel,
and old-path compatibility tests remain until the owning facade-retirement
gate closes.

Benchmark harness and Crucible are one migration strongly connected component:
each imports Tau2 surfaces from the other. BND-002 must switch them as one
compatibility cluster or stage both forwarders before changing composition;
warmed imports alone are not sufficient evidence.

## Rejected alternatives

- **Keep calling `plugins/` an external plugin layer.** The packages are
  bundled and not independently removable, so the name promises a contract
  that does not exist.
- **Split every feature into a distribution now.** No independent consumer
  requires that boundary.
- **Leave self-improving in `core`.** Campaign, mutation, evaluation,
  promotion, CLI/MCP, scheduler, and state policy are product concerns.
- **Create one feature mega-package.** It would erase distinct evaluation,
  seed, and campaign ownership.
- **Add a classification manifest or checker.** The five-row decision is
  static; the generated architecture baseline already owns repository census,
  and later GAPs own executable migration gates.

## Scope boundary

R1.1 adds no package type, registry, loader, schema, dependency, CI gate, or
runtime API. Reverse-import removal belongs to BND-002, neutral seam extraction
to BND-005, the self-improving move to BND-006, installed-kernel proof to
BND-003, and compatibility retirement to BND-007.
