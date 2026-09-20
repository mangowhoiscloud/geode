---
eval_id: typesafe-decision-handoff
eval_family: runtime-decisions
eval_kind: contract
eval_status: draft
eval_authority: diagnostic
eval_summary: Five-task comparison of source-bound Astra and Jev decisions consumed by the same root AgenticLoop.
eval_triggers: [typesafe, jev, decision-handoff, classification, extraction, confidence]
---

# Jev decision handoff pilot

Status: first five-pair diagnostic executed privately on 2026-09-21 KST;
artifact publication, Harbor admission and adoption remain unverified.
This opt-in diagnostic changes an intermediate decision helper, not GEODE's
default provider, semantic preflight, permission policy, or final verifier.
The superseded selector-only draft is not the active experiment.

The question is whether Jev's source-bound interpretation helps the same root
model complete a read-only task with different task outcomes, latency, and
observed consumption. The hypothesis is tested over five synthetic paired tasks,
not inferred from valid JSON, confident answers, or a fast helper call.

## Execution order and resumption

This contract owns the current pilot and its admission gates. The existing film
source map owns scene claims and references; run-spec/attempt/analysis files own
execution evidence. Historical selector plans remain historical: their six cases,
twelve presentations and USD 1 cap are not the active five-pair contract below.
Do not create another status ledger or silently copy those old settings forward.

