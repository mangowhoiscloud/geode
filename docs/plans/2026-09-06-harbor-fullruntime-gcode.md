# G-code follow-up: native runtime, visible inputs, and observed cache usage

## Decision and boundaries

The historical Terminal-Bench 2.1 run is immutable. Its `gcode-to-text`
results are GEODE 0/5 and native Codex 4/5. A new auxiliary study must not
replace historical attempts, fill missing historical behavior, or join the
890-cell scoreboard. No release, tag, or PyPI publication is authorized.

The candidate uses the native `GeodeRuntime` and `SharedServices` composition
inside each Harbor task container. It does not invoke `evolve`, SIL, Crucible,
or another outer candidate-search loop. Internal runtime services, native
tools, memory, hooks, middleware, and workers retain their native owners.
Fresh trial-local state and one explicitly frozen subscription model replace
the operator's personal configuration; external accounts are not imported.

## Evidence and minimum changes

| Gap | Source | Acceptance |
|---|---|---|
| Historical adapter is a one-tool control, not the full runtime | `evals/platforms/harbor.py:_build_loop` | New opt-in container adapter uses `core/wiring/runtime.py` factories; old adapter identity remains separate. |
| Available GEODE G-code traces only have `terminal_exec`; all five native trials used `view_image` | Original result hashes matched `research-v22/task-diagnostics.json`; timeout repetition 2 lacks GEODE ATIF | Generic local-image delivery passes a synthetic-image test; no task-specific OCR recipe or answer is injected. Native repetition 4 failed despite image use, so causality is not established. |
| Cache absence is coerced to zero; Harbor also reads the wrong cache key | Provider parsers, `UsageSummary`, activity projection, Harbor export | Preserve observed zero versus missing/null through provider-to-durable-activity records; retain numeric cost-counter compatibility. Export partial coverage, never a fabricated total. |
| Timeout may skip the old adapter's post-run trajectory export | `GeodeHarborAgent.run` | Container entry point finalizes native state in `finally`; incomplete/orphan traces stay incomplete rather than fabricated. |

## Prospective execution gate (not a run receipt)

1. Deterministic image, privacy, usage, lifecycle, and adapter tests; full CI
   and feature-to-develop PR gate before score-bearing model calls.
2. Freeze a new run spec and task manifest using existing `geode.eval-*`
   contracts. Pin source commit/archive, lockfile, Harbor, Codex, image digest,
   model/source/effort, all task resource/time limits, attempt count and order.
3. Read-only subscription credential check, task image/container isolation,
   free disk/available resources, and original oracle verifier must pass.
4. Non-benchmark synthetic-image live smoke under a separately frozen budget;
   then bounded G-code smoke. Concurrency 1, no automatic trial retries.
5. If gates pass, five fresh repetitions per GEODE/native arm at the original
   900-second agent limit. This is a product-level comparison, not isolation
   of the image tool's causal effect. A further ablation needs its own freeze.
6. Preserve failures, timeout zeroes, setup-invalid attempts, native records,
   call-level usage and coverage, ATIF/derived replay, verifier outputs and
   publication receipts. Redact/scan before append-only publication.

No success threshold authorizes retry-until-pass. Subscription entitlement,
image-wire acceptance, verifier preflight, and measurement are unverified
until actual receipts exist. The slides should show the historical baseline,
this candidate, and its verified state separately.

## Cache follow-up is a separate cohort

The subsequent request for same-spec cache remeasurement does **not** authorize
mixing this full-runtime/image candidate into the historical thin control.
The source is the immutable artifact commit
`d277607f3a179f191ad24b1497c0934beb9d2470`. Joining canonical selected measurement
attempt IDs, validity, and recovered call usage reproduces the original common
comparison (GEODE 339/429, native 331/429) and selects **281 pairs across 84
tasks**, or **562 new attempts**. Both arms have complete cache evidence for
148 pairs. GEODE alone is incomplete for 270, native alone for five, both for
six. The 20 prospective not-run cells and six unresolved native invalid cells
do not enter this cohort. The analysis-materialization row is not a trial.

