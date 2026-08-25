# Benchmark integrations and platform adapters

## Problem

GEODE is itself the agent runtime. Calling MCPMark, tau2, and Harbor nested
"harnesses" repeats that abstraction and obscures three ordinary roles:

- benchmark integration: tasks, scorer/verifier, dataset, and native protocol;
- runner: orchestration that executes benchmark cases;
- platform adapter: connection to an external execution platform such as Harbor.

The ambiguity makes a platform-first or benchmark-first directory cross-product
look necessary even though GEODE currently has only one external platform
adapter.

## Frontier research summary

Research was checked on 2026-08-25 against the linked primary sources and the
repository heads recorded below.

| Source | Observed pattern | Decision |
|---|---|---|
| [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent/tree/06860844e13e46a599320fa2828629391f6f2ffd) | Officially describes the agent as a harness under evaluation and compares it with model-native harnesses; its published analysis falls back to official native results when its reproduction is worse. | Retain the source's term when citing it; do not copy it into GEODE's internal namespace. |
| [Prime Verifiers](https://github.com/PrimeIntellect-ai/verifiers/tree/c521e4146026a164038b670372ad7f14edd45250) | Separates tasksets, harnesses, and runtimes; a taskset defines work and scoring while an agent selects its harness. | Preserve the role separation using conventional integration, runner, and adapter names inside GEODE. |
| [Prime benchmark porting guide](https://github.com/PrimeIntellect-ai/prime-envs/blob/26dafdc9582576975ec576f893be7319028daf51/BENCHMARK_PORTING.md) | Preserves prompts, rubrics, assets, scoring, and workspace assumptions as benchmark data; adapter code only maps interfaces. | Add original/upstream implementation as a mandatory research and parity source. |
| [Harbor](https://github.com/harbor-framework/harbor/tree/6ecebe4ae9910ee0b28a2e6e8fa30934c0b41dfa) | Keeps agent implementations separate from benchmark dataset adapters and requires original-vs-Harbor parity evidence. | Classify the GEODE connection as a platform adapter, never as a benchmark. |
| [OpenHands Benchmarks](https://github.com/OpenHands/benchmarks/tree/f60e4ed11262b667896ce9f554dd487057fd1ef2) | Owns benchmark integrations in a separate benchmark repository. | Keep benchmark-specific GEODE integration under `evals/benchmarks`. |
| [mini-SWE-agent](https://github.com/swe-agent/mini-swe-agent/tree/25941c89cfbc91eb40b3f8756348c91d9977d57e) | Groups benchmark configuration by benchmark while the agent implementation remains shared. | Keep benchmark ownership primary and avoid per-platform copies. |

## GAP analysis

| Gap | Evidence | Resolution |
|---|---|---|
| Benchmark sources are named harnesses | `HarnessSpec`, `BENCHMARK_HARNESSES`, and the CLI argument | Rename the public evaluation helpers to benchmark terminology. |
| Harbor could be mistaken for a benchmark | Its adapter sat beside benchmark modules | Move it to `evals/platforms/harbor.py` and keep it out of `BENCHMARKS`. |
| Legacy identifiers preserve the overloaded term | Manifest filename, TOML root, checkout path, artifact-schema fields, and v1.0.x Python aliases | Keep them only for compatibility and reproduction; do not extend them in new APIs. |
| Research omits Prime Agent and native parity | `.claude/skills/frontier-harness-research/SKILL.md` lists four systems | Add both as explicit research sources and checklist items. |

## Decision

Use **benchmark-first vertical slices with a separate external-platform
package**, not either directory cross-product:

```text
evals/
├── benchmarks/
│   ├── mcpmark/              # agent, runners, pinned patch
│   ├── tau2/                 # policy and provider-neutral contracts
│   ├── manifest.py
│   └── trajectory_artifacts.py
└── platforms/
    └── harbor.py
```

MCPMark and tau2 already have multiple cohesive modules, so each now forms one
vertical slice. GEODE does not vendor Harbor dataset adapters or create
`harbor/<benchmark>` copies; the upstream benchmark remains the authority for
tasks and scoring. Former flat public entrypoints, harness-named Python
symbols, manifest filename, TOML root, checkout path, and artifact-schema
fields remain compatibility or reproduction identifiers rather than becoming
a second authority.

## Verification

- Targeted manifest, CLI, Harbor adapter, MCPMark, and tau2 tests.
- Ruff, mypy, import-linter, architecture baseline, installed-package smoke,
  repository hygiene, and full non-live pytest before merge.
- No live model or paid benchmark run is required for this namespace-only
  change.
