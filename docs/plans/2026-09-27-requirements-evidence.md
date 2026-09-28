# Requirements, plans, and backend evidence

Date: 2026-09-27. Audit base: `origin/develop@049516995ca472dc529d2f71c934c7c0c59b6a81`.
Follow-up: 2026-09-28, incorporating `origin/main@04a8f4085` after the Jev rollout.
Scope: contributor conventions, heuristic preflight/evidence, and reproduced
credential/session lifecycle defects. This is a bounded correction, not an
extensibility-program claim.

## Requirement and acceptance

Distinguish intended product behavior, design contracts, execution plans,
acceptance checks, and observed results. Keep documents proportional to the
work. A requirement cannot be rewritten merely to match current code; neither
document presence nor a model's status label establishes completion.

For the backend, a lexical routing guess must not become an acceptance
requirement. Recording a final result must preserve errors and identity without
inventing evidence coverage. Existing Verify/PostVerify/Stop decisions,
approvals, checkpoints, redaction, and actual tool observations remain intact.

Non-goals: a new PRD service, requirements schema, universal evidence validator,
planner/executor, judge removal, database migration, or live model benchmark.
Historical plans and persisted observations are preserved. The September 28
request separately authorizes patch release preparation and stable publication
after the corrected feature is integrated.

## Primary-source research and critical reading

Sources were reopened on 2026-09-27. These are scoped public examples, not an
industry-wide standard or evidence of GEODE performance.

