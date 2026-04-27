# GEODE — Claude Code Scaffold

> This file is the **production scaffold** for building GEODE.
> Claude Code reads this file to understand development workflow, quality gates, and constraints.
> For GEODE's runtime identity and architecture, see `GEODE.md`.

## Project Overview

A general-purpose autonomous execution agent built on LangGraph. Autonomously performs research, analysis, automation, and scheduling.

- **Version**: 0.53.1
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)
- **Modules**: 231
- **Tests**: 4192+
- **CHANGELOG**: `CHANGELOG.md` (Keep a Changelog + SemVer)

## Quick Start

```bash
# Install
uv sync

# Thin CLI (auto-starts serve daemon if needed)
uv run geode

# Natural language CLI
uv run geode "summarize the latest AI research trends"
uv run geode "compare React vs Vue for a new project"
uv run geode "schedule daily standup reminder at 9am"

# Game IP Domain Plugin (dry-run, no LLM)
uv run geode analyze "Cowboy Bebop" --dry-run

# Game IP Domain Plugin (full run, requires API keys)
uv run geode analyze "Cowboy Bebop" --verbose
```

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Agent Identity | `GEODE.md` | Runtime architecture, domain rules, LLM models, conventions |
| Hook System | `docs/architecture/hook-system.md` | HookSystem 58 events |
| Scaffold | `CLAUDE.md` | Development workflow, quality gates, CANNOT/CAN (this file) |

## Project Structure

Code is organized in 4-layer stack under `core/`. Check module count with `find core/ -name "*.py" | wc -l`.
Key entry points: `core/cli/agentic_loop.py`(AgenticLoop), `core/graph.py`(StateGraph), `core/runtime.py`(bootstrap).

## Development

```bash
# Test
uv run python -m pytest tests/ -q

# Lint
uv run ruff check core/ tests/

# Type check
uv run mypy core/
```

### Expected Test Results

3700+ tests pass. 3 IP fixtures produce tier spread:
- Berserk: **S** (81.2) — conversion_failure
- Cowboy Bebop: **A** (68.4) — undermarketed
- Ghost in the Shell: **B** (51.7) — discovery_failure

## Implementation Workflow

> **Design Principle**: CANNOT (guardrails) comes before CAN (freedom). Constraints guarantee quality. (Karpathy P1, OpenClaw Policy Chain, Codex Sandbox)

### CANNOT — Absolute Prohibition Rules

These cannot be violated at any stage. Violations must be immediately halted and corrected.

| Area | Rule | Rationale |
|------|------|-----------|
| **Git** | No code work without a worktree | Isolated execution (OpenClaw Session) |
| | No direct push to main/develop — PR → CI → merge | Ratchet (P4) |
| | No deleting other sessions' worktrees (`.owner` mismatch) | Ownership protection |
| | No `git checkout` switching within a worktree | Isolation maintenance |
| | No modifying tracking documents from feature/develop | Single source of truth on main |
| | No branch creation when remote is out of sync | Conflict prevention |
| | No claiming "branch needs sync" from commit count alone — verify content with `git diff A B --stat` first | Graph asymmetry ≠ content asymmetry (gitflow merge commits) |
| **Planning** | No starting implementation without Socratic Gate (except bugs/docs) | Prevent over-engineering |
| **Quality** | No committing with lint/type/test failures | Ratchet (P4) |
| | No placeholders (XXXX) in metrics — measured values only | Truth guarantee |
| | No excessive `# type: ignore` — fix type errors instead | Correctness |
| | No bare `_` for unused variables — use `_prefix` naming (e.g. `_tok_before`) | Readability |
| | No unauthorized live test (`-m live`) execution | Cost control (P3) |
| **Docs** | No omitting CHANGELOG from code commits | Traceability |
| | No leaving `[Unreleased]` on main | Release discipline |
| | No version mismatch across 4 locations | Single source of truth |
| **PR** | No PR body without HEREDOC | Format consistency |
| | No PR without a "Why" rationale | Decision record |
| | No PR body without Summary/Why/Changes/Verification sections | Information completeness |
| | No merging PRs that haven't passed CI guardrails | Ratchet (P4) |

### Wiring Verification (Anti-Disconnection)

| Item | Rule |
|------|------|
| **Read-Write parity** | Every read path (context injection) must have a corresponding write path (data producer). Verify both ends before marking complete. |
| **Hook registration** | Every hook handler must be registered in bootstrap.py. Handler exists ≠ handler fires. |
| **ContextVar injection** | Every `get_*()` accessor must have a corresponding `set_*()` call in bootstrap. Unset ContextVar → None → silent skip. |
| **Singleton lifecycle** | Singleton created at startup may use stale data. Verify refresh/invalidation path exists for mutable state (OAuth tokens, config). |

