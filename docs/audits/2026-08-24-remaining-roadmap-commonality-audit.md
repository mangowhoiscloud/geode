# Remaining roadmap commonality and state-ownership audit

Status: **audit complete; RR-009 through RR-012 resolved; R8 work remains roadmap-gated**

Canonical base: `origin/develop@d8004f7f58a3da96609a2bdde29fa1b031fe6696`

Non-roadmap cleanup base:
`origin/develop@5aed7b451d1efe090f63064a15c3fd5e0aacbbe1`

Canonical execution ledger:
[`docs/architecture/extensibility-roadmap.md`](../architecture/extensibility-roadmap.md)

## 1. Purpose and authority

This audit answers four questions before the remaining architecture packages
change code:

1. Which repeated code is one authority accidentally implemented more than
   once?
2. Which repeated code is an intentional compatibility or isolation boundary
   and should not be abstracted?
3. Which concrete stubs or deferred paths still exist?
4. Which finding belongs to R8.2, R8.4, R7.4, or a separate future cleanup?

This file is evidence, not a second status ledger. It does not transition a GAP,
claim implementation work, or override the roadmap. On the audited base the
ledger has 57 GAPs: 48 `DONE`, three `SUPERSEDED`, three `IN_DEVELOP`, one
`IN_PROGRESS`, and two `OPEN`. R8.3 (`REL-004`) is the sole active claim, and no
package is `READY`.

The earliest possible R8.3 closure remains
`2026-09-19T06:53:01.550033Z`. An incompatible public release before then resets
that clock. Consequently this audit may prepare exact evidence and acceptance
checks, but it may not start R8.2 or R8.4 implementation.

## 2. Method

The audit used the checked-out canonical tree, not the dirty primary worktree.
It traced definitions to production readers/writers before classifying a
finding.

Representative checks:

```text
git status --short --branch
git rev-parse HEAD origin/develop
uv run python scripts/slop_audit.py
rg -n 'write_text|open\("a"|append_jsonl|atomic_write' \
  core/paths.py geode_product/self_improving scripts
rg -n 'pass|\.\.\.|TODO|FIXME|NotImplementedError' \
  core geode_product plugins scripts --glob '*.py'
```

An AST pass also compared function bodies and classified empty bodies by their
enclosing `Protocol`, `ABC`, or concrete class. Heuristic output was not treated
as proof: the slop scanner's 169 "dead private" and 84 duplicate-signature
candidates include dynamic registrations and conventional `main()` functions.

## 3. Findings and disposition

