# Project application index

Read the matching Part 2 or Part 5 lecture reference first. Then load only the
row needed for the current request. Historical presentation snapshots never
override current GEODE code, tests, schemas, and release documents.

| Need | Reference | Current GEODE grounding |
|---|---|---|
| Full presentation knowledge-base routing | `presentation-index-snapshot.md` | Use only to locate a relevant historical source |
| Eco² graph policy, concurrency, observability, and feedback lineage | `eco2-runtime.md` | Compare objects and authority; do not relabel Send fan-out as candidate width |
| SIL/Crucible trajectory judgement, evidence, and promotion | no additional snapshot required | `core/self_improving/`, `plugins/crucible/`, `docs/architecture/crucible-*.md` |
| Frozen-model scaffold levers and bounded search | route through `presentation-index-snapshot.md` only when historical framing is needed | `core/self_improving/loop/mutate/`, `plugins/crucible/contract.py` |
| Policy stack and trajectory provenance | no additional snapshot required | `core/agent/`, `core/observability/trajectory.py`, `core/agent/evidence_ledger.py` |
| Runtime verification and public hooks | no presentation snapshot required | `core/agent/verify.py`, `core/agent/loop/_lifecycle.py`, `core/hooks/public.py`, `docs/architecture/hook-system.md` |
| Planning, multi-step execution, and deep research | `lecture-05-planning-multistep.md` | `core/agent/plan.py`, `core/agent/loop/agent_loop.py`, `core/agent/sub_agent.py`, `.geode/skills/deep-researcher/SKILL.md` |
| Tau2 executable evidence | no presentation snapshot required | `plugins/benchmark_harness/`, `docs/eval/tau2-bench.md`, `docs/plans/2026-08-04-runtime-faithful-tau2.md` |

When a snapshot names an old version or revision, preserve it as historical
evidence and re-run the corresponding current-code check before reusing its
claim.
