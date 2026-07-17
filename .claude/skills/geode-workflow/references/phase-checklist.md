# Phase Checklist

Use this when the task is more than a trivial edit.

## Phase 0: Worktree And Scope

Run:

```bash
git status --short --branch
git fetch origin
```

Capture:

- current branch and dirty files
- user objective
- likely subsystems
- unrelated dirty work to preserve
- known failing tests or environment gaps

For architecture/extensibility work, verify that canonical `origin/develop`
contains an `IN_PROGRESS` active claim for the selected package, owner, and
intended branch before allocating its implementation worktree. If the package
is only `READY`, stop production work and merge the roadmap-only claim PR
first.

If the checkout is `main` or `develop`, fetch and allocate a feature worktree
from `origin/develop` rather than switching branches in place or assuming the
local `develop` ref moved with fetch. The only exception is a roadmap
tracking-only `DONE` PR after release: allocate it from current `origin/main`,
target `main`, then sync the merge back through a CI-gated
`main -> develop` PR.

## Phase 1: GAP Audit

Search first:

```bash
rg "<capability|schema|event|tool|provider|workflow>" core tests docs plugins scripts
rg --files | rg "<domain|feature|provider>"
```

Classify each item:

| Status | Meaning | Action |
|---|---|---|
| Existing | Code, wiring, and tests already cover it | Reuse |
| Partial | Some code exists but integration, tests, docs, or observability are missing | Fill gaps |
| Absent | No reliable implementation exists | Design and implement |
| Misfit | Request conflicts with architecture or provider limits | Document constraint |

For architecture/extensibility work:

1. Read `docs/architecture/extensibility-roadmap.md`.
2. Confirm a reconciliation PR has moved the selected dependency-satisfied work
   package from `OPEN` to `READY`.
3. Confirm a separate claim PR has moved the whole package from `READY` to
   `IN_PROGRESS` on canonical `develop` and recorded this implementation
   branch and owner.
4. Name every selected GAP ID in the implementation PR without changing its
   claimed status.
5. Stop before expanding into untracked architecture scope. Register it as an
   `OPEN` package through a separate roadmap-only GAP-registration PR; then use
   the ordinary readiness and claim transitions before implementation.

## Phase 2: Preflight

Write down:

- task class: code, docs, provider, GUI, research, PDF, eval, orchestration
- affected providers/models
- required tools or fallback harnesses
- evidence that proves success
- explicit non-goals

## Phase 3: Design

Define before editing:

- schema version and payload shape
- log destination and redaction boundary
- event names plus `action`, `entity_type`, `entity_id`
- persisted state and invalidation
- trajectory steps and terminal evaluation, if GUI/computer-use applies
- native, emulated, unsupported, and live-test-required provider paths

## Phase 4: Implement

Prefer existing GEODE surfaces:

- registries and adapters
- transcript lifecycle helpers
- evidence ledger vocabulary
- redaction helpers
- atomic-write utilities
- existing provider split patterns

## Phase 5: Report

State exact verification results. Separate regressions from known environment
failures. Never claim a branch was pushed, merged, or cleaned unless the command
completed.
