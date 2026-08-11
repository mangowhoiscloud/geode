# GPT-5.4 Tau2 OpenAI reference alignment

Status: source-grounded and no-model preflight complete; live execution pending
explicit approval. Date: 2026-08-12.

## 1. Decision

There is no public "Codex Tau2 configuration" to reproduce. The current
public Codex source has no Tau2 integration, and OpenAI publishes scores from
an undisclosed research harness. GEODE will therefore keep three identities
separate:

| Identity | What is public | Claim class |
|---|---|---|
| OpenAI GPT-5.4 | Telecom 98.9% at `xhigh`; 64.3% at `none`; research environment | `paper-reference`, directional only |
| Sierra GPT-5.4 submission | banking-knowledge 97 tasks x 4 trials; `xhigh`; GPT-5.2-low user; seed 300; AllTools; Tau2 1.0.1 | suite-official, different domain/profile |
| GEODE GPT-5.4 | runtime, route, user, task pack, limits and evidence below | GEODE product-route measurement |

Sources are the [OpenAI GPT-5.4 release](https://openai.com/index/introducing-gpt-5-4/),
the [Sierra GPT-5.4 submission](https://github.com/sierra-research/tau2-bench/blob/main/web/leaderboard/public/submissions/gpt-5-4_sierra_2026-03-25/submission.json),
and the [Tau2 submission guide](https://github.com/sierra-research/tau2-bench/blob/main/docs/leaderboard-submission.md).

## 2. Grounded revisions

| Surface | Frozen evidence |
|---|---|
| Codex source audit | `openai/codex@dad1db87bb5ad4b92af6b0f58502d12453681f81`; zero Tau2 references |
| Tau2 harness | `sierra-research/tau2-bench@668d3bcd135c02aa3438f987ef45735b7c163ee3`; `tau2==1.0.1` |
| Harness preflight | `tau2 check-data` passed; telecom `base` contains 114 ordered tasks |
| Ordered Telecom base IDs | canonical JSON SHA-256 `eed4303eea9aa5a9e12847e55ffa3083c5d010a375af1364fb24a6c6fa4b8377` |
| GEODE effort surface | GPT-5.4 accepts `none`, `low`, `medium`, `high`, `xhigh`; adapter forwards the value to Responses `reasoning.effort` |

The GEODE commit is frozen only after the feature/release workflow reaches the
exact executable head. A moving branch name is not a measurement identity.

## 3. GEODE measurement profile

The first comparison is an effort ablation, not an attempted reproduction of
OpenAI's hidden harness.

| Field | Shared value |
|---|---|
| Domain / split | Telecom / `base`, all 114 tasks in pinned split order |
| Agent | `geode_agent`, GPT-5.4, OpenAI subscription |
| User | evaluator-owned `crucible_user`, GPT-5.4, OpenAI subscription, effort `low` |
| Agent efforts | arm A `none`; arm B `xhigh` |
| Trials / seed | one complete trial first; seed 300 |
| Limits | `max_steps=200`, `max_errors=10`, `max_retries=3`, timeout 3600s |
| Concurrency | 2, matching the last valid GEODE full-cycle operating profile |
| Agent/user budgets | 600s / 180s; 32,768 / 8,192 tokens; unlimited inner rounds (`0`) |
| Score authority | native Tau2 result and executable state/action checks |
| Invalid attempts | auth, quota, transport exhaustion, harness fault and incomplete coverage excluded, never scored zero |
| Evidence | native result, runtime profile, attempt manifest, normalized trajectory, verifier receipt, redaction and publication manifests |

Why the user differs: the public OpenAI row does not identify its simulator.
Tau2 recommends GPT-5.2 and Sierra used GPT-5.2-low, but GEODE cannot route
GPT-5.2 through the current subscription account. Replacing it with an
unrecorded model would be false parity. `crucible_user` keeps the evaluator
outside the candidate mutation surface and makes the deviation explicit.

The current upstream defaults `max_steps=200`, `max_errors=10`,
`max_retries=3`, seed 300 and concurrency 3 are implementation defaults, not
published OpenAI run settings. GEODE uses concurrency 2 as an operational
quota control and records it as a deviation rather than presenting it as
official.

## 4. Execution gates

1. Copy the existing comparison-manifest template once per arm; freeze the
   exact GEODE commit, all 114 ordered IDs, hashes, limits and destinations.
2. Diff the manifests. Only `run_id`, agent effort and arm-specific evidence
   paths may differ.
3. Run one fixed Telecom task on each arm. Stop on auth, empty-output,
   unpaired-tool, state-reset or quota failure.
4. Run all 114 tasks once per arm. Reject a partial or contaminated aggregate.
5. Only after the paired one-trial run is valid, decide whether the cost of
   four trials is justified for a suite-oriented estimate.
6. Publish append-only to `geode-eval-artifacts`; pin its commit in the Tau2
   ledger. Never merge the OpenAI, Sierra and GEODE rows into one headline.

The one-trial run reports raw numerator/denominator, component rewards,
termination, latency, token/tool usage, task-level paired flips and invalid
attempts. It does not report `pass^4`, `mean_accuracy@8`, or a causal Codex
scaffold effect.

## 5. Comparability map

```text
OpenAI research score (hidden harness/user/tasks)
        -> directional model reference only

Sierra GPT-5.4 banking submission (public 97 x 4 contract)
        -> reproducible suite reference, wrong domain for Telecom

GEODE GPT-5.4 none <-> GEODE GPT-5.4 xhigh
same current harness + tasks + evaluator-owned user + limits + seed
        -> valid GEODE effort ablation
```

The next live action is the two-arm single-task smoke. It spends subscription
quota and therefore remains outside this documentation-only change until the
operator explicitly approves the live run.
