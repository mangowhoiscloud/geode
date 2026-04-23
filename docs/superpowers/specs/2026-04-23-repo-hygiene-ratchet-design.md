# Repo Hygiene Ratchet — Design Spec

- **Date**: 2026-04-23
- **Author**: pinxbot9
- **Status**: Approved (brainstorm phase) — scope B (includes latent bug cleanup)
- **Version impact**: PATCH (0.48.0 → 0.48.1)
- **Category**: Infrastructure

## Motivation

GEODE's CI already enforces three ratchets (legacy import, prompt integrity, min test count). Repo hygiene — symlink health and worktree metadata integrity — has no automated guard. Following the ratchet pattern (Karpathy P4, OpenClaw Policy Chain), add a preventive check that blocks regressions before they enter the codebase.

### Latent bug discovered during allocation

While allocating the feature worktree per CLAUDE.md §0, the instruction

```bash
echo "session=... task_id=..." > .claude/worktrees/<task-name>/.owner
```

was observed to write to the **worktree's checkout root** (because `.claude/worktrees/<task-name>/` *is* a new checkout's root directory) and overwrite a **tracked `.owner` file at the repo root**:

```
$ git show origin/develop:.owner
session=2026-04-08T04:33:31+09:00 task_id=layer-violation-fix
```

This file was committed in `6d07637` — likely an accidental inclusion during a docs reorganization. It breaks the worktree ownership convention in two ways:

1. Every worktree allocation silently modifies a tracked file (branch pollution)
2. Every worktree automatically satisfies any "presence of `.owner`" check (defeats the intended orphan guard)

Scope B therefore combines the preventive ratchet **and** the cleanup of this latent bug in one PR.

Current symlink state: zero tracked symlinks. The ratchet is preventive for symlinks (zero-state → enforce zero-state) and corrective for `.owner` (remove stale, gitignore, document).

## Scope

### Part 1 — Ratchet checks (FAIL conditions)

| # | Check | Detection |
|---|-------|-----------|
| 1 | Dangling symlink | Symlink whose target does not exist |
| 2 | Absolute-path symlink | `os.readlink(link)` starts with `/` |
| 3 | Orphan worktree metadata | Directory under `.claude/worktrees/` present in working tree but missing `.owner` |

### Part 2 — Latent bug cleanup (one-time)

| Action | Reason |
|--------|--------|
| `git rm .owner` | Remove the stale tracked root `.owner` (no consumer, was accidental) |
| Add `/.owner` to `.gitignore` | Prevent re-committing worktree session metadata (the convention writes here by design) |
| No change to CLAUDE.md §0 echo command | Gitignore makes the existing instruction safe; avoid churning the established convention |
| CLAUDE.md — short note | Add one-line explainer that `.owner` is gitignored so sessions can safely overwrite at the worktree checkout root |

### Exclusions