| Primary source | What it establishes | Limit and GEODE decision |
|---|---|---|
| [Cat Wu, Product management on the AI exponential](https://claude.com/blog/product-management-on-the-ai-exponential) | Claude Code's team uses prototypes and evals in product exploration and revisits model-specific scaffolding. The same account includes a plugin specification. | It does not establish that requirements or specs were abolished across Anthropic. Make the plan template optional; do not delete working safeguards by analogy. |
| [OpenAI, Harness engineering](https://openai.com/index/harness-engineering/) | One internal beta project distinguishes product specs, design docs, and execution plans, with lightweight plans for small changes. | It is one team's engineering account, not a universal PRD-first process. Reuse existing GEODE owners instead of duplicating its directory layout. |
| [OpenAI Cookbook, ExecPlans](https://github.com/openai/openai-cookbook/blob/main/articles/codex_exec_plans.md) | A customizable approach to long tasks, with observable outcomes, progress and resumption context; ExecPlan is an arbitrary name. | A document is guidance, not an execution engine, permission grant, or completed test. No new runtime plan architecture follows. |
| [Anthropic, Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | A web-app experiment uses feature requirements, progress records and testing to bridge sessions. | A `passes` field is a report; prompt instructions against changing it are not tamper-proof enforcement. Preserve raw results and their actual checker. |
| [Anthropic, Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps) | Broad removal initially lost performance; the author then removed individual components and examined outcomes, retaining useful planning/evaluation. | This argues against indiscriminate scaffold deletion. Here we remove a disproven coverage inference, not reflection or bounded replanning. No speed or quality gain is claimed. |
| [Anthropic, Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Task, trial, grader, transcript and final environment outcome differ; a booking claim is weaker than the actual database reservation. | A trace event can establish an observation, not the entire product requirement. Preserve separate conformance, usefulness, and comparison-validity judgments. |
| [Anthropic, Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents) | The architecture separates session history, harness execution and sandbox infrastructure. | A conceptual separation is not evidence that GEODE has equivalent isolation, durability, or recovery. Trace each local owner below. |
| [OpenTelemetry trace concepts](https://opentelemetry.io/docs/concepts/signals/traces/#span-status) | A span's status describes the operation it instruments. | Applying this to GEODE: observed row presence is not a task-level verifier. This is our inference, not a claim that GEODE uses OpenTelemetry for this ledger. |
| [Python `os.replace`](https://docs.python.org/3/library/os.html#os.replace), [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html), [SQLite WAL](https://www.sqlite.org/wal.html) | Atomic rename, database commit, synchronization policy and crash recovery have specific boundaries and assumptions. | None promises a transaction across JSONL, SQLite, checkpoints and external tool effects. Document actual scope; do not infer power-loss durability or exactly-once effects from helper names. |

The pasted interview summaries and Google Conductor chronology are not needed
for these decisions and were not independently established here. They are not
used as evidence. No upstream implementation is being adapted or benchmarked;
native-harness parity is therefore outside this change.

## Backend claim audit

The paths below refer to the audited base. Confirmed/rejected refers to the
specific claim, not a maturity score for the whole backend.

| Claim | Producer → record → reader → decision | Finding | Disposition and check |
|---|---|---|---|
| Keyword classification defines required task evidence | `task_preflight.classify_task` → `required_evidence` → `render_preflight_hint` → model system context | **Rejected.** `Update the requirements document` becomes PDF; `Explain the context window` becomes GUI. No requirement authority validates the guess. | Rename to advisory `suggested_evidence`, nested preflight schema v2; test contextual ambiguity without creating requirements. Keep provider/tool availability information. |
| The closing evidence check verifies task coverage | Preflight → `_persist_final_result` → `append_evidence_check` → JSONL `present/missing` lists | **Rejected.** The method compares names, not artifacts or success. The five task-specific names have no ledger writer in `core/`: `source_url`, `local_diff`, `document_ingest`, `screen_observation`, `gui_trajectory`. Tool observations have other owners. | Delete this isolated inference and its alias map/caller. Replace tests that codify it with actual terminal-record checks. Do not synthesize new success rows. |
| Evidence belongs to the checked turn | `EvidenceLedger.append` captures session/turn/call IDs → old check scans `self.rows` | **Rejected for the removed check.** It ignores turn ID and payload validity. An error-bearing `source_url` from turn 1 makes turn 2 report it present. Rows are also not reloaded by `for_session`, so the check is neither a complete session audit nor a turn audit. | Removal eliminates this inference. Regression uses two turns and retains earlier failure without treating it as current success. Actual verification retains its own correlation. |
| A final record means success | `append_final` → termination reason, rounds, tool count, error → diagnostic ledger | **Rejected as success claim; confirmed as observation.** Natural termination or an error can both produce a final row. | Preserve payload and turn identity for success and error cases. Add no pass field. Keep the record even with no preflight. |
| Deleting the coverage check disables completion policy | `Verify` → PostVerify/Stop hooks → policy/evidence references → continuation/escalation/termination | **Rejected.** The removed code runs after the stop decision and catches errors; it never gates completion. `_run_public_finalization_async` and its tests are separate. | Preserve Verify/PostVerify/Stop, run their existing failure/continuation tests. No new acceptance authority. |
| All final artifacts commit atomically | `_persist_final_result` → timeline, evidence JSONL, checkpoint via sequential independent calls | **Rejected.** There is no shared transaction. Evidence write exceptions are diagnostic; later checkpoint work can proceed. | Correct the function's transaction-sounding description and document best-effort observation. No backend transaction redesign is justified by this task. |
| JSONL append and checkpoint rename guarantee power-loss recovery | `append_jsonl` uses an in-process lock and file append; `atomic_write_text` uses file fsync then same-directory replace | **Not established.** JSONL append does not fsync or coordinate multiple processes; rename helper does not sync the parent directory. SQLite guarantees do not transfer to these files. | Clarify the bounded durability claim. Keep helpers unchanged; stronger durability requires an explicit consumer, failure model and crash-injection acceptance. |
| Payload hash makes evidence tamper-proof | `evidence_hash` hashes redacted payload, stored alongside writable JSONL | **Rejected.** There is no signature, external trust anchor, or hash-chain admission here. | Preserve digest/redaction utility; describe it as payload correlation, not authenticity or authorized completion. |
| Session resume undoes external effects | Checkpoint restore → runtime conversation/state; tool effects remain in external targets | **Rejected by existing coding-runtime contract.** Conversation recovery is not rollback or replay deduplication. | Retain current contract. Any exactly-once claim needs operation identity, authoritative readback, crash/retry tests and the target's idempotency contract. |

Backend inspection covers this preflight-to-finalization path and its persistence
helpers. It does not certify all provider backends, database stores, auth flows,
concurrency modes or deployed services. No live external effects were tested.

## Implementation and deletion plan

1. Add the convention at `naming-conventions.md`; route workflow and the
   conventions skill to it. Remove the executable-code-always-wins rule.
2. Replace the plan template's mandatory feature-document and three-source
   gate with problem, preservation, acceptance, evidence and resumption fields.
3. Keep the existing classifier as a fallible routing suggestion. Rename its
   evidence field and mark the prompt boundary advisory. Do not add another
   classifier, store, config switch, or model call.
4. Remove `append_evidence_check`, its aliases, finalization caller, and tests
   that equate row kinds with verified coverage. Keep real evidence writers and
   existing verifier tests; add minimal terminal/turn/failure regressions.
5. Document backend observation/persistence limits in the current authority
   owner, update the code-to-doc map and functional changelog.
6. Run targeted behavior checks, static gates and source/link checks; review
   the fixed diff independently. Required CI must pass on the actual PR head.
7. Incorporate the completed rollout before feature → develop admission; use
   current-head CI and verified merge parents. After feature integration,
   prepare the authorized patch version and promote through develop → main,
   then the stable release workflow. Verify GitHub/PyPI bytes and public
   installation; do not infer publication from a merge.

Deletion is confined to the unsound coverage inference and obsolete template
instructions. It does not remove historical logs, stored v1 preflight payloads,
plans, evaluation attempts, acceptance tests, or another session's workspace.
Current readers treat ledger payloads as observations; the outer EvidenceRow
schema remains v2. New nested preflight payloads use v2 and only the new field.
No legacy writer or compatibility alias is needed for this internal producer.

## Rollout ordering

The hold below was cleared by the user's September 28 instruction. Remote
readback confirmed #3441 merged at `204241543`, the later Jev publication
#3448 in develop at `31c87d552`, and promotion #3449 in main at `04a8f4085`.
This branch merged that main history at `7eddfe786`; the three generated
conflicts were regenerated from their source owners. No experiment pins or
historical run evidence were rewritten. Required feature CI must run again.

### Historical hold recorded September 27

The user clarified during implementation that an active develop-based rollout
takes precedence over this refactor. The refactor remains isolated on
`codex/requirements-evidence-20260927`, originally allocated from fetched
`develop@049516995ca4`; no protected branch has been modified by this task.

- [PR #3442](https://github.com/mangowhoiscloud/geode/pull/3442) was Draft pending
  rollout clearance. Green checks alone do not clear this ordering condition.
- The active `GEODE Jev-Astra 롤아웃` task uses
  [PR #3441](https://github.com/mangowhoiscloud/geode/pull/3441), inspected at
  `7f32ff272d1b07a6404c593e74dad727857e0bd8`. Its description explicitly forbids
  merge while the experimental source is frozen. This refactor does not grant
  permission to merge that PR, change its pins, or rewrite run evidence.
- Once the rollout owner resolves its integration hold, incorporate the admitted
  changes first. If #3441 is deferred/excluded instead, that must be an explicit
  disposition; do not infer it from successful CI or the passage of time.
- Fetch the resulting `develop` and merge it into this existing topic branch.
  Preserve both histories; no rebase, cherry-pick into the experiment, or edits
  to another worktree. Regenerate affected mirrors, inspect the resulting diff,
  run affected regressions and fresh required PR CI, then make #3442 ready.
- Leave the existing [main promotion #3434](https://github.com/mangowhoiscloud/geode/pull/3434)
  to the resolved integration order. At inspection it already represented 45
  merged feature PRs and 401 changed files, beyond this refactor's own scope.

A non-mutating worktree preview (`git merge-tree --write-tree --name-only`,
refactor `691d5686090b` versus #3441 `7f32ff272d1b`) found six shared paths:
`CHANGELOG.md`, `docs/architecture/extensibility-roadmap.md`,
`docs/architecture/official-docs-generation.md`, `site/public/llms-full.txt`,
`site/src/data/geode/architecture-baseline.json`, and
`site/src/data/geode/changelog.ts`. It returned the expected conflict exit 1
for the generated roadmap LOC cells, architecture JSON, and changelog mirror.
No branch or working tree was changed by this preview. Resolve source content
first and use `architecture_baseline.py --update`, site `sync-stats`, build and
`export-md`; do not hand-merge generated metrics. Absence of textual runtime
conflicts is not evidence that the refactor preserves a frozen live experiment.

## September 28 backend authority and lifecycle audit

The supplied L3/L4 scale is an author's assessment, not a published acceptance
standard. We do not certify a maturity level or treat Jev rollout completion as
proof of correctness across all backend paths.

| Feedback claim or boundary | Current evidence and disposition |
|---|---|
| CLI only handles input/display; backend owns all persistence | **Partially met.** IPC admits the active session's typed model candidate and tool projection before adoption. Auth uses one locked read/validate/write/publish transaction helper, but CLI interactive login, daemon commands and OAuth workers remain separate process writers. A transaction helper is not a single backend writer. The terminal handles secret input; shared auth owners validate/persist/activate. This meets responsibility separation without claiming mandatory single-process ownership. |
| `/key` failure leaves the old credential and reports failure | **Reproduced defect, corrected.** The legacy path changed settings and `.env` before auth persistence, swallowed a write error and reported success. Use one `save_api_key` owner for login, key, and onboarding; remove settings/`.env` mirrors. Reject invalid input or conflicting ownership before persistence. The thin client separately requests daemon refresh. Raw-key model tools are removed. |
| New credentials affect the next actual request | **Covered by offline SDK transport tests.** Existing four-provider tests inspect outgoing headers and model-specific account/endpoints after auth reload, including retained adapter objects. Borrowed in-flight clients remain open until their owning event loop drains them; PAYG refresh does not replace the Codex subscription client. This is not a live provider acceptance test or simultaneous multi-process activation guarantee. |
| Resume changes every session-bound evidence writer | **Reproduced defect, corrected.** The reused loop changed session identity but retained the old final/approval ledger. Rebind the existing ledger factory and executor approval sink together, preserving previous files and the disabled-ledger state. Same-session resume retains its owner. |
| Failed completion persistence cannot advance state | **Reproduced defect, corrected.** `_write_status` swallowed the authoritative JSON error, updated the SQLite index and let completion remove the active pointer. Propagate that failure before index/event/pointer changes. SQLite remains a derived projection; these independent stores are not one transaction. |
| StepSnapshot/BoundToolPlan and admission establish current execution policy | **Scoped support.** Existing tests cover model/source/effort/tool projection, per-call approval, rejected admission and resume-before-history ordering. StepSnapshot freezes one request's inputs and references its cancellation event; it is not a durable workspace snapshot. |
| Crash/retry/compaction/worker recovery restores all task effects | **Not supported as a universal claim.** Checkpoints restore conversation and selected guards. Existing effect receipts suppress admitted logical MUTATE/COMMUNICATE/ADMINISTRATIVE duplicates and quarantine uncertain operations; arbitrary EXECUTE/bash effects, filesystem/git drift and process reattachment remain outside that promise. Compaction guards stale history/tool pairs and preserves input on failed artifact writes. A timed-out synchronous legacy thread cannot be forcibly stopped; subprocess and bash teardown have separate owners. |
| A valid judge response or KEEP decision proves quality/promotion | **Rejected.** Preserve the existing verifier, Jev result provenance and promotion gates. Structural checks here do not establish semantic judgment accuracy, sustained improvement, or paired cost/latency/human-intervention gains. No new live comparison was run. |

Deletion covers disproven evidence inference, duplicate key persistence, retired
model credential tools, and a dormant resolver with no production caller. Tests
that exercised only retired APIs/source text leave with those APIs; actual SDK,
routing, safety, checkpoint and failure-behavior coverage remains. Historical
measurements, other worktrees and judges are preserved.

## September 28 auth/login frontier check and cleanup

Reuse the September 24 provider-storage audit, then refresh the relevant primary
sources rather than treating an old pin as a current release. This is static
source/document comparison; no upstream or paid provider runtime was executed.

| Source, revision and observation | GEODE disposition |
|---|---|
| [Codex App Server authentication](https://learn.chatgpt.com/docs/app-server#authentication-endpoints): backend login start/completion, explicit attempt identity and cancellation, and external token ownership are distinct contracts. [Claude Code authentication](https://code.claude.com/docs/en/authentication): terminal/browser setup, credential storage and source precedence are explicit. | Preserve terminal secret entry and backend validation/storage. Model tool arguments are not the credential entry channel. GEODE's synchronous terminal flow serializes native login attempts; it does not claim a full remote attempt/cancel protocol. |
| DeepSeek default `21638c56315ae6a2b552d6091945d3144c9af32e`; latest release observed is prerelease `dsh-v0.1.7-rc.2` (`477b4f420553e8a52c2fbccc464d7561b239c443`), not stable. Relevant credential source is unchanged since the prior pin. [Projection](https://github.com/deepseek-ai/deepseek-harness/blob/21638c56315ae6a2b552d6091945d3144c9af32e/packages/api/settings-controller/src/credentials.ts#L38-L104), [locked reread/commit](https://github.com/deepseek-ai/deepseek-harness/blob/21638c56315ae6a2b552d6091945d3144c9af32e/packages/credentials/credentials-local/src/index.ts#L666-L695), [completion/readback](https://github.com/deepseek-ai/deepseek-harness/blob/21638c56315ae6a2b552d6091945d3144c9af32e/packages/credentials/authorization/src/index.ts#L385-L453). | Reuse nonsecret snapshots and the existing transaction helper. A successful response without the admitted credential's persistence/activation is insufficient. Do not clone its plugin framework or infer that only one daemon may write. |
| Hermes stable `v2026.9.24` (`f97608f178d1ffeca59860195ab7da295f7c8e5f`) and default `bac0c45d8593ed9d53a8e3fcacecdc920b71a2c4` are separate. [Refresh under source-store lock](https://github.com/NousResearch/hermes-agent/blob/bac0c45d8593ed9d53a8e3fcacecdc920b71a2c4/hermes_cli/auth_codex.py#L518-L560) and [read-only inspection](https://github.com/NousResearch/hermes-agent/blob/bac0c45d8593ed9d53a8e3fcacecdc920b71a2c4/hermes_cli/auth_codex.py#L585-L624) persist from the old pin. Newer code also binds pooled credentials to their endpoint and constrains OpenRouter key detection. | Preserve key/provider/endpoint pairing. Reject stale cache publications and owner collisions; reflect external deletion. Inspection does not establish remote authentication. No new credential pool or refresh framework is needed for these fixes. |

Concrete changes and acceptance:

- API-key UI paths use hidden input and a shared backend `save_api_key` function.
  Existing explicit terminal `/key` and `/login set-key <plan> <key>` forms stay
  compatible; `/login set-key <plan>` offers hidden entry. Existing external env
  keys are read, not automatically moved/deleted. Credential registration does
  not silently change a session's billing source.
- Remove `set_api_key`, the obsolete `manage_auth` alias, duplicated OAuth wizard
  choice, unused raw-paste onboarding gate, and model instructions to solicit keys.
  Setup reuses the native login entry instead of a separate Codex-install wizard. `manage_login` executes only
  nonsecret allowlisted actions; direct malformed/secret aliases fail before
  dispatch. Legacy stored histories remain readable.
- Remove `core/llm/credentials.py` and fallback notifications whose sole producer
  had no production caller. Retain explicit request refresh callbacks and retry
  replay guards. Do not describe dormant profile methods as live adaptive health
  tracking; this work adds no speculative scoring subsystem.
- Preserve request-borrowed clients and active session selection. Readiness,
  model selection and status use routing/eligibility rather than a settings-key
  boolean. Offline availability is not provider acceptance or quota evidence.
- Reproduce and fix external file deletion returning a cached token, late stale
  reads overwriting newer cache/profile data, and a force-refresh path bypassed
  by an imported profile. The unused legacy JSON facade and its unsafe automatic
  migration are removed; old files remain untouched and require `/login openai`
  to register a current credential. Native login
  refuses concurrent attempts per store and reports cancellation/failure.

## September 28 errors, observability and IPC boundary audit

The user extended acceptance to error categories, diagnostic quality and
CLI/backend integration. "Frontier level" is not a common certification or a
single disconnect policy. Compare concrete contracts and counterexamples.
This pass observes source/docs, not upstream deployment or benchmark results.

| Primary source and observation | GEODE acceptance or rejected inference |
|---|---|
| Codex inspected main `456212ca2155747d7e9ee752ad3ef010c39be9a5`; observed stable `rust-v0.157.1` and prerelease `rust-v0.159.0-alpha.9` are separate. [Request error codes](https://github.com/openai/codex/blob/456212ca2155747d7e9ee752ad3ef010c39be9a5/codex-rs/app-server/src/error_code.rs#L3-L8) and [App Server turn completion](https://learn.chatgpt.com/docs/app-server) distinguish request rejection from terminal turn results. | Keep wire failure, transport acknowledgement and completed-operation outcome distinct. CLI consumers must preserve backend failure instead of deriving success from response text or the existence of a result object. |
| Codex [connection/request identity and request context](https://github.com/openai/codex/blob/456212ca2155747d7e9ee752ad3ef010c39be9a5/codex-rs/app-server/src/outgoing_message.rs#L56-L104) bind responses to their originating request. | Retain bounded request/session/error identity at the producer and both log formatters. This is not globally exactly-once delivery or automatic OTel propagation. |
| Codex [connection lifecycle test](https://github.com/openai/codex/blob/456212ca2155747d7e9ee752ad3ef010c39be9a5/codex-rs/app-server/tests/suite/v2/connection_handling_websocket.rs#L453-L481) keeps an unloaded-client thread until its idle policy. Hermes inspected main advanced to `801a9022a742562a3c4578c0d8dd12cfd393fc47`; stable remains `v2026.9.24`. Its [disconnect handling](https://github.com/NousResearch/hermes-agent/blob/801a9022a742562a3c4578c0d8dd12cfd393fc47/tui_gateway/session_lifecycle.py#L912-L963) considers remaining attached clients and detached/grace policy. | Reject a universal claim that frontier disconnect always cancels or always detaches. GEODE's connection-owned CLI work must have an explicit tested policy; a cancellation request is not rollback of prior external effects. |
| DeepSeek source remains `21638c56315ae6a2b552d6091945d3144c9af32e`. The [RPC client](https://github.com/deepseek-ai/DeepSeek-Harness/blob/21638c56315ae6a2b552d6091945d3144c9af32e/packages/client/connection/src/client/rpc.ts#L140-L168) checks correlation and structured errors, but the [host's unexpected exception branch](https://github.com/deepseek-ai/DeepSeek-Harness/blob/21638c56315ae6a2b552d6091945d3144c9af32e/packages/client/connection/src/rpc-host.ts#L249-L265) emits plain HTTP 500 text. | Reuse GEODE's existing wire envelope and error owners with bounded safe messages. Do not claim every frontier failure is typed and redacted or copy another plugin/RPC framework. |
| DeepSeek [session telemetry](https://github.com/deepseek-ai/DeepSeek-Harness/blob/21638c56315ae6a2b552d6091945d3144c9af32e/packages/session/session-telemetry/src/index.ts#L26-L39) has no default redaction rules and keeps canonical logs separate from export copies. | A helper's existence does not establish privacy across every sink or reliable delivery. Consolidate GEODE's duplicate scrubber, check message/traceback/wire/display behavior, and preserve the limit for unlabelled opaque secrets. |
| Hermes [error surface](https://github.com/NousResearch/hermes-agent/blob/801a9022a742562a3c4578c0d8dd12cfd393fc47/agent/error_surface.py#L1-L12) is advisory and reuses retry classification; [prompt failure/result handling](https://github.com/NousResearch/hermes-agent/blob/801a9022a742562a3c4578c0d8dd12cfd393fc47/tui_gateway/prompt_turn.py#L899-L926) preserves the original failure before terminal callbacks. | Keep domain-specific error categories with their decision owners. Do not add a global taxonomy without a distinct recovery action, lose the primary failure during cleanup, or infer persisted completion from logging/UI output. |
| [Anthropic API errors](https://platform.claude.com/docs/en/api/errors) distinguish 402 billing failure from 403 permission denial. | Correct permission-to-billing misclassification. Permanent HTTP rejections terminate; 408/409/429 retain their existing bounded recovery policy. Test actual retry and refresh counts, not class-name strings alone. |

Concrete scan boundaries: provider exception → retry decision; tool exception →
structured error; auth transaction → command return; server handler → bounded
wire envelope → legacy/fullscreen CLI rendering; streamed write → drain →
terminal delivery; request cancellation/disconnect → runtime cleanup; and
producer metadata → text/JSON log formatting. Active session state remains with
the backend. Terminal secret input and rendering remain with the CLI. Shared
auth persistence is a process-safe domain owner, not a reason to run interactive
browser login inside the daemon.

### Async-native acceptance

GEODE keeps the existing async-native provider/runtime contract. The inspected
LLM adapters use async SDKs and loop-owned caches; token measurement is a
synchronous Typer diagnostic, terminal OAuth owns its synchronous prompt/poll,
and synchronous tools use the executor boundary. Those are not proof of an
active-loop blocking defect. No whole-repository async-compliance claim or
mechanical conversion of every function is made.

[Codex connection cleanup](https://github.com/openai/codex/blob/456212ca2155747d7e9ee752ad3ef010c39be9a5/codex-rs/app-server/src/connection_cleanup.rs#L8-L39)
retains task ownership through reap/drain/abort.
[DeepSeek request cancellation](https://github.com/deepseek-ai/deepseek-harness/blob/21638c56315ae6a2b552d6091945d3144c9af32e/packages/client/connection/src/client/rpc.ts#L36-L64)
passes an abort signal and checks it after response; its
[transport cancellation](https://github.com/deepseek-ai/deepseek-harness/blob/21638c56315ae6a2b552d6091945d3144c9af32e/packages/sdk/protocol/src/transport.ts#L112-L153)
removes local pending work, not proof of remote rollback.
[Hermes dispatch](https://github.com/NousResearch/hermes-agent/blob/801a9022a742562a3c4578c0d8dd12cfd393fc47/tui_gateway/methods_prompt.py#L694-L701)
retains a thread fallback and distinguishes thread liveness from interrupt.
The shared lesson is ownership and observed termination, not universal async-only code.

The local full-suite warning exposed a real hook ownership defect: an async
callback was invoked in a thread, and timeout could discard its unawaited
coroutine. Invoke async functions/callable instances on the owning loop. Keep
synchronous extensions off-loop with copied request context, observe the retained
executor future, and close late coroutine results after waiter cancellation.
Threads themselves are not forcibly stopped, and their external effects cannot
be rolled back. Timeout diagnostics retain their exception name rather than an
empty message. IPC cancellation and checkpoint-failure handling use the existing
async lifecycle owners; worker cleanup preserves the primary failure, and a
scheduler completion callback follows successful terminal persistence.

## Verification and progress

Planned checks: capability/evidence runtime, tool-plan binding, model refresh,
prompt composition and Verify/PostVerify/Stop tests; workflow navigation; Ruff,
mypy, imports, documentation owner map, generated inventory, repository hygiene
and required remote CI. A passing structural/navigation check does not prove
the prose's semantics. The audit above and independent review cover that limit.

The original September 27 verification used CPython 3.12.12 and the
locked project dependencies in the isolated worktree; no live provider calls.

| Check | Executed result |
|---|---|
| `uv run pytest -q tests/core/agent/test_capability_evidence_runtime.py` | 10 passed; routing ambiguity, actual prompt insertion, preserved historical/error records and finalization output. |
| `uv run pytest -q tests/core/agent/test_verify.py tests/core/agent/test_replan.py tests/core/agent/test_bound_tool_plan_runtime.py tests/core/agent/test_arun_model_drift_sync.py tests/core/agent/test_agent_loop_system_prompt_override.py tests/core/agent/test_prompt_dump.py tests/test_workflow_scaffold.py` | 193 passed; existing completion-policy, plan, refresh, prompt-mode and contributor-workflow contracts. |
| `uv run ruff check core/ evals/ evolve/ tests/ scripts/` and matching `ruff format --check` | Passed; 1,398 files already formatted. |
| `uv run mypy core/ evals/ evolve/ scripts/` | Passed; 650 source files. |
| `uv run lint-imports` | All seven contracts retained. |
| `uv run python scripts/architecture_baseline.py --check` | Initial expected LOC drift after deletion; regenerated with `--update`, then passed. Only generated LOC cells change in the roadmap. |
| `uv run python scripts/check_official_docs.py --check-map` | 29 declared owner paths valid; not a semantic audit. |
| `npm run lint`, `npm run build`, `npm run test:docs`, `npm run export-md` in `site/` | Passed; TypeScript and 243 static routes built; navigation/export contracts passed; 78 Markdown twins regenerated. |
| `uv run python scripts/check_docs_links.py --quiet` | Passed; 819 site link occurrences inspected. |

At that September 27 stage, the full local Python suite and live effectiveness evaluation were not run.
Required PR CI and independent review remain separate admission steps. The
final commit and merge receipts belong to the PR/task result; this document
does not prospectively claim remote success.

September 28 intermediate verification after integrating the rollout (before
the additional auth cleanup below; not evidence for the final auth diff):

- Finalization/approval/plan/tool-policy/model/prompt/workflow/effect-receipt
  regression group: 271 passed, zero failures or skips (JUnit receipt).
- Loop-state, preflight/evidence and daemon model-admission group passed.
- Checkpoint/state-machine/admission group: 75 passed. The four new checkpoint
  persistence-failure cases failed against the previous code and passed after
  the fix. The successful-reopen log was then moved after the write and those
  four cases passed again.
- Independent lifecycle audit: 163 passed across step snapshots, bound tools,
  compaction, worker subprocesses, bash lifecycle and effect-receipt boundaries.
- Auth/login, daemon refresh/status, system-tool and actual SDK transport group:
  97 passed, including primary write failure for each legacy provider form and
  then-current partial mirror failure paths. The later single-store change
  supersedes that behavior and requires fresh checks.
- Site lint, TypeScript/static build (243 routes), navigation/export contracts
  and Markdown twins (78 routes) passed. Owner-map paths (30 surfaces), internal
  links (821 occurrences) and prompt integrity passed.

September 28 final boundary audit (overlapping groups, not additive totals):

- Auth, observability, hook, worker, scheduler, redaction and provider-error
  boundary group: 794 passed, one skipped, zero failures (795 collected).
  A later independent worker cleanup review found an ambient exception being
  mistaken for the worker's primary failure; its explicit ownership fix and
  targeted regression are verified separately below.
- IPC server/transport snapshot: 65 passed; subsequent fullscreen exit and
  approval cleanup snapshot: 43 passed. The earlier 342-case IPC/FSM run
  predates those final corrections and is not a final whole-suite result.
- Logging/public-hook group: 146 passed, including async callable deadlines,
  late synchronous coroutine cleanup and shared secret redaction.
- The earlier full local run collected 14,814 tests: 14,771 passed, 39 skipped
  and four failed. It ran while the later audit was still changing source and
  is not a green final-suite claim. Two stale expectations were corrected
  (retired wizard wording and a removed OAuth path exemption); the auth child
  process timeout passed in the isolated 10-case rerun without weakening its
  test. Generated architecture drift is handled by the final owner command.
- Independent review reproduced and corrected the worker cleanup, terminal
  checkpoint, stream delivery, credential projection and frontend approval
  races. Historical IPC negotiation stays in the legacy fixture; the current
  fixture advertises the implemented cancellation capability.
- Final worker primary-failure ownership check: all nine cases passed,
  including the real worker entry point returning failure when hook cleanup
  fails after an otherwise successful turn. Final protocol/transport fixture
  group: 75 passed; the historical negotiation fixture is unchanged.

The shared contributor entry point and convention skill route future changes
to these owners. The runtime shared agentic suffix carries only the applicable
code-change conduct; project instructions and model text do not replace
executable permission, persistence or transport enforcement.

Final local gates after those corrections:

- Full Ruff check/format and mypy passed (661 typed source files). The original
  fast preflight's import-direction and stale exception-debt failures were
  corrected at the shared routing owner and existing dispatch boundary; all
  seven import contracts and the exception check then passed. No limit or
  ignore was increased. The resulting login/IPC permission group passed 210 cases.
- Prompt integrity and six actual adapter-request modes passed 45 cases;
  contributor-scaffold checks passed 68. The authored prompt remains below its
  existing 12,000-character limit; this proves delivery, not live compliance.
- Final architecture inventory update/check passed. Security, dependencies,
  shell/workflow, roadmap, catalog, bundle, docs canon and prompt gates passed.
- Final site lint, TypeScript/build (243 routes), docs tests and export
  (78 routes) passed. Owner-map validation covered 31 paths and the internal
  link check covered 821 occurrences.
- The first performance check failed during concurrent local builds/checks:
  import 835 ms versus a 400 ms limit and runtime create/shutdown 5,213 ms
  versus 2,500 ms. Its receipt is retained, and the separate diagnostic is
  unscored. After those processes finished, the final three-sample check passed
  every unchanged limit (median import 220 ms, create/shutdown 1,109 ms).
  These machine-local measurements do not establish application speedups.

These results are local, offline behavior/structure evidence. Exact-head
remote CI, reviewed merge receipts and release-channel verification are still
required and are reported with their actual completed runs.

Rollback is a reviewed revert of this change; no user data was rewritten. Live
quality/latency/cost improvements remain unmeasured. A future evidence-coverage
feature must first name real producers, artifact validation, turn/trial scope,
failure semantics and a consumer that needs the result; it is not deferred code
to scaffold now.