`artifacts/eval/runs/terminalbench21-sol-max-cache-followup-20260906/prepare-cohort.py`
reproduces the join from five digest-pinned historical sources. Its `cohort.json`
is a selection receipt, **not a frozen execution spec**. It keeps the exact
task/repetition identities, source attempt IDs, and original task time/resource
contracts. Their agent-time upper bound is 909,000 seconds (252.5 agent-hours),
not a wall-clock forecast or a dollar estimate.

Before live execution:

1. Backport **only** cache presence, pure durable observation, and bounded
   finalization to historical revision `b549f3e448f06c75db45df6082013dc21a611dec`;
   pin the reviewed patch/archive hash separately from that base revision.
   Do not use the full-runtime entry point or the new image tool. Preserve
   prompts, tool schemas, reasoning settings, runtime control, and lockfile.
2. Use the existing run-spec and attempt contracts. Freeze Harbor 0.22.0,
   Codex 0.145.0, subscription `gpt-5.6-sol`, root effort `max`, task-specific
   canonical timeouts/resources/verifiers, zero automatic retries, and exact
   GEODE-then-native workload order. No silent model/source substitution.
3. The first gate is the first selected pair in original registry order:
   `terminal-bench/write-compressor`, repetition identity 1. One fresh attempt
   per arm at concurrency 1, after passing oracle/auth/isolation/disk checks.
   No primary cohort expansion until observed-zero, positive, missing, and
   interrupted-call handling are verified. A semantic verifier zero is not an
   instrumentation failure or a reason to rerun.
4. Gate attempts and any supplements keep their own prospective identity and
   are not retrospectively inserted into the old run or counted twice. Pin the
   remaining cohort before its calls; respect current resource availability
   without changing task allocations. Stop on unknown telemetry coverage.

Analysis should report cache-data completeness first, then paired cached-input
share (`observed cached input / observed input`), uncached-input volume, and
agent/provider latency with the exact call scope and coverage. Missing cache
is null, not zero. Do not call recorded AgenticLoop subtotals whole-runtime
usage: auxiliary text-completion routes are a separate unresolved observation
surface. Native comparison must use a compatible scope or explicitly remain
descriptive. Retain verifier outcomes as context, not a new full-suite score.
Use task-cluster uncertainty and disclose the retrospective missing-data
selection and fixed arm-order confound. Provider cache state, account traffic,
backend revisions, and unsupported seeds prevent exact historical replay.

## Current verification boundary

The adapter inherits Harbor 0.22.0 `BaseInstalledAgent`: Harbor owns setup,
agent execution, timeout classification, verifier invocation, log collection,
and job/trial results. GEODE implements installation, one native session, and
post-run ATIF projection; it does not implement a competing orchestrator.
An absolute required model policy is snapshotted by Codex adapters. Trial-local
configuration pins role models; API-key environment variables fail preflight.
Only the subscription credential is transferred, outside collected log roots.

The official G-code oracle preflight completed one trial with reward 1, no
errors, and no model calls on 2026-09-06. Its immutable job is
`terminalbench21-sol-max-fullruntime-gcode-20260906/raw/preflight/oracle-gcode-20260906`.
This proves the local task verifier path, not the candidate runtime.

The full-runtime adapter is opt-in and not live-validated. It now waits for
process exit and an export receipt after cancellation, drains child tasks,
then opens a fresh reader over the closed canonical event database. Root
`max` configuration does not override native worker-difficulty or wrap-up
effort policies. Its recorded-call cache subtotals deliberately do not populate
Harbor whole-runtime token totals while auxiliary usage remains unobserved.
Reflection, candidate judging, hosted web search and auxiliary text completion
are outside the current AgenticLoop subtotal. Dreaming is a daemon-thread
service, so a process export marker is not proof of auxiliary-call closure.
Until those scopes have complete receipts, no whole-runtime cache comparison
or 562-attempt cohort expansion is authorized by the instrumentation gate.
Container isolation/mount checks and real lifecycle smoke are still required.
Interrupted native workers may lack terminal events because their existing
runner uses SIGKILL. Their canonical sources remain preserved, but a
scope-incomplete aggregate does not receive an ATIF/replay completeness claim.
Full-runtime ATIF steps leave reasoning effort null; only the configured root
effort is declared, separately from worker and wrap-up policies.

