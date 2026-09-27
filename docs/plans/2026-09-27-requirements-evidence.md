# Requirements, plans, and backend evidence

Date: 2026-09-27. Audit base: `origin/develop@049516995ca472dc529d2f71c934c7c0c59b6a81`.
Scope: contributor conventions and the runtime's heuristic preflight/evidence
boundary. This is a bounded correction, not an extensibility-program claim.

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
planner/executor, judge removal, database migration, release, or live model
benchmark. Historical plans and persisted observations are preserved.

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
7. Merge feature → develop and, after inspecting the accumulated promotion
   diff, develop → main through the repository guard; verify merge parents.
   This does not authorize a package release or service restart.

Deletion is confined to the unsound coverage inference and obsolete template
instructions. It does not remove historical logs, stored v1 preflight payloads,
plans, evaluation attempts, acceptance tests, or another session's workspace.
Current readers treat ledger payloads as observations; the outer EvidenceRow
schema remains v2. New nested preflight payloads use v2 and only the new field.
No legacy writer or compatibility alias is needed for this internal producer.

## Verification and progress

Planned checks: capability/evidence runtime, tool-plan binding, model refresh,
prompt composition and Verify/PostVerify/Stop tests; workflow navigation; Ruff,
mypy, imports, documentation owner map, generated inventory, repository hygiene
and required remote CI. A passing structural/navigation check does not prove
the prose's semantics. The audit above and independent review cover that limit.

Implementation is complete locally. Verification used CPython 3.12.12 and the
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

The full local Python suite and live effectiveness evaluation were not run.
Required PR CI and independent review remain separate admission steps. The
final commit and merge receipts belong to the PR/task result; this document
does not prospectively claim remote success.

Rollback is a reviewed revert of this change; no user data was rewritten. Live
quality/latency/cost improvements remain unmeasured. A future evidence-coverage
feature must first name real producers, artifact validation, turn/trial scope,
failure semantics and a consumer that needs the result; it is not deferred code
to scaffold now.
