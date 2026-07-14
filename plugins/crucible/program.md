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
  environments, one frozen train plan, a finite campaign budget, and an
  optional `search.objective` whose bytes are part of `config_id` and every
  proposal request. Ambient objective environment variables have no authority.
- `ExperimentContract` binds the parent and candidate revisions, evaluator,
  harness, assay, ordered task pack, mutation, changed-line cap, and promotion
  rule. Candidate and evaluator paths cannot overlap.
- A tau2 assay declares `timeout` explicitly. `null` removes the stochastic
  row-level wall cap; one monotonic experiment deadline gives baseline the
  current remainder and candidate whatever actually remains. The runtime
  receipt binds both allocations, censoring, and measured cleanup to the exact
  contract regime. The finite campaign wall remains the outer process bound.
- Evidence requires exact task/trial coverage. Infrastructure rows are never
  performance observations, and partial coverage never receives a score.
- Train `KEEP` advances only a loop-local search ref. A disjoint one-shot sealed
  test is required before eligibility; neither verdict can move a repository
  branch or release.
- Cached rows are reusable only when revision, evaluator, harness, task pack,
  and assay hashes match, both payload hashes verify, and the row carries no
  infrastructure termination or source-attested pre-execution retry.
- A scoreless infrastructure `INVALID` replay preserves the exact candidate
  revision when its parent is unchanged, so candidate-side cached rows remain
  addressable. An evaluator-revision replay becomes a new child commit.
- A baseline-bound stable patch receives one valid train verdict per frozen
  evaluator, harness, task pack, assay, and promotion world. Its receipt lives
  under `refs/crucible/candidate-fingerprints/*`; a repeat is a closed
  `duplicate_candidate` REJECT, while an infrastructure INVALID remains
  retryable.

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
3. For a paid stochastic campaign, bind explicit pilot assumptions to a
   verified basis file and digest in `power_audit`. Prepare evaluates the
   frozen task→family structure, trial count, and promotion rule, writes an
   opaque power report, and emits no launchable config when any preregistered
   scenario misses `minimum_power`. Audit the opaque hidden pack separately
   with the packaged `power-audit` command before candidate generation.
4. Bind runtime ownership at the experiment boundary. Use
   `operational_deadline` with `assay_config.timeout=null` only with explicit
   `nonzero_clean_timeout` risk acceptance. It is an operator deadline, not a
   confidence bound, and it must exceed its declared cleanup grace so the
   experiment retains positive active runtime. Use `contract_ceiling` only when a positive row timeout is
   intentionally part of the assay; that envelope guarantees process
   termination, not clean completion, and sums bounded rows, fixed setup, and
   cleanup terms without an arbitrary headroom multiplier. Reserve the fixed
   5.5-second process-reap/receipt finalization term inside every experiment
   envelope. A `pilot_bootstrap` admission requires a
   completed uncensored `runtime-pilot.v2` from the exact runtime regime. Build
   each pilot with its verified runtime receipt so a shortened live wall cannot
   masquerade as the frozen target wall. The receipt must bind the exact arm
   evidence/raw identities and record fresh/cache provenance; a cache-backed
   cycle may inform replay economics but never increments the independent
   target-cycle count. A complete cycle must contain exactly the family blocks
   and paired rows declared by its runtime regime. Treat summed row elapsed as an
   active-compute planning model; only completed matching-cycle evaluator wall
   observations from the exact same frozen source contract may qualify a Wilks
   upper tolerance bound. Repeated cycles share that contract ID but must carry
   distinct hash-bound runtime receipt IDs.
5. Run the quota-window preflight. `cap_fit` and `history_fit` are capacity
   estimates; `defer` makes `prepare` exit 3 and blocks chained launch. None is
   a provider guarantee.
6. Run the supervisor. Its absolute shared deadline starts before evaluator
   process startup; baseline executes first and candidate receives its actual
   remainder. The separately bound fixed finalization grace is only for paid
   process-tree reaping and the receipt write. An unreachable promotion rejects
   the candidate arm without spending it. A clean timeout is recorded as a
   right-censored lower bound before checkout cleanup starts and is never
   reused as an exact runtime duration.
7. With `CRUCIBLE_ROW_CACHE_ROOT` explicitly allowlisted, identity-proven,
   infrastructure-clean semantic rows may be reused. Missing tasks run again
   and exact full coverage remains mandatory. A fail-fast infrastructure stop
   emits structured INVALID evidence and observed marginal usage, allowing a
   new campaign to replay the exact candidate without making the interrupted
   row score-bearing. Historical evidence usage stays attached to the verdict;
   only fresh marginal usage consumes the current campaign budget.
8. Build a train bundle only after `KEEP`. Burn the sealed test attempt once,
   then require a separate human-reviewed core promotion change.
9. Treat model p95/p99 as forecast markers until exact matching full-cycle
   observations exist. `runtime-forecast` derives the matching count from the
   regime and exact source-contract IDs; operators cannot increment it manually. Distribution-free
   certification counts independent completed target cycles, not rows.

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
