# GEODE Evidence-First Development Workflow

> Canonical public summary for GEODE contributors. Claude Code should use the
> project skill at `.claude/skills/geode-workflow/SKILL.md`, which applies this
> workflow through progressive disclosure.

GEODE uses an evidence-first workflow for feature work, provider/model changes,
GUI/computer-use work, PDF/document ingestion, observability changes, and large
audits. The full procedure is split across the `geode-workflow` skill and its
`references/` files so agents load only the detail needed for the task.

`AGENTS.md` owns the shared contributor entry point. `CLAUDE.md` imports it with
`@AGENTS.md`, the [official Claude Code mechanism](https://code.claude.com/docs/en/memory#agentsmd)
for sharing project instructions. Imported content is loaded too: this avoids
drift, not context cost by itself. Keep task detail in the owners below.
Claude Code project context is separate from its system prompt and execution
permissions; GEODE's own runtime SOUL and assembly remain separate again.

## Execution scope

Treat a request to do work, including "can you" in an action context, as an
instruction to produce a reviewable result within the authorized scope.
Complete already-authorized work before asking about a missing decision;
ask only when it materially changes correctness, scope, or authority. A review
or status request remains read-only. Merge, publication, paid calls, global
installation, and service changes need authority from the request or context.

User instructions override skill guidelines within the applicable system,
permission, and safety boundaries. If a skill blocks or redirects work, cite
the exact instruction and distinguish its requirement from an interpretation.

Delegate independent, bounded work when available tools and permissions allow
it and parallel work can improve time or quality. Do not force delegation by
call count or invent unavailable tools. Report outcomes concisely; routine
monitoring reports meaningful changes, completion, failure, or needed input.

## Core Loop

1. **Scope**: confirm branch, dirty files, objective, and unrelated work.
2. **GAP audit**: search before designing; classify existing, partial, absent,
   or misfit.
3. **Grounding**: verify external provider, SDK, model, OS, browser, package,
   or current API behaviour with official docs/source.
4. **Preflight**: capture task class, affected providers, required tools,
   evidence class, and explicit non-goals.
5. **Plan**: state the smallest measurable change. Define schema, state,
   provider, or rollback contracts only when the change affects them.
6. **Implement**: use existing GEODE registries, adapters, redaction helpers,
   transcript helpers, and atomic-write utilities.
7. **Observe**: use existing evidence; extend bounded records only when the
   changed behavior would otherwise be unobservable.
8. **Verify**: run targeted checks first, then broaden when risk justifies it.
9. **Report/GitFlow**: state what changed, what ran, what failed or was
   skipped, and only claim merge/push/cleanup after commands complete.

## Contract checks

Apply these checks when the changed path uses the corresponding contract:

- Trace producer → stored field → reader → decision, including explicit-input
  and automatic-selection branches. Verify hook registration and service
  binding/reset at the actual composition owner, plus refresh/invalidation
  for mutable configuration and credentials. An implementation with no caller
  is not a working feature.
- Apply failure/validation behavior at every schema conversion, not only an
  outer handler. Keep source files and fallback literals under a shared anchor
  and drift test when both are necessary. Prefer removing the duplicate.
- Distinguish latest from promoted evidence; identify which a reader consumes.
  Validate seed dimensions against the live taxonomy at pool assembly. Verify
  native viewer routes from the shipped bundle and real artifact filenames,
  not a guessed task-ID URL.
- Put index freshness in the existing build/publish producer; verify the
  reader sees newly produced items. Do not make every read-only renderer write
  merely to compensate for a disconnected producer.
- Check Git tracking only for artifacts explicitly intended for repository
  publication. Private runtime audit/history files may be ignored or live
  outside the repo; retain redaction and privacy boundaries. Do not publish raw
  transcripts to satisfy a generic tracking rule.
- Preserve failed evidence and command exit status. PR/CHANGELOG claims must
  map to actual callers, changed behavior, or execution receipts. Do not turn
  unknown values into measured zero or a partial check into full verification.

The [verification reference](../.agents/skills/geode-workflow/references/verification-gates.md)
owns failure-to-rule review and evidence reuse; do not copy its incident ledger
into each startup prompt.

## Architecture And Extensibility Program

Architecture/extensibility changes use
[`docs/architecture/extensibility-roadmap.md`](architecture/extensibility-roadmap.md)
as their execution SOT. Before implementation, a reconciliation PR atomically
promotes every row in a dependency-satisfied package from `OPEN` to `READY`.
Select that package, re-audit it against current `origin/develop`, and merge a
roadmap-only claim PR that records `IN_PROGRESS`, its owner, and its intended
implementation branch. Only then allocate the implementation worktree. The
implementation PR references that canonical claim and does not predict its own
merge. After it merges, the roadmap's narrow, explicitly authorized
reconciliation PR atomically records `IN_DEVELOP` for the whole package; a
main-based tracking PR atomically records `DONE` plus per-GAP closure evidence
after release. That tracking worktree starts from current `origin/main`, its PR
targets `main`, and its merge is followed by a CI-gated `main -> develop` sync
PR. Detailed subsystem docs continue to own behavior contracts, but they do
not independently claim program completion or reorder the roadmap. Untracked
architecture scope discovered during implementation is registered as an
`OPEN` package in a separate roadmap-only GAP-registration PR; registration
does not claim the package or authorize expanding the implementation diff.

## Progressive Disclosure Map

| Need | Skill reference |
|---|---|
| Ordinary code-work checklist | `.claude/skills/geode-workflow/references/phase-checklist.md` |
| Abstraction, naming, type/class, schema, test, site, and version conventions | `.agents/skills/geode-code-conventions/SKILL.md` + `docs/architecture/naming-conventions.md` |
| Provider/model/API capability claims | `.claude/skills/geode-workflow/references/provider-grounding.md` |
| Schema/log/event/state/trajectory consistency | `.claude/skills/geode-workflow/references/observability-contract.md` |
| Usage/cache fields, cost authority, incomplete accounting | `docs/architecture/usage-accounting.md` |
| Same-task Codex–GEODE production and comparison | `.claude/skills/geode-workflow/references/codex-geode-paired-coding.md` |
| Evaluation question, run spec, attempt lineage, analysis, and publication | `.agents/skills/geode-eval/SKILL.md` + `docs/eval/index.json` |
| Test, lint, type, prompt, and full-suite gates | `.claude/skills/geode-workflow/references/verification-gates.md` |
| Branch, PR, merge, and cleanup operations | `.claude/skills/geode-workflow/references/gitflow.md` |

## Worktree And GitFlow

```text
feature/<name> -> develop -> main
```

- Feature branches and develop-targeted roadmap branches start from the
  fetched `origin/develop` tip.
- A roadmap tracking-only `DONE` branch starts from `origin/main`, targets
  `main`, and is followed by a CI-gated `main -> develop` sync.
- Other main-maintained tracking documents use their dedicated `origin/main`
  worktree. Read [GitFlow allocation](../.agents/skills/geode-gitflow/SKILL.md#worktree-allocation)
  and the roadmap's §0.3 for the exact tracking/program exceptions.
- Use the current `main` head directly when the sync is mergeable under strict
  up-to-date protection; do not wrap a copied or fast-forwarded main head in a
  trusted sync branch.
- When conflicts or strict ancestry block that canonical head, create
  `sync/main-into-develop-*` from current `origin/develop` and merge current
  `origin/main`. Its head must have exactly those two parents, in that order.
  Immediately before merge, fetch both refs and rerun
  `scripts/resolve_architecture_roadmap_trust.py` with `--require-trust main`.
  `scripts/merge_pr.py` enforces the same parent proof against live remote tips
  before its head-pinned merge request. If either tip moved, rebuild the sync
  head and rerun CI; an earlier green no longer proves the current graph.
- Feature PRs merge into `develop` with squash merge.
- Before `develop -> main`, sync `main -> develop` if main has drift.
- `develop -> main` is a pass-through merge after gates are satisfied.
- Merge admission is a separate check, not a side effect of local test success.
  `uv run python scripts/merge_pr.py --pr <N>` is read-only; only its explicit
  `--merge` mode may submit the head-pinned merge after rechecking the PR, base,
  current PR-linked Actions evidence and protected-branch settings. Missing,
  skipped, pending, failed, ambiguous or stale required evidence blocks it.
  Required checks on `main` and `develop` must be strict and apply to
  administrators; never bypass them.
  Repeated runs can coexist on one head (for example, Draft → Ready). The
  command scopes GitHub CLI's current required-check selection by its explicit
  `pull_request` event (excluding same-head push runs), then binds its
  exact links to REST check IDs, app/head, PR workflow/suite and rollup evidence.
  Superseded runs remain in history; an older success cannot replace a current failure.
- Post-merge cleanup runs
  `scripts/check_repo_hygiene.py free-merged-worktree` from outside the target
  checkout. It verifies the squash tree by replaying the final PR head onto the
  merge parent, plus branch ancestry, remote head, clean state, and owner before
  removing remote branch, worktree, local squash branch, then pruning.

## Minimum Verification

The [verification reference](../.agents/skills/geode-workflow/references/verification-gates.md)
owns check selection, evidence reuse, independent review, and live-test gates.
Run checks appropriate to the change, complete required checks, and report
exact commands, results, and omissions. Passing a subset is not a full CI pass.

## Paired Coding Assistance

When a task explicitly calls for independent Codex and GEODE implementations,
use the [paired coding reference](../.claude/skills/geode-workflow/references/codex-geode-paired-coding.md).
It freezes one base, brief, affected scope, and acceptance command set across
two isolated worktrees, then separates production from operator-owned
verification and human selection. Normal work remains one producer plus an
independent read-only review; paired production grants no automatic merge or
promotion authority.