- **Symlink scan** (checks #1, #2) ignores: `.git/`, `.venv/`, `node_modules/`, `.claude/worktrees/`
  - Rationale: `.git/` and `.venv/` contain tool-managed links; `.claude/worktrees/` is gitignored and contains full nested checkouts — scanning into them is redundant and out of scope
- **Orphan worktree check** (check #3) **only scans** `.claude/worktrees/` at the working tree — since `.claude/worktrees/` is gitignored, CI normally sees an empty or missing directory and the check passes trivially. The check still has value as a defensive gate if `.gitignore` is ever loosened, and as a locally-runnable audit
- `.owner` content schema (session/task_id keys) is not validated — presence only
- Windows path semantics are out of scope (GEODE targets macOS/Linux)

### Non-goals

- No auto-fix (report-only ratchet)
- No allowlist mechanism yet (YAGNI — zero symlinks currently)
- No pre-commit hook integration (CI only)
- No audit of historical commits for similarly-committed `.owner` residue (out of scope; trusts that current tip is the only live concern)

## Architecture

### Components

```
scripts/check_repo_hygiene.py        — logic (single file, pure stdlib, type-annotated)
tests/test_check_repo_hygiene.py     — unit tests with tmp_path
.github/workflows/ci.yml             — new step under the lint job
.gitignore                            — add `/.owner`
.owner                                — DELETE (git rm)
CLAUDE.md                             — one-line note near §0 worktree alloc
```

Pattern follows `scripts/check_legacy_imports.py` (existing ratchet).

### Execution contract

| Aspect | Value |
|--------|-------|
| CLI invocation | `uv run python scripts/check_repo_hygiene.py` |
| Arguments | None (repo root fixed to cwd) |
| Exit 0 | No issues found |
| Exit 1 | At least one violation; list on stderr, summary on stdout |
| Dependencies | Python stdlib only (`pathlib`, `os`, `sys`) |

### Output format

```
Repo hygiene check: 3 issues

[dangling symlink]
  docs/old.md -> /nonexistent/path

[absolute symlink]
  configs/dev.toml -> /Users/foo/configs/dev.toml
    hint: use relative path (ln -sr)

[orphan worktree]
  .claude/worktrees/abandoned-task/
    hint: missing .owner file; remove worktree or add .owner

exit 1
```

Each violation includes a one-line actionable hint.

## Testing

### Unit tests (tmp_path fixture)

| Case | Setup | Expected |
|------|-------|----------|
| `test_clean_repo_passes` | Empty tmp dir | exit 0 |
| `test_dangling_symlink_fails` | Create broken symlink | exit 1, path reported |
| `test_absolute_symlink_fails` | Create `/tmp/...` symlink | exit 1, absolute hint |
| `test_orphan_worktree_fails` | Create `.claude/worktrees/x/` without `.owner` | exit 1, orphan hint |
| `test_valid_worktree_passes` | Same but with `.owner` file | exit 0 |
| `test_excluded_paths_ignored` | Symlink inside `.git/` | exit 0 |

Adds 6 tests. Current threshold `2900`, current count ~3939. Ample margin.

### Manual verification

```bash
uv run python scripts/check_repo_hygiene.py   # expect exit 0
ln -s /nonexistent /tmp/test-link             # create dangling
ln -sf /tmp/test-link ./broken                # link into repo
uv run python scripts/check_repo_hygiene.py   # expect exit 1
rm ./broken
```

### Cleanup verification

```bash
git ls-files .owner      # expect empty (file removed from index)
grep -E '^/?\.owner$' .gitignore   # expect match
```

## CI Integration

Add a step inside the existing `lint` job after "Legacy import ratchet":

```yaml
- name: Repo hygiene ratchet
  run: uv run python scripts/check_repo_hygiene.py
```

Rationale for placement: logically adjacent to the other repo-shape ratchet (legacy imports), shares the same runner, no extra `uv sync`.

## Gitflow Plan

```
main
 └─ develop
     └─ feature/repo-hygiene-ratchet       ← worktree under .claude/worktrees/repo-hygiene-ratchet
         commit A: scripts/check_repo_hygiene.py + tests (type-annotated, stdlib only)
         commit B: CI wiring (.github/workflows/ci.yml)
         commit C: cleanup — git rm .owner + .gitignore /.owner + CLAUDE.md note
         commit D: version bump + CHANGELOG (0.48.0 → 0.48.1)
         → PR to develop (HEREDOC body, CI 5/5 green) → squash merge
         → PR develop → main (abbreviated body, CI 5/5 green) → merge commit
```

Worktree lifecycle:

```bash
# allocate
git fetch origin
git worktree add .claude/worktrees/repo-hygiene-ratchet -b feature/repo-hygiene-ratchet origin/develop
# Note: until commit C lands, .owner at worktree root is a TRACKED file; do not overwrite it

# cleanup (post-merge)
git worktree remove .claude/worktrees/repo-hygiene-ratchet
```

## Docs-sync

Version bump touches 4 files:

| File | Line | Change |
|------|------|--------|
| `pyproject.toml` | 3 | `version = "0.48.1"` |
| `CLAUDE.md` | 11 | `- **Version**: 0.48.1` |
| `README.md` | 21 | `# GEODE v0.48.1 — ...` |
| `CHANGELOG.md` | — | New section `## [0.48.1] — 2026-04-23` |

CHANGELOG entry:

```markdown
## [0.48.1] — 2026-04-23

### Infrastructure
- Added repo hygiene ratchet — CI blocks PRs introducing dangling symlinks, absolute-path symlinks, or orphan `.claude/worktrees/` entries missing `.owner` metadata (`scripts/check_repo_hygiene.py`).
- Removed stale tracked `.owner` at repo root (accidentally committed via `6d07637`) and added `/.owner` to `.gitignore` so the worktree ownership convention in CLAUDE.md §0 no longer pollutes feature branches.
```

## Verification Checklist

- [ ] `uv run ruff check core/ tests/ scripts/` — 0 errors
- [ ] `uv run mypy core/` — 0 errors (CI scope; `scripts/` is type-annotated for hygiene but not in CI mypy run)
- [ ] `uv run pytest tests/ -m "not live"` — pass count ≥ previous + 6
- [ ] `uv run python scripts/check_repo_hygiene.py` — exit 0 on current repo
- [ ] `git ls-files .owner` — empty (file removed)
- [ ] `uv run geode analyze "Cowboy Bebop" --dry-run` — A (68.4) unchanged
- [ ] CI 5/5 green on feature → develop PR
- [ ] CI 5/5 green on develop → main PR

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| False positive on `.git/` internal symlinks | Hard-coded exclusion list includes `.git/` |
| `find` behavior differs between macOS BSD and Linux GNU | Use Python `pathlib` + `os.readlink`, not shell `find` |
| mypy scope — CI runs mypy only on `core/` | Confirmed; new script gets type annotations as hygiene, no CI scope change |
| Future legitimate symlink rejected | Document override path (allowlist) as follow-up if needed; not in scope now |
| Other `.owner`-like accidents not covered | `/.owner` gitignore is targeted; future audits can broaden if pattern recurs |
| Users on existing worktrees have local uncommitted `.owner` changes | After merge, `git pull` into worktree won't conflict because `.owner` is deleted + gitignored; any local override in untracked `.owner` is preserved |

## Out of Scope (Follow-up candidates)

- Pre-commit hook integration (dev-side early warning)
- `.owner` content schema validation (session/task_id keys)
- Allowlist file for intentional symlinks
- Auto-fix mode (`--fix` flag)
- Historical audit for other accidentally-committed session metadata
