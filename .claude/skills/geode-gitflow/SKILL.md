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
cd /Users/mango/workspace/geode

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
