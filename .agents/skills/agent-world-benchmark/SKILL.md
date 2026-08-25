---
name: agent-world-benchmark
description: Align, run, audit, and publish GEODE benchmark comparisons against Agent-World arXiv 2604.18292v1 across MCP-Mark, BFCL V4, and tau2-bench. Use for Agent-World or AgentWorld comparison requests, cross-suite agent benchmark design, Tau2 comparator/profile diagnosis, paired thin-runtime-versus-GEODE experiments, mean-accuracy@8 replication, or benchmark comparability and artifact reviews.
---

# Agent-World Benchmark

Build evidence that separates an external paper reference from a causal GEODE
runtime comparison. Never reconstruct missing Agent-World implementation
details from its score table.

First disambiguate the target. This skill covers Dong et al.'s Agent-World
(`arXiv:2604.18292`), not Qwen's later `Qwen-AgentWorld-35B-A3B` and
`AgentWorldBench` (`arXiv:2606.24597`).

## Security And Data-Handling Boundary

This skill does not provide cryptographic services. It does not generate or
manage keys, encrypt or decrypt data, create or verify signatures, or process
certificates. The `task hash`, `prompt hash`, `policy hash`, and `schema hash`
fields below are deterministic identities for non-secret canonical benchmark
artifacts. They support reproducibility and change detection; they do not
provide confidentiality, authentication, or authorization.

Do not choose a cryptographic primitive or implement one inside a benchmark
runbook. If a future benchmark genuinely requires encryption, signing, or
certificate handling, stop and define a separately reviewed contract covering
the security purpose, reviewed library or platform service, algorithm, key
source and ownership, storage, rotation, revocation, and destruction.

Handle sensitive data by class:

| Class | Allowed source | Handling | Public evidence |
|---|---|---|---|
| API keys, OAuth/access tokens, passwords, private keys | Existing provider, environment, OS credential, or operator-configured path only | Never request, read for validation, copy, print, hash, place in CLI arguments, or persist in benchmark artifacts | Never publish |
| Private prompts, account identifiers, user content, and PII | Only when the frozen benchmark contract requires it and the operator authorized the run | Keep in the existing private evidence location; minimize collection and do not duplicate it into manifests, logs, or reviewer prompts | Publish an aggregate, opaque ID, or redacted derivative only |
| Run IDs and artifact hashes | Canonical non-secret manifests and artifacts | Use existing repository or harness generation and validation paths | Publish when required for reproduction |

Hashing a secret is not redaction: low-entropy values can still be guessed and
the digest creates a durable correlator. On a suspected credential leak, stop
publication, report only the file and secret class, and rotate or revoke the
credential before repository cleanup. Never paste the value into an issue, PR,
review prompt, or log.

## Read First

Read these sources in order:

1. `docs/eval/agent-world-comparison-contract.md` — canonical profile,
   comparability classes, fields, and done definition.
2. `docs/eval/agent-world-run-manifest.template.json` — machine-readable
   preregistration scaffold; copy it per arm and replace every placeholder.
3. `docs/eval/benchmark-publishing-cycle.md` — execution, artifact admission,
   publication, and release workflow.
4. The suite ledger for every selected suite:
   `docs/eval/mcpmark-agentworld-comparison-runbook.md`,
   `docs/eval/frontier-agentic-tool-use-benchmark-cases.md`, and
   `docs/eval/tau2-bench.md`.
5. Current upstream primary source and repository revision. Treat the dated
   GEODE ledgers as evidence, not as a substitute for current source.

## Select The Claim Before Running

Choose exactly one claim class:

| Claim | Meaning | Authority |
|---|---|---|
| `paper-reference` | Place a GEODE result beside Agent-World Table 1 | Directional only |
| `paired-runtime` | Measure GEODE versus a thin upstream adapter with every non-runtime variable matched | Causal scaffold evidence |
| `suite-headline` | Publish a score under the official suite's own current protocol | Suite-specific only |
| `smoke` | Prove wiring, reset, scoring, and artifact flow | No performance claim |

Do not promote one class into another after seeing results.

## Freeze The Measurement Contract

Record before any live run:

- a shared comparison ID and a unique per-arm run ID;
- GEODE and harness commits, package/server versions, task IDs/order/hash;
- model label, provider, API/subscription route, and reasoning setting;
- arm-specific runtime, adapter, prompt hash, and policy hash;
- exact tool execution path and schema hash, timeout, step/error/retry budgets,
  concurrency, and environment reset;
- agent and simulated-user wall-clock, token, and round budgets;
- user simulator implementation/model/route for tau2;
- trial count, seed schedule, retry policy, score authority, and aggregation;
- confidence coverage, estimator, sampling unit, paired method, resample count,
  and uncertainty RNG seed;
- artifact destination, redaction boundary, invalid-attempt rule, and promotion
  authority.

