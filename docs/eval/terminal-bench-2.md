---
eval_id: terminal-bench-2
eval_family: terminal-bench-2
eval_kind: benchmark
eval_status: canonical
eval_authority: suite-profile
eval_summary: GEODE adoption profile for canonical Terminal-Bench 2.1 execution through Harbor, including official-submission and diagnostic comparability boundaries.
eval_triggers:
  - Terminal-Bench 2
  - Terminal-Bench 2.1
  - shell benchmark
  - Harbor
  - container verifier
eval_contracts:
  - docs/eval/schemas/run-spec.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/analysis.schema.json
  - core/observability/schemas/trajectory.schema.json
---

# Terminal-Bench 2.1 — GEODE execution profile

## 2026-09-15 progress and project accounting snapshot

Cutoff: **2026-09-14 15:40 UTC / 2026-09-15 00:40 KST**. The historical
full-suite execution is closed, but its frozen primary remains **not measurable**.
The common-valid secondary result remains GEODE **339/429**, native Codex
**331/429**. The public artifact repository was read back at
[`d277607f3a179f191ad24b1497c0934beb9d2470`](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/d277607f3a179f191ad24b1497c0934beb9d2470/terminal-bench/terminalbench21-sol-max-fullsuite-paired-20260827t190300z).
Later local evidence has not replaced that public snapshot.

The separate G-code candidate passed five fresh official-verifier trials;
its scope and limitations are recorded below. The latest uniform-effort
`modernize-scientific-stack` observation smoke ended at its frozen 600-second
timeout with **selected 0/1**, despite raw post-timeout verifier reward one.
Its 31 retained calls all requested `max`; 30 have usage and one cancelled call
remains null. Observation validation passed, but cache completeness and the
expansion gate did not. This does not close the 281-cell remeasurement plan.

The local **Beyond Pass Rates v38** film is 3,745.121 seconds (62m25s), joining
KO, EN, the preserved historical Replay and five separate G-code follow-up
replays. The retained 00:31 KST YouTube readback confirms private upload and HD
processing, not public publication or completed copyright checks. Local MP4
SHA-256: `3dfb301a8a3ca0705294ebe3459e74e570fa12ea7409d7a9680059f1f408defb`.
Fresh follow-up traces do not fill historical behavior gaps in place.

