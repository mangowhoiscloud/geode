# Project application index

Read `lecture-analysis.md` first. Then load only the row needed for the current
request. These files are 2026-08-05 presentation snapshots; current GEODE code,
tests, schemas, and release documents take precedence.

| Need | Reference | Current GEODE grounding |
|---|---|---|
| Full presentation knowledge-base routing | `presentation-index-snapshot.md` | Use only to locate a relevant historical source |
| Eco² graph policy, concurrency, observability, and feedback lineage | `eco2-runtime.md` | Compare objects and authority; do not relabel Send fan-out as candidate width |
| SIL/Crucible trajectory judgement, evidence, and promotion | no additional snapshot required | `core/self_improving/`, `plugins/crucible/`, `docs/architecture/crucible-*.md` |
| Frozen-model scaffold levers and bounded search | route through `presentation-index-snapshot.md` only when historical framing is needed | `core/self_improving/loop/mutate/`, `plugins/crucible/contract.py` |
| Policy stack and trajectory provenance | no additional snapshot required | `core/agent/`, `core/observability/trajectory.py`, `core/agent/evidence_ledger.py` |
| Runtime verification and public hooks | no presentation snapshot required | `core/agent/verify.py`, `core/agent/loop/_lifecycle.py`, `core/hooks/public.py`, `docs/architecture/hook-system.md` |
| Tau2 executable evidence | no presentation snapshot required | `plugins/benchmark_harness/`, `docs/eval/tau2-bench.md`, `docs/plans/2026-08-04-runtime-faithful-tau2.md` |

When a snapshot names an old version or revision, preserve it as historical
evidence and re-run the corresponding current-code check before reusing its
claim.