Copy `docs/eval/agent-world-run-manifest.template.json` for each arm. Give the
pair one `comparison_id`; derive each unique `run_id` by adding arm role and
runtime. Validate that each file parses as JSON, contains no `<...>`
placeholders, has a non-empty ordered task list, and uses the required JSON
number or `null` type for every limit. Literal template strings and inherited
zero defaults whose semantics were not checked are invalid. If a runtime uses
zero to mean unlimited rounds, record zero explicitly together with
`zero_rounds_semantics=unlimited`.

Apply claim-specific validation:

- Agent-World-aligned results use `repetitions=8`, `mean_accuracy@8`, and
  exactly eight ordered seeds;
- smoke runs record their actual repetition count and `diagnostic`;
- directional paper comparisons record the actual GEODE run count, statistic,
  and one seed per repetition; paper-only rows do not use a run manifest;
- `paired_task_trials=true` requires two matched arms;
- tau2 requires `user_simulator.required=true` and non-`na` user identity and
  wall/token/round budgets.

For `paired-runtime`, allow only the runtime arm to differ. Use the same model
route and decoding surface in both arms. Name the control `thin-upstream` or by
its concrete adapter; do not call the Agent-World paper row `no-loop` or
`vanilla`, because the paper says it used an undisclosed in-house evaluation
framework.

Diff paired preregistrations before running. Ignore only `run_id`, the complete
`arm` object, and arm-specific evidence destinations; reject the pair if its
comparison ID, ordered tasks, tool path/schema hash, model route/effective
decoding, user simulator, budgets, retry rule, or scoring contract differs.

## Apply The Agent-World V1 Surface

Preserve the paper's public surface without inventing hidden settings:

- suites: MCP-Mark, BFCL V4, tau2-bench;
- MCP-Mark columns: File, GitHub, Notion, Play, Post, official aggregate;
- BFCL V4 columns: WebSearch, Memory, Multi-Turn, Non-Live, Live,
  Relevant, Irrelevant, official aggregate;
- tau2 columns: Retail, Telecom, Airline, official aggregate;
- evaluation decoding target: `temperature=1.0`, `top_p=1.0`;
- eight complete repetitions and mean accuracy across repetitions.

Call the statistic `mean_accuracy@8`, not `pass@8`, `pass^8`, or `avg@8`
without definition. If a subscription route does not expose temperature or
top-p, keep the target at 1.0 but record both effective values as `null`, note
the protocol deviation, and keep the paper comparison directional.
Never manually average displayed subcolumns; use each official harness's
aggregate because the paper does not publish its aggregation implementation.

## Execute In Gates

1. Run a no-model preflight and state-reset test.
2. Run one task per environment as a wiring smoke.
3. Run one full repetition and reject infrastructure contamination.
4. Run eight complete repetitions for an Agent-World-aligned measurement.
5. Preserve every attempt; select only a valid final attempt according to the
   preregistered retry rule.
6. Report per-task rows, suite/domain rolls, mean, uncertainty, wall time,
   tokens, failures, and paired flips where applicable.

Live model, account, or remote-service calls require explicit user approval.
Quota exhaustion, missing services, and harness faults are infrastructure
invalidity, not zero reward and not a partial headline.

## Preserve And Publish Evidence

Keep these layers distinct:

- upstream native result as score authority;
- GEODE session/trajectory and exact tool call-result pairs as behavior
  evidence;
- verifier receipts and environment state diffs as judgement evidence;
- immutable eval bundle and publication manifest as release evidence.

Publish append-only artifacts to `geode-eval-artifacts`, pin its commit in the
GEODE ledger, and apply the security and data-handling boundary above before
admission.

## Fail-Loud Rules

- Reject a direct paper comparison when harness/task/user/scaffold identity is
  unknown or mismatched.
- Reject cross-suite composite scores unless a preregistered, named aggregate
  is the claim; do not use them for promotion.
- Keep Agent-World's version-unspecified MCP-Mark and MCPMark Verified in
  separate columns.
- Keep tau2 native-user and `geode_user` profiles separate.
- Keep `max_errors`, `max_steps`, user simulator, route, and model changes out
  of a single causal conclusion.
- Reject empty ordered-task lists, duplicate paired run IDs, incomplete
  agent/user budgets, and a task hash with no recorded preimage.
- Reject tau2 without a user simulator, a seed-count/repetition mismatch, and
  uncertainty recorded only as a confidence percentage without its estimator
  and sampling unit.
- Do not convert missing or infrastructure-invalid tasks to failures.
- Do not describe normal protocol `Stop` as task success without verifier
  evidence.

## Report Contract

Finish with the selected claim class, frozen/mismatched fields, suite-level
scores, uncertainty, invalid attempts, artifact commit, comparability verdict,
and the next smallest experiment that can isolate any unresolved variable.
