---
name: geode-workflow
description: GEODE evidence-first development workflow. Use for feature work, provider/model changes, GUI/computer-use work, PDF/document ingestion, observability/schema/event/state changes, verification planning, GitFlow merge prep, and requests to "follow the workflow" or "scaffold the process".
---

# GEODE Workflow

Use this skill as GEODE's default execution scaffold. It replaces the older
issue-first workflow with an evidence-first loop: inspect existing code, ground
external contracts, define the observable surface, implement narrowly, verify,
then report honestly.

## Core Loop

1. **Scope**: confirm branch, dirty files, objective, and unrelated work.
2. **GAP audit**: search before designing; classify existing, partial, absent,
   or misfit. For architecture/extensibility work, read
   `docs/architecture/extensibility-roadmap.md`, claim a `READY` work package
   on canonical `develop`, and carry its stable GAP IDs through the PR and
   reconciliation flow.
3. **Grounding**: use official docs/source for provider, SDK, model, OS,
   browser, package, or current external behaviour.
4. **Preflight**: classify task type, affected providers, required tools,
   evidence class, and out-of-scope surfaces.
5. **Design contract**: define schema, log, event, state, trajectory, provider
   split, and rollback behaviour before code.
6. **Implement**: use existing registries, adapters, redaction helpers,
   transcript helpers, and atomic-write utilities.
7. **Observe**: make runtime behaviour inspectable with bounded structured
   records.
8. **Verify**: run targeted checks first, then broaden when risk justifies
   it. Non-trivial PRs also get a Codex MCP second-opinion review of the
   committed diff before push (see `references/verification-gates.md`).
9. **Report/GitFlow**: state what changed, what ran, what failed or was
   skipped, and only claim merge/push/cleanup after commands complete.

## Reference Routing

Read only the reference needed for the current task:

| Need | Read |
|---|---|
| Phase-by-phase checklist for ordinary code work | `references/phase-checklist.md` |
| Provider/model/API capability claims | `references/provider-grounding.md` |
| Schema/log/event/state/trajectory consistency | `references/observability-contract.md` |
| Test, lint, type, prompt, and full-suite reporting gates | `references/verification-gates.md` |
| Branch, PR, merge, and cleanup operations | `references/gitflow.md` |

For simple docs or trivial bug fixes, use the core loop and skip references
that do not affect the task.

## Non-Negotiables

- Do not switch branches inside an active worktree.
- Do not revert unrelated dirty work.
- Architecture/extensibility implementation work starts only after a
  roadmap-only claim PR moves the package from `READY` to `IN_PROGRESS` on
  canonical `develop` and names its owner/implementation branch. Claim and
  reconciliation PRs establish that prerequisite; they do not require an
  earlier claim. The implementation PR preserves the claimed status and never
  predicts `IN_DEVELOP` or `DONE`.
- Register architecture scope discovered during implementation through a
  separate roadmap-only GAP-registration PR. Registration may add an `OPEN`
  package without a prior claim, but does not authorize implementing it.
- Within the architecture/extensibility program, use `origin/main` only for a
  tracking-only roadmap `DONE` worktree after release. Its PR targets `main`,
  carries no implementation code, and is followed by a CI-gated
  `main -> develop` sync.
- Do not mark unsupported provider behaviour as supported without grounding.
- Do not add ad hoc observability strings when the capability/evidence
  vocabulary should be extended.
- Do not log raw screenshots, base64 blobs, API keys, tokens, passwords, or
  secret fragments.
- Do not imply a full-suite pass if only targeted checks ran.

## Output Contract

When finishing, include:

- implementation summary
- key files changed
- verification commands and results
- known failures, skipped gates, or live-test uncertainty
- GitFlow state if any branch/PR/merge action was requested
