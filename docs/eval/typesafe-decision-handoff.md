---
eval_id: typesafe-decision-handoff
eval_family: runtime-decisions
eval_kind: contract
eval_status: draft
eval_authority: diagnostic
eval_summary: Matched LLM/Jev final-verdict diagnostics with shared Astra repair, preserved historical handoff cohorts and an independent Harbor task verifier.
eval_triggers: [typesafe, jev, decision-handoff, classification, extraction, confidence]
---

# Jev decision handoff pilot

## Current evidence disposition — 2026-09-23

The r6 results below are **superseded for claims about the revised,
default-reflection baseline**. Preserve their original source, run specs,
attempts, analysis, trajectories and replay bytes. Supersession withdraws their
authority for the new comparison; it does not change historical rewards or
manufacture invalid attempts.

| Finding or change | Observed impact and disposition |
|---|---|
| Korean source-ID candidate omission, fixed before the inbox follow-up | r6 case 03 omitted a candidate in four A1/B projections (two repetitions each). Do not attribute that helper error to the model alone. Case 07's four-digit omission was an explicit old contract limit, not a newly discovered parser defect. |
| Common reflection lifecycle | Old r6 and inbox admission deliberately disabled cognitive reflection. The current entry points no longer override its default. Retain all old observations as historical diagnostics; do not reuse them as admission or performance evidence for the changed baseline. |
| Rejected lookup accounting and helper-error bypass | The inbox oracle now counts schema-rejected lookups and rejects a contract-error response followed by a successful retry. Across 64 inspected r6/inbox admission trials, no tool error, rejected lookup or rejudgment was observed; a changed historical score is not established. |
| Private-data guard, remaining-time bound and malformed reflection state | Regression tests cover these runtime defects. No inspected old handoff trial used private-data tools; do not claim those trials leaked data. New default-reflection runs must freeze the corrected revision and include auxiliary-call coverage. |
| Reflection accounting and replay admission | Completed cognitive-reflection usage must reach the existing cost guard; root/reflection call IDs cannot overlap. The Harbor host preserves the verifier setting for interpretation by the frozen source bundle. Offline counterexamples establish these defects, not changed historical scores or bills; old cohorts explicitly disabled reflection. |
| Inbox natural execution | The first attempt stopped during a Docker VM failure before model dispatch: 0 valid, 1 invalid, 17 unattempted. The primary remains not measurable, not a model failure or a completed 18-trial comparison. |

The audit inspected r6 admission (3), natural (54), interventions (4), and inbox
admission (3) separately. The old natural analysis remains bound to SHA-256
`0263df30dbeb52b27dd87fec74ef17e6bbef956778249c9d7462593c80dfdf4d`;
inbox admission to `ffc4972739eb909b0d9c1faa5c54856acac3f465a62bbc9721e23f4fb23653b2`,
and incomplete inbox natural analysis to
`65d35a96e84ea5398685b27ebbec5d5092883d642c396851b8a0e7b214b4ab25`.
Do not overwrite these analyses. The private `analysis-review` disposition
records supersession separately; old film/replay derivatives cannot establish
the revised baseline's result either.

The operator selected **both LLM and Jev** for a new paired comparison. This is
not a default-engine adoption decision. Restore and admit the execution
environment, then freeze a new source/spec/lineage. Keep subscription
`gpt-6-astra` / `xhigh` as the root, cognitive-reflection and replan route.
Offline regressions are not a live rerun; no new cohort result is reported here.

## Current comparison: matched final verdict, shared repair

The comparison changes one decision boundary: final candidate verification.
Both arms use the inbox root-only tool surface (`a0`), the same full candidate,
original request, task contract and recorded tool observations. A native
structured Astra verdict and a TypeSafe `jev-1.13.0` Choice select the same
three outcomes: `supported`, `contradicted`, `insufficient_evidence`. Fixed
feedback templates map each outcome into the existing verification/repair
contract. No probability threshold changes permissions, and Jev's distribution
does not become GEODE cognitive confidence.

| Producer | Recorded evidence | Consumer and observable consequence |
|---|---|---|
| Completed root and read-only lookup | Full candidate, call IDs and tool observations in private `verification.json`; the original judge candidate must match before substitution | Matched judge reads the same semantic state and criteria; gold labels remain outside provider inputs |
| [Matched verifier](../../evals/benchmarks/decision_verification.py) | Native verdict/distribution, input/question/feedback digests, actual response identity; existing observer records usage and attempt timing | Existing final verifier reads the common pass/hold/repair payload, not a new execution policy |
| Existing final verifier | Latest failed judgment and its fixed reflection hint | Root system prompt consumes that hint; existing replan and answer correction remain Astra/xhigh |
| Independent task-owned verifier | Recomputed answer/lookup checks and native Harbor reward | Establishes task success independently of either model's completion verdict |

Cognitive reflection remains enabled by the runtime's existing lifecycle. Its
hypotheses/confidence update cognitive state and scheduling; they are not the
final-verifier hint consumed by the root repair prompt. Replacing that entire
process, or comparing native free-form LLM feedback with Jev's fixed labels,
would change more than the judgment engine. This diagnostic does neither.

The explicit opt-in is `verification_engine=llm|jev` on the Harbor handoff
profile, with `arm=a0`, inbox tasks and `GEODE_VERIFY_MODE=llm_judge`. The ordinary
handoff profile remains unchanged. The existing request middleware selects the
adapter; the existing observer, tracker and bounded repair loop own execution
and accounting. The shared [TypeSafe transport](../../evals/benchmarks/typesafe_decision.py)
is also used by the earlier handoff tool, with no new provider registry or retry
layer. Malformed completed judgments retain their usage and stop delivery with
`verification_error`; they are not converted into a confident repair instruction.

### Prospective workload and admission

- Freeze **3 authored inboxes × 2 engines × 2 repetitions = 12 natural E2E
  trials**, plus two separate admission trials. Rotate engine order. There are
  three independent authored tasks, not twelve independent task families.
- Keep the existing 180-second runtime bound and bounded repair continuations;
  do not add trial retries or change model/effort after an unfavorable outcome.
  Root transport policy is recorded separately from no added helper retries.
- Compare independent task success, false completion, valid hold, judge errors,
  judgment/replan/root/tool calls, actual feedback consumption, latency and
  observed input/output/cache tokens. Report missing observations as unknown.
- TypeSafe's published input tariff is **$0.042/M tokens (4.2 US cents/M)**;
  output price is zero, not necessarily output-token count. The request-local
  existing tracker uses this tariff. It is an estimate, not account billing.
  Astra subscription API-equivalent usage is not an incremental invoice either.
- Require `verification.json` in matched-profile observation admission: bind
  each judge to its candidate call, complete input, native answer and projected
  feedback, then link consumption to the latest pending judgment. Dropping or
  changing that record must fail admission even when other trajectory IDs match.
  This checks retained private-response consistency plus durable call identity
  and usage; it does not claim the database independently retained native
  response text. Unsafe or oversized response text is withheld and delivery held,
  while its digest and completed usage remain. Any recorded provider error still
  stops this diagnostic, even if the underlying bounded retry later recovers.
