# Crucible program

This is the central operating program for Crucible candidate search. It keeps
the experimentation instruction, enforced constraints, search preferences,
setup, and dynamic-feedback boundary in one tracked document.

`plugins/benchmark_harness/tau2_agent_policy.md` is the mutable artifact under
test—the analogue of autoresearch's `train.py`. It is not this program and
cannot define its own evaluator, budget, or promotion rule.

## Objective

The default campaign objective. ``search.objective`` in a supervisor config
overrides it per campaign; absent an override, the producer consumes exactly
the quoted text below.

> Keep every multi-step tool workflow monotone: maintain the unresolved
> policy-required actions and terminal checks, consume them one at a time,
> reuse confirmed successes without repeating them, and stop only when none
> remain.

## Experimentation

Only the body of `<candidate_program>` is sent to the producer model. The
surrounding sections are the operator-readable contract for the same loop.

<candidate_program>
Task: propose one small, task-independent agent-policy improvement.
Runtime: disposable no-remote Crucible producer checkout.
Model target: GPT-5.4 subscription with high reasoning.
Objective: {{objective}}
Allowed mutation surface: {{surfaces_json}}
Prior closed failure codes: {{failure_codes_json}}

Output contract:
- The candidate policy contains exactly one `Behavior:` section.
- In that section, every behavior bullet starts with exactly `- CAN` or `- CANNOT`.

Behavior:
- CAN inspect the allowed file and its caller before editing.
- CAN make the smallest defensible edit that addresses the objective.
- CANNOT edit more than the one allowed file.
- CANNOT add task IDs, expected answers, scenario literals, row-specific branches, or benchmark-specific facts.
- CANNOT depart from general behavior that transfers across tasks and domains.
- CANNOT weaken safety, confirmation, or tool-contract requirements.
- CANNOT trade a required user action, confirmation, or terminal check for a shorter trajectory.
- CANNOT add a large policy ladder when deleting or tightening wording can express the change.
- CANNOT run live/provider tests.
- CANNOT commit; the producer wrapper owns the commit.

Bounded architecture context:
<architecture_context>
{{graph_context}}
</architecture_context>
</candidate_program>

## Constraints

The Markdown explains the boundary; executable validators remain authoritative
and fail closed when prose and bytes disagree.

- `SupervisorConfig` admits one declared mutation surface, bounded process
  environments, one frozen train plan, and a finite campaign budget.
- `ExperimentContract` binds the parent and candidate revisions, evaluator,
  harness, assay, ordered task pack, mutation, changed-line cap, and promotion
  rule. Candidate and evaluator paths cannot overlap.
- Evidence requires exact task/trial coverage. Infrastructure rows are never
  performance observations, and partial coverage never receives a score.
- Train `KEEP` advances only a loop-local search ref. A disjoint one-shot sealed
  test is required before eligibility; neither verdict can move a repository
  branch or release.
- Cached rows are reusable only when revision, evaluator, harness, task pack,
  and assay hashes match and both row and context payload hashes verify.

## Preferences

- Prefer one causal hypothesis and the smallest reviewable diff.
- Prefer general policy wording over task- or benchmark-specific branches.
- Prefer deleting or tightening a clause over adding a policy ladder.
- Treat changed-line limits, materiality, confidence, absolute score floor, and
  budgets as preregistered contract values rather than constants in this file.
- Keep candidate generation outside the scorer. Reward, safety, tool-contract,
  infrastructure, and resource evidence have separate owners.

## Setup

1. Freeze an ordered train pack and an opaque disjoint test pack before
   candidate generation.
2. Build a `crucible.supervisor.v4` config from one search-head revision and
   record evaluator, harness, assay, pack, promotion, and budget identities.
3. Run the quota-window preflight. `cap_fit` and `history_fit` are capacity
   estimates; `defer` blocks launch. None is a provider guarantee.
4. Run the supervisor. Baseline executes first, and an unreachable promotion
   rejects the candidate arm without spending it.
5. With `CRUCIBLE_ROW_CACHE_ROOT` explicitly allowlisted, identity-proven
   semantic rows may be reused. Missing tasks run again and exact full coverage
   remains mandatory.
6. Build a train bundle only after `KEEP`. Burn the sealed test attempt once,
   then require a separate human-reviewed core promotion change.

## Dynamic feedback

Between attempts, the producer receives only closed failure codes from the
train evaluator. Task identities remain supervisor audit data and are not
rendered into the producer prompt. Raw tasks, trajectories, expected actions,
sealed state, free-text evaluator advice, and verdict thresholds remain outside
the adaptive channel.

## Program evolution

The parent revision and evaluator digest bind these program bytes. Editing this
file changes the search strategy for later campaigns; it is not a candidate
mutation in the current campaign. Self-modification of the program requires a
separate preregistered meta-evaluator and is outside the present promotion
authority.