| Stage | Current disposition | Evidence required to advance |
|---|---|---|
| Common baseline | Included in main `f084075f6ce3f6b8deb1a320e788677fee9a8ae1`; common fix `618e6d77c98625e794a5fa51f7a5e6076d9fd617` is an ancestor | JSON-string tool input, non-finite confidence and verifier schema fixes remain common to both arms. This pilot does not exercise all three features live. |
| Local implementation | Offline checks passed; [PR #3374](https://github.com/mangowhoiscloud/geode/pull/3374) awaits required CI | Independent review; targeted tool, continuation, accounting and runner tests; applicable static/generated gates; clean committed source. No source editing while its run is active. |
| Five-pair diagnostic | Completed on source `58b7c86d650ec592c3bf30046b55d64b6700a3fa`; private run `typesafe-handoff-astra-xhigh-20260920t213023z` | New private prospective run-spec bound to clean source, fixture, routes and oracle; provider-free preflight; all attempts and failed-call consumption retained. |
| Outcome analysis | Existing digest-bound analysis validator passed; no public artifact release or adoption | Join helper decision → consumed tool result → root action → independent oracle. Report valid failures, invalid observations, denominator, latency and accounting coverage separately; do not decide adoption from five cases. |
| External evaluation | Candidates only; separate freeze required | Start with Mind2Web selection and CUAVerifierBench completion decisions. Pin revision/split, selection and exclusion rules, input transformation, independent labels, license/access, sample size and metrics before dispatch. ScreenSpot-Pro tests candidate coverage; OSWorld is later integration, not another name for this pilot. |
| Harbor admission | Four gaps remain in the section below | Scoped two-tool composition, secret transport, mixed-route observation validation and native task/verifier/full export. One paired `corrected-target-ko` trial must prove the path before the five-task extension. |
| Replay and film | Twenty-one-scene local HTML includes the first diagnostic; no Jev trial footage or final film | Privacy-reviewed real export, native viewer play/pause/seek and capture, source/output hashes, separate clocks; small rendered samples before full KO then EN output. Preserve references followed by a short external-use-cases screen. |
| Integration and publication | Not completed for this feature | Head-specific required CI and merge-commit GitFlow; artifact publication/readback, report-owner update and film delivery are separate receipts. No release/tag/PyPI action follows automatically. |

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
A root-only control, shuffled/wrong-advice ablation, Sol block, calibrated
threshold or larger held-out study needs its own prospective contract. Existing
data candidates and previous video sources are retained, not implied to be run.

## One root, two decision helpers

The [decision tool](../../evals/benchmarks/decision_handoff.py) and
[root-loop runner](../../scripts/eval/decision_handoff_pilot.py) use the same
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
no PAYG fallback. Cognitive reflection is disabled equally in both arms for
this diagnostic. The existing finalization and native mechanical verifier run;
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

Harbor preserves the new purpose in its recorded-attempt projection, but its
observation validator still requires the frozen root route for every call.
Adding the purpose does **not** admit mixed Astra/Jev provider runs into Harbor.
A later Harbor experiment needs its own freeze and native task verifier.
See the [usage contract](../architecture/usage-accounting.md).

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
- Harder held-out tasks, another root model, Harbor and default adoption require
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

Checked 2026-09-21; preparation only. The five-task runner above is **not a
Harbor job**. Its digest-policy trajectory is not a full replay export, and no
Harbor A/B trial, viewer session or recording has been produced for this pilot.

| Surface | Verified availability and boundary |
|---|---|
| Measurement runner | [Native GEODE adapter](../../evals/platforms/harbor_runtime.py) requires exactly Harbor `0.22.0`; the worktree environment has no Harbor installation. Do not upgrade the frozen runner to obtain a newer viewer. |
| Installed inspection tool | The existing global uv `geode-agent` environment contains Harbor `0.17.1`, viewer assets and a working `harbor view --help`; its binary is not on the current PATH. It is not an admitted `0.22.0` runner, and browser compatibility remains untested. |
| Current upstream viewer | Source pin [`71c77fdd119df12eb6ab56e5bc0f29bf62fad338`](https://github.com/harbor-framework/harbor/tree/71c77fdd119df12eb6ab56e5bc0f29bf62fad338), package version `0.23.0`, checked against [official viewer documentation](https://docs.harborframework.com/core-concepts/results/view-job-results). Keep an inspection-only environment separate. |
| Existing replay tools | [GEODE's projector](../../evals/platforms/harbor.py) produces ATIF v1.7, an asciicast v2 derivative and a hash-bound `recording.receipt.json`. Three offline projection/recording tests passed; this is not a browser or real-trial test. `ffmpeg`/`ffprobe` are available; `agg` and `asciinema` are not on PATH. |

Installed source identity: Harbor `cli/view.py` SHA-256
`94eaf1e35184d39b4a564b6b508e39ee6e8caf805b471c3f7c9aa79318bbb3f3`;
`viewer/server.py` SHA-256
`227b84f32f84491c810600b61bf390ab0350f9784a6e8fc8014b958f9292a0f0`.
No installed VCS revision was available; these hashes pin the inspected bytes.

The smallest future gate is one paired `corrected-target-ko` Harbor task, then
the frozen five-task workload after admission. Package the unchanged request,
synthetic state and independent checks using Harbor's [task format](https://docs.harborframework.com/core-concepts/tasks/overview)
and [task-owned verifier](https://docs.harborframework.com/core-concepts/tasks/verifier).
Freeze identical image/architecture, reset state, task checksum, root
subscription/xhigh model, prompt, tool schemas, permissions, timeout/round rules
and verifier in both arms; only the decision helper changes. This is a new
diagnostic attempt family, not Terminal-Bench evidence or a repair of old traces.

Four implementation/admission gaps remain. Close them at the existing owners;
these are execution checks, not completed work or another provider/replay framework:

1. **Two-tool composition.** Neither Harbor composition registers this task's
   tools. Reuse `run_arm`, `StatusLookupTool` and `HandoffReceipt` from the
   [pilot runner](../../scripts/eval/decision_handoff_pilot.py) through a narrow
   evaluation owner beside the [decision tool](../../evals/benchmarks/decision_handoff.py).
   Select that profile explicitly in `GeodeRuntimeHarborAgent.run`; do not import
   the CLI runner into `core` or broaden `SharedServices.create_session` merely
   for this task. Preserve the same prompt/schema, exactly two admitted tools,
   empty policy sources, disabled cognitive reflection and `rule_based` verifier.
   Record the actual assembly function in `runtime-contract.json`, not the native
   `build_runtime+build_shared_services` path when it did not run. Extend the
   [continuation tests](../../tests/scripts/test_decision_handoff_runtime.py) and
   [adapter tests](../../tests/evals/benchmarks/test_harbor_runtime.py) to reject
   extra tools/profile drift while preserving the default native shell profile.
2. **Credentials and termination.** The native profile requires `run_bash` and
   rejects nonempty `*_API_KEY` environment values; do not relax those defaults.
   Reuse `GeodeRuntimeHarborAgent.install`'s private-file subscription transport;
   send a separate TypeSafe-only secret to arm B, never a multi-key host `.env`,
   command argument, instruction or receipt. Pass it explicitly to the scoped
   helper; arm A must allocate neither that secret nor its HTTP client. Review
   egress separately from the two-tool restriction. Preserve `_stop_runtime`'s
   bounded drain, SIGTERM handling and finalized receipt through the evaluation
   branch; do not fake runtime/service objects to enter `_finalize_native`.
   Extend the same adapter/continuation suites for credential absence/redaction,
   timeout/cancellation, closed writers and retained failure exports.
3. **Observed-call contract.** In the
   [observation checker](../../scripts/eval/check_harbor_observations.py),
   `_usage_check` currently admits only the root route and `validate_observations`
   requires `reflexion`. Bind expectations to the frozen profile/arm: Astra
   subscription/xhigh for root and helper A; TypeSafe `jev-1.13.0`/payg only for
   arm B's `structured_decision`; `rule_based` for this task. Jev's observed
   `effort=None` means not configured here, not missing root effort. Preserve
   `response_model` from canonical events in `_usage_event_metadata` or verify it
   against the digest-bound source; never substitute the requested model. Extend
   [checker tests](../../tests/scripts/test_check_harbor_observations.py) for wrong
   purpose/route/served-model, missing root effort and unknown counters. Retain
   native-profile rejection tests and the whole-runtime coverage limitation;
   the checker's current exit 2 is not a failed trial or permission to expand.
4. **Independent reward and full export.** Freeze one task bundle containing the
   unchanged `corrected-target-ko` request/state and task-owned verifier; keep
   expected labels out of model input. Reuse `_oracle`'s checks against actual
   answer, tool/result-consumption joins and lookup evidence, not a stored
   `passed` flag. The verifier must write native reward output on pass and fail.
   Export private full and digest trajectories from the same closed canonical
   evidence, then reuse `populate_context_post_run`, the existing ATIF projector
   and `write_harbor_recording` with the actual two-tool definitions. Extend
   task-verifier and adapter/continuation tests for wrong ID, missing consumption,
   same-batch premature lookup, incomplete evidence and failed exports; a playable
   replay never replaces the independent reward.

Keep the existing five-task preflight and its denominator unchanged. After these
offline checks, freeze a new one-pair source/task/profile contract before dispatch;
retain the original five-pair artifacts. Admit further Harbor tasks only after
independently checking that pair's native reward, observation validity and private
full export. Privacy-reviewed viewer playback is a separate replay gate.

These commands are preparation templates, **not executed trial/viewer commands**;
replace paths with closed, owned, privacy-reviewed artifacts and select the
separately verified Harbor binary before use:

```bash
uv run python -m evals.platforms.harbor /absolute/closed-job --dry-run
uv run python scripts/eval/check_harbor_observations.py --help
harbor view /absolute/reviewed/jobs --jobs --host 127.0.0.1 --port 8088 --no-build
```

The checker needs frozen run-spec/source hashes and trial/task/checksum identities;
its current single-route contract cannot certify arm B. Keep originals unchanged:
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
results remain score authority. Readiness still requires an admitted runner,
bounded tool/auth integration, one actual export and a privacy-reviewed viewer
play/pause/seek check; no install, container, model call or capture occurred here.

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
