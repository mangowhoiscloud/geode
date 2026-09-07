# GEODE Evidence-First Development Workflow

> Canonical public summary for GEODE contributors. Claude Code should use the
> project skill at `.claude/skills/geode-workflow/SKILL.md`, which applies this
> workflow through progressive disclosure.

GEODE uses an evidence-first workflow for feature work, provider/model changes,
GUI/computer-use work, PDF/document ingestion, observability changes, and large
audits. The full procedure is split across the `geode-workflow` skill and its
`references/` files so agents load only the detail needed for the task.

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
- A conflict-free sync uses the current `main` head directly as the PR head;
  do not wrap it in a prefixed branch that would merely fast-forward.
- When that sync needs conflict resolution, its branch name must start with
  `sync/main-into-develop-` and its head must be the exact two-parent merge of
  the current `refs/remotes/origin/develop` and
  `refs/remotes/origin/main` tips, in that order. Immediately before merge,
  fetch both refs and rerun `scripts/resolve_architecture_roadmap_trust.py`
  with `--require-trust main`; if either tip moved, rebuild the sync head and
  rerun CI. GitHub does not bind this operator check to the merge or emit a PR
  event when unrelated `main` moves, so the maintainer must run it immediately
  before merging and treat any elapsed window as unverified.
- Feature PRs merge into `develop` with squash merge.
- Before `develop -> main`, sync `main -> develop` if main has drift.
- `develop -> main` is a pass-through merge after gates are satisfied.
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