| ID | Finding | Evidence | Disposition | Owner / gate |
|---|---|---|---|---|
| RR-001 | No dataset-level ownership manifest exists. | No `dataset_id` or record declares lifecycle, schema/version, root, writer/readers, concurrency, retention/redaction, migration, rollback, and rebuild together. `core.paths` owns paths only. | Add one small, immutable, product-owned declaration. Do not add a registry manager, plugin system, or second persistence layer. | R8.2, after `REL-004` is reconciled and R8.2 is separately readied/claimed. |
| RR-002 | Tracked product state still lives under the kernel package. | `core/self_improving/state/**` is shipped as package data while the implementation lives in `geode_product/self_improving/**`. The artifact checker explicitly rejects product-owned state today. | Move tracked bytes with history/hash parity to the product package, then update packaging and artifact checks. Do not copy and retain two state trees. | R8.2. |
| RR-003 | The documented legacy handoff root is still a live writer root. | `GLOBAL_AUTORESEARCH_HANDOFF_DIR` is described as a migration breadcrumb, but session indexes, auto-trigger state, operator policy overlays, and default run timelines still write/read below it. | Classify every dataset, move live writers to the declared runtime root, and retain the legacy path only as an additive migration/read source where compatibility requires it. | R8.2. |
| RR-004 | The `results.tsv` schema has two authorities. | `ledger.RESULTS_TSV_HEADER` and `build_self_improving_hub.AUTORESEARCH_RESULTS_TSV_HEADER` repeat the same 12 columns; the builder comment still points at the former `train.py` location. | The dataset declaration owns the schema once; writer and builder consume the same projection. | R8.2. |
| RR-005 | Write and concurrency policy is fragmented. | `write_latest_pointer`, baseline/epoch writers, results/session/history appenders, and migration copies use direct `write_text`/`open("a")`; `core.memory.atomic_write` already owns crash-safe replace and process-local JSONL append, while `RunTimeline` already demonstrates cross-process `fcntl` coordination. | Reuse `atomic_write_text/json` for replace-style records. Specify concurrency per dataset; use the existing file-lock pattern for shared cross-process appenders rather than pretending the process-local JSONL lock is sufficient. | R8.2. |
| RR-006 | Epoch archive creation is a real deferred stub. | `_archive/README.md` specifies the immutable layout; `ledger.py` records a TODO and intentionally omits snapshot I/O when a new epoch is assigned. | Implement an explicit post-promote snapshot step. Do not put copy I/O in the promote critical path. Idempotency and prior-epoch content hashes are required. | R8.2. |
| RR-007 | Some readers reconstruct state paths. | `build_literature_listing.py` embeds `core/self_improving/state/mutations.jsonl`; the hub reconstructs selected runtime filenames even though `core.paths` claims one constant per state file. | Derive product readers from the feature-owned dataset declaration. Verification scripts may keep explicit expected artifact paths because they are independent probes, not runtime authorities. | R8.2. |
| RR-008 | The five compatibility facade files repeat a four-launcher shape. | Exact census: package `__init__` plus `campaign`, `prepare`, `train`, and `watch_campaign` launchers. Artifact and installed-wheel checks pin this exact surface. | **Delete, do not abstract.** A shared facade factory would add code immediately before R8.4 removes the surface. Keep all five byte-stable through R8.3/R8.2. | R8.4, after `REL-004` and `STORE-003`. |
| RR-009 | `scripts/slop_audit.py` omits the product package. | `SCAN_ROOTS` includes `core`, `plugins`, removed/absent `autoresearch`, and `scripts`, but not `geode_product`. | Replace the stale root with `geode_product` and pin the root census in the script's own focused test. The tool remains diagnostic, not a promotion oracle. | **Resolved:** exact production-root census is executable-tested. |
| RR-010 | Two web-search tool classes duplicate the same dispatch/error/result body. | `WebSearchTool.aexecute` and `GeneralWebSearchTool.aexecute` differ materially only in tool name/description. Only `general_web_search` is in `definitions.json`; the former remains a `ToolRegistry` compatibility surface. | First decide whether the compatibility name is still public. Prefer deletion/convergence; only if both names must remain, extract one function rather than a base class. | **Resolved:** both public names remain and delegate to one function; behavior tests pin routing and result parity. |
| RR-011 | Crucible repeats canonical JSON hashing and strict scalar validators. | At least seven modules repeat the same sorted compact JSON plus SHA-256 body; `contract.py` already has a canonical JSON helper, while `power.py` and `runtime_budget.py` repeat strict-field/text/number validators. | Reuse one existing Crucible contract helper after caller-specific error semantics are characterized. Do not introduce a generic repository-wide serialization framework. | **Resolved:** generic canonical hashes and exact validator copies share Crucible contract helpers; specialized normalization remains local. |
| RR-012 | The self-improving CLI renders a product-visible placeholder. | `_render_preflight()` prints `harness no-op (PR-OPS-2b wires autoresearch/petri_raw)` while the runner deliberately uses `rerun_enabled=False`. | Replace the stale future-PR wording with the truthful current contract, or remove the line. Do not silently enable paid measurement from an interactive mutation command. | **Resolved:** preflight reports that measurement is skipped for interactive mutation. |

### 3.1 Non-roadmap cleanup evidence

The four findings that did not require an architecture claim are closed on the
cleanup base above:

- `RR-009`: `SCAN_ROOTS` is exactly `core`, `plugins`, `geode_product`, and
  `scripts`; the stale absent root is gone.
- `RR-010`: `web_search` remains the default `ToolRegistry` compatibility name
  and `general_web_search` remains the declared LLM tool. Both call one shared
  adapter dispatch/error/result function; no base class or alias registry was
  introduced.
