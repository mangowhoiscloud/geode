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
evaluator hash, harness hash, and content-bound task-pack hash. Sealed test and
repository promotion remain outside the adaptive train loop.

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
| [Bazel hermeticity](https://bazel.build/concepts/hermeticity) and [SLSA provenance](https://slsa.dev/spec/v1.2/provenance) | inputs and build/execution identity are content-addressed | revision, harness including task bytes, evaluator, resolved assay config, raw artifact, and task pack are frozen together |
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

No veto averages into the primary metric. Train-only infrastructure retries
must be frozen by their assay; a sealed `INVALID` consumes its pack without a
retry. A semantic `REJECT` requires a new candidate and contract.

## Frozen contract

`plugins.crucible.contract.ExperimentContract` is the machine-readable identity
boundary. Its canonical SHA-256 is the `contract_id` recorded by every shard.

The contract fixes:

- a full champion ref plus baseline and candidate git SHAs; preflight requires
  the ref to resolve to the declared baseline;
- evaluator and harness content SHA-256 values plus a task-pack SHA-256;
- agent and user routes;
- ordered task units, each binding task ID, preregistered family, canonical
  content SHA-256, and trials per task;
- a canonical resolved assay configuration covering environment, actor,
  termination, resource, seed, and retrieval settings;
- exactly one mutation surface and hypothesis;
- evaluator paths, which cannot overlap the mutation surface;
- one paired comparison method, primary metric, absolute floor, improvement
  threshold, confidence level, bootstrap count, minimum task count, and
  minimum independent-family count;
- the whole-experiment budget;
- required vetoes;
- for sealed test, the parent train contract ID.

The preflight computes the task-pack hash from ordered task IDs, family IDs,
canonical per-task content hashes, and trial cardinality. Relabeling the same
task does not change its content hash, and duplicate content inside one pack is
invalid. Tau2 pack construction can additionally bind selection to the
upstream split manifest and rejects any requested ID outside that split. At
runtime the adapter loads the configured task set and split, then compares the
ordered task IDs, content hashes, and workflow-family hashes with the contract
before a provider call. Actual task, policy, environment, and verifier bytes
must also live inside the clean external harness tree, whose tracked content is
hashed separately. Loading assay data from outside that tree is not a valid
integration. Preflight also hashes actual evaluator paths, verifies the clean
checkout SHA, and inspects the baseline-to-candidate diff. The diff must touch
the declared mutation surface,
cannot touch frozen evaluator paths or other production surfaces, and must stay
inside the changed-line cap. A test contract must name a matching train parent
and be disjoint from train by task ID, family ID, and content hash.
Content and family hashes establish exact identity, not semantic novelty. The
versioned adapter and pack curator still own near-duplicate detection; changing
nonessential task wording cannot by itself create a defensible new family.

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
- verify the exact top-level tau2 task objects loaded during preflight against
  the frozen IDs, content hashes, and workflow-family hashes; the adapter
  derives families from criterion kinds and tool-action names rather than core
  `if/elif` cases;
- write the raw artifact SHA-256 and an atomic snapshot finalization status;
  run or route failures are preserved as `invalid`, never `complete`.

`plugins.crucible.evidence` defines an immutable normalized envelope for one
arm. It binds contract, revision, evaluator, harness, assay config, task pack,
and raw bytes; records task/trial metrics, independent checks, termination and
infrastructure status; and carries whole-arm resource totals. Tau2 normalization
also refuses a usage manifest below the calls, tokens, estimated cost, or
minimum wall time observable in raw message metadata. The tau2 adapter
validates the pinned upstream result schema without importing the harness.
`max_steps` remains a semantic zero rather than a dropped row, while upstream
`infrastructure_error`, `user_error`, and `unexpected_error` invalidate the
evidence.

`plugins.crucible.promotion.decide()` is the assay-neutral screening rule
(`paired_bootstrap.v2`). It requires exact paired coverage, computes
baseline/candidate means and a deterministic one-sided paired-bootstrap lower
bound over family-level means (trial → task → family), and keeps only when the
lower bound exceeds zero at the contract's confidence level, the point improvement
reaches the economic `materiality_pp` floor, and the candidate clears the
absolute floor; it aggregates both arms' wall/call/token/cash usage and
applies non-exchangeable checks. Verdict v3 records paired rows, task units,
family units, and trials per task separately so repeated trials or many
near-duplicate tasks are not mistaken for independent bootstrap units. The v1
rule, which required the lower bound itself to clear the improvement threshold,
was retired after a power self-audit showed it demanded a 10-30pp effect at
documented pack scales. A train-stage `KEEP` only advances a campaign search
head and has `promotion_authority=none`. Test-stage
verdicts cannot be produced through the reusable `score` CLI.

`plugins.crucible.bundle` rebuilds the complete train chain from one
supervisor-owned attempt directory: request, candidate proposal, contract,
both evidence envelopes, train KEEP verdict, canonical supervisor record, and
the persisted intent and receipt for the search-ref CAS. The CAS atomically
creates `refs/crucible/applied/<campaign>/<record-id>` at the candidate commit,
so a self-consistent JSON receipt is not provenance by itself. Bundle rebuild
verifies both that witness and the current search ref. A verdict that the
supervisor downgraded for campaign budget cannot enter a bundle. The serialized
bundle is a transport summary, not a bearer credential; sealed execution
rebuilds the chain from the attempt directory itself.
`plugins.crucible.sealed` then owns the non-adaptive test boundary. It validates
the rebuilt bundle and disjoint parent, then records the pack claim, sole
attempt, attested evidence, and terminal decision below Git's common directory.
The evaluator is invoked only after that global attempt burn. Once raw hashes
are checked, the canonical evidence and verdict are stored as a Git blob and
fixed by `refs/crucible/attestations/<test-pack>`. Recovery recomputes from that
object instead of trusting mutable mirror JSON. Infrastructure failure is
terminal rather than retried after hidden-task exposure, and a local state
deletion or rollback cannot create another attempt. A sealed KEEP may
advance only `refs/crucible/eligible/*` through the recoverable ref journal; the
resulting decision still says `release_authority=none` and cannot move a branch,
tag, release, `main`, or `develop`.

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
`refs/crucible/search/<campaign>` through a persisted record and intent followed
by a recoverable compare-and-swap journal. The active repository branch is
never moved. Each contract names a separate immutable
`refs/crucible/baselines/<campaign>/<attempt>` ref, so later search-head
advances do not invalidate historical preflight.

The shipped live path keeps the treatment smaller than the evaluator. The only
candidate-owned file is `plugins/benchmark_harness/tau2_agent_policy.md`.
`plugins.crucible.producers.codex_kg` asks GPT-5.4 subscription for one small
edit using closed failure codes and a bounded architecture-graph slice; it
cannot read raw tasks, trajectories, evaluator artifacts, or sealed state.
The graph slice is committed beside the producer and attests every referenced
source file by content hash. The producer validates all nodes and edges before
selecting the candidate surface and its one-hop neighbors. The shipped graph,
objective, model, and reasoning effort are therefore source defaults. The
measured campaign omits graph, objective, model, and effort environment
overrides, keeping those controls in the candidate's parent revision rather
than an unhashed shell value.
`scripts/eval/crucible_tau2_evaluator.py` and `plugins.crucible.tau2_live` own
the paired baseline/candidate execution. They derive the complete argv from the
contract, isolate per-arm state, retain raw evidence, and compute trace checks
separately from reward. The `crucible_user` registry identity uses the same
subscription route as the agent but lives in frozen evaluator code, outside the
candidate policy surface. `Tau2SealedEvaluator` reuses this exact execution path
for the sole hidden attempt, passes both the disjoint test contract and its
frozen train parent into the runner, and maps a missing artifact or non-zero
runner exit to terminal infrastructure evidence instead of a task score.
The command entrypoint uses `uv run --frozen --no-dev`, so direct supervisor
execution selects the repository's Python requirement and existing lock instead
of the host's ambient `python3`, without installing development-only tools in
each disposable measurement checkout.

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
# Derive opaque task/content/family identities from the frozen harness task
# file. The emitted manifest contains no scenario or oracle text.
uv run python -m plugins.crucible tau2-task-pack tasks.json \
  --task-id 17 --task-id 42 \
  --task-split split_tasks.json --task-split-name base \
  --output train.pack.json

# Normalize each finalized arm. Usage and safety/tool checks are independent
# manifests; reward is not allowed to imply those checks.
uv run python -m plugins.crucible tau2-usage baseline.results.json \
  --output baseline.usage.json
uv run python -m plugins.crucible tau2-evidence experiment.json \
  --arm baseline --results baseline.results.json \
  --snapshot baseline.snapshot.json --usage baseline.usage.json \
  --checks baseline.checks.json --output baseline.evidence.json

uv run python -m plugins.crucible score experiment.json \
  --baseline baseline.evidence.json --candidate candidate.evidence.json \
  --output verdict.json

# Bind the current train KEEP only from its complete supervisor attempt.
uv run python -m plugins.crucible bundle . \
  ../crucible-runs/verify-claims-01/attempts/0001-abc123 \
  --output promotion.bundle.json
```

The independent train loop is started from one JSON configuration:

```json
{
  "schema": "crucible.supervisor.v4",
  "campaign_id": "verify-claims-01",
  "initial_search_head_sha": "<40-char-sha>",
  "repository": ".",
  "harness_root": "../frozen-harness",
  "state_dir": "../crucible-runs/verify-claims-01",
  "allowed_surfaces": ["plugins/benchmark_harness/tau2_agent_policy.md"],
  "producer_command": ["python", "-m", "plugins.crucible.producers.codex_kg"],
  "evaluator_entrypoint": "scripts/eval/crucible_tau2_evaluator.py",
  "producer_environment": ["CODEX_HOME"],
  "evaluator_environment": ["CODEX_HOME", "CRUCIBLE_TAU2_HARNESS_ROOT"],
  "train_plan": {
    "schema": "crucible.train-plan.v3",
    "name": "verify-claims-train",
    "evaluator_sha256": "<sha256>",
    "harness_sha256": "<sha256>",
    "task_pack_sha256": "<sha256>",
    "agent_route": "<route>",
    "user_route": "<route>",
    "tasks": [
      {
        "task_id": "<train-task-id>",
        "family_id": "<adapter-derived-family-sha256>",
        "content_sha256": "<canonical-task-sha256>"
      }
    ],
    "trials_per_task": 1,
    "assay_config": {"schema": "<assay-schema>"},
    "evaluator_paths": [
      "scripts/eval/crucible_tau2_evaluator.py",
      "plugins/benchmark_harness/tau2_geode_agent.py",
      "plugins/crucible"
    ],
    "promotion": {
      "method": "paired_bootstrap.v2",
      "primary_metric": "reward",
      "materiality_pp": 0.0,
      "minimum_candidate_mean": 0.3,
      "minimum_tasks": 20,
      "minimum_families": 10,
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
part of `evaluator_sha256`. The shipped tau2 entrypoint implements this protocol
for OpenAI subscription runs. Other assays still supply a separate frozen
entrypoint rather than adding branches to the supervisor.

The Git refs and common directory above are the monotonic authority store for
this implementation. A fresh clone, rollback or deletion of that store, or an
evaluator that performs hidden internal retries is outside the guarantee. The
producer and evaluator also require an execution substrate that prevents the
candidate from writing the authority repository; Crucible does not itself turn
same-user subprocesses into a hostile-code sandbox.

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
disposable checkouts are removed. Every KEEP now persists and fsyncs its record
and canonical ref intent before one Git transaction advances the search ref and
creates the record-bound applied witness. An immutable receipt follows. If the
process stops around those points, `reconcile-ref` distinguishes pre-CAS,
complete post-CAS, and partial or third-SHA conflict without repeating
evaluation. The adaptive campaign itself is still not resumed from an existing
state directory; bundle eligibility is recovered from the record, witness, and
receipt rather than the mutable ledger snapshot.

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
producer/evaluator wrappers, not OS-level meters. Tau2 raw-message usage now
sets a non-underreportable floor on the final manifest, but it is still not an
in-run cancellation meter. Resource and independent safety manifests therefore
remain explicit trusted-adapter inputs rather than values inferred from tau2
reward. The diagnostic live result below exercises this path but does not imply
a current core promotion.

## Operating loop

1. Start from the current search-head commit. This is not a core-promotion ref.
2. Choose one causal failure signature and one mutation surface.
3. Make the smallest change that could alter that signature.
4. Commit the candidate. Do not measure a dirty worktree.
5. Freeze `experiment.json`, including evaluator/harness content hashes, task
   pack, family assignments, and the entire experiment budget.
6. Run baseline and candidate on the same task order. Interleave paired rows
   when the harness supports it.
7. The current runner enforces its wall timeout and rejects finalized evidence
   that exceeds the frozen aggregate budget. After a complete train baseline,
   the evaluator computes the best possible candidate vector under the assay's
   metric ceiling; if even that vector cannot clear the frozen materiality,
   absolute-floor, and confidence rules, it records a zero-call screening
   REJECT instead of spending the candidate arm. In-run call/token/cash
   cancellation and pairwise sequential stopping remain execution-substrate
   work. `max_steps` is a task failure, not a row to drop.
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
- A sealed pack is never retried after evaluator access: infrastructure or
  semantic failure consumes its sole attempt. Train-only retries remain an
  execution-substrate policy and carry no promotion authority.
- Contract-backed shards use fresh run IDs. Resume remains disabled until a
  checkpoint sidecar can prove the same contract, revision, evaluator, harness,
  and task-pack hashes before loading any row.
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
  harness hash, task-pack hash, raw-artifact hash, finalization status, usage,
  or contract ID;
- the rows span three repository commits and were not measured as one frozen
  paired baseline/candidate population;
- the cost preregistration explicitly has no promotion authority and references
  a task-pack path that is no longer present.

The raw tau2 files also contain task payloads and evaluation criteria. They are
operator-only incident evidence and must never be copied into producer
feedback. A future run must create v3 contracts, evidence, and verdicts plus v3 evaluation
feedback from a fresh campaign; the older artifacts are not migrated or
rescored into that protocol.

### GPT-5.4 subscription diagnostic canary

An operator-approved canary completed on 2026-07-11 using
[GPT-5.4](https://openai.com/index/introducing-gpt-5-4/) at high reasoning for
both GEODE participants. It repeated the exposed retail task109 assay once with
seed 300, `max_steps=36`, `max_errors=1`, and `max_retries=0`:

- GEODE commit `4e676f9933e12208bb7d2be5082929d6e1d7dfcd`; frozen external
  tau2 harness commit `1901a301961cbbe3fd11f3e84a2a376530c759e3`;
- task pack `c8a9d5a984c7d9afee4197fb7fac265a3d69cf2a26b331b3463a018ce7b13768`,
  containing one task and one adapter-derived family;
- reward 1.0, DB reward 1.0, all 3 write-action checks passed, normal
  `user_stop`, no provider or infrastructure error, 114.754 seconds;
- raw/trajectory SHA-256
  `e3512ebed43956933d08070d09f99664ea99d51131a105ea15d5f913eac07d49`;
  metadata SHA-256
  `24215a9ffe29ae0a91a6512e7385d662e7b64a25e4bc25a3f7b38126a5a6679f`;
- raw-message resource floor: 9 observable calls, 128,720 tokens, and
  $0.242212 normalized cost. The isolated local usage-store window recorded 17
  calls across 2 sessions with the same token and normalized-cost totals,
  including 60,928 cached-read tokens. These dollar values are price-normalized
  accounting, not an incremental subscription charge.

The snapshot deliberately records `arm=diagnostic`,
`candidate_surface=unfrozen_git`, and `promotion_authority=none`. The task was
already exposed, the pack has one family, and `geode_user` is candidate-owned.
The previous task109 run used another model and an unsealed historical checkout.
The observed 0→1 reward change is therefore not a causal candidate comparison
and cannot enter a promotion bundle.

### First paired GPT-5.4 campaign: infrastructure INVALID

The first supervisor-backed live campaign,
`tau2-telecom-gpt54-train-20260711-r1`, preregistered four exposed train tasks
from four workflow families. Both bounded attempts terminated `INVALID` before
candidate scoring. The private search ref remained at
`cb5f003c806a19f024e63195974737e1b9604b73`; the summary records zero KEEP,
zero REJECT, and two INVALID attempts.

The failures exposed two evaluator-boundary defects rather than agent
performance: the isolated evaluator `HOME` hid the credential even though
`CODEX_HOME` was allowlisted, and tau2's finalized Pydantic task objects added
three optional null fields omitted by the source JSON, producing unequal
content hashes. The OAuth reader now resolves `CODEX_HOME`, and the task adapter
normalizes those runtime-materialized defaults before hashing. The r1 reward
rows are infrastructure-contaminated and cannot be reused as baseline or
candidate evidence; a new campaign ID and newly frozen evaluator hash are
required.

The follow-up r2 campaign completed one valid paired measurement but hit a
transport defect before scoring: all four canonical tau2 task IDs exceeded the
old 100-character feedback item cap. Pure scorer recomputation over its frozen
evidence is REJECT (0.0 baseline and candidate means, all vetoes clean), but no
supervisor verdict was committed. The operator stopped attempt 2 before another
paired measurement because the same parser defect was deterministic. Feedback
now uses a 64 KiB aggregate ID budget and relies on exact membership in the
frozen train contract; r2 remains non-promotional and a fresh campaign is
required.

The r2 review also found an assay-design error rather than a candidate-runtime
error: its frozen `max_steps=24` was far below tau2's upstream text-run default
of `100`. Tau2 counts projected tool-result messages in that budget, so all four
candidate trajectories were cut off before workflow completion and the added
verification calls consumed the short budget faster. The paired zero remains a
valid result for that exact contract, but it is too insensitive to guide the
next search. A successor campaign must freeze the upstream step budget instead
of reusing r2 as calibration evidence.

The same review found that r2's external knowledge graph was nine days and
2,021 changed files behind the candidate parent, contained no Crucible/Tau2
nodes, and was supplied through an unhashed absolute environment path. That
input cannot ground a reproducible optimizer. The live producer now reads only
its source-attested graph slice from the candidate parent revision; ambient
graph paths no longer enter the campaign environment.

Campaign r3 kept the same four-family pack, restored tau2's `max_steps=100`,
removed the per-simulation timeout, and generated a three-line general policy
candidate (`1a9e95a37e`). Its first baseline workflow advanced for roughly 46
minutes before the evaluator-owned user stream raised `httpx.ReadTimeout`.
Tau2 correctly recorded `infrastructure_error`; there was no paired evidence
or verdict. Because the row had already made the attempt inadmissible, the
operator stopped the remaining simulations. The incident exposed two
orchestration gaps: strict evaluator fail-fast bypassed AgenticLoop's ordinary
call retry, and four independent tasks were scheduled serially. Fail-fast now
retries exactly one connection-class failure on the same adapter with the
identical request before surfacing infrastructure. This retry happens before a
model response reaches tool execution, so it cannot repeat a side effect.

Campaign r4 then tested tau2's thread-pool concurrency. It was stopped before
scoring for two independent reasons. The generated one-line candidate used a
`SHOULD` clause instead of the required `CAN`/`CANNOT` grammar, and four
concurrent Codex streams returned SDK event payloads as raw dictionaries. All
four baseline rows became `infrastructure_error` (`dict` has no `to_dict` or
`output`), so concurrency was not an admissible throughput optimization. The
producer now rejects any behavior clause outside the two-token grammar before
committing a candidate. Tau2's adapter-owned runtime profile also caps
`geode_agent` at concurrency one; a future parallel implementation must first
replace that profile with direct thread-safety evidence.

Campaign r5 retained that serial profile and generated a valid one-line
`CAN`/`CANNOT` candidate (`4e2f53818a`). Its baseline never reached a provider
call: the external selection had ranked two-fault rows from all 2,285 telecom
tasks while the contract fixed the 114-row `base` split. Only one of four
selected IDs belonged to that split, so tau2 rejected the pack before
measurement. The supervisor recorded attempt 1 as `INVALID`; the operator
stopped attempt 2 during proposal because the frozen evaluator would encounter
the same deterministic defect. The task-pack CLI now validates requested IDs
against the upstream split manifest, and runtime preflight independently
recomputes all loaded task identities. r5 contains no paired performance
evidence and cannot inform a promotion decision.

Campaign r6 corrected the split membership but exposed an environment boundary:
the isolated subprocess `HOME` could not see the host Codex credential store
unless `CODEX_HOME` was explicitly forwarded. Both attempts ended with 401
before candidate-task exposure, so r6 contains no performance evidence. The
next campaign fixed that route input rather than weakening isolation.

Campaign r7 completed the first clean paired measurement. Its baseline rewards
were `[1, 1, 1, 0]`; the one-line candidate produced `[0, 0, 1, 0]`. Direct
adjudication is `REJECT` with means `0.75 -> 0.25` and paired improvement
`-0.50`. The supervisor initially mislabeled it `INVALID` because the tau2
writer emitted attempt-relative artifact paths while the documented reader
resolved them from the response directory. The writer now emits local names,
and a response-contract test fixes that boundary.

Campaign r8 expanded the same deterministic train selection to all six rows
admitted by the family, intent, and persona caps. It then exposed the other
pre-execution failure shape: a baseline model call completed with reasoning
output but neither visible text nor a tool call. The Codex adapter correctly
failed the strict route, but its generic `RuntimeError` sat outside the
connection-only retry classifier. Empty completed responses now carry a typed
adapter error. Strict AgenticLoop calls retry that identical request once, at
the same boundary as connection-class failures; a second empty response remains
infrastructure. Because the first response reached no tool execution, the retry
cannot duplicate environment state changes.

Campaign r9 live-confirmed the typed retry: one baseline call produced an empty
completion, the identical retry returned usable output, and the task completed
with reward `1.0`. The arm later finished all six rows as
`[1, 1, 0, 0, 0, 0]`, but the legacy diagnostics backstop treated the recovered
dump as contamination and invalidated the attempt before the candidate arm.
Successful retries now write a sibling `.recovered` marker. The backstop ignores
only that explicitly acknowledged dump; a second empty response, a swallowed
hidden-path error, or a marker-write failure remains inadmissible.

Campaign r10 then reached the GPT-5.4 subscription hard limit before either arm
could produce a score. Both arms were correctly marked as infrastructure, but
the supervisor immediately began generating a second candidate. That mixed the
exploration loop with a measurement retry. A separate deterministic replay
producer now carries the preregistered one-commit policy diff forward only when
the candidate surface's baseline blob is unchanged. The prior candidate,
verdict, and record are hash-pinned and must prove a scoreless infrastructure
INVALID with no search-head movement. The replay uses no model call and rejects
extra paths, merge commits, or surface drift. Provider recovery can therefore
retry the same hypothesis instead of silently resampling the search.

Campaign r11 replayed that exact one-line candidate with zero producer calls.
The baseline completed six rows as `[1, 1, 1, 0, infrastructure_error, 0]`.
The fifth row received two consecutive completed GPT-5.4 responses whose
`output_text` was empty; both dumps remained unmarked. A separate empty response
in the sixth row recovered on the identical retry and carries the expected
`.recovered` marker. The distinction therefore worked: one recovered anomaly
did not contaminate the row, while the repeated empty response invalidated the
arm. The candidate arm was never started, the search head did not move, and the
2,004.8-second attempt contains no promotion evidence.

The arm snapshot already recorded `execution_status=invalid` and
`failure_class=route_contamination`, but the runner's final non-zero exit caused
the command supervisor to retain only `invalid_attempt`. Finalized invalid raw
and snapshot artifacts now pass through normalization even after a non-zero
runner exit. Train evaluation emits a zero-call `paired_arm_skipped` counterpart
for every frozen pair and returns both envelopes to the ordinary promotion
gate. The resulting verdict remains `INVALID` with zero paired rows and no
candidate execution, while preserving the infrastructure cause for deterministic
replay. A non-zero exit without valid finalized artifacts, or with evidence
claiming `complete`, still fails as a hard evaluator error.

Campaign r12 live-confirmed that boundary. The replay producer again used zero
model calls, and the baseline finished as
`[1, infrastructure_error, 0, infrastructure_error, 0, 1]`. One empty GPT-5.4
completion recovered on the identical retry, while two other rows each reached
the two-attempt ceiling; their four dumps remained unmarked. The evaluator
therefore wrote an invalid baseline with `route_contamination`, a zero-call
candidate envelope with `paired_arm_skipped`, and an ordinary verdict with
`infrastructure_contamination`, zero paired rows, and no promotion authority.
Only the baseline simulation directory exists. The search head remained at
`7071cb281`, and the sealed pack preregistered for r12 was retired without being
opened.

The attempt used 104 observable calls, 1,248,582 tokens, and $1.376436 of
normalized accounting over 1,343.1 wall seconds. Its sixth baseline row also
repeated the same successful final-state check 13 times before recovery logic
moved the conversation forward. That trace supports the candidate's general
non-redundancy hypothesis, but the contaminated arm is not candidate feedback
or score evidence. The route defect must be removed before the candidate is
measured.

Empty completed responses now receive at most three total attempts at the
strict pre-execution boundary. Connection failures retain their existing two
total attempts. Every empty retry uses the same adapter and identical request
before tool execution; a later success marks all preceding dumps as recovered,
while three consecutive empty responses leave every dump unmarked and keep the
arm invalid. This is a bounded transport recovery, not a task replay or a score
salvage path.

Campaign r13 tested that three-attempt boundary against the same replayed
candidate. The baseline was route-clean after one marked recovery and completed
as `[1, 1, 1, 1, 1, 0]`. The candidate later encountered two separate
three-empty clusters, in its first and sixth rows. Its other observed rows were
not admitted as performance feedback: the normalized candidate envelope is
`invalid/route_contamination`, the ordinary verdict is
`INVALID/infrastructure_contamination` with zero paired rows, and the search
head remained `63f004c55`. The run used 242 observable calls, 2,898,399 tokens,
and $3.391357; the campaign lasted 3,418.0 seconds. Its evidence IDs are
`541d1e7390eb` and `a10758299280`, and verdict ID `d43494bb14cb` binds the
scoreless outcome. The preregistered sealed pack was retired unopened.

The r13 traces also exposed why increasing the retry count again would be the
wrong abstraction. Each persistent empty occurred in the evaluator-owned user
simulator after the same `AgenticLoop.arun()` had already emitted usable tool
actions. The empty continuation raised out of the loop and discarded those
actions, even though tau2 accepts a tool-call turn without visible text. The
runtime now has a default-off actionable-partial boundary. Only the frozen
`crucible_user` opts in: after the bounded identical retries are exhausted, a
turn with at least one successful tool action returns those actions with
`termination_reason=actionable_partial`, and every empty diagnostic receives an
append-only `.actionable` marker. Empty output before any usable action remains
a hard infrastructure failure, the measured assistant agent retains the strict
default, and marker failure is fatal. This preserves model-emitted work; it
does not fabricate text, replay a task, or admit an invalid score.

Campaign r14 was the first attempt to pass train and consume its preregistered
sealed pack. The replayed one-line policy candidate
(`ae2678cce91fa76cd80c08ac345dd4613aa1e60d`) changed only the general batching
clause. Train rewards moved from `[1, 0, 0, 1, 1, 0]` to
`[1, 1, 1, 1, 1, 0]`; the pure train verdict was `KEEP`, with means
`0.50 -> 0.8333`, paired improvement `0.3333`, lower bound `0.1667`, and
`promotion_authority=none`. This opened exactly one six-family, task-disjoint
sealed attempt.

The sealed result did not replicate. Baseline rewards were
`[1, 0, 1, 1, 0, 0]`; candidate rewards were `[0, 1, 1, 1, 0, 0]`. Both means
were `0.50`, paired improvement was zero, and the lower bound was `-0.3333`.
Verdict `21d574b725b7` is therefore `REJECT` for
`improvement_below_materiality` and `confidence_bound_not_positive`; decision
`d3cb91bc5abe` retains `release_authority=none`. No eligible ref exists. The
pack-specific attestation ref is durable, the attempt count is one, and the
sealed pack cannot be reopened. Three exhausted empty responses in one
candidate row received `.actionable` markers and preserved a real tool action,
but that row still scored zero because the workflow remained incomplete. The
boundary preserved evidence without manufacturing a pass.

The post-run trajectory audit found two evaluator defects that cannot alter
that closed REJECT but must change the next evaluator identity:

- Unlimited inner rounds let the model continue against placeholder write
  results before the official tau2 environment replied. The candidate's
  sealed first row ran for 1,156.8 seconds and ended at `max_steps`; another
  row repeated the same successful state-changing call many times. Source
  audit confirmed that `ToolCallProcessor.reset()` clears its log at every
  `arun()` boundary, so this was model behavior inside one inner run, not
  cross-turn adapter replay.
- Evidence used the maximum single-simulation duration as each arm's wall
  usage. The six baseline simulations actually summed to 2,347.3 seconds and
  the six candidate simulations to 3,320.3 seconds, while their envelopes
  recorded only 675.6 and 1,156.8 seconds. The honest combined subprocess floor
  is therefore about 5,667.5 seconds, not 1,832.5. This correction would not
  change r14's budget veto because the frozen ceiling was 10,800 seconds; r14
  remains immutable rather than being rescored.

The successor boundary is a small external half-duplex supervisor, separate
from candidate policy. A default-off AgenticLoop option yields immediately
after one completed tool batch; ordinary callers retain `while(tool_use)`.
Tau2 keeps `max_rounds=0`, so the first model call preserves `tool_choice=auto`
and high effort, then projects the current `arun()` tool log once and lets the
official environment own the next response. The external supervisor also maps
GEODE's generic repeated-success/no-progress termination to tau2's native stop
token. An absolute per-simulation deadline wraps in-flight participant calls,
and paired evidence records measured subprocess elapsed time while retaining
raw token, call, and cost floors. Contract-backed runs require a positive
timeout and unlimited inner round configuration; the code-owned yield supplies
the actual one-batch boundary. These rules depend only on protocol state; they
contain no task ID, tool name, workflow, or score case. The source-attested
knowledge graph records the supervisor as a separate node, and size ratchets
keep the runner below 1,200 lines and the supervisor below 300.

The first successor attempts found the remaining boundary mistake without
creating score evidence. r15 generated a one-line candidate, then all six
baseline rows hit the subscription hard limit before any model response;
candidate execution was skipped and the verdict is scoreless `INVALID`. r16
replayed that candidate with zero producer calls after reset. Its first
baseline row ran 600.1 seconds as 90 alternating text messages with zero tool
calls and closed as tau2's native `timeout`; the next row was operator-stopped
at 210 seconds. The cause was using `max_rounds=1` as the initial yield signal:
AgenticLoop's wrap-up policy correctly interpreted its only round as final and
set `tool_choice=none` plus low effort. r16 is an incomplete diagnostic, its
sealed pack remains unopened, and none of its rows can enter promotion. The
default-off post-tool yield replaces that overloaded round cap.

r17 then failed before campaign initialization because its configuration named
a syntactically valid but nonexistent full commit SHA. It made no provider
call, created no attempt or campaign ref, and did not claim the sealed pack;
its partial state directory is preflight incident evidence, not a run. The
supervisor had validated the commit only after writing `config.json`. Startup
now performs the same exact-commit, clean-repository, and fresh-ref checks as a
read-only preflight before any state directory is created, then rechecks them
at the authority-ref transition. Successor configurations take the full SHA
only from `git rev-parse HEAD` rather than reconstructing it from an abbreviated
log entry.

r18 completed the first clean paired run under the corrected boundary. The
baseline was `[1, 1, 1, 1, 0, 0]` (mean `0.6667`); the replayed batching
candidate was `[1, 0, 1, 1, 0, 0]` (mean `0.50`). Verdict
`fdec8a79737a` is `REJECT`, with paired improvement `-0.1667`, lower bound
`-0.3333`, and all budget, infrastructure, safety, coverage, and tool-contract
vetoes clear. The run used 478 calls, 3,855,030 tokens, $4.5585585, and
4,256.7 attested wall seconds. Search authority stayed at `7bd12d10208d`; the
successor sealed pack remains unopened.

That REJECT exposed a feedback transport bug rather than an evaluator defect.
The supervisor correctly persisted its next-producer envelope with nested
`evaluator.failure_codes`, but the Codex producer read only a top-level field
and therefore saw an empty list. The producer now projects either direct v3
feedback or the nested supervisor envelope onto the same closed failure-code
set. A fresh campaign may preregister bounded `initial_feedback`; its failed
task IDs must belong to the frozen train pack, while only failure codes enter
the model prompt. The permanent audit request retains that identity for
verification, but the command producer receives a projected request containing
only the closed codes. The producer also removes every supervisor-protocol path
from the model-owned Codex child environment. This carries a completed train
lesson across campaign boundaries without exposing task IDs, trajectories,
free text, sealed state, or score authority to the optimizer.

r19 exercised that corrected feedback boundary with a fresh GPT-5.4 proposal.
The producer saw only the closed `workflow_completion` code and added one
general `CAN` policy clause. On the same six frozen train rows, baseline
scored `[1, 1, 1, 1, 0, 0]` and candidate scored `[1, 0, 1, 1, 1, 1]`.
The candidate recovered both multi-message workflows but regressed one mobile
data workflow, so paired improvement was `+0.1667` with lower bound `-0.1667`;
verdict `e1c6abe1ac88` remained `REJECT` under the frozen r19 evaluator.

The raw transport trace limits what that verdict can mean. The regressed
candidate row incurred a GPT-5.4 `APITimeoutError`, recovered through the
bounded identical-request retry, and then reached the 600-second row deadline.
Tau2 persisted only the final timeout, so evidence incorrectly reported
`infra_clean=true`. AgenticLoop now exposes the exception classes observed by
each current run, the external turn boundary copies their count and identity
into every tau2 raw message, and normalization rejects inconsistent telemetry.
Any recovered pre-execution retry makes that row an infrastructure error and
the paired verdict scoreless `INVALID`; it cannot be learned as a semantic
failure or success. Historical r19 artifacts remain immutable. Its exact
candidate is eligible for a preregistered replay under the corrected evaluator:
the replay producer binds the source candidate, verdict, record, and contract
by content hash and requires the current evaluator digest to differ from r19.
It cannot resample an ordinary reject under the same evaluator. A clean replay
measures the policy, while another retry closes as infrastructure without
consuming the sealed pack.

r20 attempted that corrective replay after the evaluator revision but reached
the GPT-5.4 subscription hard limit before any model response. All six baseline
rows were infrastructure errors, the candidate arm was skipped, and the
ordinary verdict was scoreless `INVALID`; the exact candidate and unopened
sealed pack therefore remained eligible for an ordinary measurement retry.

r21 completed that exact retry without a recovered transport event. Baseline
rewards were `[1, 1, 1, 1, 1, 0]`; candidate rewards were
`[0, 1, 1, 1, 0, 0]`. Verdict `307a9b10a295` is a clean `REJECT`, with means
`0.8333 -> 0.50`, paired improvement `-0.3333`, lower bound `-0.50`, and no
promotion authority. All 479 raw participant messages carried retry telemetry;
their retry count summed to zero. The run consumed 479 calls, 3,847,427 tokens,
$4.519926 of normalized accounting, and 3,227.6 attested wall seconds. The
search ref stayed at `6d2240bf6a9d`, and the sealed pack remained unopened.

Two external-loop defects were now measurable rather than hypothetical. First,
the completed baseline already made KEEP impossible: even a perfect candidate
could improve only `+0.1667`, below the frozen `+0.25` materiality floor, and
its best possible paired-bootstrap lower bound was zero. Candidate execution
therefore spent 231 calls and 1,864,709 tokens after the decision had become
immutable. Train evaluation now computes that best-case ceiling after the
baseline and emits a separately attested, zero-call screening REJECT when any
necessary promotion condition is unreachable. The screen grants no score or
authority, cannot enter a promotion bundle, and cannot be replayed as an
infrastructure retry.

Second, the evaluator reduced three candidate failures to the single code
`workflow_completion`. The r21 raw structure distinguishes one unmatched
required user action and two `max_steps` terminations without consulting task
IDs, tool names, scenario text, or gold values. Tau2 feedback now derives the
closed codes `required_user_action`, `termination`, and `workflow_completion`
from only termination class, candidate checks, and unmatched action ownership.
The producer still receives no task identity or trace. Its default objective
has also been reduced from the failed call-minimization/batching prescription
to the outcome boundary: complete every required user action, confirmation,
state change, and terminal verification without redundant repetition.

r22 live-confirmed the reachability screen on a fresh GPT-5.4 proposal. Its
baseline completed as `[1, 1, 1, 1, 0, 1]`; the perfect candidate ceiling was
again only `+0.1667`, with a zero confidence lower bound. The evaluator emitted
candidate artifact `crucible.screened-arm.v1`, zero candidate calls, and train
REJECT `898428aac9bb` with no promotion authority. The baseline used 207 calls,
1,656,079 tokens, $1.873952 of normalized accounting, and 1,390.2 attested wall
seconds. All 207 provider-call messages carried retry telemetry and summed to
zero retries. The producer's single 99,623-token proposal call brings the outer
attempt total to 208 calls and 1,755,702 tokens. Raw hashes match both evidence
envelopes, the search ref stayed at `3e326a1bd`, and candidate measurement was
never started.

That result also closes the six-row pack as a useful search surface: two clean
baselines each scored five of six, so the frozen confidence/materiality rule
usually becomes unreachable before a candidate can be measured. The next
campaign therefore takes the complete union of that exposed pack and r14's
already-consumed sealed pack. All twelve task, family, and content identities
are disjoint across the two sources; none is selected by outcome, and execution
returns to upstream task-file order. A new adapter-side curator salt-ranks an
independent three-fault stratum for sealed confirmation and returns only counts
and hashes to the operator. Its full selected-row manifest remains outside the
optimizer view.

During the transition, an operator audit parsed the prior `423b03c3` ID-only
manifest before train KEEP to recompute a disjointness fact already present in
preregistration. No selected ID or task content was emitted and no optimizer or
evaluator received a row, but the stronger unopened-manifest claim is no longer
made: that pack is conservatively retired with zero sealed attempts. The
replacement pack is separately selected before r23 candidate generation.

r23 expanded the exposed train surface to twelve disjoint families and measured
the first producer candidate on that frozen order. Candidate `0030ddd96393`
tightened the completion boundary to cover required actions, confirmations,
state changes, and terminal verification. The baseline completed as
`[1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 1, 0]`. The first six candidate rows also
completed with reward one, after which the GPT-5.4 subscription hard limit made
the remaining six rows infrastructure errors. Verdict `23fa4ccf00ef` is
therefore a scoreless `INVALID`, not a partial six-row success. The evaluator
used 624 calls, 5,004,929 tokens, $5.774251, and 4,213.5 attested wall seconds;
the producer brings the outer attempt to 625 calls and 5,103,196 tokens. All
observed pre-execution retry counts were zero, so the invalidity is the explicit
provider limit rather than a recovered retry.

r24 made the only allowed corrective replay of that exact one-line policy under
the same twelve-row assay. Baseline rewards were
`[1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0, 0]`; candidate rewards were
`[1, 1, 1, 1, 1, 0, 0, 1, 0, 0, 0, 0]`. Verdict `97f21538e229` is a clean
`REJECT`: means `0.5833 -> 0.50`, paired improvement `-0.0833`, and lower bound
`-0.1667`, with every veto true. All 922 provider-call messages carried zero
retry telemetry. The run used 7,498,490 tokens, $8.256135, and 5,747.3 attested
wall seconds. The stronger completion wording delayed some premature stops but
did not make progress monotone: one previously passing row regressed, another
reached four of five required actions without a binary pass, and three rows
still exhausted `max_steps`.

r25 used those closed failure codes to generate one new, first-valid candidate.
It added one general CAN clause for consuming unresolved actions and checks one
at a time while reusing confirmed successes, and tightened the completion
CANNOT clause. Before candidate execution, however, the same frozen twelve-row
baseline completed as `[0, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1]`, or `0.8333`.
Even a perfect candidate could improve only `+0.1667`; its best possible
family-bootstrap lower bound was `+0.0833`, below the frozen `+0.25`
materiality floor. The reachability screen emitted verdict `b84dd21a36ac` and
a zero-call `crucible.screened-arm.v1` candidate artifact. Baseline evaluation
used 546 calls, 4,403,707 tokens, $5.161777, and 3,575.3 seconds; the producer
brings the outer attempt to 547 calls and 4,504,216 tokens. Every one of the 546
raw provider messages carried zero retry count and an empty retry-error list.

The r24/r25 baseline shift from seven to ten passes on identical tasks, routes,
seed, and evaluator is the next bitter lesson. Re-running the screened r25
candidate until a lower baseline happens to make the arm reachable would
condition candidate measurement on a favorable baseline fluctuation and invite
regression-to-the-mean promotion. The next assay instead uses the already
implemented replication primitive. Trials are averaged within each task,
tasks are averaged within each workflow family, and only family deltas enter
the bootstrap; repeats therefore reduce within-task noise without pretending
to create independent families.

The post-r25 audit also found that its manually written sealed preregistration
copied a non-existent `79968339d765...` digest instead of the receipt-bound
`79968339c58a...` task-pack digest. Train REJECT prevented any sealed attempt,
but the bad declaration would have failed closed after a KEEP. While confirming
that mismatch, an operator process parsed the pack file for metadata before
KEEP. It emitted no task ID, selected row, or task content, but it violated the
stronger trusted-runner-only access claim, so that six-family pack is
conservatively retired with zero evaluator attempts.

r26 replaces it from a preregistered salt-ranked three-fault stratum. The first
`intent <= 2` and `persona <= 2` rule failed closed at five admissible rows and
wrote no pack. A separately preregistered `<= 3` rule selected six of the
remaining fifteen families; the operator-visible receipt binds task-pack digest
`6c4ceb0f8ddc` and artifact digest `d6c80617a73e`, while the selected-row
manifest stays outside the optimizer view. After excluding every exposed or
retired pack plus that replacement test pack, exactly nine three-fault families
remain. All nine, rather than an outcome-selected subset, form the r26 train
pack with two trials per task and digest `06f7321b6e2e`. This changes the assay
through frozen configuration only; it adds no second optimizer or scoring path.

The first r26 attempt stopped before candidate creation or evaluation because
the Codex subscription producer hit its usage limit. It recorded zero measured
calls and no contract, candidate, baseline, or sealed attempt. The producer
previously inspected only stderr on a non-zero Codex exit, while this CLI emits
its structured error on JSON stdout; the resulting supervisor artifact retained
only `codex exited with status 1`. The wrapper now extracts one bounded message
from `error` or `turn.failed` events without retaining model output. The frozen
train and hidden packs remain unconsumed for a fresh campaign after reset.

The strongest honest claims are:

- the frozen external tau2 baseline identified concrete retail wrong-write and
  telecom incomplete-workflow signatures;
- deterministic replay and runtime stress exposed real adapter, contamination,
  and tool-control defects;
- the campaign happened to keep core closed, but its row stitching and exposed
  test reuse mean that outcome is incident evidence, not validation of the old
  promotion protocol;
- no current candidate has sealed-test authority for core promotion.

A future promotion requires a clean committed candidate and the new disjoint
sealed test pack with an evaluator-owned user runtime. The diagnostic canary
does not satisfy that requirement.

## Explicit non-goals

- No population, router, archive policy, or gate ladder. The supervisor is a
  bounded orchestration loop, not a second in-process optimizer.
- No promotion from targeted hard negatives.
- No public leaderboard claim from subscription-route diagnostics.
- No automatic live provider calls. Live tests still require explicit user
  approval.
