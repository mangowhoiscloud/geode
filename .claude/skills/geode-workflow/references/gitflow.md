# GitFlow

Default branch flow:

```text
feature/<name> -> develop -> main
```

## Feature Worktree

For architecture/extensibility work, allocate the implementation worktree only
after a roadmap-only claim PR has moved its `READY` package to `IN_PROGRESS`
on canonical `develop` and recorded the intended branch and owner.

```bash
git fetch origin
git worktree add .claude/worktrees/<task-name> -b feature/<branch-name> origin/develop
echo "session=$(date -Iseconds) task_id=<task-name>" > .claude/worktrees/<task-name>/.owner
```

Never switch branches inside a worktree. Allocate or enter the correct
worktree. Fetching does not move a checked-out local `develop`; branch from
`origin/develop` so the new worktree contains the merged claim and all current
prerequisites. This section covers implementation and roadmap branches whose
PR target is `develop`.

## Main Closure Tracking Worktree

After a claimed package's implementation reaches `main`, create its
tracking-only closure branch from current `origin/main`:

```bash
git fetch origin
git worktree add .claude/worktrees/<task-name> \
  -b tracking/architecture-closure-<package> origin/main
```

That PR targets `main`, changes only the canonical roadmap, records
package-atomic `DONE` plus per-GAP closure evidence, and carries no
implementation code. After it merges, open and merge a CI-gated
`main -> develop` sync PR before further develop-targeted ledger work.
If it is conflict-free, use the current `main` head directly as the PR head.
If it needs conflict resolution, create it from current
`origin/develop` with a branch name starting `sync/main-into-develop-`, merge
current `origin/main` in an explicit merge commit as the exact second parent,
and rerun
`scripts/resolve_architecture_roadmap_trust.py --require-trust main`
immediately before merge.

## Merge Rules

- Feature and develop-targeted roadmap branches start from the fetched
  `origin/develop` tip.
- Within architecture-ledger work, only the tracking-only closure branch
  starts from `origin/main`; it targets `main` and is synced back to
  `develop`.
- Feature PRs merge into `develop` with squash merge.
- Before `develop -> main`, sync `main -> develop` if main has drift.
- `develop -> main` is a pass-through merge after gates are satisfied.
- No direct push to `main` or `develop`.

## Architecture Ledger

For architecture/extensibility work, the user-authorized exception applies only
to `docs/architecture/extensibility-roadmap.md`:

1. A roadmap-only reconciliation PR from current `develop` atomically moves
   every row in one audited, dependency-satisfied package from `OPEN` to
   `READY`.
2. A separate roadmap-only claim PR moves the whole selected package from
   `READY` to `IN_PROGRESS` and records its owner and intended implementation
   branch. Merge it before allocating that implementation worktree.
3. Untracked architecture scope is appended as an `OPEN` package in a separate
   roadmap-only GAP-registration PR. Registration is exempt from a prior claim
   but does not authorize implementation of the new package.
4. The implementation PR references the canonical claim, preserves
   `IN_PROGRESS`, and must not set `IN_DEVELOP` or `DONE`.
5. After the feature PR merges, a roadmap-only reconciliation PR from updated
   `develop` atomically moves the whole claimed package to `IN_DEVELOP`,
   records merge evidence, atomically promotes whole newly unlocked packages
   to `READY`, and removes the active claim.
6. After release to `main`, a tracking-only worktree from current
   `origin/main` targets `main`, atomically moves the whole package to `DONE`,
   and records per-GAP closure evidence. After merge, a CI-gated
   `main -> develop` PR synchronizes the ledger.

Other tracking documents remain main-only.

## PR Body

Use at least:

```markdown
## Summary
## Why
## Changes
## Verification
```

For audit-driven work, include a GAP Audit table.

## Cleanup

After merge:

```bash
gh pr merge <feature-pr> --squash --delete-branch
git worktree remove .claude/worktrees/<task-name>
git branch -d feature/<branch-name>
git fetch origin --prune
```

Do not force-delete branches or worktrees held by other sessions.
