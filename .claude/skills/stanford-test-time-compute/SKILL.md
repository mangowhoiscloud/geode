---
name: stanford-test-time-compute
description: Ground GEODE design and evaluation work in Stanford CS329A Test-Time Compute Scaling Part 2. Use for test-time or inference-time compute, best-of-N, parallel candidate width, sequential repair depth, measurement replication, verifier/evaluator versus promotion authority, verifier-aware scheduling, Archon or inference-program search, and GEODE/Eco²/SIL/Crucible comparisons.
---

# Stanford Test-Time Compute Grounding

Keep lecture evidence, project interpretation, measurement, and change authority
separate while applying test-time compute concepts to GEODE.

## Workflow

1. Read `references/lecture-analysis.md` completely before making a claim or
   design decision. The full read is deliberate: this user-designated SOT owns
   both the 63-minute lecture analysis and its project-mapping caveats.
2. Classify the request using the decision planes below.
3. Read only the matching project references from
   `references/project-application-index.md`.
4. Inspect current GEODE code and tests for every implementation claim.
   Historical presentation snapshots are context, never current code authority.
5. If exact timing, wording, or a slide is material, follow
   `references/source-manifest.md` and verify against the original source.
6. Report lecture evidence and GEODE application as separate claims.

## Decision planes

| Plane | Question | Do not confuse with |
|---|---|---|
| Parallel candidate width | How many alternatives solve the same task? | workflow fan-out or repeated benchmark trials |
| Sequential repair depth | How many feedback-conditioned revisions occur? | long chain-of-thought without observations |
| Inference-program search | Which bounded operator composition should run? | online self-modification or product promotion |
| Measurement replication | How uncertain is one policy's measured result? | best-of-N candidate selection |
| Promotion authority | Which evidence may change named state or release state? | verifier score or candidate ranking |

## Claim discipline

- Preserve the source labels `[직접근거]`, `[외부연구]`, and `[해석]`.
- State the search object, budget unit, verifier, measurement unit, and write
  authority for every proposed compute policy.
- Distinguish oracle coverage from delivered correctness.
- Treat a trajectory as a training-data candidate only after identity, privacy,
  duplication, reward quality, and evaluator-leakage checks.
- Call GEODE's current capability a direct implementation only when the input,
  output, decision object, and authority match the cited operator contract.

## Guardrails

- Do not call concurrent subagents parallel sampling unless they produce
  comparable candidates for the same task.
- Do not call K repeated evaluations best-of-K.
- Do not call a gate a ranker merely because it chooses keep or revert.
- Do not claim GEODE implements Archon or compute-optimal scheduling without
  current code and executable evidence.
- Do not infer performance scaling from observed trajectory length; run a
  controlled budget intervention first.
- Keep completed state-changing trajectories out of answer fusion. Consider
  fusion only before side effects, over plan or text candidates.

## Output contract

For a design, audit, or report, include:

1. the decision plane and search object;
2. lecture evidence versus project interpretation;
3. current GEODE code/test grounding;
4. verifier and promotion-authority boundaries;
5. measured GAPs, non-goals, and the smallest justified next experiment.
