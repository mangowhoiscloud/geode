---
name: geode-gitflow
description: GEODE branch strategy and PR rules. feature → develop → main merge flow, Pre-PR Quality Gate (CI guardrails + docs-sync loop), Post-PR CI ratchet (gh pr checks --watch mandatory), Korean PRs, assignee settings. Triggers on "branch", "git", "pr", "merge", "커밋", "풀리퀘스트".
---

# GEODE Git & PR Workflow

## Merge Flow (mandatory)

**feature → develop → main** order. Direct push to main prohibited — must go through PR.

```
feature/xxx ──PR──→ develop ──PR──→ main
```

For releases (version stamp bump + CHANGELOG promote), the release branch lands on **develop first**, then a straight pass-through develop → main PR ships to production. See `## Release Flow` below — this rotation eliminates the post-release backmerge that the older pattern required.

## Full Workflow

> **Principle 1**: Every work unit **starts with worktree open (alloc) and ends with worktree close (free)**.
> No direct `git checkout feature/*` in the main repo. No exceptions.
>
> **Principle 2**: develop merge uses a **queue approach** — one at a time. Rebase next worktree after merge.

```
0.  ★ Frontier Research (for new infrastructure features)
    DISCOVER → COMPARE → DECIDE → DOCUMENT
1.  worktree open + feature branch creation  ← alloc
2.  Code changes (within worktree)
3.  ★ Pre-PR Quality Gate (iterate)
4.  Commit (code + docs together)
5.  PR creation (feature → develop)
6.  ★★ Post-PR CI Ratchet (mandatory)
7.  merge (feature → develop)            ← queue: one at a time
8.  develop → main PR creation (batchable)
9.  ★★ Post-PR CI Ratchet (mandatory)
10. merge (develop → main)
11. ★★★ Docs-Sync Final Verification
12. worktree close + branch deletion          ← free
```

> **Step 0 applicability**: Mandatory for new infrastructure features (Gap, architecture changes).
> Can be skipped for simple bug fixes, documentation updates, or repeating existing patterns.

### Develop Merge Queue (when running parallel worktrees)

When multiple worktrees are open simultaneously, manage develop merges as a sequential queue.

```
Worktree A (fix/xxx)  ──→ PR → CI pass → merge #1 ──┐
                                                      │ develop updated
Worktree B (fix/yyy)  ──→ PR → CI pass ──→ rebase ──→ merge #2 ──┐
                                                                   │
Worktree C (fix/zzz)  ──→ PR → CI pass ──→ rebase ──→ merge #3 ──┘
                                                                   │
                                              develop → main PR (batch)
```

**Queue rules:**
- Only one merge to develop at a time (conflict prevention)
- After merge, next waiting worktree rebases onto develop then pushes
- Re-run CI after merge (code changed due to rebase)
- develop → main can batch multiple features

```bash
# Queue order management — rebase next worktree
cd .claude/worktrees/<next-task-name>
git fetch origin develop
git rebase origin/develop
git push --force-with-lease
# → CI re-triggered → confirm pass → merge
```

### Concurrent-session drift & CI-trigger recovery

Two failure modes surface when **another session merges to develop while your
feature PR is open** (e.g. a Tau2-promotion or scheduled routine running in
parallel). Both are expected under multi-session work — recognise and recover,
don't re-investigate from scratch each time.

**A. PR goes `CONFLICTING` / `DIRTY` — usually a CHANGELOG collision.** The
other merge added its own top entry (often under `## [Unreleased]`) or bumped
the version, so your top-of-CHANGELOG insert conflicts. Recover:

```bash
git fetch origin
git merge origin/develop            # resolve on the feature branch (squash-merge flattens it later)
# CHANGELOG.md is the usual (often only) conflict.
```

- **Fold, don't stack.** Absorb the concurrent `[Unreleased]` / entry INTO your
  release version's own `### Added/Changed/Fixed` — a release captures *all*
  unreleased work since the last version. Never leave a `## [Unreleased]`
  heading on a branch bound for main (CLAUDE.md forbids it).