### Refactoring Deception Prevention

| Item | Rule |
|------|------|
| **Partial implementation disguise** | No marking plan items complete when only partially implemented |
| **Stub disguise** | No claiming extraction is complete with empty modules (`pass` only) |
| **Original residue** | No marking "extraction complete" while code remains in the original (re-export only is allowed) |
| **Zero-context verification** | Independent agent cross-checks plan document + diff → confirms all items implemented → FAIL on any omission |

### CAN — Permitted Freedoms

Anything not in CANNOT is freely permitted. Specifically:

| Freedom | Description |
|---------|-------------|
| Simple bug/doc fixes | Skip Plan, implement directly in worktree |
| Discovering improvements not in plan | Handle in next iteration after completing current work |
| Selective test execution | Run only tests relevant to changes first, full suite at the end |
| Commit message language | Korean/English freely (maintain consistency only) |
| Tool selection | Freely choose faster tool if results are equivalent |

### Workflow Steps

```
0. Board + Worktree → 1. GAP Audit → 2. Plan + Socratic Gate → 3. Implement+Test → 4. Verify (Implementation GAP Audit) → 5. Docs-Sync → 6. PR → 7. Rebuild → 8. Board
```

#### 0. Board + Worktree Alloc

```bash
# 1) Record Backlog → In Progress on Progress Board (from main)
# Add/move work items in project tracking

# 2) Allocate Worktree
git fetch origin
# Verify main/develop sync (pull if out of sync)
git worktree add .claude/worktrees/<task-name> -b feature/<branch-name> develop
# Note: the target path IS the worktree checkout root; `.owner` is gitignored
# (see /.owner in .gitignore) so the convention does not pollute feature branches.
echo "session=$(date -Iseconds) task_id=<task-name>" > .claude/worktrees/<task-name>/.owner
```

Record on Progress Board then allocate Worktree. On completion: `git push` → `git worktree remove`

#### 1. GAP Audit

> Before implementing, verify "is this actually needed?" through code inspection. Never rebuild what already exists.

**Process**:
1. List TO-BE items from plan documents or issues
2. For each item, use `grep`/`Explore` to **verify whether it already exists in code**
3. Classify into 3 categories:

| Classification | Criteria | Action |
|----------------|----------|--------|
| **Fully Implemented** | Exists in code + tests pass | Remove from plan, move to `_done/` |
| **Partially Implemented** | Code exists but integration/tests incomplete | Implement remaining parts only |
| **Not Implemented** | Does not exist in code | Implementation target |

#### 2. Plan + Socratic Gate

> Simple bug/doc fixes may skip this. All other implementation requires the Socratic Gate.

**Socratic 5 Questions — for each plan item:**

| # | Question | On Failure |
|---|----------|------------|
| Q1 | **Does it already exist in code?** (`grep`/`Explore` verification) | → Remove |
| Q2 | **What breaks if we don't do this?** (actual failure scenario) | No answer → Remove |
| Q3 | **How do we measure the effect?** (tests, metrics, dry-run) | Cannot measure → Defer |
| Q4 | **What is the simplest implementation?** (P10 Simplicity Selection) | Adopt minimum changes only |
| Q5 | **Is this the same pattern across 3+ frontier systems?** (Claude Code, Codex CLI, OpenClaw, autoresearch) | Only 1 → Re-verify necessity |

#### 3. Implement → Unit Verify (iterate)

Code changes → repeat 3 quality gates. Fix on failure.

```bash
uv run ruff check core/ tests/      # Lint: 0 errors
uv run mypy core/                    # Type: 0 errors
uv run pytest tests/ -m "not live"   # Test: 3900+ pass
```

#### 4. Verify (Implementation GAP Audit)

> Confirm the implementation is complete, correct, and free of deception.

**4a. Completeness — Plan vs Diff cross-check**

| Check | FAIL condition |
|-------|---------------|
| Omission | Plan item has no corresponding code change |
| Stub disguise | Function exists but does nothing (`pass`/`return None`) |
| Partial implementation | Only 1 of 3 sub-items done, marked complete |
| Original residue | Code exists in both old and new location |

**4b. Correctness — Quality gates + E2E**

