---
status: active
authority: architecture-extensibility-execution-sot
baseline_commit: 34257503767e24f0531f6b2c2df7e53288eabd22
baseline_branch: origin/develop
last_audited: 2026-07-17
owners: GEODE maintainers
---

# GEODE Architecture and Extensibility Completion Roadmap

> [!IMPORTANT]
> This file is the single execution source of truth (SOT) for the architecture
> and extensibility improvement program. Detailed architecture documents and
> older plans remain useful as design evidence, but they do not own program
> status, ordering, or completion claims.

## 0. How to use this SOT

This roadmap is an execution ledger, not a proposal archive. Every
architecture or extensibility PR must reference at least one stable GAP ID from
the master ledger. Status changes follow the post-merge protocol in §0.3; an
implementation PR must not predict its own merge by setting `IN_DEVELOP` or
`DONE`.

### 0.1 Authority boundary

| Question | Authority |
|---|---|
| What does the current product do? | Current code, tests, and generated runtime schemas |
| What must a specific subsystem preserve? | The subsystem architecture document linked from this roadmap |
| What is the target architecture and merge order? | This roadmap |
| What is the current status of this program? | The master GAP ledger in this roadmap |
| Why was an older design considered? | The historical plan or research document |
| What public release metadata is generated today? | `site/src/data/geode/sot.ts` owns only package version and sync date |
| What owns architecture inventory? | `site/src/data/geode/architecture-baseline.json`, generated with `scripts/architecture_baseline.py`; §2.1 and `AGENTS.md` consume the same snapshot |

When current code and prose disagree, code plus executable tests win for the
current-state audit. When an older plan and this roadmap disagree about future
work, this roadmap wins. A conflict with an external provider contract must be
resolved against current primary documentation or source before code changes.

### 0.2 GAP and status vocabulary

The audit class describes the code shape; the status describes delivery.

| Audit class | Meaning |
|---|---|
| `EXISTS` | The required contract exists and has executable evidence |
| `PARTIAL` | A useful seam exists, but one or more consumers bypass it |
| `ABSENT` | No usable contract or gate exists |
| `MISFIT` | An abstraction exists under a misleading boundary or owns the wrong responsibility |

| Status | Meaning |
|---|---|
| `OPEN` | Audited gap; no approved implementation branch is active |
| `READY` | Dependencies are satisfied and measurable exit criteria have been defined and re-audited; safe to claim |
| `IN_PROGRESS` | Canonical `develop` contains an exclusive active claim naming the owner and implementation branch |
| `IN_DEVELOP` | Merged to `develop`, but not yet released from `main` |
| `BLOCKED` | A named external decision or dependency prevents progress |
| `DONE` | Present on `main` with closure evidence and all required gates |
| `REJECTED` | Evidence showed that closing the gap would make the system worse; rationale recorded |
| `SUPERSEDED` | Replaced by another GAP ID with an explicit lineage link |

Delivery transitions into `READY`, `IN_PROGRESS`, `IN_DEVELOP`, and `DONE`,
plus transitions into or out of `BLOCKED`, are closure-package atomic: every
GAP selected by that package moves together. Decision states
(`REJECTED`/`SUPERSEDED`) follow §0.3 and §10.3, including dependent-edge
reconciliation, before the remaining package can be regrouped under new GAP
IDs.

`DONE` is invalid unless the closure evidence records:

1. PR and merge commit on `develop`;
2. commit or release containing the change on `main`;
3. exact verification commands and results;
4. migration, compatibility, and rollback evidence where state or protocol
   changed;
5. synchronized internal and public documentation;
6. no unresolved acceptance item for the GAP.

### 0.3 Update protocol

Repository tracking documents are normally maintained from `main`. The user
directive that established this completion program explicitly authorizes
feature/develop updates to **this file only** through the roadmap-only
readiness, claim, GAP-registration, reconciliation, and full-ledger audit PRs
defined below. It does not authorize feature/develop edits to
`docs/progress.md` or any other tracking document.

All roadmap-only PRs targeting `develop` are serialized ledger transactions.
Each starts from the fetched `origin/develop` tip and must be updated to the
current tip if another ledger PR merges first; its invariant audit and
independent review are then rerun. Branch protection must require the branch to
be current, or maintainers must merge these PRs one at a time and verify the
exact base SHA immediately before merge. A stale registration, duplicate GAP or
package ID, or conflicting transition is never resolved by last-writer-wins.

Until R0.2 lands the executable validator, every roadmap-only PR body records a
manual invariant table covering unique IDs, exactly-one package selection,
dependency existence/acyclicity, package-atomic status, active-claim parity, and
legal transitions. After R0.2 merges, every ledger PR must pass against its
actual target:

```bash
uv run python scripts/check_architecture_roadmap.py \
  --check \
  --base-ref <target-base> \
  --target-branch <develop-or-main> \
  --event-mode pull_request
```

Use `origin/develop` for develop-targeted ledger work and `origin/main` for the
tracking-only main closure. A same-repository `develop` → `main` promotion
additionally passes `--trusted-develop-ref origin/develop` and must carry that
complete canonical roadmap exactly. This exact promotion is the only mode
allowed to bootstrap a target ref that predates the roadmap. A main-targeted
feature or fork PR cannot use bootstrap trust and can only append
`IN_DEVELOP` → `DONE` closure transactions after promotion.
For the post-merge `push` check, CI uses the immutable
`github.event.before` commit as `--base-ref` with `--event-mode push`; using
the already-updated `origin/main` or `origin/develop` would compare the new
ledger to itself and is forbidden. A zero `before` SHA fails closed.

Before implementation:

1. In a roadmap-only reconciliation PR from current `develop`, atomically move
   every `OPEN` row in one declared work package to `READY` only when every
   dependency outside that package is `DONE` or `IN_DEVELOP` and the whole
   package's acceptance criteria are present, measurable, and re-audited
   against current `develop`. The exit criteria do not need to be satisfied
   yet. Never create a partially `READY` package.
2. Select the earliest `READY` work package and open a roadmap-only **claim
   PR** from current `develop`. It atomically moves every row in that package
   to `IN_PROGRESS` and adds one active-claim row in §0.4 naming the owner,
   intended implementation branch, and claim evidence.
3. Merge the claim PR before allocating the implementation worktree. If
   another claim wins the merge race or the base becomes stale, re-audit and
   select again; do not overwrite the canonical claim.
4. Create the implementation worktree from the updated `develop`, confirm its
   §0.4 claim, and name every GAP ID in the implementation PR. The
   implementation PR leaves the claimed rows `IN_PROGRESS`; it does not
   predict merge.
5. If the audit discovers an untracked architecture problem, do not add it to
   the implementation diff or expand the claimed scope. Open a separate
   roadmap-only **GAP-registration PR** from current `develop`. It appends an
   `OPEN` ledger row with a stable, currently unused ID, audit class, current
   evidence, measurable exit condition, dependency edges, and exactly one new,
   currently unused closure package, plus that package's §7 acceptance entry.
   GAP-registration PRs follow the serialized-ledger rules above and are exempt
   from the active-claim prerequisite, but do not authorize implementation.
6. Merge the registration PR before work on the new scope. The new package
   still follows the ordinary `OPEN` → `READY` → `IN_PROGRESS` protocol. If the
   finding invalidates the active package's claim or exit criteria, stop that
   implementation and use the abandonment/block reconciliation in the
   after-implementation rules before changing its edges or package membership.

R0.1 is the one bootstrap exception: the roadmap-establishing PR creates the
protocol and records its own active claim because no canonical ledger existed
from which a prior claim PR could be opened.

During implementation:

1. Keep one primary architectural outcome per PR.
2. Register an untracked problem through the separate GAP-registration protocol
   above; never broaden the implementation PR merely by editing this ledger.
3. Preserve old IDs. Never renumber or delete a row.
4. Use `BLOCKED`, `REJECTED`, or `SUPERSEDED` instead of silently dropping
   work.
5. Record behavior-preserving compatibility shims and their removal GAP.
6. Each GAP belongs to exactly one `Closure package` in §5 and appears under
   exactly one `GAP:`/`GAPs:` line in §7. `Enables:` and `Uses:` references do
   not select or transition that GAP. If one closure package must become
   independently mergeable stages, add stage-specific GAP IDs before splitting
   it across implementation PRs.
7. A claim has no time-based automatic expiry and is never stolen because it
   looks old. Release it through a roadmap-only reconciliation after verifying
   that its implementation PR/worktree is inactive and recording the reason.
8. `SUPERSEDED` and `REJECTED` do not satisfy a dependency by themselves. The
   same reconciliation must rewrite every dependent edge to explicit
   replacement GAP IDs, or remove the edge with decision evidence that the
   requirement no longer applies. It must re-audit affected exit criteria and
   record the lineage/rationale in §10.3; otherwise the dependent package
   becomes `BLOCKED`.

After implementation:

1. Merge the implementation PR without a prospective status transition.
2. Immediately open a roadmap-only reconciliation PR from the updated
   `develop` branch, using the narrow exception above, and atomically move every
   row in the claimed closure package to `IN_DEVELOP` with feature PR/develop
   commit evidence for the package. Append its durable develop-transition row
   in §10.1, then remove its active-claim row in the same reconciliation. In
   that reconciliation, atomically move every row in each newly
   dependency-satisfied `OPEN` package to `READY` only after the whole
   package's measurable exit criteria are re-audited.
3. After the implementation reaches `main`, create a tracking-only worktree and
   branch from current `origin/main`, target its PR to `main`, atomically move
   every row in the closure package to `DONE`, and append one closure-evidence
   row per GAP. After it merges, sync `main` back to `develop` through a
   CI-gated `main` → `develop` PR. This is the only origin/main worktree
   exception; it never carries implementation code.
4. If an implementation PR is abandoned, atomically reconcile every
   `IN_PROGRESS` row in its claimed package back to one shared `READY`, `OPEN`,
   or `BLOCKED` status with the reason, then remove the claim. A temporary lag
   between a merge/closure and its reconciliation PR is allowed; the ledger
   must never lead code.
5. When a named blocker clears, a roadmap-only reconciliation may atomically
   move the whole package from `BLOCKED` to `OPEN`, or directly to `READY` only
   when all ordinary readiness conditions are re-audited. Record blocker and
   resolution evidence in §10.4; unresolved dependencies keep the package
   `BLOCKED`.
6. Update `baseline_commit` and `last_audited` only in a full-ledger audit PR,
   not in every feature or reconciliation PR.

Functional PRs still update `CHANGELOG.md` under `[Unreleased]`. A roadmap-only
or other documentation-only PR does not require a changelog entry.

### 0.4 Active claims

A package is exclusively owned only when its claim row and `IN_PROGRESS`
statuses are both present on canonical `origin/develop`. An open claim PR, a
local branch, or a worktree alone is not ownership. Claim PRs serialize through
normal review and CI; implementations start only after the claim merges.

