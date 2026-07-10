# Crucible — frozen experiment kernel

> Status: architecture decision, 2026-07-10. This document supersedes the
> G0-G7 operating procedure in `crucible.md`. Historical results remain useful
> as training traces and incident evidence, but not as promotion evidence.
> External evidence behind the gate design is preserved in
> [`crucible-evidence-dossier.md`](crucible-evidence-dossier.md).

## Decision

Crucible is a small, standalone autoresearch loop over executable agent
behavior:

```text
search head SHA
    -> candidate producer process
    -> one committed mutation manifest
    -> trusted evaluator process
    -> frozen paired verdict
    -> train KEEP advances only the search head
```

The supervisor is independent from `core/self_improving`; neither package
imports the other. Existing or future optimizers may participate only by
implementing the producer file protocol. Git and the artifact store retain
candidate history. A result row belongs to exactly one candidate commit,
evaluator hash, harness hash, and task-layout hash. Sealed test and repository
promotion remain outside the adaptive train loop.

## Lineage and technical foundations

Crucible is not another benchmark. It is the promotion layer above executable
assays and their execution substrate:

```text
formal specification and test oracles
  -> unit / property / metamorphic / differential testing
     -> HumanEval / MBPP -> SWE-bench -> Terminal-Bench

MDP / POMDP environment contracts
  -> RL-Glue / Gym / PettingZoo
     -> InterCode / WebArena / OSWorld / tau-bench

hermetic builds + experimental design
  -> content-addressed provenance + paired trials + adaptive holdouts
     -> champion/challenger + canary promotion

CEGIS and evolutionary program search
  -> FunSearch / AlphaEvolve -> autoresearch / DGM
                                      |
                                      v
                   Crucible: git-native promotion ratchet
```

The systems in the first two branches are **assays**: they define tasks,
environments, and executable success conditions. Inspect and Harbor are
**execution substrates**: they separate task, agent, sandbox, scorer, and
trajectory. Crucible owns neither layer. It consumes their normalized evidence
and decides whether one committed candidate may replace the champion.

The technical roots impose concrete boundaries:

| Root | Inherited rule | Crucible boundary |
|---|---|---|
| [Hoare logic](https://dl.acm.org/doi/10.1145/363235.363259) and executable test oracles | correctness is expressed as preconditions, postconditions, and invariants | scalar reward never substitutes for safety, coverage, or state vetoes |
| [QuickCheck](https://doi.org/10.1145/351240.351266), metamorphic and differential testing | examples are supplemented by generated properties and cross-checks | verifier fixtures must include known-good, known-bad, and perturbation cases |
| [Bazel hermeticity](https://bazel.build/concepts/hermeticity) and [SLSA provenance](https://slsa.dev/spec/v1.2/provenance) | inputs and build/execution identity are content-addressed | revision, harness including task bytes, evaluator, resolved assay config, raw artifact, and task layout are frozen together |
| paired randomized blocks and [adaptive holdout](https://pubmed.ncbi.nlm.nih.gov/26250683/) | compare both arms on the same units; exposed tests become training data | task/trial pairs are atomic, and opened sealed rows are never reused as held-out evidence |
| [Gym](https://arxiv.org/abs/1606.01540) and [PettingZoo](https://papers.neurips.cc/paper_files/paper/2021/hash/803f7c4c3ff61b71be53a0c803bfb57f-Abstract.html) | agent, environment, actor order, termination, and truncation are explicit | infrastructure failure is not converted into task failure, and user/environment runtimes are evaluator-owned |
| CEGIS and [autoresearch](https://github.com/karpathy/autoresearch) | one mutation is tested, failures become counterexamples, git retains the ratchet | one candidate commit and one frozen rule produce KEEP, REJECT, or INVALID |

This history also explains why executable tests are necessary but insufficient.
[SWE-bench Verified was retired as a frontier measure](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)
after test-design and contamination defects were found, and Terminal-Bench 2.1
revised many tasks for bugs, resource settings, and reward-hacking robustness
([versioned dataset record](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench-2-1/6)).
Verifier validity therefore remains an audited, versioned input rather than a
permanent ground truth.

### Extension rule

Core contains only protocol state transitions: identity, coverage, or
infrastructure defects yield `INVALID`; a valid candidate that misses a floor
yields `REJECT`; all preregistered rules passing yields `KEEP`. Assay-specific
cases do not grow as `if/elif` branches in core. A typed, versioned
`AssayAdapter` owns each raw schema, participant-isolation profile, termination
classification, and verifier mapping. Adding a harness means registering one
adapter, not editing promotion logic or inventing a configuration DSL.

## Why the reset was necessary

The July campaign produced useful failure evidence but violated the comparison
contract:

- `9a0d8992e` added 11,665 lines across four files and kept telecom/retail
  experiment history as runtime branches and tests.
- Telecom accumulated workflow variants through v72. Retail added row-specific
  projectors, including a prompt literal for a known benchmark price sum.
- Rows passed under different candidate revisions were stitched into one
  apparent target-set closure. The final candidate was not rerun on every
  earlier row, so monotone improvement was not established.
- G4 rows were inspected, excluded, repaired, and rerun. They are now training
  counterexamples, not held-out evidence.
- The latest observed semantic frontier, retail task109, still had reward 0 and
  DB reward 0 after the assistant claimed writes that it did not emit. G4, G7,
  and core promotion remained closed.
- More than one thousand gate artifacts and tens of millions of tokens did not
  create a reproducible champion because candidate, evaluator, task set, and
  cost window were not frozen together.

These are experimental-design failures, not a reason to add another gate.

## Three evidence classes

### 1. Train

Train is the repeatable development surface. Known failures, replay fixtures,
synthetic environments, and previously exposed held-out rows belong here.

- A failed train row may inform the next candidate.
- A new candidate requires a new commit and contract.
- Train can reject a candidate early but cannot authorize promotion.

### 2. Sealed test

Test is a disjoint task pack opened once for one frozen candidate.

- The candidate, agent route, user route, harness, evaluator, task order, and
  budget are frozen before opening the pack.
- A semantic failure rejects that candidate. It cannot be repaired and rerun
  under the same test claim.
- Once inspected, a test row becomes train data for later candidates.
- Shards are execution partitions only. Every shard must carry the same
  contract and revision hashes, and their concatenated task order must equal the
  frozen task pack exactly.

### 3. Veto

Vetoes are non-exchangeable floors, but their failure classes remain distinct:

- identity, infrastructure, and task coverage determine whether evidence is
  admissible at all; a failure yields `INVALID`, not a low candidate score;
- safety and tool contracts are absolute candidate checks; a failure yields
  `REJECT`;
- the whole experiment must stay within wall, call, token, cash, and
  changed-line budgets; an overrun yields `REJECT`.

No veto averages into the primary metric. `INVALID` may be rerun only under the
already-frozen retry policy; a semantic `REJECT` requires a new candidate and
contract.

## Frozen contract

`plugins.crucible.contract.ExperimentContract` is the machine-readable identity
boundary. Its canonical SHA-256 is the `contract_id` recorded by every shard.

The contract fixes:

- a full champion ref plus baseline and candidate git SHAs; preflight requires
  the ref to resolve to the declared baseline;
- evaluator and harness content SHA-256 values plus a task-layout SHA-256;
- agent and user routes;
- ordered task IDs and trials per task;
- a canonical resolved assay configuration covering environment, actor,
  termination, resource, seed, and retrieval settings;
- exactly one mutation surface and hypothesis;
- evaluator paths, which cannot overlap the mutation surface;
- one paired comparison method, primary metric, absolute floor, improvement
  threshold, confidence level, bootstrap count, and minimum pair count;
- the whole-experiment budget;
- required vetoes;
- for sealed test, the parent train contract ID.

The preflight computes the task-layout hash from the ordered IDs and trial
cardinality. It is intentionally not called a content hash. Actual task,
policy, environment, and verifier bytes must live inside the clean external
harness tree, whose tracked content is hashed separately. Loading assay data
from outside that tree is not a valid integration. Preflight also hashes actual
evaluator paths, verifies the clean checkout SHA, and inspects the
baseline-to-candidate diff. The diff must touch the declared mutation surface,
cannot touch frozen evaluator paths or other production surfaces, and must stay
inside the changed-line cap. A test contract must name a matching train parent
and use a disjoint task pack.

For tau2 runs, the declared evaluator bundle must cover both the GEODE tau2
adapter and the contract validator. The external harness checkout must also be
clean, including non-ignored untracked files, so a caller cannot pin an
irrelevant file while changing executable assay code elsewhere.

The CLI validates a contract and its shards:

```bash
uv run python scripts/eval/crucible_contract.py artifacts/eval/contracts/train.json
uv run python scripts/eval/crucible_contract.py artifacts/eval/contracts/train.json \
  --arm candidate --shard shard-01.json --shard shard-02.json
```

For an actual run, also validate the clean checkout, diff, and actual
measurement bytes:

```bash
uv run python scripts/eval/crucible_contract.py artifacts/eval/contracts/train.json \
  --repo-root . --harness-root artifacts/eval/harnesses/tau2-bench \
  --arm candidate
```

The contract file must live outside the checkout or under an ignored artifact
directory. The checkout must have no tracked or non-ignored untracked changes,
including a contract accidentally placed at its root, and HEAD must equal the
selected arm SHA.

For test, provide the frozen train contract as well:

```bash
uv run python scripts/eval/crucible_contract.py artifacts/eval/contracts/test.json \
  --parent-contract artifacts/eval/contracts/train.json --repo-root . \
  --harness-root artifacts/eval/harnesses/tau2-bench --arm candidate
```

### Current implementation boundary

The preflight still never returns `KEEP`. It enforces clean revisions, one
bounded production mutation, actual evaluator/harness bytes, train/test
lineage, and exact shard identity. Contract-backed tau2 runs additionally:

- freeze a canonical `crucible.tau2-assay.v1` object containing domain, split,
  trial count, concurrency, seed, termination limits, actor routes, per-turn
  agent budgets, user arguments, and retrieval settings;
- require an evaluator-owned native user runtime instead of the candidate's
  GEODE loop, so a core mutation changes only the agent arm;
- use a fresh, atomically reserved run ID and a pinned harness data root;
- write the raw artifact SHA-256 and an atomic snapshot finalization status;
  run or route failures are preserved as `invalid`, never `complete`.

`plugins.crucible.evidence` defines an immutable normalized envelope for one
arm. It binds contract, revision, evaluator, harness, assay config, task layout,
and raw bytes; records task/trial metrics, independent checks, termination and
infrastructure status; and carries whole-arm resource totals. The tau2 adapter
validates the pinned upstream result schema without importing the harness.
`max_steps` remains a semantic zero rather than a dropped row, while upstream
`infrastructure_error`, `user_error`, and `unexpected_error` invalidate the
evidence.

`plugins.crucible.promotion.decide()` is the assay-neutral screening rule
(`paired_bootstrap.v2`). It requires exact paired coverage, computes
baseline/candidate means and a deterministic one-sided paired-bootstrap lower
bound over task-level trial means, and keeps only when the lower bound
exceeds zero at the contract's confidence level, the point improvement
reaches the economic `materiality_pp` floor, and the candidate clears the
absolute floor; it aggregates both arms' wall/call/token/cash usage and
applies non-exchangeable checks. Verdict v2 records paired rows, task units,
and trials per task separately so repeated trials are not mistaken for
independent bootstrap units. The v1 rule, which required the lower bound
itself to clear the improvement threshold, was retired after a power
self-audit showed it demanded a 10-30pp effect at documented pack scales. A train-stage `KEEP` only
advances a campaign search head and has `promotion_authority=none`. Test-stage
verdicts also remain authority-neutral until parent-train-KEEP binding and a
one-shot committed test-pack protocol are implemented.

`plugins.crucible.supervisor` is the separate outer loop. It owns one frozen
train plan and creates a disposable, no-remote Git checkout from its private
search ref. The producer can commit inside that checkout but cannot see the
authority repository's refs. The supervisor imports the resulting commit only
after validating its proposal identity and declared surface. It then validates
the imported parentage against authority objects, does not reuse any
producer-local Git metadata or ignored files, and creates a second fresh
checkout from authority objects for diff preflight and measurement. The frozen
evaluator runs with that second checkout as its process directory. It returns
paired evidence and raw artifacts; the supervisor verifies their digests and
invokes the pure scorer locally. Only an admissible train `KEEP` advances
`refs/crucible/search/<campaign>` with compare-and-swap. The active repository
branch is never moved. Each contract names a separate immutable
`refs/crucible/baselines/<campaign>/<attempt>` ref, so later search-head
advances do not invalidate historical preflight.

### Frozen rules, external calibration

The train plan preregisters pack size, trials, confidence, materiality, quality
floor, and budget. Crucible validates and freezes those choices; it does not
claim to derive them from a fitted model. The first calibration scaffold was
removed because its declared noise and regression priors did not affect the
search, its synthetic constants confirmed their own assumptions, and adaptive
repeated tasks could not be treated as independent posterior observations.
Parameter selection therefore remains explicit pilot evidence outside the
adaptive loop until a versioned calibration dataset and validated estimator
exist. This is less automatic, but it keeps unsupported statistical authority
out of the promotion contract.

The packaged operational surface is:

```bash
# Normalize each finalized arm. Usage and safety/tool checks are independent
# manifests; reward is not allowed to imply those checks.
uv run python -m plugins.crucible tau2-evidence experiment.json \
  --arm baseline --results baseline.results.json \
  --snapshot baseline.snapshot.json --usage baseline.usage.json \
  --checks baseline.checks.json --output baseline.evidence.json

uv run python -m plugins.crucible score experiment.json \
  --baseline baseline.evidence.json --candidate candidate.evidence.json \
  --output verdict.json
```

The independent train loop is started from one JSON configuration:

```json
{
  "schema": "crucible.supervisor.v3",
  "campaign_id": "verify-claims-01",
  "initial_search_head_sha": "<40-char-sha>",
  "repository": ".",
  "harness_root": "../frozen-harness",
  "state_dir": "../crucible-runs/verify-claims-01",
  "allowed_surfaces": ["core/agent/verify.py"],
  "producer_command": ["candidate-producer", "--mode", "one-change"],
  "evaluator_entrypoint": "<frozen-executable-evaluator>",
  "producer_environment": ["OPENAI_API_KEY"],
  "evaluator_environment": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
  "train_plan": {
    "schema": "crucible.train-plan.v2",
    "name": "verify-claims-train",
    "evaluator_sha256": "<sha256>",
    "harness_sha256": "<sha256>",
    "task_layout_sha256": "<sha256>",
    "agent_route": "<route>",
    "user_route": "<route>",
    "task_ids": ["<train-task-id>"],
    "trials_per_task": 1,
    "assay_config": {"schema": "<assay-schema>"},
    "evaluator_paths": ["plugins/benchmark_harness", "plugins/crucible"],
    "promotion": {
      "method": "paired_bootstrap.v2",
      "primary_metric": "reward",
      "materiality_pp": 0.0,
      "minimum_candidate_mean": 0.3,
      "minimum_tasks": 20,
      "confidence_level": 0.885,
      "bootstrap_samples": 10000
    },
    "budget": {
      "max_wall_seconds": 1800,
      "max_calls": 500,
      "max_tokens": 500000,
      "max_cost_usd": 25,
      "max_changed_lines": 120
    },
    "vetoes": ["budget", "infra_clean", "safety", "task_coverage"]
  },
  "limits": {
    "max_attempts": 10,
    "max_consecutive_invalid": 3,
    "max_wall_seconds": 3600,
    "max_calls": 1000,
    "max_tokens": 1000000,
    "max_cost_usd": 50
  }
}
```

```bash
uv run python -m plugins.crucible loop supervisor.json
```

The producer process starts in the supervisor-created disposable checkout. Its
request contains the current search SHA, allowed surface, previous compact
feedback, and remaining campaign budget, but no artifact-store or checkout
path. The producer receives only `CRUCIBLE_PROPOSAL_REQUEST` and
`CRUCIBLE_CANDIDATE_OUTPUT`; it never chooses the task pack, evaluator,
promotion rule, contract, or campaign budget. The trusted evaluator receives
the canonical candidate and supervisor-written contract through
`CRUCIBLE_CANDIDATE` and `CRUCIBLE_CONTRACT`. The supervisor executes the frozen
regular-file `evaluator_entrypoint` directly; its executable mode and bytes are
part of `evaluator_sha256`. The placeholder above is supplied by an assay
integration and must implement the evaluation-response protocol below. Crucible
does not currently ship a generic live-provider evaluator command.

The producer output is deliberately small:

```json
{
  "schema": "crucible.candidate.v2",
  "attempt_id": "<request attempt>",
  "request_id": "<request hash>",
  "parent_sha": "<search-head-sha>",
  "candidate_sha": "<one-child-commit-sha>",
  "mutation": {"surface": "core/agent/verify.py", "hypothesis": "..."},
  "usage": {"wall_seconds": 1, "calls": 1, "tokens": 1000, "cost_usd": 0.1}
}
```

Before and after evaluation, the supervisor verifies a clean, single-parent
candidate commit, the declared mutation surface, changed-line budget, frozen
evaluator paths, and actual evaluator/harness hashes. The evaluator output is
bound to the current request and proposal and may name only attempt-local
artifacts:

```json
{
  "schema": "crucible.train-evaluation.v3",
  "attempt_id": "<request attempt>",
  "request_id": "<request hash>",
  "proposal_id": "<proposal hash>",
  "baseline": "baseline.evidence.json",
  "candidate": "candidate.evidence.json",
  "baseline_raw": "baseline.results.json",
  "candidate_raw": "candidate.results.json",
  "feedback": {
    "schema": "crucible.failure-feedback.v3",
    "failure_codes": ["tool_contract"],
    "failed_task_ids": ["task-42"]
  }
}
```

The raw-file digests must match both evidence envelopes. Oracle content — gold
actions, expected values, task payloads, sealed rows, and free-form trajectory
excerpts — is never forwarded to the next producer. The bounded feedback may
name only task IDs from the frozen train contract plus one of the closed,
domain-neutral failure codes. It has no free-text field. INVALID evidence
forwards neither task IDs nor evaluator failure codes. Parser and preflight
details stay in operator-only `error.json`; the producer receives only the
closed `invalid_attempt` reason, so rejected evaluator text cannot be reflected
through an error message.

Each fresh campaign directory contains `config.json`, an atomically replaced
`state.json`, append-only `ledger.jsonl`, immutable per-attempt artifacts, and
one `summary.json`. The private search-ref compare-and-swap is the `KEEP` commit
point; `ledger.jsonl` and `state.json` are secondary observations of that Git
state. Candidate commits are pinned under private refs after their
disposable checkouts are removed. Existing campaign directories are never
resumed or overwritten in this first implementation, so automatic
reconciliation after a post-CAS crash remains an explicit gap.

Producer and evaluator environments are allowlisted and receive isolated
`HOME`, temporary, and `GEODE_STATE_ROOT` directories. Adaptive/held-out/test
environment names are rejected for both train roles, and Python/virtualenv
override variables are not inherited. Producer exchange files live beside its
disposable checkout, outside campaign evidence; a fresh evaluator output
directory is created only after the producer process group is quiescent. This
prevents accidental reuse of old autoresearch state or sealed configuration.
It is still a dependency boundary, not a hostile-code security sandbox:
stronger filesystem, network, interpreter, and dependency attestation must
come from the execution substrate or container policy. The frozen evaluator
paths should include dependency lockfiles used by that substrate.

The remaining executable gap is **in-run** aggregate budget cancellation. The
scorer and supervisor reject an overrun after finalized evidence, but the
runner does not yet interrupt both arms the instant the whole-experiment
call/token/cash budget is crossed. A crashed evaluator can also fail before it
emits final usage. Calls, tokens, and cash are attestations from the configured
producer/evaluator wrappers, not OS-level meters; an untrusted wrapper can
under-report them. Resource and independent safety manifests therefore remain
explicit trusted-adapter inputs rather than values inferred from tau2 reward.
No live provider run or current core promotion is implied by this
implementation.

## Operating loop

1. Start from the current search-head commit. This is not a core-promotion ref.
2. Choose one causal failure signature and one mutation surface.
3. Make the smallest change that could alter that signature.
4. Commit the candidate. Do not measure a dirty worktree.
5. Freeze `experiment.json`, including evaluator/harness content hashes, task
   layout, and the entire experiment budget.
6. Run baseline and candidate on the same task order. Interleave paired rows
   when the harness supports it.
7. The current runner enforces its wall timeout and rejects finalized evidence
   that exceeds the frozen aggregate budget. In-run call/token/cash cancellation
   and sequential-futility stopping remain execution-substrate work.
   `max_steps` is a task failure, not a row to drop.
8. Normalize both raw artifacts into immutable evidence envelopes. Identity,
   coverage, or infrastructure defects produce INVALID and no performance
   comparison.
9. KEEP only when the paired confidence bound and absolute floor clear the
   preregistered rule and every candidate veto passes. Otherwise REJECT and
   leave the search head unchanged. Train KEEP still requires a disjoint sealed
   test before any release claim.
10. Complexity remains bounded by the frozen changed-line limit; no separate
    model-judged simplicity gate is used.

## Boundary rules

- Candidate behavior and measurement code cannot change in the same
  experiment.
- The user simulator is part of the assay. Changing or deterministically
  projecting user actions creates a new evaluator, not an agent candidate.
- Benchmark answers, task IDs, prices, expected arguments, or oracle-specific
  branch text cannot enter the agent prompt or runtime policy.
- Offline verifiers may inspect gold state. Candidate runtime code may use only
  observations available through the normal tool contract.
- Retry after infrastructure failure is allowed only under the frozen retry
  policy. Retry after semantic failure is a new candidate and a new contract.
- Contract-backed shards use fresh run IDs. Resume remains disabled until a
  checkpoint sidecar can prove the same contract, revision, evaluator, harness,
  and task-layout hashes before loading any row.
- Historical candidates live in git, not in CLI choices such as v1 through
  v72.

## Current evidence classification

The existing telecom v1-v72 and retail rows 0-112 have been exposed during
candidate development. They are train/counterexample evidence only.

A filesystem audit on 2026-07-10 found 79 legacy trajectory metadata snapshots,
79 copied trajectories, and one cost preregistration under
`artifacts/eval/runs/crucible`. The snapshots point to 106 tau2 simulation rows:
46 ended with reward 1, 54 hit `max_steps` with reward 0, and 6 ended in
infrastructure error. Sixty-seven rows repeat one telecom task. Only six rows
are labelled baseline; the remaining 100 are candidate diagnostics spread over
multiple stages and runtime variants.

Including the v9 worktree archive and temporary copies, the audit covered
1,638 physical files with 1,283 unique SHA-256 contents. The root durable set
is a subset of the v9 archive, and the v9 temporary set is wholly duplicated;
temporary files add scratch evidence, not another independent population. All
302 parseable tau2 raw results remain diagnostic: 225 have exact declared
task/trial coverage, numeric rewards, and no infrastructure termination, but
none is bound to a current contract/evidence/verdict chain. Of 626 legacy gate
JSONs, none carries the current identity chain; all 15 G7 verdicts explicitly
allow at most a scoped harness surface while blocking core promotion.

Those artifacts preserve useful failure traces, and all referenced raw result
and copied trajectory files were present at audit time. They are not Crucible
promotion evidence:

- no experiment contract, normalized evidence envelope, verdict, campaign
  ledger, loop summary, or `refs/crucible/*` authority exists beside them; zero
  historical JSON files load as a current contract, evidence envelope, or
  verdict;
- the legacy snapshot schema records no candidate revision, evaluator hash,
  harness hash, task-layout hash, raw-artifact hash, finalization status, usage,
  or contract ID;
- the rows span three repository commits and were not measured as one frozen
  paired baseline/candidate population;
- the cost preregistration explicitly has no promotion authority and references
  a task-pack path that is no longer present.

The raw tau2 files also contain task payloads and evaluation criteria. They are
operator-only incident evidence and must never be copied into producer
feedback. A future run must create v2 contracts and verdicts plus v3 evaluation
feedback from a fresh campaign; the older artifacts are not migrated or
rescored into that protocol.

The strongest honest claims are:

- the frozen external tau2 baseline identified concrete retail wrong-write and
  telecom incomplete-workflow signatures;
- deterministic replay and runtime stress exposed real adapter, contamination,
  and tool-control defects;
- the campaign happened to keep core closed, but its row stitching and exposed
  test reuse mean that outcome is incident evidence, not validation of the old
  promotion protocol;
- no current candidate has sealed-test authority for core promotion.

A future promotion requires a clean committed candidate and a new disjoint
sealed test pack. No live run is implied by this architecture change.

## Explicit non-goals

- No population, router, archive policy, or gate ladder. The supervisor is a
  bounded orchestration loop, not a second in-process optimizer.
- No promotion from targeted hard negatives.
- No public leaderboard claim from subscription-route diagnostics.
- No automatic live provider calls. Live tests still require explicit user
  approval.
