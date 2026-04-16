# GEODE Development Workflow

> Public-facing guide for contributors. For detailed scaffold rules, see `CLAUDE.md`.

## Branch Strategy (GitFlow)

```
feature/<name> ──> develop ──> main
```

- **feature/**: All new work branches from `develop`
- **develop**: Integration branch, CI must pass before merge
- **main**: Production, only receives merges from `develop`

No direct pushes to `main` or `develop`. Always PR with CI 5/5.

## Worktree Isolation

Each task runs in its own git worktree:

```bash
git fetch origin
git worktree add .claude/worktrees/<task-name> -b feature/<branch-name> develop
echo "session=$(date -Iseconds) task_id=<task-name>" > .claude/worktrees/<task-name>/.owner
```

On completion: `git push` then `git worktree remove`.

## Quality Gates

Every PR must pass all gates before merge:

| Gate | Command | Criteria |
|------|---------|----------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Format | `uv run ruff format --check core/ tests/` | 0 diffs |
| Type | `uv run mypy core/` | 0 errors |
| Test | `uv run pytest tests/ -m "not live"` | All pass |
| E2E | `uv run geode analyze "Cowboy Bebop" --dry-run` | A (68.4) |

## Workflow Steps

```
0. Issue + Worktree
1. GAP Audit (does it already exist?)
2. Plan + Socratic Gate (is it needed?)
3. Implement + Test (iterate)
4. Verify (plan vs diff cross-check)
5. Docs Sync (CHANGELOG, version)
6. PR + CI (feature -> develop -> main)
7. Rebuild + Restart
```

### Socratic Gate (for non-trivial features)

Before implementing, answer these 5 questions:

1. **Does it already exist in code?** (grep/explore verification)
2. **What breaks if we don't do this?** (failure scenario)
3. **How do we measure the effect?** (tests, metrics)
4. **What is the simplest implementation?** (minimum changes)
5. **Is this the same pattern in 3+ frontier systems?** (validation)

### PR Body (Required Sections)

```markdown
## Summary
## Why
## Changes
## Verification
```

See `.github/PULL_REQUEST_TEMPLATE.md` for the full template.

## Versioning

- New feature: MINOR bump (0.X.0)
- Bug fix: PATCH bump (0.0.X)
- Docs only: No version change

Version must match across: `CHANGELOG.md`, `CLAUDE.md`, `README.md`, `pyproject.toml`.

## Conventions

- **Commit messages**: Conventional commits (`feat:`, `fix:`, `chore:`, `refactor:`, `style:`)
- **Language**: Korean or English (maintain consistency within a PR)
- **No emojis** in code or prompts (allowed in reports only)
- **Line length**: 100 characters (ruff enforced)