## Headless canary closure

The first new image canary at revision
`c2aa2baa71d690a8b00143551194514f507749d8` failed before API dispatch:
`build_responses_kwargs` probed desktop availability, PyAutoGUI imported
mouseinfo, and mouseinfo raised `KeyError('DISPLAY')` in the headless task
container. An offline, socket-blocked reproduction confirmed this exact path.
The generic availability probe now treats only that missing-display error as
unavailable desktop automation; unrelated errors still propagate. Local image
reading remains available and does not require a desktop display.

The closed canary retains its Harbor result, three failed recorded call
attempts with null usage, canonical SQLite/trajectory, verifier zero, and PTY
capture under `terminalbench21-sol-max-fullruntime-gcode-20260906`.
Neither G-code arm started. This is a failed non-benchmark integration gate,
not a task-performance result or a recovered historical attempt. A corrected
candidate needs a new source hash and prospective canary before expansion.

## Nullable image-call follow-up (2026-09-07)

The closed corrected-headless canary also failed: its trace contains 17
recorded model calls, repeated numeric line controls on `read_document`, no
image provenance, and a verifier zero. This is not a G-code outcome.
The follow-up makes unused line controls explicitly nullable in the tool
schema and reader; positive text ranges and image size/path guards remain.
Zero/negative/bool/string line controls are rejected, not treated as missing.
The deterministic regression crosses schema validation and the registered
handler, then checks image content and null text defaults.

Responses can normalize unspecified strictness into a strict schema; explicit
nullable fields follow the official function-calling contract. This does not
prove the subscription backend's resolved schema or that a live model will
select the right arguments. A new prospective canary must establish image
provenance, a subsequent provider response and verifier success before G-code.

Category-only recovery selecting `show_help` is a separate confirmed defect:
absence of a tool error is not evidence that the original image read succeeded.
It is unchanged in this candidate. The canary gate must not use that status as
its acceptance criterion. Provider-returned identity and whole-runtime
auxiliary usage also remain explicitly unverified where records are absent.

Historical 0/5 versus 4/5 motivates development, not a held-out test. A fresh
full-runtime comparison changes more than image access and cannot establish
the image tool's causal effect or generalization across Terminal-Bench.

## Observability follow-up (2026-09-07)

The published historical recovery at artifact commit
`d277607f3a179f191ad24b1497c0934beb9d2470` reports verified call usage for
401 GEODE trials (4,709 events) and 418 Codex trials (12,214 events).
GEODE has 648 missing cache events, not 648 cache misses. Cache-positive
trial counts are 384 and 418 respectively; these are coverage diagnostics,
not a paired cache-efficiency comparison. The downloaded observability
projection hashes to `2f97bca0041174f4a2653996a0572d4b75df7c8b6c95f7d58dc6eda6d3e2cf84`,
matching its publication manifest. Private-source revalidation was not
repeated; the public receipt's 2,142 source checks are historical evidence.
Recounting the downloaded 890-cell projection reproduces the usage-event
coverage and finds zero non-null cache totals in trials with missing events.

Current cache extraction preserves field presence separately from billing
defaults. Lifecycle events retain absent cache as null, explicit zero as
zero, and positive counts as reported. Harbor refuses a complete subtotal
when attempt start/end identities do not pair or a field is missing.
The full-runtime adapter deliberately leaves Harbor token totals null:
reflection, judging, text completion and hosted search are not fully covered.
Its metadata carries the recorded AgenticLoop subtotal and missing counts.
Do not remove this guard to make a comparison possible.