The [bilingual project accounting section](https://mangowhoiscloud.github.io/geode/docs/benchmarks/terminal-bench/#project-status-accounting)
records **5,111,157,232 input-plus-output tokens** reconstructed from the root
production conversation, 34 linked subagents, historical fullsuite and
preparatory attempts, G-code candidates and two observation smokes plus a canary.
This is project operations, not GEODE-only runtime consumption or video
rendering alone. At least 96.6% of observed input is cached; output is
20,074,458 tokens. Duplicate cumulative snapshots, cache inputs and reasoning
outputs are not added a second time.

The current Standard short-context API-price illustration is **$4,404–$4,436**,
not actual subscription spending or a request-level invoice. Actual pricing
tiers, external tools, AWS, taxes and missing usage are outside that illustration.
Historical/preparatory sources have 940 numeric-usage results among 1,064
result locations, with 124 missing/unreadable; auxiliary and separately forked
work are not exhaustively accounted for. The private-source reconstruction is
not a complete all-project ledger. The detail section keeps method, cutoff,
scope, source hashes and missing-data limits separate from score authority.
No original run spec, raw result, trajectory or selected reward changed.

## Historical Sol paired replay

The frozen `terminalbench21-sol-max-fullsuite-paired-20260827t190300z` run
has a [public paired replay](https://mangowhoiscloud.github.io/geode/benchmarks/terminal-bench/replay/).
The reviewed bytes and receipts are pinned to
[artifact commit 52b7d0e](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/52b7d0eab37ec9122492ec51d77e1502d5b9e085/terminal-bench/terminalbench21-sol-max-fullsuite-paired-20260827t190300z/recording/replay-v19-20260905)
from artifact PR #42. Public HTML SHA-256:
`ef15b986535d6c04b395645afe9bf877c937a53e5fdfc489a0f69ac53d1a05d3`.

All 445 task/repetition pairs are navigable, with GEODE left and Codex right.
Of 890 planned cells, 835 have ATIF-derived tool events, 35 have receipts only,
and 20 were prospectively excluded. The view adds the already-preserved
`supplement-042-native` ATIF for `dna-insert` repetition 2 to the earlier
834-cell cast coverage; it does not alter a source or score. The 16,244
tool-event projections exclude command/output bodies and all model messages.
UTC event timestamps are displayed in KST; the five-events/second cadence is
editorial, not original PTY timing or proof of simultaneous arm execution.

The full-suite primary remains not measurable. Secondary common valid cells
remain GEODE 339/429 and native Codex 331/429. The view distinguishes raw
verifier reward from selected reward, including 18 canonical timeout/refusal
cells with raw verifier one and selected zero. Twenty `bn-fit-modify` and
`tune-mjcf` cells were excluded before model calls because the amd64
oracle/verifier could not complete normally on the arm64 host; six other
native cells remain infrastructure-invalid. None are silently turned into
passes or semantic zeroes.

The official replay now uses a native Next.js App Router page with a React
client player and TypeScript projection types at
`site/src/app/benchmarks/terminal-bench/replay/`. The unchanged v19 metadata
JSON is published separately at
[artifact commit dd547bd](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/dd547bdf892581fabd6cb89a440b0dedb44691c4/terminal-bench/terminalbench21-sol-max-fullsuite-paired-20260827t190300z/recording/replay-data-v19-20260906)
from artifact PR #43. Its SHA-256 is
`fd934ee47e6c26b250378bfcf57ad25146d03579c87f757faf8bc44e7b3eaeed`.
This is the existing public projection, not a new raw store or eval schema.

The client fetches those pinned bytes without credentials, verifies SHA-256,
then renders text through React. A failed download or digest blocks playback.
No external HTML, iframe or artifact script runs. The legacy `replay.html`
link redirects while retaining its pair/language query. The site remains
statically exported to GitHub Pages; no server or new dependency is required.
`site/scripts/verify-terminal-replay.mjs` checks digest rejection, fetch
failure, playback transitions, KST formatting and the compatibility redirect
in every build. Its optional JSON argument audits every consumed field across
all 445 pairs. Original HTML, video and Astra smoke evidence remain unchanged.

## Canonical identity

Terminal-Bench 2.1은 89개 containerized terminal task를 Harbor로 실행하고
task별 verifier로 채점한다. 2.1은 2026-05-06 공개되었고 89개 중 28개
task를 수정했다.

| Field | Canonical value |
|---|---|
| Release | [Terminal-Bench 2.1 announcement](https://www.tbench.ai/news/terminal-bench-2-1) |
| Task repository | [harbor-framework/terminal-bench-2-1](https://github.com/harbor-framework/terminal-bench-2-1) |
| Dataset | [terminal-bench/terminal-bench-2-1@6](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench-2-1/6) |
| Dataset digest | sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a |
| Task count | 89 |
| Harness | [Harbor](https://github.com/laude-institute/harbor) |
| Scoring | task-owned verifier reward; errors remain reward 0 for official submission metrics |
| Environment | fresh task container; task-owned CPU, memory, storage, GPU, build, agent, and verifier limits |

The repository filename remains terminal-bench-2.md for stable internal links;
the canonical suite version is 2.1.

## Official submission contract

The [official submission instructions](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/leaderboard/SUBMIT.md)
and static checker require:

- the exact canonical dataset and per-task digests;
- all 89 tasks with at least five trials each (89 × 5 = 445);
- default timeout multiplier and no agent, verifier, or resource override;
- errored trials retained as reward 0;
- an ATIF trajectory for every rewarded trial;
- maintainer static analysis plus reward-hacking review.

Community submissions are currently closed; only maintainer-run submissions are
accepted. Therefore a local GEODE run cannot claim an official rank merely by
uploading artifacts.

    harbor run -d terminal-bench/terminal-bench-2-1 -a <agent> -m <model> -k 5

Harbor exposes repetitions (-k) and concurrency (-n) but no run seed option
in 0.22.0. Record this as unsupported rather than inventing a seed.

## GEODE adapter

The active custom-agent adapter is
evals.platforms.harbor:GeodeHarborAgent; the compatibility import remains
evals.benchmarks.harbor_geode_agent.

It:

- gives AgenticLoop one terminal_exec tool backed by Harbor's isolated
  environment.exec;
- uses the frozen provider, route, effort, and model while leaving the agent
  timeout at zero so Harbor's canonical task limit remains authoritative;
- leaves task/container/verifier ownership with Harbor;
- exports a digest-oriented geode.trajectory@1 sidecar and an ATIF 1.7
  `trajectory.json` projected from the same canonical session timeline;
- reconstructs `recording.cast` from the finalized ATIF trace and binds it to
  the source with `recording.receipt.json`.

Harbor's job layout permits `agent/recording.cast`, but its contents are owned
by each agent implementation. Terminus-2 performs a raw asciinema capture;
GEODE and the instrumented native Codex adapter instead emit an asciicast v2
reconstruction after ATIF finalization. The reconstruction is replay evidence,
not a raw PTY capture or score authority. It omits provider reasoning, redacts
known secret forms, and remains private until a separate PII/path/publication
review. Observer-side `script -r` files separately record the operator console
and must not be described as Harbor-native trial recordings.

Use `evals.platforms.harbor:RecordedCodexHarborAgent` instead of the built-in
Codex name when future paired runs require the native arm to emit the derived
cast automatically. For subscription authentication, set `CODEX_FORCE_AUTH_JSON=1`
in the Harbor **process environment**, not `agent.env` in its job configuration.
Harbor 0.22.0 treats AUTH-named configuration values as secrets and can replace
every `1` in trial files with `[REDACTED]`, corrupting JSON, rewards and ATIF.
The instrumented adapter rejects this configuration before execution; actual
credential redaction remains enabled. Freeze and verify the process-level route.

Closed historical jobs can be audited and backfilled
without changing result or trajectory files:

    uv run python -m evals.platforms.harbor <job-or-run-root> --dry-run
    uv run python -m evals.platforms.harbor <job-or-run-root>

The adapter declares `SUPPORTS_ATIF=true` only after validating the projection
with Harbor's own ATIF model. Scope-incomplete session history or unmatched
tool events fail closed. GEODE's event contract does not retain exact LLM-call
grouping, so the projection emits one tool call per agent step and leaves
ATIF's `llm_call_count` unknown; this limitation is recorded in every root
trajectory. Official submission authority still requires the canonical full
suite, Hub upload, static analysis, and maintainer reward-hacking review.

## Required execution ladder

### Opt-in full-runtime candidate

`evals.platforms.harbor_runtime:GeodeRuntimeHarborAgent` uses Harbor 0.22.0's
`BaseInstalledAgent` lifecycle and installs a hash-pinned GEODE source bundle
inside each task container. Harbor retains job/trial, isolation, timeout,
verifier and result ownership. Native GEODE factories create the runtime,
tools, internal services and workers; no external scaffold-search loop runs.
This candidate is not interchangeable with the historical one-tool control.

The entry point requires a container-local home, explicit subscription routing,
an absolute required model policy, and no API-key environment variables.
New action, reflection, candidate judge and worker requests inherit the owning
loop's effort; wrap-up no longer forces a lower value. OpenAI reasoning-capable
text/search helpers receive that inherited value on the actual provider request.
Explicit worker overrides still take precedence outside the frozen experiment.
Uniform-effort studies must verify every retained call, not infer uniformity
from `[agentic].effort` or from ATIF tool steps. This changes the treatment;
historical auxiliary defaults remain unchanged in the old evidence.
The fresh task-container profile permits dangerous tools so the native shell
is available; this does not change host policy or bypass worker-role toolkits.
The adapter's `verify_mode` option defaults to `rule_based`; freeze `llm_judge`
explicitly when evaluating LLM-assisted repair. Legacy `reflexion` settings
resolve to that shared path; historical run contracts keep their original bytes.
For new native observation checks, pass `--expected-verify-mode llm_judge`;
the checker's historical default remains `reflexion`. Mode, judge model and shell
admission are checked before inference. GEODE verification supplies runtime
feedback, not the Harbor task verifier's score authority.
Native state is preserved under the trial's `agent/geode-home/`; credentials
are transferred outside the collected logs. These are private sources until
separate secret, PII and local-path scans authorize a public derivative.
Missing cache observations stay null, and AgenticLoop usage subtotals do not
populate Harbor whole-runtime totals while auxiliary calls remain unobserved.

Native bootstrap first writes `runtime-finalized.json` with
`exports_complete=false`. Child shutdown, session closure, source reads and
the two canonical trajectory exports are finalized independently; a cleanup
failure does not discard available evidence or replace the original execution
error. Bounded stage/error-class receipts accompany partial exports. Only
successful required exports from a complete source snapshot may set the flag
true. Python cleanup cannot guarantee recovery after SIGKILL, OOM or host loss;
a false or missing finalization receipt is not evidence of no execution.

Fresh reexecution can add behavior and cache observations to Replay, but it
cannot fill historical unknowns in place. Freeze a new candidate and attempt
lineage, preserve the task/model/resource contract, and identify the updated
runtime as a treatment change. Keep original reward and historical absence
alongside the separately labeled supplementary trace. Excluded tasks remain
excluded unless a new study supplies a compatible environment prospectively.

Use Harbor's `--install-only` for the no-model installation gate. Every live
study needs the existing run-spec/attempt contracts and its frozen admission
rules. The ladder below describes paired comparisons and their publication;
a candidate-only development gate can instead preregister one runtime, its
no-model preflights and a private evidence destination. It does not acquire
paired-comparison or public-release authority by passing that gate.

1. Pin Harbor version, dataset version/digest, task manifest, GEODE revision,
   model route, reasoning effort, timeout, concurrency, repetitions, and
   exclusion rule in a validated prospective run spec.
2. Fail closed on Docker, task architecture, subscription auth, adapter import,
   and canonical verifier availability.
3. Run a no-model oracle smoke.
4. For a paired comparison, run one paid GEODE/native smoke without changing
   the frozen task.
5. Expand a paired comparison only after both arms are infrastructure-valid.
6. Preserve semantic failures as valid reward 0; retry only recorded
   infrastructure-invalid attempts under the preregistered retry rule.
7. Validate run spec, attempt lineage, native result, trajectory, verifier and
   outcome receipts, analysis and source hashes. Before public publication,
   also validate the publication manifest and privacy scans; verify remote
   read-back after uploading the admitted bytes.

## Error-driven candidate ratchet

An engineering candidate advances only after the previous acceptance checks
and the regression for the observed failure pass on the exact new source.
This is not best-of-N selection over benchmark rewards.

| Observation | Next action | Evidence and authority |
|---|---|---|
| Required test, instrumentation or export fails | Pause new paid cells; diagnose and repair the smallest responsible surface | Preserve the failed log, attempt and partial exports; add the reproducer to the required checks |
| CI is absent, pending, failed or belongs to an older head | Keep the candidate unmerged and unadmitted | Bind passing checks to current source, base and source bundle; do not replace the failed receipt |
| All required engineering checks pass | Admit only the declared next preflight stage | This does not authorize paid calls, publication or score promotion |
| Frozen install, oracle, auth, resource and paid-smoke gates pass | Permit the next preregistered cell | Exact model route, effort, task limits, source/spec hashes and observability scope remain fixed |
| Official verifier reports a valid zero, including a canonical timeout | Close the cell with reward zero | Never rerun it to manufacture a pass |
| Infrastructure or evidence collection invalidates a trial | Stop expansion; retain the invalid lineage | Replacement needs a prospective rule and remaining cap; the observability-remeasurement draft grants zero replacements |

Each fix creates a new candidate revision and source bundle. A change after a
study freeze starts a separate run or prospectively declared phase; do not pool
its attempts into the earlier fixed-runtime cohort. Record failure class,
changed surface, expected effect, parent identity and digest references through
the existing run-spec, attempt and analysis contracts. The analysis identifies
the last accepted candidate and the failed checks; it does not rewrite raw
trajectory or reward evidence. Preserve null cache counters as unknown, even
when an otherwise valid task passed.

The current remeasurement draft targets 281 previously selected GEODE cells
with incomplete cache or Replay observations. Its gate evaluates observation
coverage, not higher task reward: one fresh attempt per cell, concurrency one,
zero Harbor retries and zero automatic infrastructure replacements. Historical
Codex data is a reference, not a fresh paired control. A corrected runtime and
new prompt hashes are treatment changes even when task/model/resource limits
match. Missing auxiliary-call accounting remains an explicit coverage limit,
not a whole-runtime cache-performance claim.

### Observation admission for the fresh missing-data study

The admission unit is one new attempt with an immutable source/spec identity,
not a historical cell repaired in place. A green unit test means the tested
code path is protected; only a fresh native trial and validated exports count
as newly collected data. No current video or historical ledger is silently
reclassified by a runtime patch.

Before any model call, the frozen run spec must identify root action,
turn-final verifier, cognitive reflection, candidate selection, learning/text
completion, hosted search and worker paths. For each path, bind the active or
conditional configuration, actual model/source/effort policy, observation
owner and regression evidence. A conditional path is not disabled merely to
make accounting look complete; a path not exercised in smoke remains untested
live. An uninstrumented enabled path blocks a whole-runtime study.

| Boundary | Required check before expansion | Missing or failed evidence |
| --- | --- | --- |
| Frozen experiment → trial | Source bundle, task digest, image/platform, Harbor version, route, resource/time limits, reset and attempt cap match the prospective spec | Pause; do not silently change the environment or reuse the previous source bundle |
| Adapter dispatch → durable usage | Identified starts/ends, observed counter presence, retained failed/cancelled attempts, no known sink/mapping failure, bounded purpose/source/requested effort | Pause; null is not zero and surviving pairs do not prove omitted producers |
| Native finalization → source snapshot | Successful shutdown/read/export stages; known child handles and structured parent subagent events reconciled with canonical session inventory; integrity recomputed | Preserve partial outputs; missing child rows or a false/missing receipt never establish no execution |
| Canonical trajectory → host Replay | Matching session/call identity, validated ATIF, paired tool actions/results, cast bytes and source/output receipt hashes | A true `runtime-finalized.json` alone cannot pass: host ATIF/cast generation happens later |
| Private source → public derivative | Exact-byte privacy review, declared redactions/omissions and source-bound content/count reconciliation | Withhold publication; never fill omitted action text or provider reasoning with invented content |

For cache-read comparison on this OpenAI route, require reported input,
output and cached-input fields on every admitted completed call. An explicit
zero passes the presence check. A provider-unreported field and a dropped
export field are different diagnoses, but either prevents a complete cache
claim. Unsupported cache-write detail may remain null; it is not invented as
zero or required as evidence of a cache hit. An interrupted stream without
final usage remains unknown even when its cancellation receipt is complete.

Report separate coverage denominators, not a single "recovery percentage":

| Question | Historical baseline | Fresh evidence denominator |
| --- | --- | --- |
| Does the missing Replay have new behavior evidence? | 34/435 selected GEODE cells: 28 empty agent directories and six zero-action ATIF records | Newly validated traces / 34 targeted cells; text-only/no-action attempts remain explicitly no-action |
| Are formerly partial cache observations now complete? | 247/401 usage-bearing cells; 648/4,709 retained usage events lack cache detail | Fully observed new attempts / 247 targets, plus reported/total completed calls within each attempt |
| What fraction of selected historical cells is targeted? | Disjoint union 281/435 across 83 tasks; ten excluded GEODE cells remain excluded | Executed, validated, unresolved and not-yet-run counts / the frozen 281 targets |
| Is the entire runtime observed? | Historical and current scoped exports do not establish it | Declared active/conditional producer coverage and source/export reconciliation, not just cache-bearing calls |

The 154 historically complete-cache cells are not extra recovered cells; the
435/435 available phase timestamp records are not a new runtime improvement.
Keep old scores and the six unresolved native invalid cells separate from
these accounting denominators. A valid verifier zero or canonical timeout
retains its score even if collection pauses the *next* attempt. Observation
failure is not permission to retry a semantic zero or discard its lineage.

Resume only after diagnosing the failed boundary, retaining its reproducer,
passing previous plus new checks on the new source, and freezing a successor
run or declared phase. Gate receipts are evidence, not independent authority
to launch, merge, publish or exceed the one-attempt/zero-replacement cap.

The read-only [`check_harbor_observations.py`](../../scripts/eval/check_harbor_observations.py)
checks a closed fresh trial against its canonical run-spec SHA, source bundle
SHA, task checksum and trial identity. It validates native result and ATIF
models, regenerates the cast from the retained trajectory, checks the receipt
hashes, and reconciles the existing usage projections. Invoke it with
`trial_dir`, `--run-spec`, `--run-spec-sha256`, `--source-sha256`,
`--trial-name`, `--task-name`, and `--task-checksum`, all taken from the frozen
plan rather than inferred from a successful result. Optional `--source-db`
opens the preserved trial-local database immutable/read-only (no migration or
checkpoint). It verifies each retained hook payload hash, reconciles all
retained call starts/ends and counters, and compares every canonical event's
identity, order, timestamp, payload and source hash through the existing exporter.
Consistently dropping a tool call/result pair from all exports therefore fails.
It rejects a nonempty WAL rather than silently reading a stale
database. Preserve and recover such a WAL separately before claiming a closed
snapshot. No second raw store is created.

For a new native-profile study, freeze collection admission separately from
provider-internal or invoice completeness: require the reviewed producer
inventory and regression evidence above, successful owner shutdown, and this
exact source/export reconciliation. Do not use the checker's unconditional
`whole_runtime_complete=false` as evidence of a newly discovered missing
producer, or change a historical run's admission rule after execution. The
checker alone grants no admission; completed-call cache coverage and every
unreported cancellation counter remain separately reported.

For a prospectively frozen uniform-effort study, add `--require-uniform-effort`.
The checker rejects missing request metadata or any root/auxiliary effort that
differs from the spec's `reproduction.model.reasoning`. Its
`accounting.uniform_requested_effort` field describes retained calls only;
wire-level regression tests and the producer inventory are still required.
Neither that check nor a provider accepting `max` measures its internal compute.

`observation_valid` and `cache_complete` answer different questions. Missing
required evidence fails validation; intact exports with absent provider cache
fields remain incomplete for cache comparison. Neither grants full-runtime
expansion. Resource allocation, timeout/retry policy, auth and container/oracle
preflight remain separate admission requirements. Export agreement also cannot
prove that a producer lost neither side of an entire call pair.

Freeze this finite native producer inventory with the candidate's existing
evidence references; for each row, distinguish enabled/conditional, covered by
a deterministic failure test, and actually exercised by the live smoke.
Zero observed calls do not establish that a conditional path was tested.

| Producer in this native profile | Observation owner | Activation |
|---|---|---|
| Root/worker action and turn-final verifier | `_provider_call` shared terminal | Action or verification request; count once |
| Root/worker cognitive reflection | Middleware terminal | Reflection policy |
| Parent candidate selection | Middleware terminal | Multiple successful delegated candidates |
| Root/worker hosted search | Capability dispatch with the tool's event bus | Model-selected search |
| Root learning extraction | Capability dispatch with root event bus | Full turn-completed hook |
| Root/worker context-exhausted text | Capability dispatch with loop event bus | Context-limit termination |
| Root/worker compaction and model-switch summary | Capability dispatch with owning loop event bus | Context/model-switch policy |
| Root dreaming | Runtime-owned background service and capability dispatch | Full turn-completed hook; absent from minimal worker hooks |

New text-helper observations distinguish `learning_extraction`,
`context_compaction` (including model-switch summary), `context_exhaustion`
and `memory_dreaming` in the existing purpose field. Older `text_completion`
rows remain unattributed; do not infer their producer from timing. Deterministic
wiring tests do not establish live exercise. The optional database check closes
the retained-source-to-export join, not the claim that every physical provider
dispatch was recorded. A failed sink close also degrades final observation
health, even if every surviving call pair matches.

The run-local ratchet may admit only the *next declared collection cell* after
this code-bound inventory, current preflight, writer shutdown and intact
input/output/cache-read observations pass together. This bounded collection
decision is not whole-runtime billing assurance: `whole_runtime_complete`
remains false, and the standalone export checker never grants execution.
The agent deadline applies to already-admitted background work as well; final
cleanup grace cannot purchase extra model execution. Freeze the lifecycle
policy on the new revision rather than silently changing an old run.

### Why remeasure these missing observations

The immediate target is diagnosable execution, not a higher historical score:
34 selected cells lack useful behavior/Replay and 247 have partial cache data.
Repair the responsible runtime boundary, then bind one fresh attempt's request
metadata, result, verifier and trace to its revision. Preserve the old absence.
Only validated new evidence moves on to the artifact repository, Replay and film.

The user's [Atria AI video](https://www.youtube.com/watch?v=5c5ojBJUznU) is linked
from Hyundai's [official Data Flywheel account](https://www.hyundai.news/eu/articles/press-releases/ai-powered-data-flywheel.html).
That account describes hard-example selection, event evidence collection,
common data structures and revalidation of existing performance. The Special
Event Recorder captures significant events; further AI-driven collection enhancements are
described as exploratory. The video's spoken words and timestamps were not
recovered, so the written source is the evidence for these points.

Our application is narrower: select a failed or unobservable attempt, retain
its evidence, fix one cause and remeasure under a new frozen revision. A passing
diagnostic is not a held-out improvement estimate; regression checks and a fresh
paired control answer different questions. GEODE harness repair is not Atria
model retraining, and a new trace is not a reconstruction of missing history.

## 2026-09-13 full-runtime G-code development gate

The separate `terminalbench21-sol-max-reflexion-ratchet-r3-20260913` run
completed five fresh `gcode-to-text` trials: **5/5 official verifier passes,
zero invalid attempts**. It measured source
`815f75950af580b42cbd52dcc78b0b3ea0017a8f` with OpenAI subscription
`gpt-5.6-sol`, actor effort `max`, Harbor 0.22.0, `verify_mode=reflexion`,
a 900-second agent limit, concurrency 1 and zero automatic retries. The task
image and external scorer were unchanged; earlier candidates were not pooled.

The [development record](../plans/2026-09-13-reflexion-gcode-ratchet.md)
preserves candidate failures, source/spec hashes, admission checks and the
intermediate candidate's unresolved SHM custody incident. The final run's
existing canonical bundle passed validation. Its private raw evidence remains
local; a public artifact package or updated film is not implied by this report.

All five internal judges accepted candidate attempt 0; no repair occurred.
The 87 recorded AgenticLoop calls have no missing input/output/cached-input
fields, but this remains scoped accounting, not whole-runtime cost or billing.
This task was used for candidate selection. There is no fresh baseline/native
Codex comparator, held-out claim, measured repair effect or change to the
historical full-suite primary's not-measurable status.

## Comparability grades

| Comparison | Grade | Required wording |
|---|---|---|
| Same frozen local tasks, dataset digest, verifier, model, route, effort, timeout, and concurrency; harness differs | direct paired-runtime diagnostic | Report exact numerator/denominator and harness-internal differences |
| Different task subset, repetition count, machine architecture, CLI version, or execution date | directional only | Never present as one rank table |
| Local subset versus official 89-task k>=5 maintainer-reviewed leaderboard | not comparable | No official rank or suite accuracy claim |

Official leaderboard values are reference context only. They do not replace a
same-protocol comparator and must remain separate from local paired results.

## 2026-09-05 GPT-6 Astra subscription E2E smoke

The current account completed one preregistered
`openssl-selfsigned-cert` trial through GEODE 1.0.27, Harbor 0.22.0,
`gpt-6-astra`, reasoning `high`, and the OpenAI subscription route. The
canonical result was **1/1 reward**, all **6/6 verifier checks** passed, and
there was no retry or fallback.

The [run record](2026-09-05-terminalbench-astra-openssl-smoke.md) binds the
frozen contract, attempt lineage, publication manifest, and limitation set.
The [append-only artifact bundle](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/a32abcbf78ab6100ea1e85540a2ace9436dc6f76/terminalbench/results-smoke/terminalbench21-astra-high-openssl-smoke-20260904t202725z)
was read back byte-for-byte from its merge commit.

This result establishes account-scoped route and task execution for one
scenario only. It has no suite, rank, paired-comparison, promotion, or general
account-availability authority.

## 2026-08-26 diagnostic

The first current-contract Sol/max paired run is recorded in
[2026-08-26-terminalbench-2-1-sol-max-paired.md](2026-08-26-terminalbench-2-1-sol-max-paired.md).
GEODE and native Codex each passed 3/3 on the frozen diagnostic subset; the
result has paired-runtime diagnostic authority only.