- **Re-check the version number isn't already taken.** If the other session
  bumped `pyproject`/CHANGELOG to the number you picked, bump past it
  (`grep -m1 '^version' <(git show origin/develop:pyproject.toml)` before
  resolving — see [[feedback_concurrent_session_version_collision]]).
- **Regenerate the derived SoT after editing CHANGELOG.md** — the version
  fan-out is not just the 5 text files: `node site/scripts/sync-stats.mjs`
  (rebuilds `changelog.ts` / `sot.ts` / `llms.txt`) + `uv run python
  scripts/check_llms_version.py --fix`, else the CI version ratchet blocks the
  merge on a stale `changelog.ts`.
- Re-run the gates, `git add -A`, `git commit` (completes the merge), push.

**B. A fresh PR attaches 0 CI checks (webhook miss).** `gh pr checks <N>` prints
"no checks reported" and stays that way. Confirm it's a *miss*, not slowness:

```bash
gh api "repos/<owner>/<repo>/commits/$(git rev-parse HEAD)/check-runs" --jq .total_count   # 0 = nothing attached
```

If `total_count` is 0 minutes after opening (Actions enabled, other PRs' runs
present), re-fire the trigger:

```bash
gh pr close <N> && gh pr reopen <N>   # fires a `reopened` event → CI re-triggers
```

Verify attachment via the `check-runs` API, **not** `gh pr checks` alone (it
errors identically on "not yet run" and "will never run"). Don't leave a monitor
spinning on the repeating "no checks" error — diagnose the trigger first.

---

## Release Flow (rotation — eliminates backmerge)

