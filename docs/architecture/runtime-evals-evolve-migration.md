# Runtime, evaluation, and evolution namespace migration

Status: implementation record for roadmap package R8.5 / GAP BND-009.

## Decision

GEODE is the runtime. Evaluation and hill-climbing are consumers of that
runtime, not a second product shell. The repository therefore converges on
three shipped Python roots and deletes every compatibility or unsupported
surface made redundant by that split.

```text
core/                         # GEODE runtime and official operator surface
├── agent/                    # AgenticLoop, workers, safety, collaboration
├── cli/                      # `geode`
├── mcp_server.py             # `geode-mcp`
├── server/                   # daemon / IPC
├── tools/                    # native tools and immutable tool plan
├── worker.py                 # native subprocess composition
└── wiring/                   # runtime composition and lifecycle

evals/                        # measurement over the runtime
├── benchmarks/               # MCPMark and provider-neutral tau2 contracts
├── geo.py                    # GEO measurement state
├── petri/                    # Petri audit and inspect-ai adapter
├── seed_generation/          # seed evidence generation
├── worker.py                 # evaluation subprocess composition
└── cli.py                    # `geode-eval`

evolve/                       # scaffold search / hill-climbing
├── crucible/                 # experiment supervision and promotion
├── scaffold_search/          # campaign, mutation, gates, timelines, state
└── cli.py                    # `geode-evolve`
```

Allowed dependency edges:

```text
evolve ───────▶ evals ───────▶ core
   └─────────────────────────▶ core
```

Forbidden edges are `core -> evals`, `core -> evolve`, and `evals -> evolve`.
The import-linter contract and installed-wheel smoke enforce this direction.

## Migration map

| Before | After | Disposition |
|---|---|---|
| `geode_product.petri_audit` | `evals.petri` | move |
| `geode_product.benchmark_harness` | `evals.benchmarks` | move; Crucible-specific adapters move with Crucible |
| `geode_product.seed_generation` | `evals.seed_generation` | move |
| `geode_product.geo_state` | `evals.geo` | move |
| `geode_product.crucible` | `evolve.crucible` | move |
| `geode_product.self_improving` | `evolve.scaffold_search` | rename and move |
| `geode_product.cli` | `core.cli`, `evals.cli`, `evolve.cli` | split by responsibility |
| `geode_product.wiring` | `core.wiring.runtime` plus outer-loop callers | split; core never imports evals/evolve |
| `geode_product.tool_handlers` | `core.tools.composition` plus explicit evaluation contributions | split by owner |
| `geode_product.mcp_server` | `core.mcp_server` | native MCP entry; evolution tools move to `geode-evolve` |
| `geode_product.worker` | `core.worker` | official native worker composition; `core.agent.worker` retains the neutral protocol |
| `geode_product.slash_commands` | `evals` / `evolve` CLI commands | runtime no longer imports outer-loop commands |
| `plugins.*` | canonical roots above | compatibility facades deleted, no alias |
| `core.self_improving.*` | `evolve.scaffold_search.*` | launch/import facades deleted, no alias |

Entry-point mapping:

| Before | After |
|---|---|
| `geode = geode_product.cli:app` | `geode = core.cli:app` |
| `geode-mcp = geode_product.mcp_server:main` | `geode-mcp = core.mcp_server:main` |
| inspect-ai → `geode_product.petri_audit` | inspect-ai → `evals.petri` |
| `geode audit`, seed/evolution subcommands | `geode-eval`, `geode-evolve` |

Shell-level outer controls remain reachable through direct commands:
`geode-eval audit`, `geode-eval audit-seeds`, `geode-eval petri`,
`geode-evolve scaffold`, and `geode-evolve recall`. Runtime-only slash command
injection is deliberately absent from `geode`; GEO state and handlers remain
owned by evaluation composition rather than being imported into the runtime.

Old Python imports and source-module launchers are deliberately absent after
the release. This is a selected breaking namespace migration, not a deprecation
facade. Git history and the preceding v1.0.23 release are the rollback source.

## State contract

Tracked scaffold-search evidence moves from `geode_product/self_improving/state`
to `evolve/scaffold_search/state`. Every payload file must retain byte identity;
the ownership README may change. The migration records the before/after SHA-256
manifest and uses `git mv` so file history remains traceable.