| Closure package | GAP IDs | Owner/session | Implementation branch | Claim evidence | Claimed at (UTC) |
|---|---|---|---|---|---|
| R8.3 | REL-004 | `session=codex-root task=r8-3-publication-grace-evidence` | `feature/r8-3-publication-grace-evidence` | Readiness [#3039](https://github.com/mangowhoiscloud/geode/pull/3039); v1.0.23 GitHub/PyPI parity and candidate interval re-audited | `2026-08-20T07:41:19Z` |
| R5.1 | LLM-001 | `session=codex-root task=r5-1-interface-segregation` | `feature/r5-1-interface-segregation` | Reconciliation/readiness [#3092](https://github.com/mangowhoiscloud/geode/pull/3092); minimal completion protocol and optional capability surfaces re-audited | `2026-08-22T23:35:55Z` |

## 1. Program objective

GEODE already has strong extension seams—Skills, MCP, hooks, `Tool`, LLM
adapters, and narrow Calendar/Notification/Session ports—but its product
composition is not uniformly extensible. The current verdict is **B+,
conditionally approved**: the runtime is extensible at its edges, while the
agent loop, product/plugin boundary, tool registration path, and service
ownership still concentrate architectural knowledge.

The program is complete when GEODE has:

1. a closed, readable agent kernel whose visible primitive remains
   `while tool_use`;
2. an honest separation between kernel, bundled product features, and
   third-party extensions;
3. one immutable per-step tool plan from which model schemas, execution,
   authorization, data handling, and resource serialization are derived;
4. explicit session/turn/step lifetimes rather than process-global service
   lookup;
5. an LLM adapter interface split by capability with scoped discovery and
   deterministic collision handling;
6. a versioned public protocol distinct from internal hook/event churn;
7. storage behavior aligned with the existing SQLite/JSONL SOT rules;
8. executable architecture, change-surface, and documentation-drift gates;
9. every master-ledger row in `DONE`, `REJECTED`, or `SUPERSEDED`, with
   evidence.

### 1.1 Non-goals

- No ground-up rewrite of the agent loop.
- No requirement that every internal component become a plugin.
- No crate-per-concern mechanical split copied from a Rust workspace.
- No universal Python plugin SDK before two real external consumers need it.
- No mega `SessionServices`/`RuntimeServices` bag that merely hides constructor
  arguments.
- No change to Google credential storage just to make capability registration
  cleaner.
- No unversioned promise that every internal `HookEvent` is public API.
- No live provider tests without explicit approval.
- No file-size-only refactor that leaves the same responsibilities coupled.

## 2. Audited baseline

The qualitative audit is pinned by the frontmatter. The quantitative inventory
below is generated from the current source tree and checked for drift in CI.

### 2.1 Quantitative snapshot

<!-- generated:architecture-baseline:start -->
Generated by `scripts/architecture_baseline.py`; the canonical
machine-readable artifact is
`site/src/data/geode/architecture-baseline.json`.

| Measure | Current tree |
|---|---:|
| Production Python files (`core/` + `geode_product/` + `plugins/`) | 586 |
| Test Python files | 685 |
| `core/` Python LOC | 119,784 |
| `geode_product/` Python LOC | 61,217 |
| `plugins/` Python LOC | 193 |
| Test Python LOC | 183,468 |
| Tool definitions / executable registrations / valid schemas | 86 / 89 / 86 (definition-only 0; execution-only 3; invalid schema 0) |
| `RuntimeEvent` members | 57 |
| Built-in LLM adapters | 5 |
| Module/class-scoped `ContextVar`-backed bindings in production packages | 24 |
| `core` → product import sites | 0 across 0 files |
| Import-linter contracts / ignored edges | 6 / 16 |
| `AgenticLoop` file LOC / methods / constructor args | 1,112 / 38 / 12 |
| `SubAgentManager` file LOC / methods / constructor args | 811 / 17 / 18 |
| `RuntimeCoreConfig` fields | 6 |
| Global Ruff ratchets | complexity 52; args 23; branches 51; returns 18; statements 207 |
<!-- generated:architecture-baseline:end -->

`uv run lint-imports` passes all four configured contracts. That is useful
evidence, but the generated ignored-edge inventory includes comments promising
later removal and therefore cannot be treated as closure.

An isolated import probe that rejects every `plugins.*` import passes for
`core`, `core.agent`, `core.llm`, `core.tools`, `core.memory`,
`core.runtime`, and `core.self_improving.train`. It fails for `core.cli`
because `core/cli/__init__.py` imports Petri and seed-generation modules at
module load. The permanent gate must test the installed package, not rely on a
one-off import probe.

### 2.2 Largest architecture-relevant modules

| File | LOC | Main concern |
|---|---:|---|
| `core/agent/loop/agent_loop.py` | 2,714 | turn orchestration, policy, retry, compaction, tool flow, termination |
| `core/self_improving/campaign.py` | 2,557 | campaign orchestration and Petri integration |
| `core/llm/adapters/_openai_common.py` | 1,699 | shared transport/provider behavior |
| `core/cli/commands/login.py` | 1,388 | provider/source login surfaces |
| `core/server/ipc_server/poller.py` | 1,331 | IPC receive and application dispatch |
| `core/memory/session_manager.py` | 1,283 | session schema, state, and persistence |
| `core/agent/sub_agent.py` | 1,277 | sub-agent request, execution, role, and result flow |
| `core/hooks/system.py` | 1,267 | event taxonomy and dispatch |

These numbers are ratchet inputs, not proof of a design defect by themselves.
The defect is present where the module owns multiple independently changing
policies.

### 2.3 Extension-surface audit

| Surface | Existing strength | Current gap | Verdict |
|---|---|---|---|
| Skills | Three-tier discovery and progressive disclosure | Lifecycle is intentionally file-based, not a general code plugin contract | Strong; preserve |
| MCP | External capability protocol and server discovery | Manager still combines configuration, connection, call, and persistence concerns | Strong seam, partial internals |
| Hooks | Discovery plus sync/async/interceptor dispatch | Internal event taxonomy and public protocol stability are not explicitly separated | Strong seam, public-boundary gap |
| Native tools | Runtime-checkable `Tool` and `ToolRegistry` | Schema, handler, safety, personal-data, approval, auth, and defer metadata have separate lists | Shotgun-surgery gap |
| LLM adapters | Eight adapters and optional capability protocols | Base protocol still requires optional-looking methods; registry/discovery lifetime is broad | Partial |
| Google Workspace | `/login google`, keyring-backed multi-account schema, 11 native tools, Calendar adapter | Service bundle, tool schema, CLI handler, safety, approval, policy, and personal-data metadata are duplicated | Ideal pilot for convergence |
| `plugins/` | Petri, seed generation, benchmark and product features are modular directories | `core` imports them at 31 sites; they are not independently removable | Misnamed product boundary |
| Composition | `GeodeRuntime` and grouped config objects exist | `RuntimeCoreConfig` has 17 fields and downstream code still uses service-locator globals | Partial |
| Agent loop | Unlimited `while tool_use`, explicit termination, budgets, hooks, tool processor | One coordinator still owns too many lifetimes and policies | God application-service risk |

### 2.4 Google schema invariant

The implemented Google contract in
[`google-workspace-oauth.md`](google-workspace-oauth.md) is retained:

- `~/.geode/google/accounts.json` is a versioned, atomic, mode-`0600`
  metadata registry.
- Refresh tokens, client secret, account email, and display name live in the
  OS keyring under `geode.google.oauth`.
- Access tokens are process-memory only.
- Account identity, Workspace payloads, and credentials are not copied into
  the registry.
- Existing per-invocation personal-data and mutation consent remains
  fail-closed.

Capability refactoring may derive policy from descriptors, but it must not
weaken this storage or consent boundary. A schema change requires an explicit,
lossless, idempotent migration and a separate security review.

## 3. Target architecture

### 3.1 Dependency rings

The target is three honest rings:

```text
third-party extensions
        │
        ▼
product shell + bundled features
        │
        ▼
closed agent kernel
```

1. **Closed kernel**: agent loop, tool/capability contracts, hooks, memory
   ports, provider-neutral LLM contracts, and narrow infrastructure ports.
   It imports neither bundled features nor third-party extensions.
2. **Product shell and bundled features**: CLI/server composition, Petri,
   seed generation, self-improving product flows, and first-party integrations.
   Bundled does not imply a public plugin contract.
3. **Third-party extensions**: Skills, filesystem hooks, MCP servers, and
   explicitly supported Python entry points. They receive narrow capability
   contexts, never the entire runtime container.

The exact package migration is staged. A compatibility import remains for its
registered publication-based window, but the dependency direction is not
negotiable. If a directory cannot be installed, disabled, and tested
independently, it must not be called a third-party plugin.

### 3.2 Step capability and tool plan

Tool metadata is split by responsibility and composed into an immutable
step snapshot:

```text
ToolSpec                model-facing name, description, parameters
ExecutionBinding        handler factory and resource-key resolver
SafetyPolicy            effect, data class, consent and headless/sub-agent rules
CapabilityRequirement   provider/service/auth requirements
        │
        └──────────────► ToolRegistration
                              │
                              ▼
                    immutable ToolPlan
                    ├── provider schemas
                    ├── execution dispatch
                    ├── approval/data gates
                    ├── deferred-loading set
                    └── resource serialization
```

This is deliberately not one 40-field manifest. Small immutable records own
one reason to change; `ToolRegistration` references them. A `ToolPlan` is
created at the start of each `StepScope` from the session's registry/capability
snapshot plus the current policy and authorization state. It receives a
generation or content hash and is immutable through one model response, its
optional tool-call batch, and the resulting observation set. Refresh may create
a new generation for the next step; it never changes an in-flight step.

Google is the first vertical:

- `GoogleServiceDescriptor` owns bundle name, exact scopes, risk, API
  availability, and implication rules.
- Google tool registrations reference required bundle(s) and their
  read/write/personal-data policy.
- `/login google` renders choices from the same descriptors.
- OAuth storage and token refresh remain separate from Workspace consumers.

### 3.3 Agent lifetimes

```text
SessionScope
├── immutable RuntimeServices
├── immutable AdapterRegistrySnapshot
├── mutable session stores/caches
└── TurnScope
    ├── TurnState
    └── StepScope
        ├── StepSnapshot
        ├── ToolPlan
        ├── budgets/cancellation
        └── one model response → optional tool batch → observations
```

`StepSnapshot` is immutable and carries identity, route, capability-plan
generation, policy generation, budgets, cancellation handle, and trace
correlation. `TurnState` owns the mutable message/plan/retry/termination
accumulator. Long-lived services are injected through cohesive groups.
`ContextVar` is allowed for bounded request-local identity, diagnostics,
mutable request state, and request-local caches where explicit threading would
obscure the call contract. Every use requires an owner, reset boundary,
lifetime, and async propagation test. It is never a process-global service
locator.

`AgenticLoop` keeps the visible `while tool_use` control flow. Input,
prompt/model-call, tool execution, observation, and termination are extracted
as testable phases without replacing the loop with an opaque framework.

### 3.4 Protocol and persistence boundary

- Internal `HookEvent` can evolve with the runtime.
- IPC, gateway, and extension-facing events are explicit versioned
  projections with compatibility tests.
- Queryable runtime state follows
  [`storage-hierarchy.md`](storage-hierarchy.md) and
  [`event-persistence.md`](event-persistence.md): project `sessions.db` is the
  SOT for sessions/messages/runtime/hook events; JSONL remains for ordered,
  portable, bounded, or git-reviewable artifacts.
- Derived indexes and views are rebuildable from their declared SOT.
- New writers must name ownership, retention, redaction, concurrency,
  migration, and rebuild behavior before implementation.

## 4. Fixed architecture decisions

| Decision | Rule |
|---|---|
| D-001 Closed kernel | Product composition moves outward; `core` never reaches into optional feature packages |
| D-002 Honest plugin semantics | “Plugin” means independently discoverable, enableable, removable, and testable |
| D-003 No speculative universal SDK | Add a Python extension SDK only after two external implementations validate the contract |
| D-004 Tool plan is derived once | Model schema and executable handler maps come from the same immutable registrations |
| D-005 Narrow records over mega-bundles | Split spec, binding, safety, and capability metadata; group services by lifecycle and cohesion |
| D-006 Scoped globals only | `ContextVar` may carry request identity, never a process service that can be injected |
| D-007 Public protocol is projected | Internal hook enum changes do not automatically become public breaking changes |
| D-008 Storage policy is preserved | SQLite/JSONL ownership follows existing architecture docs; no second truth source |
| D-009 Google secrets remain keyring-only | Capability convergence does not move secrets or personal labels to plaintext |
| D-010 Trust is separate from enablement | An extension can be installed/enabled without automatically receiving sensitive authority |
| D-011 Self-improving is a bundled product control plane | Campaign, mutation, evaluation, promotion, and their CLI/MCP/scheduler surfaces move outside the closed kernel; this first-party feature remains bundled and is not presented as a third-party plugin |
| D-012 Mechanism moves before state | Neutral policy/context/activity contracts are extracted before the product move; code/import migration, compatibility-facade retirement, and durable-state relocation are separate transactions with one canonical implementation and writer at every stage |
| D-013 Released evidence is immutable | The v1.0.0 tag, portfolio commit links, commands, and historical package paths remain truthful snapshots; later releases describe boundary evolution instead of rewriting prior-release claims |
| D-014 Compatibility windows start at publication | The v1.0.23 facade and preserved state roots remain publicly available for a final qualifying interval of at least 30 consecutive days measured from confirmed GitHub Release and PyPI publication; every release inside that interval retains them |
| D-015 Facade retirement is removal-only | Retiring `core.self_improving` removes only forwarding imports and legacy source/module launchers after the publication gate; canonical product code, configuration, durable state, and unrelated APIs do not move in the same transaction |
| D-016 State follows declared ownership | A feature-owned dataset manifest declares lifecycle, schema, path, writer, and migration policy; the code move does not relocate data, tracked SoT moves in R8.2 before facade retirement, and runtime cutovers remain additive, idempotent, and single-writer |
| D-017 Collaboration control is not a second transcript | Mutable child-run state and bounded mailboxes live in the existing session database; child checkpoints, messages, and append-only session events remain the independent rollout history and sole replay source |
| D-018 Execution history is not active memory | Session and trajectory facts stay in their canonical records; only explicit memory writes or admitted learning may change model-visible memory, and cleanup removes duplicate authorities without deleting historical user files |

## 5. Master GAP ledger

Dependencies refer to other GAP IDs. `—` means no GAP dependency. Every row has
one `Closure package`; that package is the only package allowed to transition
the row. Edges between rows in the same closure package define its internal
implementation order, while readiness evaluates only dependencies outside the
package. A non-empty dependency cell is a comma-separated list of unique,
full GAP IDs; duplicate IDs and free-form tokens are parse errors. Delivery
and closure evidence are appended in §10.

| ID | Audit | Baseline evidence | Exit condition | Closure package | Depends on | Status |
|---|---|---|---|---|---|---|
| GOV-001 | `ABSENT` | Status is fragmented across dated plans and architecture docs | This file is linked from contributor entry points and governs status | R0.1 | — | `DONE` |
| GOV-002 | `PARTIAL` | Hand-audited counts disagree with `AGENTS.md` (78 tools/56 hooks vs 67/65 prose) | One generated architecture baseline and a drift check own the counts | R0.2 | GOV-001 | `DONE` |
| GOV-003 | `MISFIT` | Old plans describe removed paths and implemented work as current gaps | Overlapping docs carry a historical-status banner and point here | R0.1 | GOV-001 | `DONE` |
| GOV-004 | `PARTIAL` | 24 import ignores and very high global Ruff ceilings lack uniform owner/expiry metadata | Every exception is removed or recorded per symbol/edge with owner, rationale, expiry, and ratchet | R0.3 | GOV-002 | `DONE` |
| BND-001 | `MISFIT` | `plugins/` contains first-party features that `core` imports | Every package is classified kernel, product shell, bundled feature, or external extension; names match semantics | R1.1 | GOV-002 | `IN_DEVELOP` |
| BND-002 | `MISFIT` | 31 `core` → `plugins` import sites across 14 files | AST gate reports zero reverse dependency; composition owns feature registration | R1.2 | BND-001 | `IN_DEVELOP` |
| BND-003 | `ABSENT` | One-off core-only probe fails at `core.cli`; CI does not test an installed kernel without features | Isolated wheel/package test boots and runs kernel tests without bundled/third-party modules | R1.3 | BND-001, BND-002, BND-006 | `IN_DEVELOP` |
| BND-004 | `PARTIAL` | Skills/hooks/MCP have different discovery rules; Python feature collision/trust behavior is not unified | Each supported external surface declares non-executing discovery, precedence, collision, enablement, trust-before-load, reload, isolation, and teardown | R6.3 | BND-001, LLM-002 | `OPEN` |
| CAP-001 | `PARTIAL` | Google service bundles exist but do not own all tool/policy relationships | Generic capability records plus `GoogleServiceDescriptor` are executable SOTs | R2.1 | BND-002 | `IN_DEVELOP` |
| CAP-002 | `ABSENT` | `ToolRegistry` owns tool objects while other registries/lists own execution and safety | Immutable `ToolRegistration` and `ToolPlan` derive every tool consumer | R2.1 | CAP-001 | `IN_DEVELOP` |
| CAP-003 | `MISFIT` | Native Google handlers are bound in `core/cli/tool_handlers/delegated.py` | Runtime/composition binds handlers; CLI only renders/forwards user interaction | R2.3 | CAP-002, BND-002 | `IN_DEVELOP` |
| CAP-004 | `MISFIT` | Google names repeat in safety, approval, policy, personal-data, and CLI modules | Effect/data/auth/resource metadata derives gates; no independent tool-name allowlists | R2.2 | CAP-002 | `IN_DEVELOP` |
| CAP-005 | `PARTIAL` | `definitions.json`, tool objects, provider schemas, and defer sets can drift | Anthropic/OpenAI/deferred schemas and execution map share one plan hash and parity tests | R2.3 | CAP-002 | `IN_DEVELOP` |
| CAP-006 | `ABSENT` | Adding a native/Google tool requires edits across several policy files | Change-surface fixture proves the bounded file/registration budget in §8 | R7.2 | CAP-003, CAP-004, CAP-005 | `OPEN` |
| LOOP-001 | `ABSENT` | No immutable object freezes one step's route, policy, tool plan, and trace identity | `StepSnapshot` is created once per step and used by model/tool/telemetry paths | R3.1 | CAP-002 | `IN_DEVELOP` |
| LOOP-002 | `PARTIAL` | Mutable state is distributed across loop fields, contexts, checkpoints, and helpers | `TurnState` and explicit session/turn/step ownership replace ambiguous lifetimes | R3.1 | LOOP-001 | `IN_DEVELOP` |
| LOOP-003 | `MISFIT` | `AgenticLoop` owns orchestration plus many independently changing policies | Visible loop delegates to bounded input/model/tool/observe/termination phases | R3.2 | LOOP-001, LOOP-002 | `IN_DEVELOP` |
| LOOP-004 | `ABSENT` | Loop has 2,714 LOC, 67 methods, and 27 constructor args with no local ratchet | Closure budgets in §7.3 are executable and cannot regress | R3.3 | LOOP-003 | `IN_DEVELOP` |
| LOOP-005 | `MISFIT` | `SubAgentManager` combines request codec, role resolution, execution, validation, and announcements | Separate collaborators own those responsibilities; manager remains an orchestrator | R3.4 | LOOP-002 | `IN_DEVELOP` |
| DI-001 | `PARTIAL` | 26 module-level `ContextVar` declarations have no lifecycle classification | Generated inventory classifies request identity, diagnostics, mutable request state, request-local cache, and forbidden service lookup | R4.1 | LOOP-002 | `IN_DEVELOP` |
| DI-002 | `PARTIAL` | `GeodeRuntime` groups config, but `RuntimeCoreConfig` still has 17 fields | Cohesive lifecycle groups contain at most seven fields and have explicit owners/teardown | R4.2 | DI-001 | `IN_DEVELOP` |
| DI-003 | `MISFIT` | Downstream modules obtain injectable services through globals and CLI modules | Constructor/factory injection owns services; allowed ambient context is documented and tested | R4.2 | DI-001, DI-002 | `IN_DEVELOP` |
| DI-004 | `MISFIT` | `MCPServerManager` combines config, discovery, connection, call, trace/persistence, and lifecycle | Separate config catalog, connection pool, invoker, and persistence collaborators preserve public behavior | R4.3 | DI-002 | `IN_DEVELOP` |
| LLM-001 | `MISFIT` | `LLMAdapter` documentation calls the contract minimal but requires streaming and introspection methods | Minimal completion protocol plus optional capability protocols; no empty stubs required | R5.1 | DI-002 | `IN_PROGRESS` |
| LLM-002 | `PARTIAL` | Eight built-ins use a mutable registry with broad bootstrap lifetime | Built-in plus entry-point discovery yields immutable session snapshots with generation and collision policy | R5.2 | LLM-001, BND-001 | `OPEN` |
| LLM-003 | `PARTIAL` | Provider identity, credential source, transport, and adapter selection overlap | Provider profile, credential route, and transport are separate composable records | R5.3 | LLM-001, LLM-002 | `OPEN` |
| LLM-004 | `PARTIAL` | Interactive and autonomous LLM paths share taxonomy but retain multiple retry/failover implementations | Explicit `RetryPolicy` preserves intentional differences on one classification/telemetry substrate | R5.4 | LLM-003 | `OPEN` |
| PROTO-001 | `MISFIT` | Internal `HookEvent` taxonomy can leak into persistence/IPC expectations | Public activity/event projections are separate from internal dispatch events | R6.1 | LOOP-002, DI-002 | `READY` |
| PROTO-002 | `PARTIAL` | IPC has typed behavior but no single versioned external compatibility contract | Versioned envelopes, capability negotiation, unknown-field behavior, and golden compatibility tests | R6.1 | PROTO-001 | `READY` |
| STORE-001 | `PARTIAL` | `SessionStorePort`, `SessionManager`, checkpoints, transcripts, and event store have overlapping ownership | Ports and writers conform to the existing sessions.db/JSONL destination matrix; projections are rebuildable | R6.2 | — | `DONE` |
| STORE-002 | `PARTIAL` | Logging/transcript/resume/replay plan still contains staged/open parity work | Each subsystem has one declared writer, resume contract, replay doctrine, retention, and redaction test | R6.2 | STORE-001 | `DONE` |
| TRUST-001 | `ABSENT` | Registration/enabled status does not uniformly distinguish trusted authority | Installed, enabled, trusted, and granted-capability states are separate and observable; executable code is never imported before trust approval | R6.3 | BND-004 | `OPEN` |
| TRUST-002 | `PARTIAL` | Extension seams can receive broader runtime objects than required, and arbitrary in-process Python cannot be capability-confined | Trusted in-process code receives narrow ports for API discipline; untrusted executable code runs out of process behind a brokered capability boundary | R6.3 | DI-002, TRUST-001, TRUST-003 | `OPEN` |
| TRUST-003 | `ABSENT` | Mutation serialization is not derived from explicit tool resource metadata | `resource_keys(args)` drives per-resource serialization; no argument-name heuristic | R2.4 | CAP-004 | `IN_DEVELOP` |
| VER-001 | `PARTIAL` | Quality gates pass but lack core-only, reverse-import, exception-budget, and tool-plan drift tests | All architecture gates in §9 run in CI and locally | R7.1 | BND-003, BND-004, CAP-005, LOOP-004, DI-003, LLM-002, PROTO-002, GOV-004, VER-003 | `OPEN` |
| VER-002 | `ABSENT` | No contract suite measures how many central edits each extension type requires | Six extension scenarios in §8 pass without forbidden edits | R7.2 | CAP-006, LLM-002, BND-004 | `OPEN` |
| VER-003 | `PARTIAL` | Public/internal metric prose drifts from executable counts | `sync-stats` or one shared generator updates site, AGENTS facts, and roadmap baseline; check mode is green | R0.2 | GOV-001 | `DONE` |
| VER-004 | `PARTIAL` | Cold-start and runtime metrics exist, but refactors lack one architecture regression baseline | Startup, first-turn, tool-plan build, memory, and event-write budgets are pinned and non-regressing | R7.3 | CAP-005, LOOP-003, DI-004, LLM-004, PROTO-002, STORE-002 | `OPEN` |
| BND-005 | `MISFIT` | Generic agent/provider/observability consumers import self-improving transcript, SoT-resolution, and prompt-injection helpers | Neutral policy snapshot/source, context-contribution, run identity, and activity-sink contracts replace every classified-kernel import of a self-improving helper without changing runtime behavior | R1.4 | BND-001 | `IN_DEVELOP` |
| BND-006 | `MISFIT` | `core/self_improving` contains 39 Python files and 16,159 LOC of opt-in campaign, Petri/seed orchestration, mutation, gate, CLI/MCP, scheduler, and state policy | One cohesive first-party bundled feature owns the control plane outside the kernel; outer composition wires it, classified kernel modules import it zero times outside the exact forwarding-facade allowlist, a retirement GAP is registered before implementation, and v1.0 commands/imports/config/state behavior pass compatibility and installed-wheel tests | R1.5 | BND-002, BND-005 | `IN_DEVELOP` |
| REL-001 | `MISFIT` | PyPI and GitHub Releases still publish v1.0.0, while repository metadata and the changelog declare an untagged, unpublished v1.1.0; the operator selected v1.0.1 as the next public release | Wheel, sdist, CLI, daemon, site SOT, changelog, tag, GitHub release, and PyPI all report v1.0.1 with artifact-hash parity and no rewritten v1.0.0 evidence | R1.6 | BND-003, BND-006, GOV-004 | `SUPERSEDED` |
| REL-002 | `ABSENT` | No registered gate prevents the v1.0.1 compatibility facade or preserved state roots from being retired immediately after a local tag, draft release, or registry publication | Official GitHub Release and PyPI evidence proves compatible public artifacts continuously exposed the facade and preserved roots for a final qualifying interval of at least 30 consecutive days, starting no earlier than v1.0.1, and every release inside that interval retained them | R8.0 | REL-001 | `SUPERSEDED` |
| BND-007 | `ABSENT` | The current `core/self_improving` import and source/module launcher surface has no enumerated consumer census, old-to-new migration map, or removal-only closure gate | After REL-002, every repository and documented consumer is classified, migration guidance names canonical replacements, only the forwarding facade and legacy launchers are removed, and installed-wheel import/CLI/MCP/config/state parity proves the canonical product remains intact | R8.1 | REL-002, STORE-003 | `SUPERSEDED` |
| STORE-003 | `MISFIT` | Self-improving datasets span tracked `core/self_improving/state`, runtime `~/.geode/self-improving`, actively written `~/.geode/autoresearch/handoff`, and isolated `GEODE_STATE_ROOT/autoresearch` roots without one dataset-level ownership manifest | A feature-owned manifest declares every dataset's lifecycle, schema/version, root, writer/readers, concurrency, retention/redaction, migration, rollback, and rebuild contract; tracked SoT leaves `core` with hash/history parity, while runtime/override/worker roots remain compatible or migrate additively with one writer | R8.2 | REL-004, STORE-001 | `OPEN` |
| HOOK-001 | `MISFIT` | The 56-member internal `HookEvent` enum is exported at the package root, one registry mixes observer, result-transform, and control-interceptor authority without a stable public allowlist, and verification is emitted only inside terminal finalization | Exactly 13 versioned `HookName` contracts expose the Codex 11-event lifecycle plus `PreVerify`/`PostVerify`; typed authority, redaction, correlation, unknown-name rejection, and compatibility tests prevent internal RuntimeEvent growth from expanding the ABI, while one monotone bounded `PreVerify` → verifier → `PostVerify` → `Stop` state machine supports executable external continuation without erasing built-in failure or replaying side effects | R6.4 | — | `DONE` |
| HOOK-002 | `PARTIAL` | Tool request interception is mixed with `TOOL_EXEC_STARTED`; no typed sequential tool/LLM request transform or async `next_call` chain wraps the accepted executor and provider call across every runtime path | `tool_request`, `tool_execution`, `llm_request`, and `llm_execution` are four typed join points with N→N+1 request composition, original/effective trace, single-use async `next_call`, exception identity, policy-before-execution ordering, and all-path parity tests | R6.4 | HOOK-001 | `DONE` |
| COLLAB-001 | `MISFIT` | `delegate_task` tells callers that long-running work should not block, but awaits the complete fan-out and returns no stable handle for later control | Opt-in background delegation returns before completion and supports parent-scoped list, bounded wait, and interrupt while preserving the existing depth, session-cap, and Lane limits | R6.5 | HOOK-001 | `IN_DEVELOP` |
| COLLAB-002 | `MISFIT` | Subagent completion announcements live only in a five-minute process-memory queue, so parent inactivity or daemon restart can discard collaboration delivery | A bounded, redacted mailbox in the existing session database preserves ordered parent/child messages and completion delivery with transactional at-most-once consumption | R6.5 | COLLAB-001, STORE-002 | `IN_DEVELOP` |
| COLLAB-003 | `PARTIAL` | Child checkpoints and session history are durable, but every isolated worker invocation creates a fresh conversation and never restores the child checkpoint | Follow-up and resume reopen the same child session as a new generation, restore its checkpoint, accept queued mailbox input at a loop boundary, and preserve one independent rollout without replaying successful side effects | R6.5 | COLLAB-001, COLLAB-002 | `IN_DEVELOP` |
| HOOK-003 | `PARTIAL` | All 13 public hooks are wired, but no production `PostVerify` policy is registered; an empty decision set can deliver a retryable verifier failure, continuation authority is encoded as a user-role pseudo-system message, and durable verification records aggregate handler decisions without a stable candidate target | A deterministic fallback maps pass/retryable failure/non-retryable failure to accept/revise/escalate; revision enters the bounded dynamic system context, reaches the existing verify-fail replan path, and records candidate-digest-bound per-handler decisions without replaying completed side effects or adding a new hook plane | R6.6 | HOOK-001, STORE-002 | `DONE` |
| MEM-001 | `MISFIT` | One live system-prompt branch creates a default user profile outside the wired project scope, `TURN_COMPLETED` promotes a low-information turn/tool trace into active project memory, and caller-free session-checkpoint plus journal write/aggregate APIs imply competing authorities | The wired profile is the sole prompt profile source; automatic turn traces remain in canonical session records; dead `SessionStorePort` checkpoint and `ProjectJournal` write/aggregate APIs are removed while historical files remain untouched; executable tests and docs identify the live read/write authority without adding a store or framework | R6.7 | HOOK-001, STORE-002 | `DONE` |
| GOAL-001 | `PARTIAL` | Explicit Goal state, contextual continuation, accounting, and trajectory events persist, but automatic continuation is owned only by one `AgenticLoop.arun()` call; no process owner discovers an active Goal after return or daemon restart, restores its checkpoint, or prevents duplicate idle launches | The existing serve process owns a bounded idle Goal continuation host that restores the same checkpoint as a new session generation, admits at most one continuation per session, uses the internal contextual-Goal path rather than a synthetic user turn, preserves Lane, PostVerify/replan, accounting, and trajectory contracts, and does not hot-loop an unchanged active Goal | R6.8 | HOOK-003, STORE-002 | `DONE` |
| CODE-001 | `PARTIAL` | Coding work spans session/checkpoint/timeline, task preflight/TaskGraph, Goal, collaboration, worktree workflow, file/bash tools, and reviewer/verification paths, but no canonical contract maps their current writers, recovery authority, or residual coding-runtime boundaries | One reviewed coding-runtime authority contract maps every proposed record and operation to an existing or residual owner, fixes recovery/history/projection and drift/rollback invariants, and proves that no duplicate runtime store, task ledger, policy plane, or implementation API was introduced | R9.1 | STORE-002, HOOK-003, MEM-001, COLLAB-003, GOAL-001 | `OPEN` |
| REL-003 | `MISFIT` | PyPI, GitHub Releases, repository metadata, and the changelog report v1.0.22, which predates the delivered boundary refactor | Wheel, sdist, CLI, daemon, site SOT, changelog, tag, GitHub release, and PyPI all report v1.0.23 with artifact-hash parity and no rewritten earlier-release evidence | R1.7 | BND-003, BND-006, GOV-004 | `DONE` |
| REL-004 | `ABSENT` | No registered gate prevents the v1.0.23 compatibility facade or preserved state roots from being retired immediately after a local tag, draft release, or registry publication | Official GitHub Release and PyPI evidence proves compatible public artifacts continuously exposed the facade and preserved roots for a final qualifying interval of at least 30 consecutive days, starting no earlier than v1.0.23, and every release inside that interval retained them | R8.3 | REL-003 | `IN_PROGRESS` |
| BND-008 | `ABSENT` | The current `core/self_improving` import and source/module launcher surface has no enumerated consumer census, old-to-new migration map, or removal-only closure gate | After REL-004, every repository and documented consumer is classified, migration guidance names canonical replacements, only the forwarding facade and legacy launchers are removed, and installed-wheel import/CLI/MCP/config/state parity proves the canonical product remains intact | R8.4 | REL-004, STORE-003 | `OPEN` |

## 6. Dependency and merge sequence

```text
R0  SOT + generated baseline
 │
 ▼
R1  honest package and extension boundaries
 ├───────────────┐
 ▼               ▼
R2 capability    R3 agent kernel/lifetimes
 └───────┬───────┘
         ▼
R4 composition and service ownership
         │
         ├───────────────┐
         ▼               ▼
R5 LLM plane        R6 protocol/storage/trust
         └───────┬───────┘
                 ▼
R7 closure gates, benchmarks, docs, release
```

R3.1 starts after R2.1 so `StepSnapshot` consumes the new immutable `ToolPlan`
rather than inventing a competing tool snapshot. The remaining R2 and R3
packages may then progress in parallel. R5 and most of R6 may progress in
parallel after the composition root is stable, but R6.3 waits for R5.2 because
its unified extension lifecycle includes LLM-adapter discovery. R6.4 is a
narrow compatibility-preserving package over the current measured call sites
and sinks. It owns convergence of those call sites into its four middleware
join points, but does not claim or bypass the broader owner replacements
elsewhere in R2-R6.

R6.5 is a narrow collaboration-control package over the delivered public-hook
and storage contracts. It makes the existing depth-one subagent runtime
durable and controllable without introducing a general thread manager, a
planner, or a second transcript, and it does not claim the broader R3.4
`SubAgentManager` responsibility split.

R6.6 closes the measured delivery-control gap left after R6.4 without changing
the 13-name public ABI. It reuses the existing finalization state machine,
dynamic system context, verify-fail replan gate, bounded continuation budget,
and semantic session timeline. It does not add a policy framework, a prompt
template, a transition writer on the hot path, or a required-handler trust
model without a measured external consumer.

R6.7 is a residual memory-authority cleanup over the delivered hook and
storage contracts. It routes the two live prompt profile blocks through one
wired instance, stops promoting a duplicate turn trace into active memory, and
removes only APIs with a measured zero production-caller census. It does not
introduce a context-snapshot framework, admission engine, new database, or
checkpoint schema; those require separate measured GAPs.

R6.8 gives explicit Goals a process-level continuation owner without reopening
R6.5's deliberately bounded child-collaboration contract or introducing the
future R3 phase/service extraction. The serve daemon reuses the existing
checkpoint, Lane, Goal projection, and session-event writers. It does not add a
general thread manager, execute `PlanStep` objects, clone environment state, or
claim LATS/SPRINT/SWiRL training behavior.

### 6.1 v1.0.23 boundary-release train

v1.0.23 is an intermediate, explicitly registered architecture checkpoint. It
does not claim that the complete R0-R7 program is finished, and it does not
remove the compatibility facade introduced by R1.5.

| Wave | Package | Required outcome |
|---|---|---|
| 0 | R0.3 | Ratchet existing architecture exceptions before adding boundary-specific allowlists |
| 1 | R1.1 | Fix the package classification and product-shell migration map |
| 2A | R1.4 | Extract neutral host seams without changing self-improving behavior |
| 2B | R1.2 | Remove kernel-to-feature reverse dependencies through outer composition |
| 3 | R1.5 | Move the bundled self-improving control plane and retain the exact compatibility facade |
| 4 | R1.3 | Prove the installed kernel boots without bundled or third-party features |
| 5A | R1.7 | Reconcile, build, publish, and verify v1.0.23 |
| 5B | R0.1/R0.2 and checkpoint packages | Record main/release closure evidence and synchronize `main` back to `develop` |

Section 5 remains the status authority. The table is a release-specific view of
already registered packages, not an alternate ledger or permission to skip
claim and reconciliation transactions. The rest of R2-R7 remains in the
master-ledger order and continues after the checkpoint.

REL-003 must be `DONE` before R8.3 can become `READY`, but that ledger
transition does not set the historical compatibility clock. The interval starts
at the later official GitHub/PyPI publication timestamp defined by R8.3; local
commits, tags, draft releases, and repository metadata consume none of it.

Public release truth is re-audited against the official
[PyPI project](https://pypi.org/project/geode-agent/) and
[GitHub Releases](https://github.com/mangowhoiscloud/geode/releases) surfaces
immediately before the cut. As audited on 2026-08-20, both identify v1.0.22 as
the latest public release, matching repository metadata and the changelog.

## 7. Phase work packages

### R0 — SOT, baseline, and debt governance

#### R0.1 Canonical roadmap bootstrap

GAPs: GOV-001, GOV-003.

- Add this stable document and contributor/workflow links.
- Mark overlapping plans as historical design evidence.
- Preserve their original design content and provenance while explicitly
  freezing obsolete status/SoT labels.
- Establish the status and closure rules before functional work begins.

Acceptance:

- `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, and `docs/workflow.md` link to
  this file.
- The overlap audit in §12 dispositions every identified architecture,
  persistence, loop, and release plan that could look live.
- A repository search identifies no undispositioned document claiming to own
  architecture/extensibility program status.
- Legacy plans remain readable for rationale but point here for current status.

#### R0.2 Generated architecture baseline

GAPs: GOV-002, VER-003.

Create one deterministic checker/generator that emits at least:

- Python file and LOC counts by package;
- tool definition/registration/schema parity;
- HookEvent count;
- built-in adapter count;
- `ContextVar` inventory;
- `core` → feature/plugin import edges;
- import-linter ignored-edge count;
- coordinator LOC/method/constructor metrics;
- configured complexity thresholds.

The generator must have `--check` and update modes. Human prose consumes its
output; no second script re-derives the same facts differently.

R0.2 also adds `scripts/check_architecture_roadmap.py` and wires a
target-aware invocation into CI:

```bash
uv run python scripts/check_architecture_roadmap.py \
  --check \
  --base-ref "origin/${GITHUB_BASE_REF:-develop}" \
  --target-branch "${GITHUB_BASE_REF:-develop}" \
  --event-mode pull_request
```

The validator fails on duplicate GAP or package IDs, missing or cyclic
dependencies, a GAP selected by zero or multiple §7 packages, package/ledger
mapping drift, non-atomic package statuses, active-claim mismatch, missing
delivery/decision/blocker evidence, and an illegal transition relative to the
named base ref. A main-closure tracking PR uses `--base-ref origin/main
--target-branch main`.

#### R0.3 Exception debt ledger

GAP: GOV-004.

- Replace global “temporary” comments with machine-readable edge/symbol debt.
- Require owner, reason, created date, target GAP/phase, and expiry condition.
- Fail on new unregistered exceptions.
- Lower a threshold in the same PR whenever the current maximum drops.
- Prefer structural contract changes over adding another ignore edge.

### R1 — Honest package and extension boundaries

#### R1.1 Package classification ADR and migration map

GAP: BND-001.

Enables: BND-004. This package supplies its package-classification evidence but
does not transition BND-004; R6.3 owns that GAP's closure.

Classify every current `plugins/*` package and the current
`core/self_improving` umbrella:

- independently removable external extension;
- bundled product feature;
- kernel concern in the wrong directory;
- compatibility shim scheduled for removal.

Per D-011, the classification outcome for the self-improving control plane is
already fixed as a first-party bundled product feature. R1.1 chooses the
product-shell package and migration map; it does not reopen whether that
control plane belongs in the closed kernel or mislabel it as a third-party
plugin. Petri, seed generation, and self-improving remain cohesive sibling
features in one product ring and distribution unless independent installation
is later proven necessary.

The migration map names source, target ring, public imports, entry points,
state paths, test ownership, and rollback. It must decide the product-shell
package before moving CLI/server imports. No mass rename lands without
compatibility tests.

#### R1.2 Reverse-dependency removal

GAP: BND-002.

Remove the 31 reverse imports in behavior-preserving clusters:

1. CLI command registration;
2. LLM/Petri provider helpers;
3. self-improving/Petri orchestration;
4. tool handlers and audit surface.

The outer composition layer imports feature registrations and passes narrow
ports inward. Kernel error classification may not import a product feature to
recognize one provider.

#### R1.3 Core-only distribution truth gate

GAP: BND-003.

Enables: VER-001. The core-only gate becomes one input to the complete
architecture CI suite, whose closure package remains R7.1.

Build/install the kernel without bundled or third-party features in an
isolated environment, then run:

- import of every declared kernel public module;
- kernel unit tests;
- tool/adapter registry construction with zero extensions;
- start/stop lifecycle with fake ports;
- package metadata inspection proving no hidden import dependency.

The test must not rename directories in-place or rely on import cache.

#### R1.4 Neutral self-improving host seams

GAP: BND-005.

Characterize the current daily runtime and then extract only the neutral
mechanisms that the closed kernel legitimately owns. Names may change during
implementation, but the responsibilities remain separate:

- immutable policy snapshot/source selection presented to a step without
  exposing autoresearch paths;
- provider-neutral context/prompt contributions registered at composition,
  not imported from one provider adapter;
- bounded run identity and activity/transcript sink contracts;
- generic hook dispatch and scheduler ports, without promoting
  mutation/campaign/Petri payloads into stable kernel APIs.

The existing product-shaped `RunTranscript`, autoresearch SoT resolution, and
in-context recipes do not remain in the kernel merely because generic callers
currently import them. They implement the neutral ports from the product side.

Acceptance:

- prompt bytes/hashes, termination reasons, hook ordering, retry/cost behavior,
  and no-SoT fast paths are characterized before extraction;
- `core.agent`, `core.llm`, `core.memory`, `core.observability`, and
  `core.skills` no longer import `core.self_improving`;
- a neutral contract can run with no self-improving feature installed or
  registered;
- no mega `SelfImprovementPort` or service-locator `ContextVar` replaces the
  direct imports.

#### R1.5 Bundled self-improving product relocation

GAP: BND-006.

Move the high-variance control plane into the product-shell namespace selected
by R1.1 as one cohesive bundled feature:

- campaign, train, prepare, fitness, gate, measure, and ledger;
- mutation runner/policies, attribution, benchmark/statistical observers, and
  inference-time contribution recipes;
- Petri/seed-generation orchestration and self-improving configuration;
- feature-specific CLI, MCP, hook, and scheduler registrations.

Petri and seed generation remain cohesive sibling bundled features rather than
being fragmented into independent distributions or swallowed by one
mega-module. Outer composition supplies narrow evaluator, seed/baseline,
policy, and activity ports. The closed kernel imports none of those concrete
features.

The canonical implementation moves once. A publication-gated
`core.self_improving.*` compatibility facade, the legacy `python -m
core.self_improving.{train,campaign,prepare,watch_campaign}` entry points, and
the documented source-checkout launchers at
`core/self_improving/{train,campaign,prepare,watch_campaign}.py` delegate to
that canonical implementation through the R8.3 window; they must not duplicate
a ContextVar, hook bridge, singleton, registry, or writer. BND-008 is the stable
facade-retirement GAP. BND-007 satisfied R1.5's planning prerequisite at the
time; BND-008 now owns retirement, and its REL-004 dependency forbids removal
before the publication window closes.

The boundary move preserves:

- `/self-improving`, `geode campaign`, and MCP propose/apply/status behavior;
- `[self_improving_loop.*]` config keys and validation;
- `~/.geode/self-improving/`, `~/.geode/autoresearch/handoff/`,
  `GEODE_STATE_ROOT/autoresearch`, and the current tracked-SoT location/schema
  for the compatibility window, including local policy overrides, transcripts,
  handoff indexes, and scheduler lock/timestamp/history records;
- JSON/JSONL/TSV schemas, append-only ledgers, worker isolation, confirmation
  gates, and optional audit-extra degradation;
- one base wheel containing the kernel and bundled product features.

Acceptance:

- AST probes report zero classified-kernel → relocated-feature imports; the
  exact `core/self_improving` forwarding files are a narrow, separately checked
  allowlist and may import only the canonical relocated modules;
- installed-wheel probes verify both feature-absent kernel boot and
  facade-present bundled-product behavior without import obfuscation;
- old and new imports resolve the same canonical class/function/context
  objects, and the supported `python -m` plus source-checkout path launchers
  have output/exit-code parity;
- CLI/MCP/scheduler/prompt/provider behavior and state fixtures pass
  characterization tests, including override reads and transcript, handoff,
  and auto-trigger writes under the preserved roots;
- no physical state relocation or compatibility-facade removal is hidden in
  the package move.

#### R1.6 v1.0.1 boundary release checkpoint

GAP: REL-001.

Superseded by REL-003/R1.7 after official release surfaces proved that v1.0.1
had already shipped before the boundary refactor. The original criteria remain
as immutable decision history.

Reconcile and publish the boundary refactor as v1.0.1 without rewriting the
historical v1.0.0 record:

- re-query the official PyPI and GitHub Releases surfaces immediately before
  the cut and fail closed if a v1.1.0 artifact has appeared;
- reconcile `pyproject.toml`, lock/build metadata, CLI and daemon version
  reporting, generated site SOT, changelog, public docs, tag, and release notes
  to one v1.0.1 value;
- fold material under the untagged v1.1.0 changelog heading into the actual
  v1.0.1 release or `[Unreleased]`; two competing current-release headings are
  forbidden;
- preserve the v1.0.0 tag, release notes, portfolio commit links, commands, and
  historical package-path claims as released evidence;
- run the complete non-live quality gates, build wheel and sdist, and verify
  clean-environment `uv`/`uvx`, CLI, daemon, bundled-feature, compatibility,
  and kernel-only installation smoke tests;
- record SHA-256 parity from locally verified artifacts through the GitHub
  release assets and PyPI files, then complete roadmap promotion and
  main-to-develop tracking transactions.

The release narrative states the architecture evolution explicitly: v1.0.0
physically consolidated the product under `core`; v1.0.1 aligns the package
boundary with the already documented outer-loop model while preserving the
public compatibility window. Facade retirement and durable-state relocation
require separately registered packages and cannot ride this release.

#### R1.7 v1.0.23 boundary release checkpoint

GAP: REL-003.

Publish the delivered boundary refactor as v1.0.23 without rewriting any
earlier release record:

- re-query PyPI and GitHub Releases immediately before the cut and fail closed
  if v1.0.23 already exists with nonmatching artifacts;
- reconcile package, lock/build, CLI/daemon, generated site, changelog, public
  docs, tag, and release-note versions to v1.0.23;
- fold intended release material from `[Unreleased]` into one v1.0.23 heading;
- preserve every earlier tag, release note, portfolio link, command, and
  historical package-path claim;
- run complete non-live gates plus clean-environment `uv`/`uvx`, CLI, daemon,
  bundled-feature, compatibility, and kernel-only installation smoke tests;
- verify SHA-256 parity across local artifacts, GitHub assets, and PyPI files,
  then complete the required roadmap and main/develop tracking transactions.

The release documents the `core`/`geode_product` boundary and starts the
publication clock; facade retirement and durable-state relocation remain
separate packages.

### R2 — Unified capability and tool plane

#### R2.1 Small immutable metadata records

GAPs: CAP-001, CAP-002.

Introduce `ToolSpec`, `ExecutionBinding`, `SafetyPolicy`,
`CapabilityRequirement`, `ToolRegistration`, and `ToolPlan` in a neutral
kernel module. Names may change during implementation, but responsibilities
must not collapse into one broad manifest. Define the executable
`GoogleServiceDescriptor` shape and its existing bundle data here; migration of
all Google consumers remains R2.2.

Required invariants:

- duplicate names fail unless an explicit, observable override policy applies;
- registrations are validated before a session starts;
- a plan is immutable and has a generation/content hash;
- plan refresh never mutates an in-flight step;
- schema and execution maps contain identical names;
- unavailable capability and denied policy are distinguishable.

#### R2.2 Google descriptor pilot

GAP: CAP-004.

Uses: CAP-001 and CAP-002 from R2.1.

Move existing service bundle/scopes/risk/implication data into executable
Google descriptors and migrate all 11 native Workspace tools plus Calendar
surfaces to reference them.

The pilot is accepted only when adding a future service does not require
independent edits to:

- `core/agent/safety.py`;
- `core/agent/approval.py`;
- `core/tools/policy.py`;
- `core/tools/personal_data.py`;
- `core/cli/tool_handlers/delegated.py`;
- `core/tools/definitions.json`.

The refactor must preserve `/login google`, multi-account selection, actual
granted-scope persistence, per-invocation consent, headless/sub-agent denial,
keyring-only secrets, and bounded API results.

#### R2.3 Runtime binding and provider projections

GAPs: CAP-003, CAP-005.

- Move handler factories out of CLI ownership.
- Build Anthropic/OpenAI schemas and deferred-loading data from `ToolPlan`.
- Keep provider-specific representation in adapters, not in the registry.
- Add plan parity and deterministic ordering tests.
- Expose plan generation/hash in bounded diagnostics.

#### R2.4 Resource and data policy derivation

GAP: TRUST-003.

Uses: CAP-004 from R2.2.

Safety metadata declares:

- effect: read, mutate, execute, communicate, or administrative;
- data classification and persistence/redaction rule;
- approval cacheability and mandatory per-invocation consent;
- headless and sub-agent availability;
- required auth/capability bundle;
- deterministic resource keys for mutation serialization.

Policies consume metadata and may further restrict it; they may not weaken a
tool's declared minimum.

### R3 — Agent kernel and lifetime extraction

#### R3.1 `StepSnapshot` and `TurnState`

GAPs: LOOP-001, LOOP-002.

Add immutable step identity and an explicit mutable turn accumulator before
extracting loop phases. Pin:

- all current `TerminationReason` members, their producer map, persisted
  string compatibility, and the explicitly producerless legacy/unknown cases;
- unlimited-round default with time-budget control;
- context-overflow recovery;
- checkpoint-before-retry behavior;
- approval and input-block semantics;
- usage/cost and hook event ordering;
- session-wide cancellation and sub-agent identity.

#### R3.2 Phase collaborators

GAP: LOOP-003.

Extract in this order:

1. input/interceptor preparation;
2. prompt/model-call preparation;
3. provider call and retry decision;
4. tool-call processing;
5. observation/compaction;
6. termination/result assembly.

Each extraction first receives characterization tests. The public
`AgenticLoop.arun` behavior stays stable, and the central loop remains easy to
read top-to-bottom.

#### R3.3 Structural ratchets

GAP: LOOP-004.

Closure budgets:

| Measure | Baseline | Closure budget |
|---|---:|---:|
| `agent_loop.py` LOC | 2,714 | ≤ 1,600 |
| `AgenticLoop` methods | 67 | ≤ 40 |
| `AgenticLoop.__init__` direct args | 27 | ≤ 12 |
| Architecture-owned function complexity | up to global 62 | ≤ 30 or registered algorithmic exception |
| Architecture-owned function branches | up to global 68 | ≤ 35 or registered algorithmic exception |
| Architecture-owned function statements | up to global 273 | ≤ 120 or registered algorithmic exception |

These are guardrails, not incentives to hide code in generic helpers or
service bags. A budget change requires an evidence-backed decision entry in
this roadmap.

#### R3.4 Sub-agent decomposition

GAP: LOOP-005.

Extract request codec, role/tool policy resolver, worker launcher, result
validator, best-of judge, and announcement publisher. Preserve max depth,
session cap, Lane concurrency, task isolation, and cancellation.

### R4 — Composition and service ownership

#### R4.1 Ambient-state inventory

GAP: DI-001.

Classify every module/class-scoped `ContextVar`-backed binding in the current
generated inventory:

- request identity;
- request-local mutable state;
- diagnostic scope;
- cache;
- service locator to remove.

Every declaration gets owner, setter/resetter, lifetime, async propagation
test, and teardown behavior. A service-locator classification cannot remain at
closure.

#### R4.2 Cohesive runtime services

GAPs: DI-002, DI-003.

Construct service groups around lifetimes such as execution, persistence,
integration, and authentication. Each group contains at most seven cohesive
fields, exposes narrow ports, and owns teardown where applicable. Avoid a
single all-purpose session bundle.

Factories build services at the composition root. Downstream modules receive
only the group or port they use. Compatibility globals may delegate for one
release and must name their removal GAP.

#### R4.3 Manager splits

GAP: DI-004.

Split `MCPServerManager` into configuration catalog, discovery, connection
pool, invoker/result guard, and trace/persistence collaborators. Apply the same
responsibility test to other large managers, but do not reopen LOOP-005 after
R3.4; add a GAP before expanding scope.

### R5 — LLM adapter plane

#### R5.1 Interface segregation

GAP: LLM-001.

The required adapter surface becomes identity plus one completion operation.
Streaming, model listing, environment diagnostics, quota inspection, web
search, computer use, and text completion are optional capability protocols.
Dispatch uses protocol/capability checks; adapters do not implement dishonest
empty stubs.

#### R5.2 Scoped discovery and collision policy

GAP: LLM-002.

Enables: BND-004. R6.3 generalizes the lifecycle/trust contract across every
supported extension surface; LLM-002 does not wait for that later closure.

- Built-ins are registered explicitly by a factory.
- Supported third-party adapters use package entry points.
- Discovery produces a registry generation and validation report.
- Session bootstrap freezes an immutable registry snapshot.
- Duplicate canonical IDs fail by default; an explicit override records
  origin, priority, and trust decision.
- Reload creates a new generation for **new sessions only**. A live session
  keeps its bootstrap snapshot through every turn and step so routing and replay
  remain deterministic.

#### R5.3 Provider profile × transport

GAP: LLM-003.

Separate:

- provider/model semantics and defaults;
- credential source and account selection;
- transport/API shape;
- optional native capabilities;
- retry/quota policy.

This keeps “OpenAI model over Responses API with Codex OAuth” composable
without a new closed provider enum branch. Existing adapter names remain
compatibility aliases until migration is proven.

#### R5.4 Call-stack convergence

GAP: LLM-004.

Re-audit
[`2026-06-20-llm-call-stack-unification.md`](../plans/2026-06-20-llm-call-stack-unification.md)
against current code. Share classification, billing-fatal handling, OAuth
refresh, telemetry, and retry state. Preserve the intentional policy split:

- interactive quota exhaustion returns control to the operator;
- autonomous/self-improving work may use bounded quota backoff.

No refactor may silently change call counts, backoff, model fallback, billing,
or hook ordering.

### R6 — Public protocol, persistence, and trust

#### R6.1 Versioned public projection

GAPs: PROTO-001, PROTO-002.

Define explicit IPC/gateway/extension envelopes with:

- protocol version and feature negotiation;
- stable public event names;
- bounded typed payloads;
- unknown field/event behavior;
- redaction and size limits;
- request/response correlation;
- golden backward/forward compatibility fixtures.

Internal hooks project into this protocol. They are not serialized by dumping
an enum/dataclass wholesale.

#### R6.2 Storage contract reconciliation

GAPs: STORE-001, STORE-002.

Inventory every session/event/transcript writer and reader. For each, record:

- canonical SOT and rebuildable projections;
- schema version and migration owner;
- concurrency/WAL/atomicity behavior;
- retention and pruning;
- redaction/personal-data policy;
- resume and replay semantics;
- corrupt/partial-write recovery.

Use the existing storage hierarchy rather than introducing a second canonical
log. The linked plan is behavior-contract evidence, not a competing execution
SOT. Close or supersede its open items in
[`2026-06-19-aligned-logging-transcript-policy.md`](../plans/2026-06-19-aligned-logging-transcript-policy.md)
with current code evidence.

#### R6.3 Extension trust and least authority

GAPs: TRUST-001, TRUST-002, BND-004.

Depends on: TRUST-003 resource metadata closed by R2.4. The ledger records
this status-driving edge on TRUST-002.

Model separate states:

```text
discovered → installed → enabled → trusted → capability granted
```

Discovery of third-party executable extensions is manifest-only and must not
import or instantiate extension code. Trust and policy authorization are
decided before load. In-process execution is permitted only for fully trusted
code; its `ExtensionContext` exposes declared narrow ports as API discipline,
not as a Python security sandbox.

Untrusted or capability-confined executable extensions run out of process
behind brokered ports and OS/process controls. Closing TRUST-001/002 requires
executable evidence that untrusted code is not loaded in-process and cannot
bypass the broker to obtain filesystem, network, credential, or runtime-global
authority. Startup reports collisions, rejected manifests, missing capability
grants, and degraded extensions. Teardown is deterministic. Resource mutation
uses descriptor-provided keys, not argument-name guessing.

#### R6.4 Public hooks, middleware join points, and finalization control

GAPs: HOOK-001, HOOK-002.

The measured design evidence is carried by
[#2832](https://github.com/mangowhoiscloud/geode/pull/2832), grounded against
Hermes `36e41c09ed02bd783c1186564bf08cca5c8e821d`, OpenClaw
`90a22b4f50226b13735e77dde81a92340ae724cf`, and Codex
`578c1b2230288104041e880a86d0f7f3a5ca6e47`. The 2026-07-31 readiness
re-audit found that the initially registered external dependencies described
desirable future owners, not prerequisites for this package. Current `develop`
has one injected hook system, a primary `ToolCallProcessor` executor terminal,
three direct recovery executor calls, async adapter calls in the main loop,
reflection, candidate sampling, and the API mutator. It also has the
finalization helper, a bounded SQLite hook event sink, and conditional JSONL
projections. R6.4 owns convergence of this finite measured tool and
`AdapterCallRequest`-based completion set into the four middleware join points
and characterizes the existing persistence behavior directly. It can do so
without waiting for the broader tool-plan, loop-decomposition,
provider-profile, storage-ownership, trust-broker, or protocol programs. It
does not implement or claim those programs, replace their future types, expose
untrusted code in-process, or change persisted event values.

This section remains the execution SOT. The public ABI contains exactly:

```text
UserPromptSubmit
PreToolUse, PermissionRequest, PostToolUse
PreCompact, PostCompact
SessionStart, SessionEnd
SubagentStart, SubagentStop
PreVerify, PostVerify, Stop
```

The 56 current runtime signals remain internal and retain their stored values.
There are three authority surfaces, not four generic planes:

- `HookName` + `HookRegistry` is the bounded public ABI;
- `MiddlewareRegistry` owns the four trusted request/execution methods;
- `RuntimeEvent` + `RuntimeEventBus` is internal observation and persistence.

Stateful compaction, approval, subagent, and verification services remain
domain owners rather than becoming a fourth extension surface. Unknown public
names fail closed; a versioned JSON-safe schema fixes each hook's input, result,
authority, redaction, timeout, composition, and correlation behavior.

The canonical names are deliberately small. No `PublicHookRegistry`,
`MiddlewarePipeline`, `MiddlewareKind`, `MiddlewarePoint`, or
`ExtensionRuntime` abstraction is introduced. Request and execution role
protocols consistently end in `Middleware`. The legacy names `HookEvent` and
`HookSystem` migrate to `RuntimeEvent` and `RuntimeEventBus`; they are never
reused for public-hook semantics.

Migration is value-preserving:

| Current surface | Canonical target | Compatibility rule |
|---|---|---|
| `HookEvent` / `HookSystem` | `RuntimeEvent` / `RuntimeEventBus` | legacy Python aliases for the declared migration window; stored enum values and rows never change |
| observer `register` / `trigger*` | `subscribe` / `emit*` | move callers mechanically, keep sinks and prefix subscription internal |
| `USER_INPUT_RECEIVED` interceptor | `HookName.USER_PROMPT_SUBMIT` | old row remains a legacy observation |
| `TOOL_EXEC_STARTED` interceptor | `HookName.PRE_TOOL_USE` plus actual execution-start event | emit start only after policy and approval, immediately before the executor |
| `TOOL_RESULT_TRANSFORM` feedback | `HookName.POST_TOOL_USE` | stop new compatibility-event writes; keep old-reader projection |
| `CONTEXT_OVERFLOW_ACTION` feedback | typed compaction policy port | `PreCompact`/`PostCompact` surround the domain service, not its strategy selection |
| per-turn `SESSION_STARTED/ENDED` | durable public session hooks plus internal turn boundaries | do not rewrite historical JSONL/SQLite rows |
| verify result events | `PostVerify` input plus internal outcomes | preserve the immutable built-in result and stored outcome |

Compatibility control APIs are removable only after production
`trigger_interceptor*`/`trigger_with_result*` callers reach zero, the declared
release window ends, and stored-reader fixtures still pass.

The four middleware join points are methods on one registry, not enum-like
extension kinds:

- `tool_request`: immutable N→N+1 transformation before validation, policy,
  and approval;
- `tool_execution`: async onion around the accepted exactly-once executor only;
- `llm_request`: immutable N→N+1 transformation of the assembled adapter
  request while preserving prompt-cache invariants;
- `llm_execution`: async onion around the actual provider call.

The LLM join points deliberately cover the runtime's
`AdapterCallRequest` → `LLMAdapter.acomplete` completion contract. Optional
adapter capabilities such as text completion and web search, provider SDK calls
owned inside tool handlers such as computer grounding and document ingestion,
and plugin-owned evaluator backends are not silently folded into the same
request type. Their outer tool call still passes `tool_execution`; a future
typed seam requires its own measured consumer instead of overloading
`llm_request`.

Every parallel, sequential, MCP, recovered, deferred, and subagent tool path,
and every declared adapter-completion and retry path, uses its corresponding
terminal. Execution middleware cannot wrap or weaken hard policy and approval.
It receives the effective accepted payload, may call its `next_call` at most
once, and preserves downstream exception identity. Original and effective
payload hashes plus extension provenance are observable without persisting
secrets or unrestricted content.

Verification and stopping are three checkpoints in one internal finalization
state machine, not three competing dispatch pipelines. `PreVerify` can add
requirements, the built-in verifier creates one immutable `VerifyResult`,
`PostVerify` can accept, strengthen to revision, or escalate but cannot turn a
failure into a pass, and `Stop` controls only final delivery versus bounded
continuation. Continuation appends a correlated follow-up; it never rewinds or
replays a successful side effect. Attempt and idempotency budgets close the
loop.

Acceptance:

- generated schema and round-trip fixtures pin exactly 13 public names and
  prove that adding an internal RuntimeEvent does not change the public ABI;
- all public payloads are bounded and redacted, unknown names are rejected,
  handler authority is type-specific, and compatibility fixtures cover the
  previous `HookSystem` facade during its declared migration window without
  ever reassigning `HookEvent` to public semantics;
- production callers of `trigger_interceptor*` and `trigger_with_result*`
  reach zero before those control APIs are removed, while stored-value and
  historical-row fixtures remain readable;
- request transforms prove N→N+1 order, immutable original input, invalid
  output rejection, and original/effective trace correlation;
- execution chains prove onion order, single-use async `next_call`,
  short-circuit semantics, cancellation, timeout/failure policy, exception
  identity, and exactly one accepted terminal call across every declared tool
  and `AdapterCallRequest`-based completion path;
- tool tests prove transformed final arguments are revalidated and approved,
  hard denial cannot be weakened, blocked calls never emit execution-start,
  and start/end/error outcomes have exact cardinality;
- LLM tests prove request replacement reaches the adapter, retry correlation is
  stable, and system prompt/history/tool cache prefixes cannot change without
  an explicit capability and invalidation trace;
- lifecycle fixtures distinguish durable session generation from turn and
  step, pair runtime-owned compaction boundaries honestly, and characterize
  the current bounded SQLite hook-event sink plus conditional JSONL projections
  without relying on the future R6.2 storage-ownership contract;
- finalization fixtures prove monotone verify composition, built-in
  fail-to-pass rejection, bounded revise and Stop continuation, no side-effect
  replay, timeout fallback, external evidence correlation, and final
  persistence/delivery ordering.

#### R6.5 Durable child collaboration control

GAPs: COLLAB-001, COLLAB-002, COLLAB-003.

This package separates foreground `delegate_task` from durable collaboration
without creating a general-purpose thread subsystem. `spawn_agent` returns a
stable child handle; explicit list, bounded-wait, interrupt, message, and
follow-up tools each own one schema and effect. Children remain depth one,
retain the session cap and global Lane limit, and cannot control siblings or
create descendants.

Mutable run status and bounded mailbox delivery use additive tables in the
existing `sessions.db`. They are control projections, not replay history. The
child's checkpoint, messages, hook/runtime events, and projected trajectory
remain its independent rollout. A resumed child increments a generation and
restores that same checkpoint; the runtime does not replay a successful call,
but a model may issue it again, so this is not an exactly-once side-effect
contract. A daemon restart may mark an uncertain in-flight process
interrupted, but does not automatically restart it.

Acceptance:

- foreground `delegate_task` behavior remains compatible, while `spawn_agent`
  returns before child completion and exposes one stable child handle;
- list, bounded wait, and interrupt are scoped to the owning parent, preserve
  terminal status, and emit exactly one terminal transition per generation;
- messages and completion notices are bounded, redacted, ordered, durable
  across parent inactivity and daemon restart, and acknowledged only after
  checkpoint admission;
- a running child consumes mailbox input only at an agent-loop boundary;
  follow-up/resume on a terminal or interrupted child restores the same child
  checkpoint as a new generation without runtime replay of completed calls;
- depth, per-session task cap, Lane concurrency, approval/policy, hooks,
  checkpoint, session-event, and trajectory contracts remain executable in
  foreground, background, interrupted, resumed, failed, and timed-out tests;
- architecture and migration documentation distinguish mutable collaboration
  control state from the independent append-only child rollout, and document
  the deliberate absence of nesting, a residency cache, and automatic crash
  restart.

#### R6.6 PostVerify delivery control

GAP: HOOK-003.

The public hook ABI and finalization ordering delivered by R6.4 remain fixed.
This package makes the already-wired `PostVerify` seam effective when no
external policy is installed and makes its decisions reconstructable without
inventing another extension surface.

The built-in fallback is monotone: a passing verifier result is accepted, a
retryable failure requests one bounded revision, and a non-retryable failure
enters the existing external-verification checkpoint. An external decision may
strengthen those outcomes but may not turn a built-in failure into a pass.
`Stop` remains the last delivery checkpoint and the existing two-attempt budget
remains the loop bound.

Revision authority is a one-shot dynamic system hint. It is never appended to
provider history with role `user`, while the semantic timeline still records
the correlated root turn, attempt, source, and instruction. Verification
decisions retain bounded handler attribution, action, reason, evidence refs,
and the candidate SHA-256 digest. Trajectory projection may later map that
digest to a transition ID; the runtime does not emit a dangling future ID.

Acceptance:

- production census still exposes exactly 13 public hooks and adds no public
  hook or middleware kind;
- with no `PostVerify` handler, pass delivers once, retryable failure revises,
  and non-retryable failure enters pending external verification;
- invalid failure-plus-accept escalates, external revise/Stop continuation
  preserves priority, and the third continuation fails closed at the existing
  budget without replaying a completed tool side effect;
- revision text is absent from user-role provider history and present once in
  the bounded dynamic system context used by the next provider request;
- a retryable failure consumes the existing reflection signal and reaches the
  `verify_fail` replan path before the next provider call;
- the semantic session timeline preserves one bounded decision record per
  handler plus the fallback source, rooted by session, root turn, attempt, and
  candidate digest; raw candidate content is not duplicated;
- current PostVerify timeout/error observability remains compatible and
  optional handler failure remains fail-open; a required-handler policy is
  deferred until a measured SIL/Crucible consumer needs mixed authority.

#### R6.7 Runtime memory authority cleanup

GAP: MEM-001.

This package removes three measured residual authority conflicts without
changing the delivered session, trajectory, hook, or storage schemas. Existing
user files are compatibility inputs, not cleanup targets.

Acceptance:

- user and learning prompt blocks read the same wired `FileBasedUserProfile`,
  including its project overlay, and `system_prompt.py` constructs no default
  profile;
- `TURN_COMPLETED` no longer registers `turn_auto_memory`; explicit project
  memory tools continue to work and canonical session/tool events remain
  unchanged;
- caller-free `SessionStorePort` checkpoint methods and their in-memory
  implementation are removed; the independent `SessionCheckpoint` resume path
  remains intact;
- caller-free `ProjectJournal` cost, error, learned-write, and cost-aggregate
  methods are removed, while its currently referenced learned reader and all
  historical `costs.jsonl`, `errors.jsonl`, and `learned.md` files are left
  untouched;
- runtime documentation distinguishes the live system-prompt path from the
  opt-in `GeodeRuntime.assemble_context()` facade and makes no claim that every
  model request traverses `ContextAssembler`;
- targeted memory, prompt, wiring, session, hook, and context tests pass with
  the architecture, legacy, slop, format, type, import, and non-live test
  gates.

#### R6.8 Hosted Goal continuation

GAP: GOAL-001.

An explicit active Goal already supplies the long-horizon objective, budget,
and mutable control projection. This package adds only the missing execution
owner: while `geode serve` is alive and ordinary foreground work is idle, it
may restore the Goal's checkpoint and start the same internal continuation used
inside `AgenticLoop.arun()`.

The search object remains one sequential Goal trajectory. Stanford Part 5's
LATS action-tree search, SPRINT parallel candidate plans, and SWiRL training
pipeline remain non-goals because GEODE does not clone state, rank alternative
paths, or update a policy in this runtime path.

Acceptance:

- daemon start and later idle ticks discover active Goals from the existing
  project `sessions.db`; inactive, budget-limited, blocked, or complete Goals
  never launch;
- continuation restores the same `SessionCheckpoint` as a new session
  generation, preserves its model and conversation, and enters the request as
  bounded internal Goal context rather than `message.user`;
- one process admits at most one continuation for a session, launches no Goal
  while foreground Lane work is active, and does not retry the same unchanged
  active state indefinitely;
- the existing Goal token/time accounting, PostVerify revision, verify-fail
  replan, hook/middleware, session-event, trajectory, and checkpoint writers
  remain on the live path without a second transcript or result store;
- daemon restart recovery, duplicate-admission, no-progress, terminal Goal,
  missing/corrupt checkpoint, and foreground compatibility tests pass;
- documentation states that hosted continuation requires `geode serve`, does
  not promise exactly-once external side effects, and is not an automatic
  Plan-and-Execute or trajectory-search engine.

### R7 — Closure, hardening, and release

#### R7.1 Architecture CI

GAP: VER-001.

Uses: the GOV-004 exception ledger and ratchet closed by R0.3.

Add executable gates for:

- generated architecture baseline drift;
- zero kernel → bundled/extension reverse imports;
- core-only installed distribution;
- import-linter contract with no ignored edges;
- tool registration/schema/execution/policy parity;
- registry collision and immutable-generation behavior;
- forbidden service-locator `ContextVar` use;
- coordinator structural budgets;
- public protocol compatibility;
- roadmap structure, evidence, and legal-transition validation;
- documentation links and generated site stats.

#### R7.2 Extension scenario suite

GAPs: VER-002, CAP-006.

Run the scenarios in §8 as black-box fixtures. A scenario fails if it requires
a forbidden central edit, even when unit tests pass.

#### R7.3 Performance and behavior closure

GAP: VER-004.

Compare pre/post baselines for:

- import/cold-start time;
- runtime creation and shutdown;
- first-turn latency excluding provider network time;
- tool-plan build/refresh;
- tool dispatch overhead;
- MCP first call and warm call;
- session/event persistence;
- memory and descriptor/registry size.

Characterization suites pin termination, retry, approval, Google consent,
storage, and protocol behavior. Regressions require an explicit accepted
tradeoff, not an averaged-away benchmark.

#### R7.4 Full-program documentation and release closure

Uses: VER-003, which closes in R0.2. This release step promotes every remaining
`IN_DEVELOP` closure package atomically only after that whole package and its
per-GAP evidence are complete; it is not a second GAP selection.

A separately registered intermediate release checkpoint such as R1.7 may
promote its dependency-closed slice without marking unrelated `OPEN` work
complete. It must carry the complete canonical roadmap, satisfy its own release
acceptance, and preserve all unresolved rows and their status. This exception
does not weaken the final full-program closure below.

- Update `AGENTS.md`, `CLAUDE.md`, internal architecture docs, public docs,
  landing claims, `README.md`, generated SOT, and release notes from executable
  facts.
- Remove compatibility shims whose window has ended.
- Run the full non-live quality gates.
- Complete independent second-opinion review.
- For the full-program closure, merge `develop` to `main` only after the master
  ledger has no unexplained `OPEN`, `READY`, `IN_PROGRESS`, or `BLOCKED` row.

### R8 — Post-checkpoint compatibility lifecycle

Active R8 packages describe the v1.0.23 compatibility lifecycle; they do not
imply a dependency on every R7 package. Readiness comes only from the explicit
§5 edges, so this lifecycle can progress alongside unrelated R2-R7 work. R8.2
precedes R8.4 because tracked state must leave the facade directory in its own
transaction before the forwarding package can disappear cleanly.

#### R8.0 Publication grace evidence

GAP: REL-002.

Superseded by REL-004/R8.3 because v1.0.1 shipped before the compatibility
facade existed. The original criteria remain as immutable decision history.

Protect the compatibility window with release evidence rather than branch
intent:

- start the 30-day clock at the later of the confirmed v1.0.1 GitHub Release
  publication timestamp and PyPI file availability timestamp;
- verify that the published wheel exposes the documented
  `core.self_improving.*` facade, legacy module/path launchers, and preserved
  state roots named by R1.5;
- inspect every public GEODE release inside the candidate interval; if one
  omits or breaks those surfaces, invalidate that interval and start a new
  candidate clock at the later official GitHub/PyPI publication timestamp of
  the corrective release that restores them;
- count only releases inside the final qualifying continuous interval when
  deciding whether REL-002's exit condition is satisfied;
- record immutable official URLs, timestamps, artifact hashes, and installed
  smoke results as closure evidence.

R8.0 is evidence-only. Ordinary readiness may be reconciled after REL-001 is
`DONE`, but it cannot become `IN_DEVELOP` or `DONE` from a local build, branch
timestamp, tag, draft release, planned date, or elapsed time since merge. No
facade-retirement or state-location package may treat REL-002 as satisfied
before the complete publication interval is verified.

#### R8.3 Publication grace evidence

GAP: REL-004.

Protect the v1.0.23 compatibility window with official release evidence:

- start the 30-day clock at the later confirmed GitHub Release publication and
  PyPI file-availability timestamp;
- verify the published wheel exposes the documented facade, legacy launchers,
  and preserved roots named by R1.5;
- inspect every release inside the candidate interval and restart the interval
  after any omission or breakage is repaired;
- record official URLs, timestamps, artifact hashes, and installed smoke
  results before closure.

R8.3 is evidence-only. It cannot reach `IN_DEVELOP` or `DONE` from repository
time, a local build, tag, or draft release.

#### R8.1 Self-improving facade retirement

GAP: BND-007.

Superseded by BND-008/R8.4 because its immutable exit condition names the
superseded REL-002 publication gate. The original criteria remain as decision
history.

Retire the compatibility surface as a narrow removal transaction after R8.0:

- census imports, module invocations, source-checkout launchers, tests, docs,
  site examples, and release guidance that reference `core.self_improving`;
- classify each hit as canonical product use, supported compatibility use,
  historical v1.0.0 evidence, or stale internal use, and publish an exact
  old-to-new import/command map;
- verify that v1.0.1 release notes and public migration guidance exposed the
  canonical replacements throughout the qualifying R8.0 interval;
- remove only the `core/self_improving` forwarding files, legacy
  `python -m core.self_improving.*` entry points, and source-checkout path
  launchers; retain historical tagged documentation unchanged;
- remove the R1.5 AST facade allowlist rather than broadening it or replacing
  the facade with dynamic import indirection.

Acceptance:

- the retirement lands in a public release after REL-002 is `DONE`, never in
  v1.0.1 or an artifact inside its qualifying compatibility interval;
- repository source and active docs contain no unclassified old import or
  launcher, while frozen v1.0.0 evidence remains truthful;
- clean installed-wheel probes prove old imports/launchers are deliberately
  absent and canonical imports plus CLI, MCP, scheduler, prompt/provider,
  configuration, and state behavior still pass;
- canonical object identity, writer ownership, and the state locations finalized
  by R8.2 are unchanged; the R8.1 retirement transaction performs no
  durable-state migration.

#### R8.2 Self-improving state ownership

GAP: STORE-003.

Introduce a machine-readable state manifest owned by the canonical bundled
feature. Each logical dataset record declares at least:

| Field | Required meaning |
|---|---|
| `dataset_id` | Stable logical identity independent of a filesystem path |
| `lifecycle` | `tracked_sot`, `user_runtime`, `operator_override`, or `worker_ephemeral` |
| `format` / `schema_version` | JSON, JSONL, TSV, text, directory, or lock format and compatible reader version |
| `root_resolver` / `relative_path` | Named path resolver plus relative location; no consumer literal reconstruction |
| `source_of_truth` | Canonical state versus rebuildable projection, cache, pointer, or archive |
| `writer` / `readers` | Exactly one canonical writer and the bounded reader set |
| `atomicity` / `concurrency` | Atomic replace, append/lock discipline, conflict behavior, and worker isolation |
| `retention` / `redaction` | Lifetime, sensitivity, permissions, and prohibited payloads |
| `migration` / `rollback` / `rebuild` | Version marker, cutover/fallback rule, rollback source, and deterministic rebuild procedure |

The inventory includes tracked policies, mutations, baseline archive/epochs,
results and seed pools; runtime baseline/logs/handoff/campaign/seed-generation
artifacts; operator-local policies, sessions, transcripts, and auto-trigger
lock/timestamp/history; the `GEODE_STATE_ROOT/autoresearch` worker layout; and
the sibling per-worker `transcript.jsonl` selected through
`GEODE_RUN_TRANSCRIPT_PATH` directly under the raw worker root. It resolves the
current mismatch where `GLOBAL_AUTORESEARCH_HANDOFF_DIR` is described as legacy
while active writers still use it.

Migration order:

1. Freeze fixtures for every JSON/JSONL/TSV schema, path resolver, file mode,
   append/atomicity rule, and isolated-worker layout.
2. Move the tracked SoT with git history into the canonical product package
   selected by R1.1; preserve byte hashes and update all code, scripts, hub
   builders, package data, tests, and active docs from the manifest.
3. Keep `~/.geode/self-improving/`,
   `~/.geode/autoresearch/handoff/`, and
   `GEODE_STATE_ROOT/autoresearch` readable at their existing semantics unless
   an individual manifest record declares a versioned cutover.
4. For a runtime cutover, copy additively, validate schema and content hashes,
   switch exactly one canonical writer, then read new-first with an old-root
   fallback. Never dual-write, overwrite a conflict, or delete the rollback
   source in this package.

Acceptance:

- tracked SoT has one canonical location outside `core`, one writer per
  dataset, preserved git provenance/bytes, and installed-wheel package-data
  tests; `core/self_improving/state` no longer creates a data-only namespace;
- mutable JSON uses atomic replace, append-only JSONL/TSV preserves ordering
  and schemas, lock/timestamp/history records retain cross-process behavior,
  and user-private data retains restrictive permissions and redaction;
- migration is lossless and idempotent under empty, legacy-only, both-present,
  partial-copy, corrupt-row, interrupted-cutover, rollback, and concurrent
  worker fixtures;
- config keys, logical dataset IDs, runtime behavior, hub/eval outputs, and
  `GEODE_HOME`/`GEODE_STATE_ROOT` overrides remain compatible;
- no active runtime or operator root is deleted without another registered,
  versioned retirement GAP after its fallback window.

#### R8.4 Self-improving facade retirement

GAP: BND-008.

After R8.3 and R8.2, retire only the compatibility surface:

- census and classify every old import, module invocation, source launcher,
  test, active doc, and release-guide reference;
- publish the exact canonical replacement map and verify v1.0.23 exposed it
  throughout the qualifying R8.3 interval;
- remove only forwarding files and legacy launchers, then remove the narrow
  facade allowlist instead of adding dynamic import indirection.

Acceptance:

- retirement lands only after REL-004 and STORE-003 are `DONE`, never inside
  the qualifying v1.0.23 compatibility interval;
- frozen earlier-release evidence remains unchanged while active source and
  docs contain no unclassified legacy path;
- installed-wheel probes prove deliberate old-surface absence and unchanged
  canonical CLI, MCP, scheduler, prompt/provider, config, and state behavior;
- canonical object identity, writer ownership, and R8.2 state locations remain
  unchanged; this package performs no state migration.

### R9 — Coding-agent runtime authority

R9 starts from the source-pinned
[Codex runtime evolution research](../research/2026-08-15-codex-runtime-evolution-geode-modernization.md),
but turns none of its prospective runtime modules into implementation scope.
Its first package freezes authority and overlap boundaries before any residual
coding-runtime package can be registered.

#### R9.1 Coding-agent runtime authority contract

GAP: CODE-001.

This package adds no second Goal, session, collaboration, approval, timeline,
task, or promotion source of truth. It authorizes no runtime implementation.

Acceptance:

- a source-and-test census identifies the current writer, readers, lifecycle,
  persistence, and recovery owner for coding task, session/turn, workspace,
  process, mutation/diff, review, instructions/context, and cross-domain task
  lookup;
- one authority matrix names durability, recovery, migration, compatibility,
  redaction, failure, and rollback rules while preserving messages/checkpoints
  as recovery authority, `SessionTimeline` as append-only history, and Goal,
  scheduler, collaboration, and evaluation/promotion as their domain sources
  of truth unless a later registered migration says otherwise;
- every overlap with LOOP, PROTO, CAP, TRUST, HOOK, STORE, COLLAB, GOAL, and
  memory contracts receives a `reuse`, `extend after dependency`, or
  `separate measured GAP` disposition; no generic thread manager, universal
  task ledger, second transcript, policy framework, or review hook is added;
- every deferred candidate names its registration trigger: a current consumer
  or failure, exact affected source path, measurable exit, and independently
  mergeable boundary;
- crash, race, partial-mutation, drift, redaction, and rollback failure modes
  map to observable acceptance tests, and the roadmap validator plus document
  link checks pass without any runtime-code change.

## 8. Change-surface acceptance scenarios

These black-box scenarios define extensibility more usefully than class count.

| Scenario | Allowed product changes | Forbidden central changes |
|---|---|---|
| Add a project Skill | Skill directory and tests/docs | Kernel registry, CLI dispatcher, provider adapter |
| Add a filesystem hook | Hook manifest/handler and tests | Agent loop branch, public protocol enum unless a new public event is intended |
| Add an MCP server | User/project config or extension package | Native tool registry and CLI handler list |
| Add a third-party LLM adapter | External package entry point, adapter, tests | GEODE provider enum/switch, built-in registry source |
| Add a native tool | Tool implementation, one registration, tests/docs | Independent edits to CLI handler, safety, personal-data, provider-schema, defer lists |
| Add a Google Workspace service | Service descriptor, client/tool adapter, tests/docs | OAuth engine, account/keyring schema, unrelated central tool-name allowlists |

The budgets count semantic edit sites, not generated files. Generated
`definitions.json` or public reference pages may change if the generator owns
them.

## 9. Verification contract

Every functional PR runs targeted tests first. Phase-closing PRs run:

```bash
uv run ruff check core/ tests/ plugins/ scripts/
uv run ruff format --check core/ tests/ plugins/ scripts/
uv run mypy core/ plugins/
uv run lint-imports
uv run python scripts/check_architecture_exceptions.py \
  --check \
  --base-ref <target-base>
uv run pytest tests/ -m "not live"
uv run geode version
git diff --check
```

As new architecture gates land, their exact commands are added here and to CI.
No report may imply that an unrun gate passed. Live provider tests remain
excluded unless the user explicitly approves cost/network use.

After R0.2, every roadmap-only PR also runs:

```bash
uv run python scripts/check_architecture_roadmap.py \
  --check \
  --base-ref <target-base> \
  --target-branch <develop-or-main> \
  --event-mode pull_request
```

Use `origin/develop` for readiness, claim, registration, reconciliation, and
full-ledger audit PRs; use `origin/main` for a main-closure tracking PR.
The required `main` → `develop` resynchronization uses `origin/develop` as its
ordinary transition base and `origin/main` as a same-repository trusted parent.
Only exact `DONE` states and §10.2 rows already validated on that main parent
receive trust; develop-side ledger progress is still checked against develop,
and a fork branch merely named `main` receives no such authority.
A same-repository `develop` → `main` promotion passes
`--trusted-develop-ref origin/develop`; the complete current roadmap,
including frontmatter and protocol prose, must equal that trusted parent
exactly and must preserve all earlier main `DONE` states and append-only
evidence. Main closure status and §10.2 rows are then recorded in a separate
tracking-only main transaction. That tracking transaction may change only
`IN_DEVELOP` status cells and append matching §10.2 rows; every other source
byte is immutable.

A phase may be reported closed only after its implementation PR and required
follow-up evidence collectively provide:

- committed-diff second-opinion review;
- a merged post-implementation roadmap reconciliation PR/commit that records
  the whole closure package's `IN_DEVELOP` status and implementation evidence
  without making the implementation PR predict its own merge;
- migration rollback rehearsal when durable state changed;
- installed-wheel smoke test when packaging/imports changed;
- public docs build when user-facing behavior or metrics changed.

## 10. Delivery and closure evidence

Evidence rows are append-only transition events, not prospective placeholders.
The validator requires canonical repository PR links
(`[#{number}](https://github.com/mangowhoiscloud/geode/pull/{number})`), full
40-character commit SHAs where a commit is required, ISO-8601 UTC active-claim
timestamps, and an explicit passed/verified/re-audited result in verification
columns. A required row must be appended in the same diff as its matching
status or dependency transition; an older or pre-seeded row cannot satisfy a
later transition. Every newly appended evidence row must include the exact
verification command in inline code and the literal result marker
`RESULT: PASS`; negative language such as `failed` or `not passed` invalidates
the result even if a positive keyword also appears. Format checks operate on
comment-stripped, HTML-entity-decoded content: a PR, SHA, command, result, or
contract hidden in an HTML comment never counts, and result suffixes such as
`PASS=false` or `PASS/FAIL` are invalid.

### 10.1 Develop transition evidence

Append one package row whenever a claimed closure package reaches
`IN_DEVELOP`. The feature PR and exact develop merge commit are required. This
row is written in the same reconciliation that removes the active claim, so
pre-release delivery evidence survives after the claim row is gone.

| Closure package | GAP IDs | Feature PR | Develop merge commit | Verification / handoff evidence |
|---|---|---|---|---|
| R0.1 | GOV-001, GOV-003 | [#2767](https://github.com/mangowhoiscloud/geode/pull/2767) | `ab1a80e91f9947defc15fa97f5b4ce66126c0c13` | CI Gate, lint/format, security, tests, type check, and macOS/Ubuntu install smoke passed; committed-diff re-review returned no findings |
| R0.2 | GOV-002, VER-003 | [#2775](https://github.com/mangowhoiscloud/geode/pull/2775) | `7e3d2b2595306f8fbad44b961d53a2fc1d4f9180` | `uv run python scripts/architecture_baseline.py --check`; `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (CI Gate, full non-live tests, type check, lint/format, security, Pages build, and macOS/Ubuntu install smoke all green; committed-diff review found no findings) |
| R0.3 | GOV-004 | [#2788](https://github.com/mangowhoiscloud/geode/pull/2788) | `15a9d674be790303f2034c89c7631d5c93978aee` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (CI Gate, 10,178 standard tests, type check, lint/format, security, Pages build, macOS/Ubuntu install smoke, and committed-diff review all passed) |
| R6.4 | HOOK-001, HOOK-002 | [#2836](https://github.com/mangowhoiscloud/geode/pull/2836) | `95a474789645d4f3af5487f082cedf3eb60e66a4` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (CI Gate, 10,345 non-live tests, type check, lint/format, security, Pages build, macOS/Ubuntu install smoke, two GPT subscription E2E passes, and the committed consumer handoff all passed) |
| R6.2 | STORE-001, STORE-002 | [#2850](https://github.com/mangowhoiscloud/geode/pull/2850) | `dc8b9175525db50ff23d8460e4c89316b16767cf` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full non-live tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, GPT subscription hook/middleware E2E, privacy-gated trajectory publication, independent remote read-back, and committed cross-review all passed) |
| R6.6 | HOOK-003 | [#2892](https://github.com/mangowhoiscloud/geode/pull/2892) | `308fd12f2779a1abb73d08ef619be98368fec129` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,424 non-live tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, generated-doc parity, and candidate-digest-bound decision persistence all passed) |
| R6.5 | COLLAB-001, COLLAB-002, COLLAB-003 | [#2886](https://github.com/mangowhoiscloud/geode/pull/2886) | `4bf93d6415504495e54628ee5efaa88c9b828b3e` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,433 non-live tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, durable mailbox/checkpoint/follow-up tests, and existing GPT subscription collaboration and hook E2E evidence all passed) |
| R6.7 | MEM-001 | [#2903](https://github.com/mangowhoiscloud/geode/pull/2903) | `a7a59b69f18589bec82eb515b482355924ac9467` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,407 non-live tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, independent GPT-5.6-Luna max review with its sole P2 fixed, 13-of-13 public-hook subscription E2E, and immutable eval-artifact [#15](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/15) with manifest `aba8839af72cd4d96e7e22979affac98e04cbe027fff41e3b67732e75720103d` all passed) |
| R6.8 | GOAL-001 | [#2931](https://github.com/mangowhoiscloud/geode/pull/2931) | `543994952dddd068695d5717e02263322aaafd38` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,377 non-live tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, deterministic hosted-restart/Lane/terminal-race coverage, GPT-5.6-sol committed-diff review with all seven findings resolved, and immutable eval-artifact [#16](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/16) all passed) |
| R1.1 | BND-001 | [#3001](https://github.com/mangowhoiscloud/geode/pull/3001) | `1e62473d5a391a750068fbb8de20e303c168ce60` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full tests, lint/format, type check, security, Pages build, official-doc parity, macOS/Ubuntu install smoke, and independent committed-diff review all passed) |
| R1.4 | BND-005 | [#3004](https://github.com/mangowhoiscloud/geode/pull/3004) | `e20584650809d8b4f2480d45fe01359aa95a28f2` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, import-linter 5/5, slop ratchet 83/83, and independent committed-diff review all passed; policy paths and RunTimeline storage remain product-owned, no durable state migrated, and thin compatibility facades preserve historical readers) |
| R1.2 | BND-002 | [#3022](https://github.com/mangowhoiscloud/geode/pull/3022) | `200a11efd421cf84efdbb0c107a2caa79e8378bf` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,524 non-live tests, 79.98% combined kernel/product coverage, lint/format, type check, security, Pages build, official-doc parity, macOS/Ubuntu install smoke, isolated wheel/resource checks, zero kernel-to-product imports, and exhaustive curated-facade identity tests all passed) |
| R1.5 | BND-006 | [#3025](https://github.com/mangowhoiscloud/geode/pull/3025) | `34bce3677dee545b057d9c60a6cde56bd914cd14` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full non-live tests, lint/format, type check, security, Pages build, official-doc parity, macOS/Ubuntu install smoke, isolated wheel/resource checks, exact five-facade census, zero classified-kernel product imports, and committed-diff review all passed) |
| R1.3 | BND-003 | [#3028](https://github.com/mangowhoiscloud/geode/pull/3028) | `6f1581c9bc64ff22e3e3cf7f05ea45c01179ebba` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full non-live tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, an ephemeral core-only wheel projection, exhaustive isolated import of 393 installed kernel modules, zero-extension registry and lifecycle checks, 42 installed-kernel unit tests, and committed-diff review all passed) |
| R1.7 | REL-003 | [#3033](https://github.com/mangowhoiscloud/geode/pull/3033) | `70a1f1bcd0520b33e50436cc340265b6534bc133` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full non-live tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, committed-lock validation, clean-wheel daemon IPC v1.0.23, 393 isolated kernel imports plus 42 installed-kernel tests, public-metadata parity, and independent committed-diff review all passed) |
| R2.1 | CAP-001, CAP-002 | [#3043](https://github.com/mangowhoiscloud/geode/pull/3043) | `ba7eea3288bd443a52181151de13032f5280d263` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full non-live tests with coverage, lint/format, type check, security, Pages build, official-doc parity, macOS/Ubuntu install smoke, wheel/sdist inspection, clean installed-package smoke, and independent staged-diff review all passed; the product daemon now retains a generation/hash-bound immutable ToolPlan beside the compatibility handler map, while live consumer convergence remains required before R2.1 can reach DONE) |
| R2.2 | CAP-004 | [#3047](https://github.com/mangowhoiscloud/geode/pull/3047) | `9038d635d0ed3989b11569de5dbfd6cb7a47db43` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full non-live tests with coverage, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, wheel/sdist and isolated installed-package checks, exact descriptor-consumer parity, and independent staged-diff review all passed; `definitions.json` convergence remains required in R2.3 before R2.2 can reach DONE) |
| R2.3 | CAP-003, CAP-005 | [#3053](https://github.com/mangowhoiscloud/geode/pull/3053) | `ffeb41e13d4bd9c59bc1ba286300c352800f6a03` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,431 non-live tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, wheel/sdist and clean installed-package checks, 399 isolated kernel imports plus 42 installed-kernel tests, installed daemon IPC v1.0.23, exact bound-plan schema/execution/provider/defer parity, and independent adversarial review all passed) |
| R2.4 | TRUST-003 | [#3060](https://github.com/mangowhoiscloud/geode/pull/3060) | `709ccb0d0eb31080ed3b17896d4056f784db0281` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,431 selected non-live tests, lint/format, type check, security, Pages build, official-doc parity, macOS/Ubuntu install smoke, wheel/sdist inspection, clean installed-package smoke, 396 isolated kernel imports plus 42 installed-kernel tests, plan-owned safety/redaction/resource-lock poison coverage, and independent committed-diff review all passed) |
| R3.1 | LOOP-001, LOOP-002 | [#3067](https://github.com/mangowhoiscloud/geode/pull/3067) with follow-up [#3068](https://github.com/mangowhoiscloud/geode/pull/3068) | `e6ccaf73e1ff6027e510bfc5e4e16b8679f369e4` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature and follow-up CI Gates, 10,398 non-live tests, lint/format, type check, security, Pages build, official-doc parity, macOS/Ubuntu install smoke, additive event schema v5 with public-hook v1 query compatibility, exact step/turn/model/tool/telemetry correlation coverage, and independent committed-diff review all passed; the original feature merged as `c3e309f01e939e69bd22876df7f79b41731ac733`) |
| R3.2 | LOOP-003 | [#3071](https://github.com/mangowhoiscloud/geode/pull/3071) | `a130ceb75364e128cf0e273edbff65302273bb3e` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full non-live tests, lint/format, type check, security, Pages build, official-doc parity, macOS/Ubuntu install smoke, wheel/sdist and clean installed-package checks, 397 isolated kernel imports plus 42 installed-kernel tests, ordered six-phase characterization, and two independent committed-diff reviews all passed) |
| R3.3 | LOOP-004 | [#3074](https://github.com/mangowhoiscloud/geode/pull/3074) | `8469092baddff2d0b453b03230c46ec2b7e79bac` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,411 non-live tests, lint/format, type check, security, Pages build, official-doc parity, macOS/Ubuntu install smoke, wheel/sdist and clean full/kernel installed-package checks, executable structural budgets, and independent committed-diff review all passed) |
| R3.4 | LOOP-005 | [#3079](https://github.com/mangowhoiscloud/geode/pull/3079) | `8a73c6be74f31d7611730d44321b9cdceabdaad5` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full non-live tests, lint/format, type check, security, Pages build, official-doc parity, macOS/Ubuntu install smoke, wheel/sdist and clean full/kernel installed-package checks, 393 isolated kernel imports plus 42 installed-kernel tests, executable `SubAgentManager` structural budget, and independent committed-diff review all passed) |
| R4.1 | DI-001 | [#3088](https://github.com/mangowhoiscloud/geode/pull/3088) | `90e039ceab5b510f26a7a38df1aceebad1fd35f7` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,306 non-live tests with 80.01% coverage, lint/format, type check, import contracts, architecture and official-doc gates, Pages build, wheel/sdist inspection, clean full and kernel installed-package smoke, 395 isolated kernel imports plus 42 installed-kernel tests, literal dynamic-import drift coverage, and independent committed-diff review all passed) |
| R4.2 | DI-002, DI-003 | [#3091](https://github.com/mangowhoiscloud/geode/pull/3091) | `d7f566e12ce96adabd74e6c268d53336ec12fc81` | `uv run python scripts/architecture_baseline.py --check`; `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, full non-live tests, lint/format, type check, security, import contracts, official-doc and Pages build, macOS/Ubuntu install smoke, wheel/sdist inspection, clean daemon and full/kernel installed-package checks, 394 isolated kernel imports plus 42 installed-kernel tests, zero remaining service-locator `ContextVar` bindings, and three independent committed-diff reviews with all ten findings resolved) |
| R4.3 | DI-004 | [#3094](https://github.com/mangowhoiscloud/geode/pull/3094) | `4c2c68a7535b1c1bf5705fc898d052c9d6a16105` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS (feature CI Gate, 10,317 non-live tests, 171 MCP tests, 18 direct-caller test files, lint/format, type check, security, import contracts, architecture and official-doc gates, Pages build, macOS/Ubuntu install smoke, behavior-preserving public facade coverage, and independent committed-diff review all passed) |

### 10.2 Main closure evidence

Append one row whenever a GAP reaches `DONE`. A `DONE` ledger row without a
matching main-closure evidence row is a CI error once the roadmap checker
lands. Migration/compatibility and Docs cells must contain meaningful visible
evidence; comments, markup-only content, and one-character placeholders do not
count.

| GAP ID | Feature PR / develop commit | Main commit / release | Verification evidence | Migration/compatibility | Docs |
|---|---|---|---|---|---|
| GOV-001 | [#2767](https://github.com/mangowhoiscloud/geode/pull/2767) / `ab1a80e91f9947defc15fa97f5b4ce66126c0c13` | [#2787](https://github.com/mangowhoiscloud/geode/pull/2787) / `ccfa5286de313fa484447e38cb204ecdd8d92a96` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; main CI Gate, lint/format, type check, security, tests, Pages build, and macOS/Ubuntu install smoke passed | Governance-only transaction; runtime APIs, persisted state, and user configuration remain compatible | `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, and `docs/workflow.md` route architecture work through this execution SOT |
| GOV-003 | [#2767](https://github.com/mangowhoiscloud/geode/pull/2767) / `ab1a80e91f9947defc15fa97f5b4ce66126c0c13` | [#2787](https://github.com/mangowhoiscloud/geode/pull/2787) / `ccfa5286de313fa484447e38cb204ecdd8d92a96` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; main CI Gate, lint/format, type check, security, tests, Pages build, and macOS/Ubuntu install smoke passed | Historical plans retain their evidence while visible status banners prevent them from competing with the current ledger | Overlapping architecture and dated-plan documents carry historical-status banners and canonical-roadmap links |
| GOV-002 | [#2775](https://github.com/mangowhoiscloud/geode/pull/2775) / `7e3d2b2595306f8fbad44b961d53a2fc1d4f9180` | [#2787](https://github.com/mangowhoiscloud/geode/pull/2787) / `ccfa5286de313fa484447e38cb204ecdd8d92a96` | `uv run python scripts/architecture_baseline.py --check`; `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; main CI Gate and full non-live verification passed | The committed baseline is deterministic and check-mode reproducible; duplicate tool-handler registration fails closed without changing supported handler contracts | `AGENTS.md`, `site/src/data/geode/architecture-baseline.json`, and the bilingual architecture system index consume the generated inventory |
| VER-003 | [#2775](https://github.com/mangowhoiscloud/geode/pull/2775) / `7e3d2b2595306f8fbad44b961d53a2fc1d4f9180` | [#2787](https://github.com/mangowhoiscloud/geode/pull/2787) / `ccfa5286de313fa484447e38cb204ecdd8d92a96` | `uv run python scripts/architecture_baseline.py --check`; `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; generated-document, Pages, and repository-hygiene gates passed | Source inventory and generated consumers share one checked snapshot, with base-relative transition validation preserving earlier evidence | The public architecture system index and contributor entry points render or summarize the committed generated baseline |
| GOV-004 | [#2788](https://github.com/mangowhoiscloud/geode/pull/2788) / `15a9d674be790303f2034c89c7631d5c93978aee` | [#2797](https://github.com/mangowhoiscloud/geode/pull/2797) / `5b7c82394dabe37266390a1098f04c817880501d` | `uv run python scripts/check_architecture_exceptions.py --check --base-ref origin/main`; `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; feature and promotion CI Gates, 10,178 standard delivery tests, full non-live promotion tests, lint/format, type check, security, Pages build, and macOS/Ubuntu install smoke passed | The existing 20 ignored edges across 24 contract occurrences and measured Ruff ceilings remain behavior-compatible but now fail closed on unowned or increasing debt; the control-flow refactor preserved guard priority, and no persisted state, public runtime API, or user configuration migrated | `docs/architecture/exception-debt.md` and `docs/architecture/exception-debt.toml` document the record model, ratchet, owners, expiry conditions, and removal workflow; `AGENTS.md` and the generated architecture baseline point to the executable gate |
| HOOK-001 | [#2836](https://github.com/mangowhoiscloud/geode/pull/2836) / `95a474789645d4f3af5487f082cedf3eb60e66a4` | [#2839](https://github.com/mangowhoiscloud/geode/pull/2839) / `21e813d82ebb9c5becafce178996e62545e9e73e` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; main CI Gate, 10,345 non-live feature tests, two GPT subscription E2E passes, Pages deployment, and macOS/Ubuntu install smoke passed | Existing stored event values and SQLite readers are unchanged; `HookEvent`/`HookSystem` remain aliases, and consumers can migrate one registration at a time to the bounded `HookRegistry` without rewriting history | `docs/architecture/hook-system.md`, its Korean twin, the public hook/register guides, and `docs/plans/2026-07-31-hook-middleware-handoff.md` document the versioned ABI, external-loop contract, and migration map |
| HOOK-002 | [#2836](https://github.com/mangowhoiscloud/geode/pull/2836) / `95a474789645d4f3af5487f082cedf3eb60e66a4` | [#2839](https://github.com/mangowhoiscloud/geode/pull/2839) / `21e813d82ebb9c5becafce178996e62545e9e73e` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; main CI Gate, tool/LLM request and execution parity tests, live executor correlation verification, Pages deployment, and macOS/Ubuntu install smoke passed | Middleware adds no persisted schema; an empty `MiddlewareRegistry` preserves the direct execution path, while effective tool identities are reclassified and re-approved before execution and single-use `next_call` prevents duplicate side effects | `docs/architecture/hook-system.md`, its Korean twin, the public harness hook guide, and the consumer handoff document all four join points, authority limits, SQLite/JSONL boundary, and rollback shape |
| STORE-001 | [#2850](https://github.com/mangowhoiscloud/geode/pull/2850) / `dc8b9175525db50ff23d8460e4c89316b16767cf` | [#2852](https://github.com/mangowhoiscloud/geode/pull/2852) / `686ff37257fc7dd655025049dccee7a10d6ef340` (v1.0.11) | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; feature and release CI Gates, full non-live tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, GPT subscription E2E, privacy-gated publication, and independent artifact read-back passed | The `sessions.db` schema is additive; historical JSONL remains readable, compatibility aliases keep transcript consumers working, and native receipts remain external with typed references and digests instead of acquiring a second authority | `docs/plans/2026-07-31-session-record-contract.md`, `docs/architecture/event-persistence.md`, `docs/architecture/storage-hierarchy.md`, and the public observability/publish-trajectory guides document the writer matrix, replay boundary, and migration path |
| STORE-002 | [#2850](https://github.com/mangowhoiscloud/geode/pull/2850) / `dc8b9175525db50ff23d8460e4c89316b16767cf` | [#2852](https://github.com/mangowhoiscloud/geode/pull/2852) / `686ff37257fc7dd655025049dccee7a10d6ef340` (v1.0.11) | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; runtime/session/hook persistence tests, trajectory-schema tests, official-docs build, release CI Gate, and artifact publication/read-back evidence passed | Resume state stays mutable, behavioral history stays append-only, JSONL stays a rebuildable projection, and immutable evaluation bundles keep source references and checksums without duplicating raw receipts into SQLite | `docs/plans/2026-07-31-session-record-contract.md`, `docs/architecture/observability-report.md`, `docs/eval/external-artifact-repository.md`, and the public Tau2/observability guides document lifecycle, redaction, retention, and external-loop compatibility |
| HOOK-003 | [#2892](https://github.com/mangowhoiscloud/geode/pull/2892) / `308fd12f2779a1abb73d08ef619be98368fec129` | [#2896](https://github.com/mangowhoiscloud/geode/pull/2896) / `c1743281f81bd8d3791963a7413f85954d570494` (v1.0.15) | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; feature, release, and main CI Gates, 10,424 non-live local tests, duplicate main-promotion CI test passes, lint/format, type check, security, Pages build, generated-doc parity, and macOS/Ubuntu install smoke passed | The session timeline change is additive and historical SQLite/JSONL records remain readable; external PostVerify decisions retain precedence, while the fallback only fills an empty decision set and revision context stays ephemeral without replaying completed tool side effects | `docs/architecture/hook-system.md`, its Korean twin, `docs/architecture/event-persistence.md`, the public harness hook guide, and `docs/plans/2026-08-07-runtime-memory-trajectory-convergence.md` document control authority, persistence, compatibility, and replay boundaries |
| MEM-001 | [#2903](https://github.com/mangowhoiscloud/geode/pull/2903) / `a7a59b69f18589bec82eb515b482355924ac9467` | [#2906](https://github.com/mangowhoiscloud/geode/pull/2906) / `c28d06910f8044beb96eadea241fcc31b88fc936` (v1.0.16) | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; feature, release, and main CI Gates, 10,407 non-live local tests, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, public wheel/sdist digest parity, GPT-5.6-Luna max review, 13-of-13 public-hook subscription E2E, and immutable eval-artifact read-back passed | No durable schema changed; historical profiles, session records, and journal files remain untouched, while only caller-free checkpoint and journal write/aggregate APIs and the implicit turn-memory writer were removed | `docs/architecture/context-lifecycle.md`, its Korean twin, `docs/plans/2026-08-07-runtime-memory-trajectory-convergence.md`, the public context and memory guides, and `docs/eval/external-artifact-repository.md` identify the canonical profile, session-record, and evaluation-artifact boundaries |
| GOAL-001 | [#2931](https://github.com/mangowhoiscloud/geode/pull/2931) / `543994952dddd068695d5717e02263322aaafd38` | [#2935](https://github.com/mangowhoiscloud/geode/pull/2935) / `a2615fb25814277c8abd96b0f70f26f8eec6b1fb` (v1.0.19) | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request` — RESULT: PASS; feature, release, and main CI Gates, 10,377 non-live local tests, duplicate main-promotion CI test passes, lint/format, type check, security, Pages build, macOS/Ubuntu install smoke, deterministic hosted-restart/Lane/terminal-race coverage, GPT-5.6-sol review, and immutable eval-artifact read-back passed | Goal tables and session events are additive; sessions without a Goal keep prior turn behavior, continuation restores the existing checkpoint as a new generation, and the bounded host neither synthesizes a user turn nor replays completed side effects | `docs/architecture/event-persistence.md`, `docs/architecture/session-state-machine.md`, `docs/plans/2026-08-10-stanford-part5-plan-deep-research.md`, and the public runtime research guide document Goal ownership, continuation, advisory-plan boundaries, and trajectory evidence |
| REL-003 | [#3033](https://github.com/mangowhoiscloud/geode/pull/3033) / `70a1f1bcd0520b33e50436cc340265b6534bc133` | [#3036](https://github.com/mangowhoiscloud/geode/pull/3036) / `b1949883764914ae45bdcacbe61064137a1db870` (v1.0.23) | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/main --target-branch main --event-mode pull_request`; `python3 scripts/verify_public_distribution.py --version 1.0.23 --repository mangowhoiscloud/geode --source-sha b1949883764914ae45bdcacbe61064137a1db870`; `uvx --no-cache --from geode-agent==1.0.23 geode version` — RESULT: PASS; feature, develop reconciliation, main-sync, promotion, main-push, Pages, install-smoke, and release workflow [run 32340621793](https://github.com/mangowhoiscloud/geode/actions/runs/32340621793) passed; public GitHub assets and both PyPI files have matching SHA-256 digests, the annotated tag resolves to the main commit, and the exact-version public smoke reports v1.0.23 | The exact five self-improving facades, four legacy launchers, and preserved `core/self_improving/state` roots remain in the published wheel; no persisted schema or earlier release evidence was rewritten, and the core-only projection still imports 393 installed kernel modules and runs 42 installed-kernel tests without product features | `CHANGELOG.md`, `README.md`, `README.ko.md`, `CLAUDE.md`, generated site SOT, `llms.txt`, and `llms-full.txt` consistently identify v1.0.23 and the released kernel/product boundary |

### 10.3 Non-closure decision evidence

Append one row whenever a GAP becomes `REJECTED` or `SUPERSEDED`, or when a
dependency edge is added or removed because the requirement graph changed. A
replacement is not complete merely because this row exists; downstream
`Depends on` cells must name the replacement GAPs before they can become
`READY`. Use `DEPENDENCY_REMOVED` in the Decision column for an edge-only
removal and `DEPENDENCY_ADDED` for an edge-only addition. The referenced GAP
set must be known, non-self-referential, and exactly equal to the edge delta;
supersets cannot authorize a later or unrelated edit.

| GAP ID | Decision | Replacement GAPs / changed edges | Rationale | PR / commit | Affected packages re-audited |
|---|---|---|---|---|---|
| BND-003 | DEPENDENCY_ADDED | BND-006 | The distribution gate must validate the final self-improving product layout rather than close on the pre-move package tree; this edge makes R1.3 wait for R1.5 | `cef746de5f74204260cdbfcacd517e567beda191` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |
| BND-007 | DEPENDENCY_ADDED | STORE-003 | Tracked state currently sits under the facade directory; R8.2 must move it in a separate transaction so R8.1 can retire forwarders without hiding a state move or leaving a data-only `core.self_improving` namespace | `2c14d8c982b8112d68e29dc49ce16ad8fcc95fdd` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |
| HOOK-001 | DEPENDENCY_REMOVED | PROTO-001, STORE-001, TRUST-002, LOOP-003 | Current develop already has an injected hook owner, finalization seam, bounded SQLite hook-event sink, and conditional JSONL projections; R6.4 will characterize those concrete behaviors directly rather than depending on R6.2's future storage-ownership contract, and can add its narrow public registry without exposing untrusted code in-process | [#2834](https://github.com/mangowhoiscloud/geode/pull/2834) | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |
| HOOK-002 | DEPENDENCY_REMOVED | CAP-002, LOOP-003, LLM-003 | R6.4 explicitly owns convergence of the measured primary/recovery tool terminals and main-loop/reflection/candidate/API-mutator `AdapterCallRequest` paths into its four join points; optional adapter capabilities, tool-internal provider SDK calls, and plugin evaluators remain outside this typed contract, while future ToolPlan, loop-phase, and provider-profile types need not land first | [#2834](https://github.com/mangowhoiscloud/geode/pull/2834) | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |
| STORE-001 | DEPENDENCY_REMOVED | DI-002, PROTO-001 | Current develop already owns queryable session/message/runtime/hook state in project `sessions.db`, versioned redacted activity projections, bounded JSONL run artifacts, and additive schema migration. R6.2 reconciles those measured writers, readers, resume/replay semantics, and rebuild contracts without replacing the future DI service groups or the broader IPC/gateway protocol envelope. | [#2848](https://github.com/mangowhoiscloud/geode/pull/2848) | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |
| REL-001 | SUPERSEDED | REL-003 | Official PyPI and GitHub release evidence shows v1.0.1 shipped before the boundary refactor and v1.0.22 is now the matching latest release; REL-003 preserves the checkpoint intent at the next patch version | `4ff91e55a21660108991b678db1a8ed8c5ab05a9` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |
| REL-002 | SUPERSEDED | REL-004 | A compatibility interval cannot start from v1.0.1 because that artifact predates the facade; REL-004 binds the same publication gate to the replacement checkpoint | `4ff91e55a21660108991b678db1a8ed8c5ab05a9` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |
| BND-007 | SUPERSEDED | BND-008 | BND-007's immutable exit condition names the superseded REL-002 gate; BND-008 preserves the removal-only scope behind REL-004 without rewriting the historical contract | `4ff91e55a21660108991b678db1a8ed8c5ab05a9` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |
| STORE-003 | DEPENDENCY_REMOVED | REL-002 | REL-002 was superseded because its release target predates the preserved state-root contract | `4ff91e55a21660108991b678db1a8ed8c5ab05a9` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |
| STORE-003 | DEPENDENCY_ADDED | REL-004 | REL-004 is the replacement publication window that must close before durable state relocation | `4ff91e55a21660108991b678db1a8ed8c5ab05a9` | `uv run python scripts/check_architecture_roadmap.py --check --base-ref origin/develop --target-branch develop --event-mode pull_request` — RESULT: PASS |

### 10.4 Blocker evidence

Append one package row whenever a package enters or leaves `BLOCKED`. A recovery
row must identify the resolved evidence and whether re-audit returned the
package to `OPEN` or proved every readiness condition for `READY`.

| Closure package | GAP IDs | Transition | Blocker / resolution | Evidence | Dependency and exit-criteria re-audit |
|---|---|---|---|---|---|
| _none yet_ | — | — | — | — | — |

## 11. Risk and rollback rules

| Risk | Required control |
|---|---|
| Package/ring migration breaks imports | One seam per PR, compatibility import with removal ID, installed-wheel smoke |
| Compatibility facade forks runtime identity | Old and new imports delegate to one canonical module; assert ContextVar, hook, registry, and class identity rather than copying implementations |
| Facade retirement hides another package or state move | Removal-only diff, current consumer census, old-to-new map, installed-wheel probes, and unchanged canonical object/writer/state identities |
| State relocation forks the experiment truth | Dataset manifest, byte/schema parity, git-history proof, one-writer cutover, old-root fallback, idempotent migration, and conflict/rollback fixtures |
| Compatibility window is shortened by repository-only time | Measure from the later official GitHub/PyPI publication, inspect intervening releases, and require 30 continuous days of installed facade/state compatibility |
| Release target conflicts with an existing public artifact | Re-query official registries, converge every version consumer on v1.0.23, fail closed on nonmatching existing artifacts, and preserve immutable earlier-release evidence |
| Tool metadata changes policy behavior | Plan parity plus read/write/personal-data/approval characterization tests |
| Loop extraction changes termination/retry | Golden turn fixtures and event-order assertions before moving code |
| DI hides a new service locator | Group size/cohesion gate and forbidden service `ContextVar` check |
| Adapter split changes billing or fallback | Route/call-count/backoff/usage characterization tests |
| Protocol evolution breaks old clients | Version negotiation and old-client/new-server golden fixtures |
| Storage refactor loses user data | Additive schema, idempotent migration, backup/rollback rehearsal, corruption fixtures |
| Extension override becomes supply-chain escalation | Fail-closed collision, origin display, separate trusted/capability states |
| Docs regain stale counts | Generated SOT plus check-mode CI |

## 12. Prior work disposition

These documents remain evidence but do not own current program status:

| Document | Disposition |
|---|---|
| [`domain-free-core-audit.md`](domain-free-core-audit.md) | Historical motivation; old domain/count/path facts require re-audit |
| [`agentic-loop-evolution.md`](../plans/agentic-loop-evolution.md) | Historical capability plan; many premises are obsolete |
| [`2026-05-23-llm-adapter-abstraction.md`](../plans/2026-05-23-llm-adapter-abstraction.md) | Adapter design provenance; implementation has partially landed |
| [`2026-06-20-llm-call-stack-unification.md`](../plans/2026-06-20-llm-call-stack-unification.md) | Detailed LLM retry/call-stack constraints; status rolls up to LLM-004 |
| [`2026-05-24-transcript-standardization-and-claude-resume.md`](../plans/2026-05-24-transcript-standardization-and-claude-resume.md) | Historical transcript/resume sprint and frozen status snapshot; current work rolls up to STORE-002 and LLM-004 |
| [`2026-06-19-aligned-logging-transcript-policy.md`](../plans/2026-06-19-aligned-logging-transcript-policy.md) | Historical logging/transcript/resume/replay policy; current persistence ownership and parity work rolls up to STORE-001/002 |
| [`2026-05-22-self-improving-roadmap.md`](../plans/2026-05-22-self-improving-roadmap.md) | Historical 30-item execution order; architecture-shaped residuals roll up to LOOP, DI, PROTO, and STORE GAPs |
| [`2026-05-24-hookevent-activity-schema.md`](../plans/2026-05-24-hookevent-activity-schema.md) | Historical 74-event schema plan and frozen follow-ups; current work rolls up to PROTO-001 and STORE-001/002 |
| [`2026-05-14-hermes-strengths-absorption.md`](../plans/2026-05-14-hermes-strengths-absorption.md) | Historical Hermes comparison; current code and upstream must be re-audited |
| [`2026-06-14-obs-logging-config-convergence.md`](../plans/2026-06-14-obs-logging-config-convergence.md) | Historical pre-v1.0 plan; its SoT/status language is frozen and any remaining architecture work must be registered here |
| [`2026-05-24-pr-comm-3-runtime-db-integration-audit.md`](../plans/2026-05-24-pr-comm-3-runtime-db-integration-audit.md) | Historical storage decision audit; it records alternatives but no longer represents a pending operator decision; current residuals roll up to STORE-001/002 |
| [`2026-06-14-state-sot-runtime-split.md`](../plans/2026-06-14-state-sot-runtime-split.md) | Historical path/storage migration plan; its pending table is frozen, while current residuals roll up to STORE-001/002 |
| [`2026-06-30-agentic-loop-progress-ux.md`](../plans/2026-06-30-agentic-loop-progress-ux.md) | Historical liveness/UX plan; landed behavior is code-owned and architecture residuals roll up to LOOP-003/004 and CAP-004/005 |
| [`2026-05-16-async-tool-loop-migration.md`](../plans/2026-05-16-async-tool-loop-migration.md) | Historical async-migration record; current boundary/lifetime residuals roll up to LOOP-002/003, DI-003, and PROTO-002 |
| [`2026-06-13-path-system-modernization.md`](../plans/2026-06-13-path-system-modernization.md) | Historical path-convergence sprint; current storage and service-ownership work rolls up to STORE-001/002 and DI-003 |
| [`2026-06-17-v1.0.0-release-readiness.md`](../plans/2026-06-17-v1.0.0-release-readiness.md) | Historical pre-v1.0 gate snapshot; v1.0.0 has shipped and this program's future release closure is §7 R7.4 |
| [`2026-05-17-release-packaging.md`](../plans/2026-05-17-release-packaging.md) | Historical v0.99.12 packaging plan; current distribution behavior is code/release-workflow owned and program closure is §7 R7.4 |
| [`wiring-audit-matrix.md`](wiring-audit-matrix.md) | Wiring evidence; numeric event claims are not current SOT |
| [`google-workspace-oauth.md`](google-workspace-oauth.md) | Current Google OAuth/storage/consent behavior contract; retained |
| [`storage-hierarchy.md`](storage-hierarchy.md) | Current storage placement policy; retained |
| [`event-persistence.md`](event-persistence.md) | Current HookEvent persistence policy; retained |

## 13. Frontier and pattern decisions

The target adopts ideas, not repository shapes:

| Source | Adopt | Do not copy |
|---|---|---|
| Codex | Immutable step context, tool spec/execution plan from one builder, narrow extension registry, versioned thread/protocol boundaries | Large crate taxonomy and a broad all-services session bag |
| Grok Build | Typed tool/dynamic dispatch boundary, registry-owned dispatch, enabled vs trusted distinction | Giant turn function, closed provider enum, argument-name resource-lock heuristics |
| Hermes Agent | Generation-aware tool registry, provider profile separated from transport, progressive Skills/MCP OAuth, explicit plugin discovery | Large monolithic run loop, process globals, last-writer-wins overrides without a GEODE trust decision |
| GoF | Command for tools, Strategy/Adapter for providers and service ports, Observer/Chain for hooks and policy | Calling every registry a GoF pattern or adding patterns without a change-pressure reason |

Commit-pinned primary source references used by the 2026-07-17 audit:

- Codex
  [`spec_plan.rs`](https://github.com/openai/codex/blob/315195492c80fdade38e917c18f9584efd599304/codex-rs/core/src/tools/spec_plan.rs),
  [`extension-api/registry.rs`](https://github.com/openai/codex/blob/315195492c80fdade38e917c18f9584efd599304/codex-rs/ext/extension-api/src/registry.rs),
  and
  [`state/service.rs`](https://github.com/openai/codex/blob/315195492c80fdade38e917c18f9584efd599304/codex-rs/core/src/state/service.rs).
- Grok Build
  [`xai-tool-runtime/tool.rs`](https://github.com/xai-org/grok-build/blob/8adf9013a0929e5c7f1d4e849492d2387837a28d/crates/common/xai-tool-runtime/src/tool.rs)
  and the repository at commit
  [`8adf901`](https://github.com/xai-org/grok-build/tree/8adf9013a0929e5c7f1d4e849492d2387837a28d).
- Hermes Agent
  [`tools/registry.py`](https://github.com/NousResearch/hermes-agent/blob/0f102fa4dc04b7dfdab048169aaaa640d09d7523/tools/registry.py),
  [`provider runtime guide`](https://github.com/NousResearch/hermes-agent/blob/0f102fa4dc04b7dfdab048169aaaa640d09d7523/website/docs/developer-guide/provider-runtime.md),
  and the
  [`google-workspace` Skill](https://github.com/NousResearch/hermes-agent/blob/0f102fa4dc04b7dfdab048169aaaa640d09d7523/skills/productivity/google-workspace/SKILL.md).

## 14. Immediate next unit

R1.7 (`REL-003`) is `DONE` after the v1.0.23 promotion, tracking-only main
closure [#3037](https://github.com/mangowhoiscloud/geode/pull/3037), and
CI-gated main-to-develop sync
[#3038](https://github.com/mangowhoiscloud/geode/pull/3038).

R8.3 (`REL-004`) is `IN_PROGRESS` under the active claim for
`feature/r8-3-publication-grace-evidence`. Its candidate interval starts at
PyPI file availability at `2026-08-20T06:53:01.550033Z`; no closure is eligible
before `2026-09-19T06:53:01.550033Z`, and any intervening incompatible release
restarts the interval. This evidence-only package reuses the public
distribution verifier and does not authorize runtime or schema changes.

R2.1 (`CAP-001`, `CAP-002`) is `IN_DEVELOP` after feature
[#3043](https://github.com/mangowhoiscloud/geode/pull/3043) merged as
`ba7eea3288bd443a52181151de13032f5280d263`. The delivered boundary retains
one immutable, generation/hash-bound native `ToolPlan` beside the compatibility
handler map and validates ordered schema, execution, safety, and capability
parity before product daemon sessions. R2.3 now supplies the immutable CAP-002
“every tool consumer” evidence for live `AgenticLoop`/`ToolExecutor`,
provider/deferred, and worker/MCP roots; R2.1 remains `IN_DEVELOP` until the
corresponding main closure records complete package evidence.

R2.2 (`CAP-004`) is `IN_DEVELOP` after feature
[#3047](https://github.com/mangowhoiscloud/geode/pull/3047) merged as
`9038d635d0ed3989b11569de5dbfd6cb7a47db43`. One frozen association now maps
all 14 Google and Calendar tool names to service alternatives and derives the
migrated safety, approval, profile-policy, personal-data, delegated-handler,
and direct-Google scope projections. Native Workspace registrations record
declarative OAuth capabilities while Calendar remains enabled for its Google,
MCP, and Apple alternatives. R2.3 now closes the remaining independent
`definitions.json` schema, handler-ownership, and provider/deferred projection
surfaces. Deterministic resource-key and data-policy derivation remains R2.4;
R2.2 remains `IN_DEVELOP` until main closure. The active R8.3 claim and
publication clock remain independent and unchanged.

R2.3 (`CAP-003`, `CAP-005`) is `IN_DEVELOP` after feature
[#3053](https://github.com/mangowhoiscloud/geode/pull/3053) merged as
`ffeb41e13d4bd9c59bc1ba286300c352800f6a03`. One immutable,
generation/hash-bound plan now owns handler construction,
`AgenticLoop`/`ToolExecutor`, worker/MCP, provider, and deferred projections
with exact schema/execution parity, explicit transient overlays, and bounded
diagnostics. Public product worker and daemon roots inject composition; the
direct kernel worker and uncomposed `SharedServices` construction fail closed.
R2.4 (`TRUST-003`) is `IN_DEVELOP` after feature
[#3060](https://github.com/mangowhoiscloud/geode/pull/3060) merged as
`709ccb0d0eb31080ed3b17896d4056f784db0281`. One hash-bound native plan now
owns minimum effect, data handling, approval lifetime, profile restrictions,
and deterministic resource strategies. Effective middleware and hook rewrites
cannot weaken that minimum; durable personal-data projections are redacted;
and one process-owned lock pool serializes conflicting daemon-session and MCP
mutations while preserving unrelated concurrency and sync-handler lease
lifetime through timeout or cancellation.

R3.1 (`LOOP-001`, `LOOP-002`) is `IN_DEVELOP` after feature
[#3067](https://github.com/mangowhoiscloud/geode/pull/3067) merged as
`c3e309f01e939e69bd22876df7f79b41731ac733` and corrective follow-up
[#3068](https://github.com/mangowhoiscloud/geode/pull/3068) merged as
`e6ccaf73e1ff6027e510bfc5e4e16b8679f369e4`. One immutable `StepSnapshot`
now carries the authoritative model, tool, policy, middleware, trace, and
usage identity for each step, while `TurnState` owns mutable turn
accumulation. Additive event schema v5 persists `step_id`; public-hook v1
queries and prior stored rows remain compatible.

R3.2 (`LOOP-003`) is `IN_DEVELOP` after feature
[#3071](https://github.com/mangowhoiscloud/geode/pull/3071) merged as
`a130ceb75364e128cf0e273edbff65302273bb3e`. The physical turn now calls six
ordered input, model-call, provider/retry, tool, observation/compaction, and
termination/result collaborators while preserving the existing public
`AgenticLoop.arun`, `StepSnapshot`, and `TurnState` behavior.

R3.3 (`LOOP-004`) is `IN_DEVELOP` after feature
[#3074](https://github.com/mangowhoiscloud/geode/pull/3074) merged as
`8469092baddff2d0b453b03230c46ec2b7e79bac`. Executable ratchets now hold
`agent_loop.py` at 1,113 LOC, 38 `AgenticLoop` methods, 12 direct constructor
arguments, complexity at most 30, branches at most 35, and statements at most
120; the obsolete constructor exception is removed and legacy policy keywords
still map to `AgenticLoopConfig`.

R3.4 (`LOOP-005`) is `IN_DEVELOP` after feature
[#3079](https://github.com/mangowhoiscloud/geode/pull/3079) merged as
`8a73c6be74f31d7611730d44321b9cdceabdaad5`. `SubagentProtocol` now owns
request construction, role resolution, and result validation, while
`SubagentAnnouncements` owns runtime/public hook and timeline projection.
`SubAgentManager` remains the depth-one orchestration, session-cap, durable
collaboration, and cancellation owner at 811 LOC, 17 methods, and 18
constructor arguments; the existing `IsolatedRunner`, role registry, and
candidate-sampling judge remain the single worker-launch, policy, and best-of
implementations.

R4.1 (`DI-001`) is `IN_DEVELOP` after feature
[#3088](https://github.com/mangowhoiscloud/geode/pull/3088) merged as
`90e039ceab5b510f26a7a38df1aceebad1fd35f7`. Its generated manifest first
classified 35 module/class-scoped `ContextVar`-backed bindings, including the
eleven service-locator removal inputs. R4.2 has now removed those inputs; the
current inventory contains 24 bindings limited to seven request identities,
nine request-local mutable states, seven diagnostic scopes, and one cache. CI
continues to own declaration, lifecycle, propagation, reset, teardown, and
literal dynamic-import drift checks, and rejects any new service locator.

R4.2 (`DI-002`, `DI-003`) is `IN_DEVELOP` after feature
[#3091](https://github.com/mangowhoiscloud/geode/pull/3091) merged as
`d7f566e12ce96adabd74e6c268d53336ec12fc81`. Six lifecycle-owned execution,
persistence, lifecycle, integration, authentication, and identity groups now
contain at most seven cohesive fields; runtime, daemon, worker, MCP one-shot,
tool, scheduler, hook, and adapter paths receive their owned services through
composition-root, constructor, or `ToolContext` injection. The eleven ambient
service locators are removed, lifecycle shutdown remains runtime-owned, and no
durable schema or provider/tool contract migrated.

R4.3 (`DI-004`) is `IN_DEVELOP` after feature
[#3094](https://github.com/mangowhoiscloud/geode/pull/3094) merged as
`4c2c68a7535b1c1bf5705fc898d052c9d6a16105`. `MCPServerManager` now delegates
configuration, pooled connection ownership, invocation/result guarding,
trace persistence, and lifecycle cleanup to focused collaborators while its
public facade and behavior remain compatible. No other manager, R5 adapter,
or R6 protocol responsibility moved.

R5.1 (`LLM-001`) is `IN_PROGRESS` under the active claim for
`feature/r5-1-interface-segregation` after reconciliation/readiness
[#3092](https://github.com/mangowhoiscloud/geode/pull/3092) merged as
`3f059ba467ff58cde47095ffef94730ac39fbaef`. DI-002 is `IN_DEVELOP`. The
claimed scope makes identity plus `acomplete` the required `LLMAdapter`
surface, moves streaming, model listing, environment diagnostics, quota,
credential detection, web search, computer use, and text completion behind
optional capability protocols, and removes dishonest empty stubs without
changing provider wire behavior. It authorizes no R5.2 registry/discovery,
R5.3 provider-profile/transport, or R5.4 retry/failover work. The implementation
worktree may be allocated only after this claim merges and canonical `develop`
is refreshed.

R6.1 (`PROTO-001`, `PROTO-002`) remains `READY` and unclaimed. Its public
protocol gap remains measurable but authorizes no implementation until its own
serialized claim merges.

R9.1 (`CODE-001`) was already dependency-satisfied and remains `OPEN` pending
its own serialized whole-package readiness transaction later in master order.
R6.3 remains `OPEN` behind its other package dependencies. The active R8.3
claim and publication clock remain unchanged. R8.2 (`STORE-003`) remains
`OPEN` behind REL-004 and STORE-001; R8.4 (`BND-008`) additionally waits for
STORE-003.