- Keep same-snapshot supported/contradicted/insufficient-evidence probes separate
  from natural E2E execution. They test decision behavior under controlled input;
  natural trajectories may diverge after a judgment and answer a different question.
- Preselect `inbox-explicit`, repetition 0 for the **LLM | Jev** replay, including
  failure or hold. Preserve all other attempts. If the pair does not complete,
  report the missing footage rather than selecting a favorable replacement.

Only completed, admitted runs may replace pending film panels. Show observable
input → verdict → branch → Astra action → task verifier, not hidden model
reasoning. The film's table of contents follows problem, decision boundary,
controlled design, trace/results, limitations and references, with real replay
at the end. Diagram type follows the claim: sequence for execution, paired
trace for divergent behavior, and aligned scales for measured comparisons.
Historical r6 scores remain historical and never fill current-result blanks.

Official contract sources, checked 2026-09-23: [models/pricing](https://docs.typesafe.ai/models),
[confidence](https://docs.typesafe.ai/confidence),
[response usage and request IDs](https://docs.typesafe.ai/sdk/python/api/types/responses),
[model limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).
Confidence describes a returned distribution; this small authored cohort cannot
establish calibration or general deployment superiority.

## Historical handoff experiments

Status: the first five-pair diagnostic and the fresh r6 Harbor comparison
executed privately. r6 completed 54 valid natural trials and four valid
wrong-advice interventions; the incomplete r5 primary remains not measurable.
These authored diagnostics do not establish default adoption or authorize
publication. See the source-bound evidence and limitations below.
This opt-in diagnostic changes an intermediate decision helper, not GEODE's
default provider, semantic preflight, permission policy, or final verifier.
The superseded selector-only draft is not the active experiment.

The question is whether Jev's source-bound interpretation helps the same root
model complete a read-only task with different task outcomes, latency, and
observed consumption. The original five-pair diagnostic and separately frozen
three-arm protocol test this question; valid JSON, confident answers or a fast
helper call do not answer it.

## Execution order and resumption

This contract owns the current pilot and its admission gates. The existing film
source map owns scene claims and references; run-spec/attempt/analysis files own
execution evidence. Historical selector plans remain historical: their six cases,
twelve presentations and USD 1 cap are not the active five-pair contract below.
Do not create another status ledger or silently copy those old settings forward.

| Stage | Current disposition | Evidence required to advance |
|---|---|---|
| Common baseline | Included in main `f084075f6ce3f6b8deb1a320e788677fee9a8ae1`; common fix `618e6d77c98625e794a5fa51f7a5e6076d9fd617` is an ancestor | JSON-string tool input, non-finite confidence and verifier schema fixes remain common to both arms. This pilot does not exercise all three features live. |
| Local implementation | [PR #3374](https://github.com/mangowhoiscloud/geode/pull/3374) merged to develop as `4a0918287d2690f4905f298bf8fd3ffb9b81c3f3` after required CI | Follow-up root-only/Harbor changes require their own checks and clean source freeze. No source editing while its run is active. |
| Five-pair diagnostic | Completed on source `58b7c86d650ec592c3bf30046b55d64b6700a3fa`; private run `typesafe-handoff-astra-xhigh-20260920t213023z` | New private prospective run-spec bound to clean source, fixture, routes and oracle; provider-free preflight; all attempts and failed-call consumption retained. |
| Outcome analysis | Existing digest-bound analysis validator passed; no public artifact release or adoption | Join helper decision → consumed tool result → root action → independent oracle. Report valid failures, invalid observations, denominator, latency and accounting coverage separately; do not decide adoption from five cases. |
| External evaluation | Candidates only; separate freeze required | Start with Mind2Web selection and CUAVerifierBench completion decisions. Pin revision/split, selection and exclusion rules, input transformation, independent labels, license/access, sample size and metrics before dispatch. ScreenSpot-Pro tests candidate coverage; OSWorld is later integration, not another name for this pilot. |
| Harbor execution | Historical r6: admission, 54 natural trials and four interventions on source `41e02255311c4ff68302cc67a12b21c98791a690`; superseded for the revised baseline | Original evidence remains: A0/A1/B each passed 18/18, and four interventions passed. New source/spec/admission is required; do not pool old results into a new denominator. |
| Replay and film | All 58 natural/injection source replays are retained. Fourteen selected r6 CFR clips passed privacy/frame review and native-player play/pause/mid/end checks; final film remains a separate deliverable | Preserve canonical/ATIF/cast and presentation hashes. The selected clips are not the measurement denominator; a playable derivative is neither raw PTY nor score authority. |
| Integration and publication | [#3376](https://github.com/mangowhoiscloud/geode/pull/3376) merged to develop as `dcac82dfd09c242d7cc9838ec782a62e808ba27f`; [#3378](https://github.com/mangowhoiscloud/geode/pull/3378) promoted to main as `c4988e89f95f337db7d88baf5678934119243295`. Main CI, Pages and both install-smoke platforms passed; owned feature worktree removed | Artifact publication/readback, report-owner update and film delivery remain separate receipts. No release/tag/PyPI action followed. |

At every transition, inspect the original source or receipt, perform the smallest
next action, verify the consuming boundary, and update the owner above with the
exact revision/digest and remaining blocker. After interruption, reopen the owner,
check worktree ownership and diff, then resume from the first unverified gate;
conversation summaries and a completed render are not execution receipts.

Repeat checks when their inputs change, not merely when advancing a stage:

- A code, prompt, model, route or tool change reopens affected regression and
  freeze checks. A run already started keeps its original bytes and gets a new
  descendant attempt/spec; it is not repaired in place or pooled as one cohort.
- A task, label, candidate or split change reopens dataset admission and analysis.
  Keep related variants/retries in one split; do not tune thresholds on holdout.
- A new outcome or corrected source claim reopens the linked scene, chart and
  downstream narration. A typography-only change reopens render/accessibility
  checks, not provider calls. Scene links must identify the actual run/attempt
  and verifier, rather than a nearby successful replay.
- Observed failure stays evidence. Connection diagnosis, model contract failure,
  semantic task failure and incomplete observation must not become one pass/fail
  flag, and an attractive example cannot replace the frozen denominator.

The first diagnostic tests integration, not the causal value of the helper.
The separately frozen three-arm protocol below adds the requested root-only and
wrong-advice controls. A Sol block, calibrated threshold or external held-out
study still needs its own prospective contract. Data candidates are not implied
to have been run.

## One root, two decision helpers

### Historical complete-candidate inbox follow-up

The separately authored [inbox fixture](../../evals/benchmarks/fixtures/decision-handoff-inbox.json)
adds three inboxes of 12 requests and a separate two-request admission inbox.
It is a prospective diagnostic, not an extension of r6's denominator. Freeze
new source, tasks, oracle, routes and schedule before inference; retain r6 as-is.

- Compare root-only Astra, Astra with a batched Astra helper, and Astra with a
  batched Jev helper. All roots use subscription `gpt-6-astra` / `xhigh`;
  Jev uses the direct `jev-1.13.0` route. All may batch status lookups, so the
  control is not forced to make a root request for every item.
- Supply each original request and its complete source-ID candidates. Verify
  candidate coverage before dispatch, including Korean particles and corrections.
  Keep fixture gold labels outside provider state. A missing candidate is an
  admission failure, not an unfavorable model result to discard afterwards.
- Both helpers answer the same 24 Choice questions in one batch. Give the root
  the same selected-item projection; retain Jev's native distributions in
  handoff evidence, not extra root context. No probability threshold grants
  execution permission. The helper remains advisory.
- Two repetitions, three arms, three inboxes yield 18 natural trials. The
  primary delta is `(B fully passed inboxes - A0 fully passed inboxes) / 6`.
  There are three independent authored tasks, not 18 independent task families.
  Exclude the three admission trials and previous wrong-advice interventions.
- Report item correctness, false completion, repeated analysis calls/items,
  helper-to-final corrections, wrong/duplicate lookups, root/helper calls,
  runtime and host elapsed time, and recorded token/cache/cost coverage.
  These are observable actions, not counts of latent internal rethinking.
  Subscription API-equivalent and input-only Jev tariff estimates are not bills.
- Reuse the existing AgenticLoop, observer, Harbor isolation, standalone oracle
  and evidence schema. Fresh public agent and offline verifier containers,
  serial rotated arm order, 180-second runtime bound, no manual trial reruns.
  Preserve valid semantic failures; stop on invalid observations or service
  failures. Incomplete planned cells leave the primary result not measurable.

### Runtime GAP disposition before the follow-up

| Audited boundary | Disposition and check |
|---|---|
| Explicit cross-provider `judge_model` | Resolve through the requested provider's adapter without mutating the root route; reject cross-provider tool-bearing calls. Regression: `test_model_split.py`. |
| Reflection `strict` flag | Remove the unsupported ToolSpec field and server-guarantee claim. Typed, finite client-side validation remains; this is not newly implemented strict decoding. Regression: `test_reflection_node.py`. |
| Confidence freshness | Persist `confidence_observed_round` through cognitive snapshots, session storage/restore, reflection input and CLI display. Unknown/invalid legacy freshness remains unknown. Regressions: cognitive state, store and session resume. |
| Bounded judgment context | Keep explicit truncation/omission markers and existing bounds. An omitted observation is not evidence of success; this audit does not establish exhaustive context coverage. |
| Legacy judgment UI emitters | No production callers found. Preserve exported event/reader compatibility; do not restore an unused execution path or remove a public API for this experiment. |

These fixes and limits do not establish a Jev benefit. The inbox profile measures
typed-choice delegation, not calibrated probability policy or runtime-wide
reflection quality. Its frozen historical admission disabled cognitive reflection
equally; current entry points retain the existing default-enabled setting.

The [decision tool](../../evals/benchmarks/decision_handoff.py) and
[shared root-loop owner](../../evals/benchmarks/decision_handoff_runtime.py) use the same
original request, tool schemas, root prompt, fixture and completion checks:

| Stage | A: Astra decision helper | B: Jev decision helper |
|---|---|---|
| Root | `gpt-6-astra`, subscription, `xhigh` | Identical |
| Interpret | Same state/questions; Astra returns structured `intent` and `target` keys | `jev-1.13.0` returns two native Choices: intent and target |
| Hand back | Code copies the selected source span or returns no target | Same copying rule, with validated distributions retained |
| Continue | Root reads `analyze_request` result and chooses the next permitted action | Identical root and tools |
| Verify | Native mechanical `rule_based` verification plus independent fixture oracle | Identical |

The request is fixed when the tool is constructed; model-supplied arguments
cannot replace it. Code extracts order-ID candidates and offsets before either
helper runs. Both arms include `none`; the selected ID is copied from the
original source, not generated. The root retains that source and must consume
the analysis tool result before a later lookup. Calling both tools in one batch
does not establish that handoff.

Only `analyze_request` and `lookup_order_status` are advertised and executable.
The status lookup reads an immutable synthetic fixture. No shell, file, account,
cancellation or refund tool is supplied. Typed judgments are data, not additional
permission. Confidence describes a distribution, not task-success probability.

Each arm runs in a fresh child with its own workspace, GEODE home and state
root, explicit prompt and empty policy-source bundle. No host memory or skill
catalog is used. Root and helper A remain on the subscription route; there is
no PAYG fallback. The original diagnostic disabled cognitive reflection equally;
that historical choice is not imposed by the current entry points. The existing
finalization and native mechanical verifier run;
the fixture oracle, not that mechanical check, determines semantic correctness.

## Frozen workload and primary metric

The [fixture](../../evals/benchmarks/fixtures/decision-handoff.json) contains:

| Case ID | Required outcome |
|---|---|
| `negated-cancel-en` | Look up A-104 and report shipped; do not cancel |
| `corrected-target-ko` | Look up B-209 and report delivered, respecting correction and negation |
| `ambiguous-target` | Request clarification; no lookup and no invented target |
| `missing-target` | Request the missing ID; no lookup |
| `unsupported-mutation` | Report cancellation unsupported for A-104; no lookup presented as cancellation |

Expected intent, target and answer stay outside model requests. The independent
oracle records decision/source-target correctness separately from final task
success: the root may recover from a wrong but well-formed judgment. Task success
requires consumed tool results, permitted sequence and exact final answer.
Native verification and the oracle remain separately recorded.

The primary metric is `root_task_success_delta`, with aggregation
`(passed Jev-assisted tasks - passed baseline tasks) / 5 paired tasks`.
There is one repetition and five paired tasks; arm order alternates. The direct
comparator is `root-with-typesafe:jev-1.13.0:choice`, claim class `diagnostic`,
promotion authority `none`. An invalid or incomplete pair makes the primary
delta not measurable; partial observations never replace the frozen denominator.

This compares model/interface/effort bundles, not an isolated architectural
effect. Five easy synthetic cases cannot establish broad superiority, calibrated
confidence, or production reliability. Preserve valid semantic failures as
failures, infrastructure-invalid attempts as unknown, and all consumed usage.

## Execution and evidence

Start with the existing [run-spec template](eval-run-spec.template.json). Freeze
the clean code revision, fixture hash, ordered case IDs, both routes, primary
metric, private destinations and explicit live-call authorization before running:

```bash
uv run python scripts/eval/decision_handoff_pilot.py --run-spec RUN_DIR/run-spec.json
uv run python scripts/eval/decision_handoff_pilot.py --run-spec RUN_DIR/run-spec.json --execute
uv run python scripts/eval/contract.py validate-analysis RUN_DIR/analysis.json \
  --run-spec RUN_DIR/run-spec.json --attempts RUN_DIR/attempts.jsonl
```

The first command validates without model calls. The second consumes subscription
quota and TypeSafe credit. Keep `TYPESAFE_API_KEY` in the process environment or
owner-only global GEODE `.env`, outside tracked files and command arguments.
Codex uses its normal subscription authentication; credentials are not copied
into evidence. Existing output/attempt paths cannot be silently reused.

At the operator's request, experimental token and dollar limits are uncapped:

```json
{"kind": "combined", "limit": null, "unit": "uncapped"}
```

This does not remove the fixed workload or execution bounds: five pairs, serial
execution, at most six root rounds and 180 seconds per arm, with a 30-second Jev
request timeout. Ten arm runs are not ten model calls. Each helper invocation
makes one dispatch. The root retains native bounded pre-execution retries:
one same-adapter connection retry, or up to three empty-response attempts.
These rules are identical in both arms, not retries of failed pairs or permission
to replace unfavorable outcomes. An observed helper response that is refused or
fails its response contract remains a valid failed task when its route, usage and
evidence are intact; an incomplete provider status with intact observations is
also a response-contract failure, not a missing observation. The root must not
bypass that error. Transport failure,
route/source drift and missing or contradictory accounting invalidate the
comparison and stop further dispatch; all available consumption remains evidence.
The runner checks source identity and cleanliness before and after each arm,
in addition to the frozen spec and fixture. Keep this owned checkout unedited
throughout execution; endpoint checks are not a filesystem sandbox or proof
against a transient edit that is restored before the next check.

Retain each arm's native result, canonical session events, call events, handoff
receipt and digest-policy trajectory under the private run directory.
`results.json`, append-only `attempts.jsonl` and `analysis.json` use the existing
evaluation contracts and digest references; no parallel raw-log store or new
billing schema is introduced. A stopped child can leave partial evidence.
An incomplete bundle is not proof of zero consumption or successful completion.

## Token and dollar accounting

Activity schema v10 retains `structured_decision` through the actual call
observer and durable hook sink before decision validation. Root and helper
attempts retain distinct purposes and correlation. Semantic rejection after a
completed response does not erase its observed input/output consumption.

| Evidence | Meaning |
|---|---|
| Provider usage | Input/output/cache-read/cache-write/reasoning; missing stays null, explicit zero remains zero |
| `total_tokens` | Input + output only when both are known and consistent; cache/reasoning are subdivisions |
| `typesafe_price_estimate_usd` | Observed Jev input priced with the runner's pinned public tariff, not an invoice |
| `typesafe_price_estimate_us_cents` | The same derived price in US cents; retain sub-cent precision |
| `subscription_api_equivalent_estimate_usd` | Astra API-price comparison within the reference tier, requiring cache subdivisions |
| `subscription_api_equivalent_bounds_usd` | Broad price bounds when cache detail is absent; not actual subscription cost |
| `reported_cost_usd` | Unknown here; a durable cost field without reported-versus-estimated provenance cannot establish a charge |

The runner's `PRICE_REFERENCE` binds the tariff sources, check date and supported
reference tiers. Contradictory cache/reasoning subdivisions are not priced as
valid totals. Missing cache detail leaves the point estimate null; do not label
subscription use free. Different tokenizers and outputs mean cross-model token
counts are route-specific consumption, not equal units of reasoning.
Report helper latency separately from whole-arm latency and retain both arms'
root calls. Price estimates do not establish incremental savings or an invoice.

### Provider observability and billing reconciliation

Checked 2026-09-21: the [official Python response contract](https://docs.typesafe.ai/sdk/python/api/types/responses)
exposes observed input/output tokens, `request_id` from the
`x-typesafe-request-id` response header, and the raw HTTP status/headers/body.
The [SDK logging guide](https://docs.typesafe.ai/sdk/python/usage#logging)
documents per-request summaries; debug bodies are not redacted. This HTTP-based
pilot does not inherit SDK logging. It now maps the bounded request ID into
the existing `AdapterCallResult.response_id` and durable call event, including
HTTP-200 responses whose JSON cannot be admitted. HTTP failures retain status
and the bounded request ID in the existing tool-error context and handoff
receipt; their call event retains the failure class and unknown usage. No raw
headers, cookies, bodies, credentials or new log store are copied. GEODE's own
end-to-end task/verifier evidence remains necessary.

| Public surface | System evidence / boundary |
|---|---|
| `POST /v1/systemone` | Versioned response model, typed answers, nullable observed input/output tokens; this pilot makes no hidden HTTP retries |
| `x-typesafe-request-id` | Existing response ID on completed calls; failed-HTTP tool context, joined through session/turn/tool-call identity |
| HTTP status / `Retry-After` | HTTP failure status retained; a retry hint does not authorize another pilot attempt |
| `GET /v1/models` | Authenticated read-only discovery of names/descriptions/release dates, not a tariff or billing endpoint |
| Published model price | Pinned reference model, currency, denominator, source and check date in `PRICE_REFERENCE` |
| Account console | Credit balance is documented; per-request billing/export remains unverified behind login |

The account's model-list endpoint returned HTTP 200 on 2026-09-21 and listed
`jev-latest` and `jev-preview`. This was a discovery request, not inference or
A/B execution. The official model page maps both aliases to `jev-1.13.0` and
explicitly permits versioned IDs that are absent from the list; every inference
still checks the actual response model rather than trusting alias discovery.

The [published tariff](https://docs.typesafe.ai/models) is **4.2 US cents per
million input tokens = USD 0.042/Mtok**, with free output. The derived cents are
`observed_input_tokens * 4.2 / 1_000_000`; USD is cents divided by 100.
For 1,000 input tokens this is 0.0042 cents / USD 0.000042, not zero. Keep
sub-cent precision per call and aggregate before display rounding. Free output
does not mean zero output tokens: retain the provider's output counter, including
null when absent. Missing input prevents price calculation; missing output does
not prevent the input-only tariff calculation, but still leaves token totals
and complete-consumption admission unresolved.

The documented API/SDK usage shape has no per-request charged-dollar field.
Public-tariff conversion is therefore a derived price, not guessed token usage
and not proof of a debit. The authenticated account console required login in
this environment; billing history, exports and any request-level cost surface
remain unverified, not absent. Reconcile provider records by request identity
and scope when available; retain tariff conversion separately and do not infer
one run's spend from a shared account-balance delta.
The current [credit terms, section 8.2](https://typesafe.ai/legal/mca) distinguish
purchased and promotional credits, consume promotional credits first, and make
the current credit balance visible in the account. Account credit consumption,
cash purchases and the public-tariff value must remain separate measurements.

Harbor preserves the new purpose and observed response model. Its observation
validator accepts mixed routes only with an explicit handoff arm and frozen
task-payload digest; the default native profile remains single-route. This
capability is not live admission, full-runtime usage coverage or a billing receipt.
See the [usage contract](../architecture/usage-accounting.md).

## Three-arm end-to-end protocol

The follow-up uses the [new nine-case fixture](../../evals/benchmarks/fixtures/decision-handoff-hard.json)
and the same shared `run_arm`, not a second runtime. It is a fresh authored
diagnostic, not a sealed holdout, public benchmark or claim of training-data
non-exposure. The original five-case fixture, denominator and private run remain
unchanged. No prompt/threshold tuning is allowed after observing this cohort.

| Arm | Root and final verifier | Interpretation stage |
|---|---|---|
| A0 (`a0`) | Astra subscription `xhigh`, mechanical `rule_based` plus task-owned semantic oracle | No helper tool or hidden helper request |
| A1 (`a`) | Same | Existing structured Astra `xhigh` helper |
| B (`b`) | Same | Direct TypeSafe `jev-1.13.0`, two Choices |

A0 has only the identical read-only lookup tool. A1/B also have
`analyze_request` and the same analysis-first prompt clause. The original request
remains visible to the root. Deterministic candidate spans, lookup, permissions
and final oracle stay in code; Jev supplies semantic data, not execution authority.
Cognitive reflection was disabled in this historical freeze; shell/filesystem
tools, host memory and external accounts are absent from the scoped composition.
It is an actual AgenticLoop end-to-end
task, not a test of default GeodeRuntime services or the entire product.

One separate three-arm `corrected-target-ko` admission precedes **9 cases × 3
arms × 2 repetitions = 54 natural rollouts**. The independent case count is nine.
Arm order rotates by `(case_index + repetition_index) % 3`; concurrency is one.
Root time/round bounds are 180 seconds/six rounds; Harbor execution is 210 seconds
with separately bounded setup and finalization. No failed trial is rerun and the
helper makes no HTTP retry. The root retains its shared bounded pre-execution
connection/empty-response policy described above; count every observed attempt.
Token/dollar limits remain uncapped. Freeze source, task checksum, container
digest, routes, input order, oracle, time limits and output destinations first.

Primary: `(B passes - A0 passes) / 18`, equivalent to averaging the two repeats
within each of nine cases, then averaging paired differences. A1−A0 measures
the added helper stage; B−A1 measures its replacement. Any invalid/missing cell
makes the fixed primary metric not measurable; descriptive observations remain
with explicit denominators. Semantic failures are retained and do not stop the
remaining workload. Missing usage, source drift or broken evidence stops dispatch.

New status-answer cases allow extra read-only lookups before a final correct,
observed and consumed answer. Record extra/wrong-target reads and recovery
separately; do not call a recovered task a semantic failure merely because it
cost more. Missing/ambiguous/unsupported cases still require no lookup. The
original five-case oracle keeps its exact lookup-sequence contract.

The four-digit `Q-7318` case deliberately exposes the existing three-digit
candidate parser's omission. `none` can be correct within supplied choices while
the full target is missing. Report candidate coverage, conditional selection and
root recovery separately; do not repair this parser after seeing the result.

The **four-rollout wrong-helper block** uses cases 01/02 and A1/B once each,
separate from natural errors. After a real valid helper call, trusted middleware
delivers the same wrong source-bound intent/target in both arms, with
`primitives=null`. Retain original and injected projections, call usage and
consumption receipts. This tests error propagation/recovery without fabricating
probabilities; it does not estimate either helper's natural error rate.

Report final success, honest incomplete/unsupported outcomes, false completion,
mechanical-verifier false acceptance, extra root calls/lookups, whole-arm elapsed
time, helper latency and per-route observed input/output/cache counters. Actual
charges remain unknown; published Jev input tariff and Astra API-equivalent
estimates are not a combined cash invoice. Partial provider fields stay null.
No small-sample equality, calibration or adoption claim follows automatically.

Timing has two distinct boundaries. `runtime.elapsed_seconds` covers the shared
loop, helper, tools and runtime verification, but not setup, trajectory export
or the independent Harbor verifier. `host_elapsed_seconds` also includes trial
setup, export, verifier and environment/credential cleanup; it excludes the
host collector's subsequent accounting/replay audit and final aggregation.
Neither field measures the complete production-and-audit workflow.

## Verification and outstanding evidence

Local verification on 2026-09-21, before the first live freeze: the five focused
decision/runner/continuation/activity/persistence suites passed **200 tests**;
the six adjacent taxonomy, Codex, auxiliary-usage, Harbor projection and contract
suites passed **284 tests**, with one optional Harbor-SDK test skipped because
the frozen Harbor environment is not installed here. `preflight.sh --fast`
passed its static/generated gates after temporary, checksum-verified actionlint
and ShellCheck were supplied; it did not run full pytest or site gates. Site
build and Markdown export also passed separately. These are offline receipts,
not full-suite, required remote CI, Harbor admission or live acceptance evidence.

- [Decision-tool tests](../../tests/evals/benchmarks/test_decision_handoff.py):
  fixed source, copied spans, route admission, usage retention and sanitized failures.
- [Root continuation tests](../../tests/scripts/test_decision_handoff_runtime.py):
  the real AgenticLoop consumes the decision and lookup results before finalization.
- [Runner tests](../../tests/scripts/test_decision_handoff_pilot.py):
  freeze, accounting and retained attempt/analysis evidence.
- The first direct-account run completed five pairs with retained attempt
  input/output coverage. Its private analysis SHA-256 is
  `b32d40fc7b778e923655b01103091ec898a9ee53845f7dc3c7e5257c12087ef9`;
  its prospective run-spec SHA-256 is
  `1bd9c6be79714d7b5a62fc5a0c7f2a591ee7e0c683405e1cf6aad5c00c79ea40`.
  These identify local receipts, not publicly retrievable evidence or complete
  account billing. Published claims must wait for reviewed artifact release and
  independent readback; do not rerun merely to obtain a publishable success.
- External held-out tasks, another root model and default adoption require
  separate decisions. This experiment does not close unrelated billing audits.

The separately owned KO/EN report has 92 pages; page 32 is a design reference,
not its total length. Report correction and video remain drafts until their
evidence and exact public bytes are reviewed. This pilot does not publish them.

## Sources and limits

Primary API contracts checked 2026-09-21: [TypeSafe API](https://docs.typesafe.ai/api),
[State](https://docs.typesafe.ai/concepts/state) and
[Choice](https://docs.typesafe.ai/primitives/choice).
[Pre-parsed extraction](https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook)
grounds selection of code-found source values; cookbook examples are not GEODE
results. Price references are [TypeSafe models](https://docs.typesafe.ai/models)
and [OpenAI API pricing](https://developers.openai.com/api/docs/pricing#astra).
Text-only input does not establish visual verification; unpublished model
architecture must not be described as encoder-only. Preserve raw evidence
privately until exact-byte publication approval.

## Harbor A/B and replay preparation

Implementation and r5 admission checked 2026-09-21 UTC (2026-09-22 KST).
The original five-pair diagnostic was not a Harbor job. Its
digest-policy trajectories, denominator and private receipts remain unchanged;
the new A0/A1/B profile does not retroactively make them Harbor evidence.

The first Harbor admission on source `14d46ad90b4f0c68c9a3c48228d663471786119d`
stopped during environment construction, before installation or model execution.
The shared public-agent / offline-verifier policy required Docker's dynamic
egress support, which the local VM did not advertise. Input/hash preflight had
not checked the actual environment capability. This is an integration/preflight
defect, not a model failure or a zero task score; the invalid attempt is retained.

Repair admission requires a separate verifier with a static `no-network`
baseline. The narrow [Docker integration](../../evals/platforms/harbor_docker.py)
reuses Harbor's shipped `network_mode: none` Compose overlay for Linux
single-container static isolation; it does not patch Harbor's installed source,
claim dynamic policy support, or change the agent's public-network route.
Custom Compose and changing/allowlisted policies remain outside that static path.
The provider rejects versions other than `harbor==0.22.0` before construction.
The audit extra retains its separately locked Harbor dependency; CI exercises
unsupported-version rejection there and the ten native Docker contracts in an
isolated 0.22 environment. Skipping an unavailable optional SDK in the base job
does not replace that supported-version gate.
Bake the unchanged oracle and its locked dependencies into the verifier image;
transfer only its declared result inputs, never agent credentials or home state.
Before any model call, exercise both actual environment paths, prove verifier
network isolation, execute positive/negative oracle fixtures, and verify teardown
of both exact environment identities. Freeze that evidence with the new run.

Replay admission is separate from task success. Recompute full-private
trajectory integrity and require `replay_complete=true` at the producer and
post-run reader; digest-only scope completeness is insufficient. Preserve
incomplete exports and failure receipts, but stop further experiment dispatch
when full content, native ATIF, derived cast, or their digest joins are missing.
A small new admission must also load the reviewed replay in the supported
player and exercise play/pause/seek before the larger cohort. Original reduced
trajectories are not rewritten; new execution does not recover old history.

Reconcile usage rows by durable source-event identity, not the chronological
or reverse-chronological order returned by different readers. Compare every
field and retain multiplicity so this normalization cannot hide altered or
duplicate attempts. The native `Trial.create` factory selects a concrete trial
class; environment identity observation belongs at actual environment creation,
not an override on a subclass that the factory does not instantiate. Preserve
available call usage even when later cleanup or replay admission fails.

Credential transport must resolve the actual agent UID inside the container,
including when Harbor's task user is unset. Native Compose upload can retain
the host UID; a default root process being able to read that file does not prove
correct ownership. Subscription and TypeSafe installation share the same
owner-only upload path, while the Jev entry-point ownership check stays strict.
Retain the failure stage and `execution_started=false` for pre-call failures;
a missing handoff result must not replace that cause with a collector `KeyError`
or turn an unexecuted arm into a semantic model failure.

### Executed r5 evidence and interruption

Source `6822eac4c2dc15bc428c70706fd00f46843ca5c2` completed three fresh
`corrected-target-ko` admission arms with native reward 1, valid observations,
full canonical/ATIF/cast exports and verified teardown. The private admission
results SHA-256 is
`24e81704af258ca6504d4d4da71ff5f0106cb2f795736325d137cd2e22a7b358`.
All three privacy-reviewed CFR videos passed actual Harbor 0.22 Recording-tab
play/pause/middle/end seek and final-response readability; playback receipt
SHA-256 is `fdbcee762e7f49848b24cc7e95bd5a021a3d09242e7a6bd187f09e50774f2fa0`.
The earlier VFR conversion placed a final frame outside the reported playback
duration. Original ATIF/casts and rejected derivatives were retained; no missing
execution content was invented. Video length is not runtime latency.

The natural phase then attempted ten of 54 cells: nine valid successes followed
by a first-call subscription `RateLimitError`. That failed call retains unknown
usage, not zero; its native reward 0 is not a semantic task-failure score. Export
and cleanup completed, and its short replay correctly contains no generated
assistant answer. The collector's outer `AssertionError` masked the retained
runtime cause. Keep runtime failure, collection failure and replay completeness
separate. The other 44 cells and injection phase were not dispatched.

The operator authorized one new 54-cell cohort plus four separate interventions
on 2026-09-22 KST. Freeze them as a new run; do not replace the failed cell,
pool the old nine successes, or relabel the incomplete r5 primary as measured.
Neither admission nor successful replay grants performance, adoption or
publication authority.

### Completed r6 comparison and interpretation

The fresh run uses source `41e02255311c4ff68302cc67a12b21c98791a690` and the
same preregistered nine-case workload, two repetitions and serial rotated arm
order. Its 54 natural trials and separate four interventions completed without
invalid observations, failed recorded calls or trial retries. All 58 full
canonical/ATIF/cast exports passed admission; the 116 agent/verifier environment
identities were cleaned up. These are private receipts, not an artifact release.

| Natural cohort, 18 trials per arm | A0: root only | A1: Astra helper | B: Jev helper |
|---|---:|---:|---:|
| Task-owned verification | 18/18 | 18/18 | 18/18 |
| Median runtime work, seconds | 6.228 | 14.367 | 8.793 |
| Median host trial, seconds | 53.655 | 63.081 | 58.624 |
| Median helper tool, seconds | N/A | 5.045 | 0.600 |
| Recorded root / helper calls | 26 / 0 | 44 / 18 | 44 / 18 |
| Observed input / output tokens | 51,630 / 1,306 | 105,028 / 2,599 | 108,170 / 2,769 |
| Subscription API-equivalent, USD | 0.468704 | 0.811590 | 0.834274 |
| Jev input-tariff calculation, US cents | N/A | N/A | 0.0499128 |

The frozen primary is `(18 - 18) / 18 = 0`; the two secondary success deltas
are also zero. There are nine independent authored cases, not 54 independent
tasks or a sealed holdout. Equal observed outcomes do not demonstrate population
equivalence. The median paired runtime difference is B-A1 `-5.439` seconds,
but B-A0 `+2.427` seconds. Replacing this xhigh LLM helper was faster; adding
either helper to this root-only workload did not establish a quality benefit.
The xhigh helper is one pinned configuration, not an optimized low-cost frontier.

The table retains all recorded root and helper consumption. B's root cache-read
tokens were 21,504 versus A1's 40,960; Jev cache/reasoning fields are unreported,
not zero. The API-equivalent comparison depends on those observed cache fields
and is not evidence of a causal price effect or actual cash savings. Actual
charges remain null. B's 11,884 Jev input tokens yield USD `0.000499128` at the
pinned tariff; its 1,470 observed output tokens are retained despite free output.
The scope is recorded root/helper attempts, not complete account or runtime
billing coverage.

Both helper arms matched the full intent/target label in 14/18 observations.
The four incomplete projections per arm were followed by correct root actions
and task completion: conditional recovery 4/4, not 4/18. Correct-helper
degradation was 0/14. Candidate coverage was 8/12 required-target observations:
besides the intended four-digit omission in case 07, case 03 exposed a shared
parser defect. Python's Unicode word boundary omitted `E-536이` and `E-536의`,
leaving only `none`; the root still read the original request and looked up
E-536. A concentrated distribution over that sole option is not evidence that
the intended order was identified. The raw `helper_supplied_candidate_answer_correct`
field compares a fixture expectation, not feasibility in the actual supplied
choice set, so its case-03 mismatch must not be reported as a model-only error.

The common parser's Korean-suffix correction was made **after** this frozen
run. Offline regression evidence for that correction does not turn r6 into a
live result for the corrected source. The three-digit contract and case-07
omission remain unchanged; no outcome was replaced or rerun.

The four preselected wrong-advice interventions were all delivered and passed
(A1 2/2, B 2/2), with no wrong-target/extra lookup, false completion or mechanical
false acceptance observed. Original helper outputs remain distinct from the
wrong projections. This demonstrates recovery behavior in these four supplied
states, not a natural error rate, calibrated probability or general robustness.
The root retained the original request; its internal reasoning is not observed.

The task-owned oracle is recomputed in a separate offline verifier environment
using shared oracle code; it is not an independently implemented judge or an
LLM-as-a-Judge. The only tools are interpretation and synthetic read-only lookup.
No mutation tool or ACL is exercised, so this cohort cannot establish permission
enforcement or prevention of real harmful actions. B also exposes native
probability fields while A1 has `primitives=null`: this is a model/interface
bundle comparison, not a model-only substitution at identical output content.

Private result identities:

- Natural results SHA-256: `dc3138bbd0681e21f8507c5c3645e586824c0c50301c5a5b41260a1d89bf0d47`.
- Natural analysis SHA-256: `0263df30dbeb52b27dd87fec74ef17e6bbef956778249c9d7462593c80dfdf4d`.
- Injection results SHA-256: `5e93357d2b3cced9dc47f7d69518a08a37801bf480efc6760f9beaf954af4184`.
- Injection analysis SHA-256: `1016de8fbf916e505a91fa76a542834111be304d99a9b7712702a7028279a215`.

Retain the root-only path for this task. The evidence supports evaluating a
Jev replacement where a decision helper is already necessary; it does not
justify adding a mandatory helper to every request or changing runtime defaults.

| Surface | Current owner and boundary |
|---|---|
| Scoped runtime | [Shared `run_arm`](../../evals/benchmarks/decision_handoff_runtime.py) owns the actual AgenticLoop, lookup, consumption receipt and oracle. The original [pilot CLI](../../scripts/eval/decision_handoff_pilot.py) and new [Harbor handoff adapter](../../evals/platforms/harbor_handoff.py) call it. A0 has one tool; A1/B have two. No fake native runtime object or default-service expansion is used. |
| Source, task and credentials | The handoff adapter inherits [native installation and bounded stop](../../evals/platforms/harbor_runtime.py), pinned to Harbor `0.22.0`. It binds task bytes by SHA, compares the exact instruction, requires fresh GEODE home and rejects prompt templates/extra environment. Subscription auth uses the existing private-file transport; only B receives a private regular TypeSafe key file, removed after reading and during entry-point cleanup. These controls do not by themselves prove egress isolation or safe retained-container custody. |
| Observed calls | The [checker](../../scripts/eval/check_harbor_observations.py) accepts handoff only with both `--handoff-arm` and `--handoff-case-sha256`. It checks `geode-handoff`, `rule_based`, exact tool sets, frozen identities, requested routes and actual `response_model`. Only B's `structured_decision` may use TypeSafe `jev-1.13.0`/payg with observed `effort="none"`; all other calls, including explicit `cognitive_reflection`, require Astra subscription/xhigh. This is an admission constraint, not automatic engine selection. New native `llm_judge` checks pin `--expected-verify-mode llm_judge`; the historical checker default remains `reflexion`. |
| Finalization and replay export | Handoff retains execution results, attempts full/digest canonical exports independently, and writes runtime summary/finalization receipts even when a projection fails. A known incomplete source snapshot marks both trajectories incomplete and blocks ATIF. Healthy exports reuse the native post-run consumer and [existing ATIF/cast projector](../../evals/platforms/harbor.py); a cast is not raw screen/PTY footage or score authority. |

[Adapter regressions](../../tests/evals/platforms/test_harbor_handoff.py) cover
task/profile/secret boundaries and failed export preservation;
[continuation tests](../../tests/scripts/test_decision_handoff_runtime.py) cover
real loop consumption and oracle outcomes; [checker tests](../../tests/scripts/test_check_harbor_observations.py)
cover mixed-route rejection, actual response identity, unknown counters and
unchanged native gates. `handoff_call_coverage_complete` joins each observed
root logical request ID to its durable attempts and each helper tool invocation
ID to its structured-decision attempt. Explicit `reflection_request` receipts
join cognitive-reflection attempts separately and never establish root tool-result
consumption. Missing or unknown purpose fails scoped coverage rather than being
inferred from a tool name. Root retries may share one logical ID;
dropping an entire recorded call pair must still fail this scoped join. This is
closure for the fixed root/helper profile, not general wire-dispatch coverage.
The oracle also counts lookup attempts rejected before tool middleware. A
clarification/unsupported case cannot pass after such an attempt; attempted,
rejected, extra successful and wrong-target reads remain separate burden fields.
The checker still returns `whole_runtime_complete=false`
and CLI exit `2` after healthy exports: its coverage blocker is neither a failed
task nor permission to expand. `--require-uniform-effort` retains its literal
all-calls meaning and is unsuitable for B's intentionally mixed effort values.

Historical inspection, not runner admission: the global uv `geode-agent`
environment contained Harbor `0.17.1` and viewer assets; it cannot replace the
required `0.22.0` runner. Its inspected `cli/view.py` SHA-256 was
`94eaf1e35184d39b4a564b6b508e39ee6e8caf805b471c3f7c9aa79318bbb3f3`;
`viewer/server.py` SHA-256
`227b84f32f84491c810600b61bf390ab0350f9784a6e8fc8014b958f9292a0f0`.
No installed VCS revision was available. The separately inspected upstream viewer
was `0.23.0` at pin [`71c77fdd119df12eb6ab56e5bc0f29bf62fad338`](https://github.com/harbor-framework/harbor/tree/71c77fdd119df12eb6ab56e5bc0f29bf62fad338),
with [official viewer guidance](https://docs.harborframework.com/core-concepts/results/view-job-results).
Keep viewer inspection separate from the frozen runner and recheck the actual
environment before use; those historical source hashes prove neither installation
readiness nor browser playback.

The historical three-arm source's admission gate was **three `corrected-target-ko` arms**, separate
from both the old five pairs and the [new 54 natural + 4 injected rollouts](#three-arm-end-to-end-protocol).
Freeze a clean source bundle and identical image/architecture, initial state,
task checksum, request, oracle, bounds and destinations using Harbor's
[task format](https://docs.harborframework.com/core-concepts/tasks/overview).
Its [task-owned verifier](https://docs.harborframework.com/core-concepts/tasks/verifier)
must check actual answer, consumed result and lookup evidence and write native
reward on pass and fail; a stored `passed` flag is not independent verification.
Confirm native reward, observation/source joins and private full export before
admitting the new cohort. Keep admission and wrong-helper intervention results
out of the natural cohort's denominator. There are no trial/helper retries;
the root's bounded connection/empty-response policy remains as documented above,
not a claim of zero provider retries. This is not Terminal-Bench evidence.

These commands are preparation templates, **not executed trial/viewer commands**;
replace paths with closed, owned, privacy-reviewed artifacts and select the
separately verified Harbor binary before use:

```bash
uv run python -m evals.platforms.harbor /absolute/closed-job --dry-run
uv run python scripts/eval/check_harbor_observations.py --help
harbor view /absolute/reviewed/jobs --jobs --host 127.0.0.1 --port 8088 --no-build
```

The checker needs frozen run-spec/source hashes and trial/task/checksum identities,
plus the explicit handoff arm and frozen task-payload SHA for this profile.
An accepted B observation does not certify semantic success or actual billing.
Keep originals unchanged:
`--dry-run` only checks cast eligibility; never overwrite historical recordings.
Harbor's [Recording tab](https://github.com/harbor-framework/harbor/blob/71c77fdd119df12eb6ab56e5bc0f29bf62fad338/apps/viewer/app/routes/trial.tsx#L2829)
plays `agent/recording.mp4`, not `.cast`; Compare is a result matrix, not synchronized
terminal playback. Use the official [asciinema player](https://docs.asciinema.org/manual/player/quick-start/)
or [agg](https://docs.asciinema.org/manual/agg/usage/) for an admitted cast, with any
derived MP4 only in a reviewed presentation copy. No new playback engine is needed.

Preserve job/trial/arm/attempt IDs, verifier files, source/output hashes and cast
receipt provenance. Label `ATIF-derived replay`, keep separate A/B clocks, and
record cuts, acceleration and synthetic/clamped timestamps; agg's default idle
cap is five seconds. A playable cast proves neither full replay completeness nor
task success. Review exact bytes for private paths, identities, secrets and model
reasoning before display; pattern redaction alone is insufficient. Native verifier
results remain score authority. Replay readiness requires admitted real exports
and a privacy-reviewed viewer play/pause/seek check, followed by capture and
source/output hash verification. The r5 receipt covers its three admission
videos only; implementation and offline fixtures cannot replace new-run checks.

## Film treatment: a decision is not the completed task

Editorial record, 2026-09-21 KST. This section is a **proposed illustration and
capture plan**, not a filmed run or a measured result. Keep this plan with the
experiment rather than creating another score or status ledger. When the film's
existing narrative, storyboard and source map are assembled, link this section
and the admitted run/attempt hashes; do not copy private raw records into them.

The example request is:

> A-104 주문을 취소하지 말고 상태만 확인해. B-209는 예전 주문이야.

The question for the viewer is not whether Jev can print a plausible JSON object.
It is whether source-bound interpretation lets the same root model take the
right next action and complete the original request without a prohibited write.

| Beat / approximate dwell | Claim and dominant visual | Korean narration draft | Evidence needed before replacing the illustration |
|---|---|---|---|
| 1 · 8–10 s | Show the request on the left. Highlight `취소하지 말고`, `상태만`, and the two IDs one at a time. Label `설명용 합성 예시`. | “여기에는 취소라는 단어가 있지만, 사용자가 원하는 행동은 상태 조회입니다. 주문번호도 두 개이므로, 단어를 찾는 것만으로는 다음 행동을 정할 수 없습니다.” | Frozen fixture and its intended result; no invented response or timing |
| 2 · 8–10 s | On the right show two Choice questions: intended action and target ID. Connect code-found source spans to the ID options, including `해당 없음`. | “코드가 원문에서 후보 값을 찾습니다. Jev는 어떤 행동과 어떤 주문을 뜻하는지 각각 판단합니다. 선택한 값은 원문에서 그대로 가져오고, 임의의 주문번호를 생성하지 않습니다.” | Actual question/state contract and validated primitive answers; probabilities only when observed |
| 3 · 8–10 s | Two horizontal rows: baseline above, Jev-assisted below. Both end in the same root model, status tool and verifier. The lower row's additional data arrow is the focus. | “이 결과가 작업의 끝은 아닙니다. 같은 주 실행 모델이 분류 결과와 근거를 읽고 조회 도구를 호출합니다. Jev의 판단이 실행 권한을 새로 만드는 것도 아닙니다.” | Joined root tool call → analysis result → next root call → lookup result, with source and call IDs |
| 4 · actual replay duration | Replace only this beat with reviewed execution footage. Pause on the returned status and deterministic checks: correct target, correct answer, no writes. Keep separate clocks for A/B. | “이제 실제 기록에서 같은 흐름이 이어졌는지 확인합니다. 선택 결과뿐 아니라 올바른 주문을 조회했는지, 금지한 변경은 없었는지까지 검사합니다.” | Pinned revision/run/attempt, actual tool sequence, native finalization and independent scenario oracle |
| 5 · 8–10 s | Show a second request with no usable ID, or a confusing distractor. Leave the outcome blank until measured; show the required hand-back to the root. | “후보가 빠졌거나 뜻이 불명확하면 그 한계도 전달해야 합니다. 높은 확률이 사용자의 의도나 작업 성공을 보증하지는 않습니다.” | An admitted missing-candidate/ambiguity case, including failures; no cherry-picked success montage |

Keep component latency separate from total task latency. The comparison scene
must include root and auxiliary calls, observed input/output/cache coverage,
TypeSafe price estimate, subscription API-equivalent estimate or bounds, and
unknown reported charges. No experimental token/dollar cap is applied, and no
subscription consumption is labelled free. Count final task success with the
frozen oracle, not the number of syntactically valid Choice responses.

Place this example after the Jev/primitives introduction and before the measured
A/B chapter. Introduce `Choice` concretely here; introduce `Noul` or `Score` only
if an actual later question needs them. Do not describe unpublished architecture
as encoder-only. The final adoption/limitations chapter must follow the observed
outcomes, including integration work and errors, rather than a predetermined win.

Production tools and responsibilities: `anything2explainer` owns the evidence-led
scene plan and existing renderer reuse; `typesafe-ai` grounds primitive meaning;
`geode-eval` owns experiment/attempt authority; `fluent-korean` guides narration.
Use the existing screen-recorder and supported Harbor viewer/replay surfaces
only when capture is actually needed and their relevant guides have been read.
No renderer, TTS call, screen recording, upload or publication has occurred for
this scene plan. A local synthetic-loop capture must not be labelled Harbor.

After the references, include a short “Further examples” screen linking to
[function calling](https://docs.typesafe.ai/cookbooks/function_calling),
[source-value selection](https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook),
and [extraction cascades](https://docs.typesafe.ai/cookbooks/sde_cascade).
Label these external design examples, not GEODE benchmark results. Use an official
logo asset only after checking its source and permitted use; do not invent one.