```bash
uv run ruff check core/ tests/                      # Lint: 0 errors
uv run mypy core/                                    # Type: 0 errors
uv run pytest tests/ -m "not live"                   # Test: 3900+ pass
uv run geode analyze "Cowboy Bebop" --dry-run        # E2E: A (68.4) unchanged
```

**4c. Cleanliness — Dead code & regression audit**

| Check | FAIL condition |
|-------|---------------|
| Dead code | Unused import, unreachable function |
| Test deletion | Test file line count decreased |
| Lint bypass | New `# noqa`, `# type: ignore` added |
| Secret exposure | Credentials in committed code |

**4d. Verification team (large-scale changes only)**

See `verification-team` + `anti-deception-checklist` skills.

#### 5. Docs-Sync

See `geode-changelog` skill.

| Sync Target | Verification |
|-------------|--------------|
| Version across 4 locations | CHANGELOG, CLAUDE.md, README.md, pyproject.toml |
| Metrics | Tests, Modules, Commands — measured values |

**Versioning**: New feature = MINOR, Bug fix = PATCH, Docs only = none.

#### 6. PR & Merge

See `geode-gitflow` skill. feature → develop → main. HEREDOC PR. CI 5/5 required.

**PR Body Template (MANDATORY):**

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
| Pipeline node | `graph.py` + E2E |
| LLM adapter | `client.py` + E2E |

#### 7. Rebuild & Restart

After merging to main, rebuild CLI and serve to update the runtime to the latest code.

```bash
# 1) Stop geode serve
kill $(ps aux | grep "geode serve" | grep -v grep | awk '{print $2}')

# 2) Reinstall CLI as editable + sync dependencies
uv tool install -e . --force
uv sync

# 3) Verify version + restart serve
geode version          # Confirm version match
geode serve &          # Restart in background
```

#### 8. Progress Board

Update project tracking from main. Backlog → In Progress → Done.

### Quality Gates

| Gate | Command | Criteria |
|------|---------|----------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Type | `uv run mypy core/` | 0 errors |
| Test | `uv run pytest tests/ -m "not live"` | 3900+ pass |
| E2E | `uv run geode analyze "Cowboy Bebop" --dry-run` | A (68.4) |

## Custom Skills (Scaffold)

Skills used by Scaffold during GEODE development (`.claude/skills/`). Separate from GEODE runtime's `core/skills/` SkillRegistry.

| Skill | Triggers | Content |
|-------|----------|---------|
| `geode-pipeline` | pipeline, graph, topology, send api | StateGraph patterns, node contracts |
| `geode-scoring` | score, psm, tier, rubric, formula | Scoring formulas, 14-axis rubric |
| `geode-analysis` | analyst, evaluator, clean context | Analyst/Evaluator patterns, prompts |
| `geode-verification` | guardrail, bias, cause, decision tree | G1-G4, BiasBuster, Decision Tree |
| `geode-e2e` | e2e, live test, verification, langsmith, tracing | Live E2E patterns, LangSmith verification, quality checks |
| `geode-gitflow` | branch, git, pr, merge, commit | Gitflow strategy, PR templates, CI fix loops |
| `geode-changelog` | changelog, release, version, release | CHANGELOG management, SemVer versioning |
| `karpathy-patterns` | autoresearch, agenthub, ratchet, context budget | 10 autonomous agent design principles (P1-P10) |
| `openclaw-patterns` | gateway, session, binding, lane, plugin | Agent system design patterns (OpenClaw) |
| `frontier-harness-research` | research, gap, frontier, harness, case study | Frontier harness 4-system comparative research process |
| `verification-team` | verification, review, verify, inspect | 5-persona verification (Beck/Karpathy/Steinberger/Cherny + Anti-Deception) |
| `tech-blog-writer` | blog, posting, tech blog | Technical blog writing guide |
| `explore-reason-act` | explore, reason, root cause, read before write | 3-phase explore-reason-act before code modification (REODE backport) |
| `anti-deception-checklist` | deception, fake success, regression | Fake success prevention verification checklist (REODE backport) |
| `code-review-quality` | quality, SOLID, dead code, resource leak | Python code quality 6-lens review (REODE backport) |
| `dependency-review` | dependency, import, layer, circular, lazy | 6-Layer dependency health review (REODE backport) |
| `kent-beck-review` | kent beck, simple design, simplify, god object, SRP | Simple Design 4-rule code review (REODE backport) |
| `codebase-audit` | audit, dead code, refactor, god object, duplication | Code audit + refactoring workflow (v0.24.0 proven) |
| `geode-serve` | serve, gateway, slack, binding, poller, config.toml | Slack Gateway operations + debugging guide |