- `RR-011`: generic compact sorted-JSON SHA-256 identity now has one Crucible
  helper. Exact bounded-text, positive-integer, and runtime forecast validators
  reuse their existing owners. Task-specific normalization, raw-file hashing,
  and caller-specific error wrappers remain intentionally local.
- `RR-012`: interactive mutation still performs no paid measurement, and the
  preflight says so without a future-PR placeholder.

`RR-001` through `RR-008` remain unchanged. They may move only through the R8.3
evidence gate followed by separate R8.2 and R8.4 readiness/claim transactions.

## 4. Dataset ownership matrix for R8.2

The R8.2 manifest must describe logical datasets, not merely filenames. A
dataset may have compatibility paths, but it has one writer contract at a time.

| Dataset | Current root / shape | Current writer(s) | Principal readers | Required R8.2 decision |
|---|---|---|---|---|
| Mutation policies | tracked `core/self_improving/state/policies/*.{json,jsonl}` plus operator overlays under legacy handoff | policy writer, train wrapper writer, few-shot append | product composition, prompt/context contributors, mutator | Move tracked bytes to product state; preserve operator overlays as explicitly local inputs; one schema/version per policy kind. |
| Mutation audit ledger | tracked `mutations.jsonl` | mutator runner, attribution writer, rollback CLI | campaign, gate, MCP/CLI, outer bundle, public builders | One append contract, cross-process policy, retention and redaction declaration. |
| Baseline history | tracked `baseline_archive.jsonl` | ledger promote/backfill path | gate, watcher, hub, epoch logic | Product-owned path and schema; append only after the runtime anchor succeeds. |
| Epoch labels and archive | tracked `baseline_epochs.json` and `_archive/<be-NNN>/` | label writer; archive writer absent | ledger, tests, operators | Atomic label write plus idempotent post-promote snapshot and immutable archive policy. |
| Run results | tracked `results.tsv` and `results.jsonl` | ledger | self-improving hub and operators | One schema authority; define append/concurrency and rebuild relationship between raw JSONL and TSV projection. |
| Seed pools | tracked `seed_pools/cycle-input` and `seed_pools/held-out` | assembly script/operator commit | campaign and audit selection | Remain repo-pinned even under worker override; declare immutable/content-hash identity and rebuild command. |
| Latest baseline | runtime `~/.geode/self-improving/baseline.json`, worker override under `GEODE_STATE_ROOT/autoresearch` | ledger promotion | gate, status/MCP, prompt contributor, hub | Atomic single-writer anchor; additive legacy migration and rollback semantics. |
| Run and campaign logs | runtime `run.log`, `campaign-progress.log`, `campaign/runs/*.json` | train/measure and campaign | watcher, resume, hub/operator | Distinguish replace, append, and resumable checkpoint datasets; declare bounds/retention. |
| Cross-run pointer | runtime `handoff/latest_pointer.json` | seed-generation orchestrator through `core.paths` | train and baseline reader | Move the feature-specific helper out of kernel paths; atomic replace and version validation. |
| Session index | both runtime/legacy handoff `sessions.jsonl` paths are referenced | ledger and mutator runner | generation numbering, history, outer-loop joins | Select one live destination and one append implementation; migration/read fallback must not create dual writers. |
| Auto-trigger state | legacy handoff timestamp, history JSONL, lock | auto-trigger | scheduler, outer bundle, operator status | Move to the declared runtime root additively; keep file locking and bound the history. |
| Run timeline | legacy handoff `<session>/events.jsonl`, isolated worker files, merged campaign file | `RunTimeline`, campaign merge | operator/outer bundle/observability | Preserve the existing `fcntl` sequence/compaction behavior; declare projection/rebuild status and redaction. |
| Seed-generation runs | runtime `seed_generation/<run_id>/**` | seed-generation orchestrator/checkpointer | pointer reader, search, hub | Keep runtime-only; declare retention, checkpoint version, and pointer relationship. |

This matrix is the minimum required starting set. R8.2 must fail if a
production self-improving writer or reader cannot be mapped to exactly one
declared dataset.

## 5. Commonality decisions

### 5.1 Reuse

- Reuse `core.memory.atomic_write.atomic_write_text` and
  `atomic_write_json` for replace-style state.
