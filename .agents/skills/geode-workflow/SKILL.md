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

Follow the [canonical workflow](../../../docs/workflow.md#core-loop) and its
[execution scope](../../../docs/workflow.md#execution-scope). Produce the
requested reviewable result; load only the references relevant to the task.
For abstraction, naming, type/class, schema, test, site, or version decisions,
use `$geode-code-conventions`.

## Reference Routing

Read only the reference needed for the current task:

| Need | Read |
|---|---|
| Phase-by-phase checklist for ordinary code work | `references/phase-checklist.md` |
| Abstraction, naming, type/class, schema, test, site, and version conventions | `$geode-code-conventions` (follow its task-specific SOT routing) |
| Provider/model/API capability claims | `references/provider-grounding.md` |
| Schema/log/event/state/trajectory consistency | `references/observability-contract.md` |
| Same-task Codex–GEODE production and comparison | `references/codex-geode-paired-coding.md` |
| Test, lint, type, prompt, full-suite reporting, or failure-to-rule review | `references/verification-gates.md` |
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