Pre-2026-05-23 GEODE used the canonical gitflow pattern: release branch off
develop → merge to main → backmerge main → develop. That created a one-way
push of version stamps + CHANGELOG promotes into main, leaving develop's
stamps stale until the backmerge PR landed. Every release cycle paid the
cost of a 6-file backmerge PR, **AND** CHANGELOG conflicts when
develop moved while the release PR was in flight (we hit this 4 times
across PR #1499, #1504, #1506).

The current pattern rotates the order so release stamps land on develop
first:

```
develop ──cut──→ release/vX.Y.Z (stamp bump + CHANGELOG promote)
                       │
                       └─PR─→ develop  (1)  ← release branch absorbs back
                                │
                                └─PR─→ main (2)  ← straight pass-through
```

**Step (1)** — release/* → develop PR. Carries the 5-location stamp bump
(`pyproject.toml`, `CLAUDE.md`, `README.md`, `README.ko.md`, CHANGELOG
header) and the `## [Unreleased]` → `## [X.Y.Z]` promote. Insert a fresh
empty `## [Unreleased]` above the just-promoted section so the next batch
of feature PRs has somewhere to land. Develop is now content-equivalent to
the eventual main state.

**Step (2)** — develop → main PR. No new commits beyond merge — it just
moves main's tip up to develop's. Abbreviated PR body (Summary +
Verification only) is fine here.

**No backmerge step.** Develop already has every commit that main has.
After release, the two are content-identical (modulo gitflow merge-commit
asymmetry).

```bash
# ── Release flow (rotation) ──

# 1. Cut release branch
git fetch origin
git worktree add .claude/worktrees/release-vX.Y.Z -b release/vX.Y.Z origin/develop

# 2. Bump stamps + CHANGELOG promote + add fresh [Unreleased]
# (edit 5 files; see geode-changelog skill for [Unreleased] ratchet rules)

# 3. PR release → develop
gh pr create --base develop --head release/vX.Y.Z \
  --title "release: vX.Y.Z — <summary>" \
  --body "<release notes>"
# → CI ratchet → merge

# 4. PR develop → main (straight pass-through)
gh pr create --base main --head develop \
  --title "release: vX.Y.Z (develop → main)" \
  --body "<abbreviated body>"
# → CI ratchet → merge → Pages workflow fires
```

### Backmerge safety net

`.github/workflows/auto-backmerge.yml` watches main pushes. If for any
reason (rotation skipped, force-push, hotfix landed directly on main) main
moves ahead of develop, the workflow opens an auto-backmerge PR. Manual
intervention required only if the auto-PR has conflicts.

The safety net should fire **rarely** under the rotation pattern — it
exists so a one-off mistake doesn't silently drift develop behind main.

### Docs pipeline compatibility

The rotation pattern preserves every existing docs / release workflow
trigger:

| Workflow | Trigger | Behavior under rotation |
|----------|---------|-------------------------|
| `pages.yml` | `push: main` (paths include `CHANGELOG.md`, `pyproject.toml`, `CLAUDE.md`) | Fires when develop → main pass-through PR merges. Same moment as before. |
| `petri-publish.yml` | `push: main, develop` | Fires on develop merge AND main merge. Unchanged. |
| `release.yml` | `workflow_dispatch` (manual, default `ref: main`) | Manual trigger unchanged. The `version` input matches both `pyproject.toml` and `CHANGELOG.md` `## [X.Y.Z]` header. |
| `site/scripts/sync-stats.mjs` | invoked by `pages.yml` build | Counts CHANGELOG `## [X.Y.Z]` headers excluding `[Unreleased]`. Rotation's fresh-`[Unreleased]` block is correctly skipped. |

No workflow file needs editing for the rotation. `auto-backmerge.yml` is
additive.

---

## Step 0: ★ Frontier Research (mandatory pre-implementation research)

> Applicability: Mandatory for new infrastructure features (Gap, architecture changes). Can skip for simple bug fixes.

Investigate implementations in frontier harnesses (Claude Code, Codex CLI, OpenClaw, Aider, autoresearch, etc.),
create a comparison matrix, and document design decisions.

```
DISCOVER (investigate harnesses via parallel Agents)
  → COMPARE (feature × harness matrix)
  → DECIDE (Option A/B/C + selection rationale)
  → DOCUMENT (docs/plans/research-<topic>.md)
```

> Open source (Codex, Aider, autoresearch, OpenClaw) — verify source directly via `gh api`.
> Closed source (Claude Code only) — official docs/secondary sources — state verification limitations.

---

## Step 1: Worktree Open (alloc)

**Every work unit** starts by opening a worktree. No exceptions.

```bash
# 0. Sync verification gate (CANNOT rule — never skip)
git fetch origin

LOCAL_MAIN=$(git rev-parse main)
REMOTE_MAIN=$(git rev-parse origin/main)
[ "$LOCAL_MAIN" != "$REMOTE_MAIN" ] && echo "STOP: local main ≠ origin/main" && git checkout main && git pull origin main

LOCAL_DEV=$(git rev-parse develop)
REMOTE_DEV=$(git rev-parse origin/develop)
[ "$LOCAL_DEV" != "$REMOTE_DEV" ] && echo "STOP: local develop ≠ origin/develop" && git checkout develop && git pull origin develop

# 1. Create worktree = allocate workspace (based on develop)
git worktree add .claude/worktrees/<task-name> -b feature/<branch-name> develop

# 2. Move to work directory
cd .claude/worktrees/<task-name>

# → Steps 2~11 all performed within this worktree
```

**Worktree rules:**
- `.claude/worktrees/` is in `.gitignore`
- No `git checkout` within worktree (HEAD conflict)
- No `git checkout feature/*` in main repo — access only via worktree
- Leak check: `git worktree list` to find unclosed worktrees

---

## ★ Pre-PR Quality Gate (mandatory loop before commit)

**After code changes, this loop must pass before commit/PR.**

```
Code changes complete
   │
   ▼
┌─────────────────────────────────────────┐
│  Step 1: CI Guardrails (all must pass)  │
│                                         │
│  uv run ruff check core/ tests/         │ → On fail: ruff --fix then re-run
│  uv run ruff format --check core/ tests/│ → On fail: ruff format then re-run
│  uv run mypy core/                      │ → On fail: fix types then re-run
│  uv run bandit -r core/ -c pyproject.toml│ → On fail: fix security then re-run
│  uv run pytest tests/ -m "not live" -q  │ → On fail: fix tests then re-run
│                                         │
│  Any failure → fix → re-run Step 1      │
│                                         │
│  ※ Detailed inspection lenses:          │
│    code-review-workflow                  │
│    (structure/deps/security/migration/   │
│     performance)                         │
└────────────────┬────────────────────────┘
                 │ All passed
                 ▼
┌─────────────────────────────────────────┐
│  Step 2: Docs Writing (mandatory on     │
│  code changes)                          │
│                                         │
│  □ Add entry to CHANGELOG.md            │
│    [Unreleased]                         │
│    - Added / Changed / Fixed / Removed  │
│    - Can skip if no code changes        │
│                                         │
│  □ Sync CLAUDE.md metrics (if changed)  │
│    - When Tests, Modules change         │
│                                         │
│  □ Update docs/progress.md today's      │
│    date section                         │
│    - Completion table + remaining table  │
│                                         │
│  Omission found → fix → re-run Step 1   │
└────────────────┬────────────────────────┘
                 │ All complete
                 ▼
┌─────────────────────────────────────────┐
│  Step 3: Commit                         │
│                                         │
│  Include code + docs in a single commit │
│  No separate docs-only commits          │
│  (maintain consistency)                 │
│                                         │
│  git add <code files> CHANGELOG.md ...  │
│  git commit -m "<type>: <description>"  │
└────────────────┬────────────────────────┘
                 │
                 ▼
           Ready to create PR
```

### Quality Gate Anti-patterns

| Anti-pattern | Result | Correct Approach |
|-------------|--------|------------------|
| Creating PR with CI failures | Wastes reviewer time | Pass all locally before PR |
| Code-only commit, docs in separate PR | CHANGELOG missing, version mismatch | Code + docs in same commit |
| Direct push to main | Gitflow violation, history pollution | Must go through PR |
| Skipping docs-sync | README/CHANGELOG fall behind | Step 2 checklist mandatory |
| **Merging without CI confirmation** | **Broken code enters main** | **gh pr checks --watch mandatory** |

---

## ★★ Post-PR CI Ratchet — Mandatory Before Merge (CRITICAL)

> **Karpathy P4**: Ratchet = advance only on verification pass, rollback on failure.
> Merging a PR without CI green is a **ratchet violation**.

### Absolute Rule

**Before running `gh pr merge`, you must check CI status with `gh pr checks`.**
Merge prohibited if CI is still running or has failed.

### Merge Ratchet Loop

```
PR creation complete
   │
   ▼
┌──────────────────────────────────────────────────┐
│  Step A: Wait for CI completion + check results   │
│                                                   │
│  gh pr checks <PR#> --watch --repo <owner/repo>   │
│                                                   │
│  → All pass  → Proceed to Step B                  │
│  → Any fail → Proceed to Step C                   │
│  → pending/running → Wait (--watch auto-waits)    │
└────────────────┬──────────────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
┌──────────────┐  ┌──────────────────────────────┐
│  Step B:     │  │  Step C: Failure fix loop      │
│  Run Merge   │  │                                │
│              │  │  1. gh run view --log-failed    │
│  gh pr merge │  │     → Identify failure cause    │
│  <PR#>       │  │  2. Fix locally                 │
│  --merge     │  │  3. Commit + push (same branch) │
│              │  │  4. CI auto re-triggered         │
│              │  │  5. Return to Step A             │
│              │  │                                  │
│              │  │  (Repeat until pass)             │
└──────────────┘  └──────────────────────────────────┘
```

### Merge Command Template (copy and use)

```bash
# ── feature → develop ──

# 1. Create PR
gh pr create --base develop --assignee mangowhoiscloud \
  --title "<type>: <description>" \
  --body "<detailed body template>"

# 2. ★★ CI Ratchet: Wait for checks to pass (MUST — never skip)
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode

# 3. Merge only after all pass
gh pr merge <PR#> --merge --repo mangowhoiscloud/geode

# ── develop → main ──

# 4. Create PR
gh pr create --base main --head develop --assignee mangowhoiscloud \
  --title "<type>: <description> (develop → main)" \
  --body "<develop → main template>"

# 5. ★★ CI Ratchet: Wait for checks to pass (MUST — never skip)
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode

# 6. Merge only after all pass
gh pr merge <PR#> --merge --repo mangowhoiscloud/geode
```

### CI Failure Fix Loop

```bash
# Check failure logs
gh pr checks <PR#> --repo mangowhoiscloud/geode
gh run view <run_id> --log-failed

# Fix locally → push → CI auto re-runs
# ... fix ...
git add -A && git commit -m "fix: <CI failure cause fix>"
git push

# Check ratchet again
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode
# pass → merge
```

### Common CI Failure Causes and Responses

| Failure | Response |
|---------|----------|
| `ruff` lint error | `uv run ruff check --fix core/ tests/` + `uv run ruff format core/ tests/` |
| `mypy` type error | Fix types, minimize `# type: ignore` |
| `bandit` security warning | Add `# nosec` or to pyproject.toml skips (only when justified) |
| `pytest` failure | Fix test code, add tests for new code |
| `coverage < 75%` | Add tests for modules with insufficient coverage |

---

## PR Writing Rules

| Item | Rule |
|------|------|
| **Language** | **Korean** (both title + body) |
| **Title** | `<type>: <Korean description>` (under 70 chars) |
| **Assignee** | `--assignee mangowhoiscloud` (always) |
| **Base** | feature → `develop`, develop → `main` |

### ★ PR Body Build Rules (CRITICAL — must follow)

> **A weak PR body prevents reviewers from understanding the change intent.**
> A 1-3 line PR body is an **anti-pattern**. Fill all required sections from the template below.

**Before generating PR body, you must:**
1. Check full diff with `git diff develop...HEAD`
2. Classify all changed **files** into core/secondary/docs
3. Write a one-line **why** rationale for each file change
4. Copy test result numbers from **actual execution output** (no XXXX placeholders)
5. Use HEREDOC format (prevents line break/markdown breakage)

### Anti-pattern vs Correct PR Body

| Anti-pattern (prohibited) | Correct Approach |
|---------------------------|------------------|
| `"progress hooks"` (3 words) | Write summary + changes + impact scope + QG in full |
| `"develop → main merge. X changes."` (1 line) | Include PR numbers, CI confirmation results for develop→main too |
| Summary only without listing changed files | Per-file AS-IS → TO-BE + one-line rationale |
| `XXXX passed` (placeholder) | `2168 passed` (actual number) |
| Skipping Quality Gate checklist | All 5 CI tools + 4 docs items checked |

## PR Body Detailed Template (feature → develop)

**All sections are required. If not applicable, state "N/A".**

```markdown
## Summary
<!-- Required. 2-3 lines. "What" + "why" changed. Include background motivation. -->

<Core of the change in 2-3 sentences. What problem existed and how this PR solves it.>

## Changes

### Core Changes (Code)
<!-- Required. List all changed files without omission. -->
- `filepath:line-range`: Change content — AS-IS → TO-BE
  - Rationale: One-line explanation of why this change was made

### Secondary Changes (Code)
<!-- If N/A, state "None" -->
- `filepath`: Rename/format/type fixes etc.

### Documentation/Config Changes
<!-- Required. If code changed, CHANGELOG must be included. -->
- `CHANGELOG.md`: Items added to [Unreleased] > Fixed/Added/Changed
- `CLAUDE.md`: Updated items (if applicable)
- `pyproject.toml`: Dependency/config changes (if applicable)

## Impact Scope
<!-- Required. -->
- **Affected modules**: <specific paths like core/cli, core/ui>
- **Backward compatibility**: Maintained / Broken (if broken, attach migration guide)
- **Test changes**: Added N / Modified N / Deleted N

## Design Decisions
<!-- Required for structural changes. For simple bug fixes, state "Simple fix, no design decisions needed." -->
- Why was approach B chosen over approach A?
- If referencing frontier harness cases: link `docs/plans/research-<topic>.md`
- Alternative comparison: Option A (pros/cons) vs Option B (pros/cons) → selection rationale

## Pre-PR Quality Gate (required — paste actual execution results)
- [x] `ruff check` — 0 errors
- [x] `ruff format --check` — OK (N files)
- [x] `mypy core/` — Success (N source files)
- [x] `bandit -r core/` — 0 issues
- [x] `pytest -m "not live"` — **N passed** in Xs
- [x] CHANGELOG.md [Unreleased] entry added
- [x] README.md metric consistency verified
- [ ] CLAUDE.md sync (if applicable)
- [x] docs/progress.md today's date section updated

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## PR Body Template (develop → main)

```markdown
## Summary
develop → main merge. <1-2 line summary of main changes. What features/fixes are included.>

## Included Changes
<!-- Required. List all feature PRs with numbers and titles. -->
- #number `<type>: <title>` — One-line summary of core change
- #number `<type>: <title>` — One-line summary of core change

## Change Metrics
- **Files**: N files changed
- **Tests**: N passed (compared to previous +N/-N)
- **Modules**: N (specify if changed)

## Testing
- [x] Full CI passed (`gh pr checks --watch` confirmed)
- [x] feature → develop CI pass confirmed

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### gh pr create Command — HEREDOC Required

PR body must be passed in **HEREDOC** format. Inline `--body "..."` prohibited.

```bash
# ✅ Correct: HEREDOC
gh pr create --base develop --assignee mangowhoiscloud \
  --title "<type>: <description>" \
  --body "$(cat <<'PRBODY'
## Summary
...fill full template...

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PRBODY
)"

# ❌ Prohibited: Inline (line breaks broken, content truncated)
gh pr create --body "One line summary"
```

---

## ★★★ Docs-Sync Final Verification (after main merge, before cleanup)

> Performed after the work unit is fully merged to main.
> Even if docs were written in Pre-PR Step 2, metrics may change during the merge process, so final verification is needed.

### Verification Checklist

```
main merge complete (step 10)
   │
   ▼
┌──────────────────────────────────────────────────┐
│  □ README.md metric consistency                   │
│    - modules: find core/ -name "*.py" | wc -l     │
│    - tests: uv run pytest --co 2>&1 | wc -l       │
│    - tools count, version                         │
│                                                   │
│  □ CLAUDE.md metric consistency                   │
│    - Verify Tests, Modules using same criteria    │
│                                                   │
│  □ CHANGELOG.md [Unreleased] omission check       │
│    - Are changes merged to main recorded?         │
│                                                   │
│  □ docs/progress.md today's date section exists   │
│    - If missing, add and commit                   │
│                                                   │
│  □ pyproject.toml coverage omit                   │
│    - Check if new module is in omit breaking      │
│      coverage                                     │
│                                                   │
│  → If mismatch found:                             │
│    docs(sync) commit → feature → develop → main   │
│    (apply same gitflow loop)                      │
│  → If no issues: proceed to step 12               │
│    (workspace cleanup)                            │
└──────────────────────────────────────────────────┘
```

### Pre-PR Step 2 vs Docs-Sync Final Verification

| Phase | Timing | Role |
|-------|--------|------|
| Pre-PR Step 2 | Before commit | **Write** docs (CHANGELOG entry, CLAUDE.md metrics) |
| Docs-Sync Final Verification | After main merge | **Verify** docs (README metrics, coverage omit, omission check) |

Docs are written in Pre-PR, and the final verification after main merge catches anything missed — a dual-layer structure.

---

## Branch Structure

```
main ─────────────────────────── production (stable, tagged)
  │
  └── develop ────────────────── integration (CI mandatory)
        │
        ├── feature/<name> ───── Feature development
        ├── hotfix/<name> ────── Emergency fixes (branch from main)
        └── release/v<semver> ── Release preparation
```

## Commit Convention

```
<type>(<scope>): <description>

Types: feat, fix, refactor, test, docs, ci, chore
Scopes: pipeline, scoring, analysis, verification, cli, memory, tools, llm

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

## CI Pipeline (GitHub Actions)

```
lint ─────┐
typecheck ─┤
test ──────┼──→ gate (all must pass for merge)
security ──┘
```

```bash
# Local CI guardrails (Pre-PR)
uv run ruff check core/ tests/
uv run ruff format --check core/ tests/
uv run mypy core/
uv run bandit -r core/ -c pyproject.toml
uv run pytest tests/ -m "not live" -q

# GitHub CI ratchet (Post-PR, mandatory before merge)
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode
```

## Step 12: Worktree Close (free)

**After merge completion**, worktree must be closed. No exceptions.

```bash
# 1. Return to main repo
cd ~/workspace/geode

# 2. Update develop/main to latest
git checkout develop && git pull origin develop

# 3. Remove worktree = release workspace
git worktree remove .claude/worktrees/<task-name>

# 4. Branch cleanup (local + remote)
git branch -d feature/<branch-name>
git push origin --delete feature/<branch-name>

# 5. Leak check
git worktree list   # No unclosed worktrees should remain
```

---

## Local Merge (exception when PR creation impossible)

Only use local merge when PR creation is impossible (e.g., GitHub "No commits between" error):

```bash
git stash
git checkout develop && git merge feature/<name> --no-edit && git push origin develop
git checkout main && git merge develop --no-edit && git push origin main
git checkout feature/<name> && git stash pop
```

---

## Worktree Allocation (Workflow Step 0)

Record on the Progress Board, then allocate the worktree.

```bash
# 1) Record Backlog → In Progress on Progress Board (from main)

# 2) Allocate Worktree
git fetch origin
# Verify main/develop sync (pull if out of sync)
git worktree add .claude/worktrees/<task-name> -b feature/<branch-name> develop
# Note: the target path IS the worktree checkout root; `.owner` is gitignored
# (see /.owner in .gitignore) so the convention does not pollute feature branches.
echo "session=$(date -Iseconds) task_id=<task-name>" > .claude/worktrees/<task-name>/.owner
```

On completion (after the PR merges) tear down all three stale artifacts — remote branch, worktree, local branch — per [Post-Merge Cleanup](#post-merge-cleanup-mandatory-after-every-merge) below.

## PR Body Template (MANDATORY)

```
## Summary
<1-3 bullet points: what changed and why>

## Why
<Problem statement — what broke, what was missing, what user reported>

## Changes
| File | Change |
|------|--------|
| `path/to/file.py` | description of change |

## GAP Audit (if applicable)
| Item | Status | Notes |
|------|--------|-------|
| ... | Implemented / Dropped / Already exists | ... |

## Verification
- [ ] ruff check clean
- [ ] mypy clean
- [ ] pytest pass (count)
- [ ] E2E unchanged (if applicable)

## Reference
<Source: frontier codebase, PR, issue, serve log, etc.>
```

Minimum required sections: **Summary**, **Why**, **Changes**, **Verification**.
develop → main PRs may use abbreviated form (Summary + Verification only).

| Change | Cascading Updates |
|--------|-------------------|
| New tool | `definitions.json` + handlers + E2E |
| LLM adapter | `core/llm/router/` + `core/llm/providers/` + E2E |

## Post-Merge Cleanup (MANDATORY after every merge)

A merged PR leaves three stale artifacts behind: the remote branch, the local
worktree, and the local branch. Tear all three down — in this order, because
the order is load-bearing:

```bash
# 1) Merge + delete the REMOTE branch in one option (never chain && git push --delete).
#    feature → develop = --squash (one commit/feature); develop → main = --merge.
gh pr merge <PR#> --squash --delete-branch       # feature→develop; cf. [[feedback_merge_then_delete]]

# 2) Remove the WORKTREE first — `git branch -d` REFUSES to delete a branch a
#    worktree still holds, so worktree-remove must precede branch-delete.
git worktree remove .claude/worktrees/<task-name>   # add --force only if the tree has untracked build junk (.venv)

# 3) Delete the LOCAL branch + prune the now-dangling remote-tracking ref
git branch -d feature/<branch-name>              # -d (not -D): refuses if somehow unmerged
git fetch origin --prune
```

> `gh pr merge --delete-branch` deletes the *remote* branch but leaves the
> *local* branch + worktree — and it cannot delete the local branch while a
> worktree still occupies it (you'll see `cannot delete branch '…' used by
> worktree at …`). Always worktree-remove, then branch-delete.

**Periodic bulk prune** (when merged branches have accumulated across sessions):
delete every branch merged into `develop`, EXCLUDING `develop` / `main` /
`release/*` and any branch a worktree still holds (those may belong to another
live session — never delete another session's `.owner`-protected worktree or its
branch). `git branch -d` / `--merged` make this safe — they refuse anything
unmerged.

```bash
held=$(git worktree list --porcelain | awk '/^branch /{gsub("refs/heads/","",$2); print $2}')
# local: merged into develop, not worktree-held, not develop/main
git branch --merged develop --format='%(refname:short)' | grep -vE '^(develop|main)$' \
  | while read b; do echo "$held" | grep -qxF "$b" || git branch -d "$b"; done
# remote: same filter (+ skip release/*), batch the push --delete
git branch -r --merged origin/develop --format='%(refname:short)' | sed 's#^origin/##' \
  | grep -vE '^(develop|main|HEAD)$' | grep -vE '^release/' \
  | while read b; do echo "$held" | grep -qxF "$b" || echo "$b"; done \
  | xargs -n 40 git push origin --delete
git fetch origin --prune
```

## Rebuild & Restart (Workflow Step 7)

After merging to main, rebuild CLI and serve to update the runtime to the latest code.

```bash
# 1) Stop any running geode serve daemon(s). Use `pgrep -f`, NOT
#    `ps aux | grep "geode serve"` — ps aux truncates the long python path
#    before "geode serve", so the grep silently matches nothing, the kill is a
#    no-op, and stale daemons survive a "rebuild" and then fight over
#    ~/.geode/cli.sock (the multi-serve pathology behind the 2026-06-09
#    model-resolution bug: banner shows one daemon's model, calls route through
#    another). `geode serve stop` / `geode doctor` already use pgrep -f
#    internally (core/cli/cmd_lifecycle.py, core/cli/doctor.py); this manual
#    line should match.
pkill -f "geode serve" || true   # no-op if none running; verify: pgrep -f "geode serve"

# 2) Reinstall CLI as editable + sync dependencies.
#    The [audit] extra (inspect_ai) is REQUIRED — the seed-generation pilot's
#    petri_audit tool and the self-improving loop's audit subprocess both need
#    it. Omitting it makes the pilot fail loudly ("petri_audit aborted —
#    install the [audit] extra") instead of measuring; pre-fix it silently
#    emitted all-zero dim_means (PR-PILOT-PETRI-AUDIT-WIRING, 2026-06-01).
uv tool install -e ".[audit]" --force
uv sync --extra audit

# 3) Verify version + restart serve
geode version          # Confirm version match
geode serve &          # Restart in background
```

## Progress Board (Workflow Step 8)

Update project tracking from main. Backlog → In Progress → Done.