- Reuse the established sidecar-`fcntl` pattern for datasets shared across
  subprocesses. Do not mistake `append_jsonl`'s `threading.Lock` for a
  cross-process guarantee.
- Reuse one product-owned dataset declaration for paths and schema projections.
  Callers may expose compatibility aliases during migration, but aliases do not
  own values.
- Reuse existing packaging and installed-wheel probes as independent migration
  evidence; update their explicit expected paths when ownership moves.

### 5.2 Keep intentionally local

- The four repeated `_train()` lazy accessors in `measure`, `ledger`, `fitness`,
  and `gate` preserve a mutual-import and monkeypatch seam. A new helper module
  would save little code while making the cycle less obvious. Keep them unless
  the train-module dependency itself is removed.
- GLM PAYG and Coding Plan adapters share wire-shaping code already located in
  `_openai_common` and capability helpers. Their repeated terminal methods keep
  credential/billing sources visibly isolated. Do not add a two-subclass base
  merely to remove those lines.
- `campaign.py`, `train.py`, `cli_commands.py`, `ledger.py`, and `measure.py`
  are large, but size alone is not evidence for a new abstraction. R8.2 should
  extract only dataset ownership/writer concerns required by its exit.

### 5.3 Delete later

- Delete the exact five `core.self_improving` facade files and legacy module/source
  launchers in R8.4 after the publication and state gates. Do not replace them
  with a facade framework.
- Delete stale duplicate path/schema constants only after all readers use the
  manifest and compatibility evidence passes.

## 6. Stub classification

The AST scan found no unexplained concrete empty implementation.

| Candidate | Classification |
|---|---|
| `...`/`pass` bodies in tool, adapter, hook, calendar, notification, secret-store, and Crucible contracts | Intentional `Protocol` or `ABC` surface. Not a stub. |
| `_StreamingWriter.flush(): pass` | Correct file-like no-op: each `write()` is synchronously relayed and there is no local buffer to flush. |
| Five facade modules | Temporary executable compatibility surface pinned by release checks, not a stub. |
| R7.2 six extension fixtures | Implemented black-box scenarios; their small shared bind/policy helpers are sufficient. No generated mega-fixture needed. |
| R7.3 13 performance metrics | Implemented local, network-free ratchet with deliberate small test doubles. Not a synthetic placeholder. |
| Epoch archive auto-snapshot | **Real deferred implementation**, owned by RR-006/R8.2. |
| CLI measurement label | **Resolved:** the interactive preflight truthfully reports that measurement is skipped. |

## 7. Implementation sequence and acceptance

The order is fixed by the roadmap:

1. **R8.3 evidence only** — preserve the five facade files and every current
   state root until the qualifying publication interval completes. Record
   official GitHub/PyPI evidence; do not change runtime code.
2. **R8.2 readiness and claim** — re-audit this document against the then-current
   `origin/develop`; transition/claim only through separate roadmap PRs.
3. **R8.2 implementation** — land the product-owned dataset declaration, move
   tracked state with history/hash parity, converge schema/path/writer authority,
   preserve worker isolation, and perform additive runtime migration with one
   writer. Implement the post-promote epoch snapshot outside the promote
   critical path.
4. **R8.2 verification** — exact writer/reader census, migration/rollback tests,
   concurrent append/atomic replace tests, package/install checks, and hash
   parity for moved tracked bytes. No test deletion, skip, or gate weakening.
5. **R8.4** — run the consumer census and remove only the five facade files and
   legacy launchers. Canonical product code, configuration, and state do not move
   in this transaction.
6. **R7.4** — run the full program audit and release/main closure, including the
   already-implemented R7.2 change-surface and R7.3 performance evidence.

R8.2 is complete only when the manifest is executable evidence rather than a
comment-only inventory: every declared path resolves under default and worker
roots, every writer maps to one dataset, schema projections cannot drift, and a
cutover cannot create two active writers.

## 8. Explicit non-goals

- No new persistence framework, service locator, registry manager, or generic
  migration engine.
- No abstraction of the facade files before deleting them.
- No broad split of large self-improving modules without an R8.2 acceptance
  reason.
- No paid/live audit, model, or provider call as part of this evidence pass.
- No R8.2/R8.4 implementation worktree before the legal readiness and claim
  transactions.