Runtime user data keeps its existing on-disk meaning and writer:

- `~/.geode/self-improving`
- `~/.geode/autoresearch/handoff`
- `GEODE_STATE_ROOT/autoresearch`

No automatic user-data copy, schema migration, second writer, or alias tree is
introduced.

Tracked payload parity against the claimed implementation base
`origin/develop@0a3a4ccd5f1c93bc137529165770da5659b30953`:

| Relative payload | SHA-256 before and after |
|---|---|
| `baseline_archive.jsonl` | `63ad9c5aedff1f9ebd1db9cdf66f8cf27c01475da208bb5b0e00d4ee905425c4` |
| `baseline_epochs.json` | `2f9b7e1949ece23abaccc067c00b9466e1336e19ae9895adf56a38007a86bd8d` |
| `mutations.jsonl` | `b8fa53482002123bba86a30470bd8bf8598e5cb24def3c978f3da8fab461b472` |
| `policies/.gitkeep` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `policies/hyperparam.json` | `1e36fd4e87ab3ea40c989bd0dcd5d571b779443f08ef7cbad424251e8cd1d9e6` |
| `results.jsonl` | `c951c1a00acc9c3cfff11b3a782a79fc8dc0cd9f7bd734d804584ab66535bd10` |
| `results.tsv` | `c279dd5e4625a59ea5faabab888edee1496d7b39c662e4f061f0f9e443288f22` |
| `seed_pools/.gitkeep` | `32e6278177dd000e619540f5ab97a3880f89d07f82c5ef2ec0d37342ca218e1a` |

The two ownership README files intentionally change path prose and are not
payload evidence.

## Deliberate removals

The following have no replacement directory or stub:

- `geode_product/`
- `plugins/`
- `core/self_improving/`
- `packaging/homebrew/` and its candidate renderer/test/instructions
- `docker/computer-use-sandbox/`
- `computer_use_env=sandbox`, sandbox URL settings, HTTP/Xvfb dispatch, and
  sandbox-only doctor/error/docs/tests

Host computer-use remains. Unrestricted Petri audit cannot claim a removed
sandbox, so computer-use remains fail-closed in that mode.

## Common ownership and duplicate audit

| Finding | Resolution |
|---|---|
| `plugins` and `core/self_improving` forward to canonical implementations | deleted in hotfix #3144; no compatibility mirror remains |
| `tests/plugins` has no `tests/geode_product` mirror or byte-identical behavior tests | move by role to `tests/evals` / `tests/evolve`; empty package markers are not duplicated behavior |
| seed generation re-exports scaffold baseline readers | move shared baseline/seed-pool evidence to `evals`; no wildcard facade |
| benchmark tau2 modules import Crucible contracts | keep provider-neutral runtime contracts in `evals`; move Crucible adapters to `evolve` |
| one product CLI mixes runtime, audit, seed, and campaign commands | expose three explicit entry points; do not build another plugin registry |
| one product composer mixes native and evaluation handlers | retain one core compiler and pass explicit outer contributions from outer roots |
| tracked state lives under the former product shell | move once to the scaffold-search owner with a hash manifest |

No interface, registry, manager, archive namespace, dynamic import alias, or
empty compatibility package is added for this migration.

## Verification contract

The implementation is complete only when all of the following are true:

1. repository searches find no active `geode_product`, `plugins`, or
   `core.self_improving` import and no Homebrew/sandbox setting or dispatcher;
2. import-linter proves the declared dependency DAG;
3. state payload SHA-256 manifests match before and after;
4. runtime, Petri, benchmark, seed, Crucible, scaffold-search, host
   computer-use, worker, MCP, daemon, scheduler, and CLI characterization tests
   pass without deleted-test substitutes, skips, or config weakening;
5. architecture and official-doc generators are clean;
6. wheel and sdist contain only `core`, `evals`, and `evolve`; a clean install
   proves the three entry points and deliberate old-import absence;
7. full non-live CI passes before merge, then v1.0.24 GitHub/PyPI artifacts
   have exact digest parity and installed `uvx` smoke passes.

## Scope exclusions