A separate loss was confirmed in Responses translation: the SDK response ID
and returned model were not copied to the existing result fields consumed by
the lifecycle writer. The fix mirrors the Chat Completions translator and
leaves absent identities empty. Configured routing is not proof of the model
returned by a server. This patch does not retrofit historical identities.

Remaining admission limits before a cache-efficiency claim:

- Reconcile provider response -> attempt event -> private trajectory -> admitted
  numeric projection on a fresh smoke; deterministic fixtures are not live proof.
- Input/output/reasoning numeric defaults outside the cache-presence path still
  require a presence audit before treating every zero as observed.
- Legacy `LLMUsage.to_dict` and monthly `UsageRecord.to_dict` omit zero cache
  counters and their readers default absence to zero. They are not new-run
  cache authorities. The native Harbor adapter reads durable attempt events,
  not these lossy serialized rollups.
- Whole-runtime auxiliary-call coverage remains incomplete. Compare only an
  explicitly matched measured scope, or finish coverage before claiming totals.
- Phase durations describe elapsed time, not CPU or peak RAM. Neither resource
  usage nor subscription dollar billing can be recovered from token counts.
- Historical usage events are not joined to ATIF tool steps; do not label them
  tokens per tool turn. Re-execution creates new evidence, not recovered history.

No model calls or artifact publication occurred in this follow-up.

## Verification and recovery candidates (2026-09-07)

Two deterministic false-success paths are fixed before any new paid run:

- Verifier exceptions and malformed judge verdicts previously became passes.
  They now retain `verification_error`, structural score 0, and no automatic
  repair request, including when PreVerify adds requirements. This is not a
  Harbor reward zero; the external task verifier remains score authority.
- Automatic recovery previously treated category/price as tool equivalence.
  A successful help response could replace a failed read/status operation.
  Remove this substitution, retaining same-tool retry, admission gates and
  attempt lineage. The model may select a new tool after observing the failure.

Acceptance is observable correctness first: malformed verdicts never pass,
unrelated tool success never clears the requested operation's failure, and
existing successful retries still work. Targeted tests pass (121 cases);
these checks do not establish a benchmark gain.

The measured loop will keep the frozen baseline, prospectively register the
candidate revision and matched resources, preserve all attempts, and promote
only after independent task-verifier results and observation-coverage checks.
Do not optimize on verifier exceptions, overwrite old trajectories with fresh
runs, or count missing cache fields as zero. Present this as an engineering
hill-climbing experiment, not an implemented DGM search system. Outcome slides
remain pending until measurement finishes.

Live admission is still blocked: the host has approximately 5.2 GiB free on
2026-09-07, below the task's 10 GiB storage allocation before image overhead.
Do not prune other sessions or silently shrink the frozen environment.

## Primary references

- [Darwin Godel Machine](https://arxiv.org/abs/2505.22954): empirical evaluation
  of code candidates and candidate archives; inspiration, not implementation parity.
- [Reward tampering research](https://www.anthropic.com/research/reward-tampering):
  motivates keeping evaluator authority separate from the optimized agent.
  The defects above are harness bugs, not evidence of deliberate reward hacking.
- [Datasheets for Datasets](https://arxiv.org/abs/1803.09010): preserve collection
  conditions, missingness, permitted interpretations and lineage in run artifacts.

- [Published recovery receipt](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/d277607f3a179f191ad24b1497c0934beb9d2470/terminal-bench/terminalbench21-sol-max-fullsuite-paired-20260827t190300z/recording/research-v20/data/recovery-check.json)
  and its adjacent publication manifest: historical numeric recovery, not a new run.
- [OpenAI Responses contract](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create):
  response ID/model and usage fields; subscription live presence remains to be checked.

- [Harbor custom agents](https://www.harborframework.com/docs/agents): the
  adapter here is checked against the installed `harbor==0.22.0` source.
- [OpenAI function outputs](https://developers.openai.com/api/docs/guides/function-calling)
  and [Codex image handler](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/view_image.rs):
  image content is not a base64 text string or a native computer-use result.
