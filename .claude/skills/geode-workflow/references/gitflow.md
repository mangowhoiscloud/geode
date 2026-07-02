# GitFlow

Default branch flow:

```text
feature/<name> -> develop -> main
```

## Feature Worktree

```bash
git fetch origin
git worktree add .claude/worktrees/<task-name> -b feature/<branch-name> develop
echo "session=$(date -Iseconds) task_id=<task-name>" > .claude/worktrees/<task-name>/.owner
```

Never switch branches inside a worktree. Allocate or enter the correct
worktree.

## Merge Rules

- Feature branches start from `develop`.
- Feature PRs merge into `develop` with squash merge.
- Before `develop -> main`, sync `main -> develop` if main has drift.
- `develop -> main` is a pass-through merge after gates are satisfied.
- No direct push to `main` or `develop`.

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