- no new runtime, plugin system, distribution split, state store, or policy
  plane;
- no paid/live provider evaluation as part of the migration gate;
- no rewrite of immutable historical release evidence;
- no unrelated runtime tool or provider behavior change.

## Implementation audit log

Record newly discovered duplicate code, stubs, dead callers, or scope hazards
here before resolving them. The final implementation must either remove each
item or state the measured reason it remains.

| Finding | Evidence | Final disposition |
|---|---|---|
| Moving the old product wiring wholesale would create `core -> evolve` imports | `geode_product/wiring.py` combines runtime construction with scaffold-search middleware, activity, hooks, and scheduler contributions | split composition at the existing injected-builder seams; no reverse dependency |
| Configuration and run-timeline helpers were shared by evaluation and evolution callers | the former product config and scaffold-search timeline had readers on both sides of the new boundary | moved once to `evals/config.py` and `evals/run_timeline.py`; callers import the owner directly, with no forwarding module |
| Seed generation and scaffold search duplicated baseline and seed-pool evidence readers | wildcard re-exports and parallel metadata readers obscured which package owned measurement inputs | consolidated the baseline reader under `evals/seed_generation` and pool validation under `evals/petri`; removed the superseded files rather than keeping stubs |
| Provider-neutral Tau2 contracts and Crucible-specific adapters shared one benchmark directory | the runtime contract has evaluation callers, while the adapter and preflight import Crucible promotion types | kept the neutral contract in `evals/benchmarks` and moved the two Crucible adapters to `evolve/crucible` |
| Petri and seed generation each carried dimension or pool validation knowledge | both pipelines consumed the same audit vocabulary | centralized dimensions in `evals/petri/dimensions.py` and pool validation in `evals/petri/pool_validation.py`; no new registry was added |
| Current CLI documentation still described outer commands as injected into `geode` | runtime `COMMAND_REGISTRY` is disjoint from `EVAL_COMMAND_SPECS` and `EVOLVE_COMMAND_SPECS` | documented and tested three explicit entry points; removed stale runtime slash-command claims instead of adding compatibility registrations |
| The public metadata generator still required the schema-5 `geode_product` inventory | `site/scripts/sync-stats.mjs` rejected the new schema before reading its generated artifact | advanced the existing validator to schema 6 and required `core`, `evals`, and `evolve`; no second counter or migration layer was introduced |
| Core runtime composition still needed native handlers after removing the product shell | daemon, worker, and MCP roots previously reached `geode_product` only to obtain the same bound native plan | moved the existing compiler to `core/tools/composition.py` and runtime wiring to `core/wiring/runtime.py`; outer roots contribute explicitly and core remains self-contained |
| Putting native composition back into `core.agent.worker` broke the agent-layer import boundary | the neutral worker protocol indirectly reached CLI/server through the tool and runtime composers | kept `core.agent.worker` protocol-only; `core.worker` and `evals.worker` are the two explicit composition roots, and import-linter remains zero-ignore |
| The installed-package smoke loaded only the MCP entry point and did not require the two worker composition modules | console-script metadata alone could stay correct while a moved CLI or worker module was omitted from the wheel | load all four installed entry points, import both worker roots, require both roots in wheel and sdist manifests, and make direct `python -m core.agent.worker` fail before reading a request |
| The first split left status/run/history/rollback actions reachable only through the retired `/self-improving` slash registration | `evolve/cli.py` initially registered only `campaign`, `outer-bundle`, Crucible, and MCP | added one thin `geode-evolve scaffold <action>` adapter over the existing dispatcher and a behavioral forwarding test; no duplicate command implementation |
| Petri binding and recall controls existed only as outer slash handlers after the split | runtime cannot import `evals` or `evolve`, but both handlers are already shell-safe dispatchers | exposed thin `geode-eval petri` and `geode-evolve recall` adapters over the existing functions; no second parser or registry |
| `core.audit.contracts` contains an explicit soft `claim_grounded` placeholder | the row is `hard=False`, always `not_evaluated`, predates BND-009, and has dedicated tests proving it cannot veto promotion | retained as a measured non-authoritative historical contract; implementing a structured judge is separate evaluation scope, not a namespace stub or compatibility facade |
