# GEODE — Claude Code Scaffold

> This file is the **production scaffold** for building GEODE.
> Claude Code reads this file to understand development workflow, quality gates, and constraints.
> For GEODE's runtime identity and architecture, see `GEODE.md`.

## Project Overview

A general-purpose autonomous execution agent built on LangGraph. Autonomously performs research, analysis, automation, and scheduling.

- **Version**: 0.99.44
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)
- **Modules**: 355 core + 58 plugins = 413
- **Tests**: 6849 (+5 live)
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

# Domain analysis plugins are distributed separately from GEODE core.
```

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Agent Identity | `GEODE.md` | Runtime architecture, LLM models, conventions |
| Hook System | `docs/architecture/hook-system.md` | HookSystem 69 events |
| Scaffold | `CLAUDE.md` | Development workflow, quality gates, CANNOT/CAN (this file) |

## Project Structure

Production code splits into two top-level Python packages:
- `core/` — general-purpose autonomous agent runtime. 4-layer stack.
- `plugins/` — first-party auxiliary plugins.

Check module count: `find core/ -name "*.py" | wc -l` for core, `find plugins/ -name "*.py" | wc -l` for plugins.
Key entry points: `core/agent/loop/`(AgenticLoop), `core/runtime.py`(bootstrap).

## Development

```bash
# Test
uv run python -m pytest tests/ -q

# Lint (core + plugins both gated)
uv run ruff check core/ tests/ plugins/

# Type check (core + plugins both gated)
uv run mypy core/ plugins/
```

### Expected Test Results

Core tests pass without bundled analysis fixtures. External packages own their
own fixture/E2E gates.

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
| | No version mismatch across 5 locations | Single source of truth |
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
| **Conditional read parity** | A reader that loads context in ONE branch (e.g. auto-pick) must load it in the SYMMETRIC branch (explicit input) too — otherwise the feature half-disconnects depending on call shape. |
| **Writer destination tracked** | Every file the code writes for "audit / history / ledger" must be `git check-ignore`-clean. An ignored path silently breaks `git add`; the writer thinks it persisted, history doesn't. |

### Refactoring Deception Prevention

| Item | Rule |
|------|------|
| **Partial implementation disguise** | No marking plan items complete when only partially implemented |
| **Stub disguise** | No claiming extraction is complete with empty modules (`pass` only) |
| **Original residue** | No marking "extraction complete" while code remains in the original (re-export only is allowed) |
| **Zero-context verification** | Independent agent cross-checks plan document + diff → confirms all items implemented → FAIL on any omission |
| **CHANGELOG/PR-body parity** | Every verb/adjective in the PR title + CHANGELOG ("git-tracked", "X-driven", "automatic", "committed") must be grep-provable in code. Run `git check-ignore`, `grep -rn "<source-doc>"`, and "is there a caller?" before push. |

### DONT — Real Incidents (case studies)

Karpathy program.md style: paste the failure verbatim so future-you doesn't repeat it.
Append (don't rotate) — each row is a *frozen* lesson.

| Date | Anti-pattern | What you said | What the code did | Lesson |
|------|--------------|---------------|-------------------|--------|
| 2026-05-20 PR-G5b #1350 | CHANGELOG/PR-body parity violation | "git-tracked audit log of every applied mutation" | `MUTATION_AUDIT_LOG_PATH = autoresearch/state/mutations.jsonl`, but `.gitignore` matches `autoresearch/state/*`. `git add` fails silently; `_git_commit_audit_log` returns False; ledger never enters git. | Run `git check-ignore <path>` on every path the PR claims is "tracked / committed / persisted". Caught by Codex MCP, missed by ruff/mypy/pytest/CI 8-of-8. Codified as test guard in `tests/test_ratchet_policies_in_repo.py::test_policy_files_not_gitignored` after PR-RATCHET-1 (2026-05-21). |
| 2026-05-20 PR-G5b #1350 | CHANGELOG/PR-body parity violation | "program.md-driven self-improving loop runner" | `_SYSTEM_PROMPT` is a hardcoded f-string; `grep -rn "program.md" core/ autoresearch/` shows zero reads. PR title overstates implementation. | Any "X-driven" claim → `grep` for X. If the file isn't loaded, the claim is fiction. Fixed in `runner.py:_load_program_md` (G5b.fix1.b); pinned by `tests/test_self_improving_minimal_1.py::test_load_program_md_actually_reads_disk_file` (PR-MINIMAL-1, 2026-05-21). |
| 2026-05-20 PR-G3 #1347 | Conditional read parity | "seed-generation reads baseline.json evidence" | `_resolve_target_dim` loads baseline ONLY in the `--target-dim auto` branch; explicit `--target-dim <name>` returns `(dim, None)`. Half the call sites get no evidence. | A new context-loading feature must work for ALL call shapes that touch the same downstream prompt. Symmetric branches > one-sided wiring. |
| 2026-05-20 PR-G3 #1347 | Graceful-contract violation | "`load_baseline` returns `None` on unparseable JSON" | True for malformed JSON, but `float(v)` on non-numeric `dim_means` raises `ValueError` before the contract kicks in. | "Graceful" must be defined at every input boundary, not just the outer try. Schema-typed casts need their own try. |
| 2026-05-20 PR-G2 #1346 | Reader-assumption drift | "evidence in baseline.json reaches downstream" | Evidence only persists when the audit PROMOTES the baseline. A failing/regressed audit never updates `baseline.json` → downstream reads stale evidence forever. | "Latest" and "promoted" are different SoTs. Document which one each reader assumes; persist both if the loop needs them. |
| 2026-05-21 PR-fallback-knob | Premature scope expansion (deletion vs knob) | "FALLBACK 체인과 레이어를 제거해. Self-improving Loop + Agentic Loop 스코프에 전역으로 지켜야할 사안" → interpreted as *delete every code path*. After Steps 1-8 finished (~30 files), the user clarified "사용자가 명시적으로 튜닝할 여지를 남겨두는거면 찬성이야" — the intent was a *user-tunable knob*, not full deletion. | When a user directive says "제거" without specifying *what* is being removed (the silent default behaviour vs. the entire code path), pause to disambiguate: ask "should the chain be a knob the user can opt into, or should the chain code itself be deleted?" The cheap one-question gate would have saved ~30 edits + a `git checkout origin/develop -- <files>` revert. |
| 2026-05-21 PR-MINIMAL-2 #1398 | Silent dual-prompt drift | The mutator runner reads `autoresearch/program.md` from disk via `_load_program_md()`; on `OSError` (missing file / unreadable) it falls back to the hardcoded `_FALLBACK_SYSTEM_PROMPT` literal. If an operator edits `program.md` but not the fallback (or vice versa), the LLM sees a different contract depending on whether the disk read succeeds — the loop continues running but with mismatched instructions. | Pin a stable anchor that BOTH paths must share (`## Setup` header in program.md, mutation-contract schema fields like `target_section`/`new_value`/`rationale` in the fallback) via a drift invariant test. Codified at `tests/test_self_improving_minimal_2.py::test_fallback_prompt_shares_setup_anchor_with_program_md` (PR-MINIMAL-2, 2026-05-21). |
| 2026-05-23 PR-CSP-14-UI mockup | Slop UI signals — box-card + emoji | Initial literature-bundle mockup used emoji card icons (📊 audit / 📚 literature / 🧪 seeds / 🔬 validation) + rounded card boxes with hover-lift for the landing grid. User flagged as Slop signals — LLM-generated boilerplate aesthetic, not GEODE's dense-information style. | Never use emoji as section anchors / card titles / nav prefixes on docs/site/CLI surfaces. Prefer dense `<table>` + `<dl>` over decorative `<div class="card">` grids when content is data. Hierarchy via typography (h1/h2/h3 weight), not bordered card boxes. Emoji only allowed in opt-in report-generation outputs (CHANGELOG / blog posts). See `[[feedback-no-box-ui-no-emoji]]` for the full rule. |

**How to use this table**:
1. Before every PR push, scan the table for an analogous pattern. If your PR could match a row, it probably does.
2. When a new incident lands, append (don't rewrite). The table is the project's accumulated immune system.
3. The `karpathy-patterns` skill's "Anti-patterns" table is the abstract counterpart; this table holds the concrete sprint-level evidence.

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
uv run ruff check core/ tests/ plugins/      # Lint: 0 errors
uv run mypy core/ plugins/                    # Type: 0 errors
uv run pytest tests/ -m "not live"            # Test: 3900+ pass
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
uv run geode version                                 # CLI smoke
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
| Version across 5 locations | CHANGELOG, CLAUDE.md, README.md, README.ko.md, pyproject.toml |
| Metrics | Tests, Modules, Commands — measured values |

**Versioning**: New feature = MINOR, Bug fix = PATCH, Docs only = none.

#### 6. PR & Merge

See `geode-gitflow` skill. **Flow**: `feature → develop` (per-change), then for releases `release/* → develop → main` (the release branch carries stamp + CHANGELOG bumps; it merges into develop *first* so develop never lags behind main on those files; develop → main is then a straight pass-through). HEREDOC PR. CI 5/5 required. `.github/workflows/auto-backmerge.yml` is the safety net — fires only if some past release skipped the rotation and develop drifts behind main.

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
| Lint | `uv run ruff check core/ tests/ plugins/` | 0 errors |
| Type | `uv run mypy core/ plugins/` | 0 errors |
| Test | `uv run pytest tests/ -m "not live"` | 3900+ pass |
| CLI smoke | `uv run geode version` | version prints |

## Custom Skills (Scaffold)

Skills used by Scaffold during GEODE development (`.claude/skills/`). Separate from GEODE runtime's `core/skills/` SkillRegistry.

| Skill | Triggers | Content |
|-------|----------|---------|
| `geode-pipeline` | pipeline, graph, topology, send api | StateGraph patterns, node contracts |
| `geode-scoring` | score, tier, rubric, formula | Generic scoring formulas and rubric patterns |
| `geode-analysis` | analyst, evaluator, clean context | Analyst/Evaluator patterns, prompts |
| `geode-verification` | guardrail, bias, cause, decision tree | G1-G4, panel guard, Decision Tree |
| `geode-e2e` | e2e, live test, verification, tracing | Live E2E patterns, native observability verification, quality checks |
| `geode-gitflow` | branch, git, pr, merge, commit | Gitflow strategy, PR templates, CI fix loops |
| `geode-changelog` | changelog, release, version, release | CHANGELOG management, SemVer versioning |
| `karpathy-patterns` | autoresearch, agenthub, ratchet, context budget | 10 autonomous agent design principles (P1-P10) |
| `openclaw-patterns` | gateway, session, binding, lane, plugin | Agent system design patterns (OpenClaw) |
| `frontier-harness-research` | research, gap, frontier, harness, case study | Frontier harness 4-system comparative research process |
| `verification-team` | verification, review, verify, inspect | 5-persona verification (Beck/Karpathy/Steinberger/Cherny + Anti-Deception) |
| `tech-blog-writer` | blog, posting, tech blog | Technical blog writing guide |
| `explore-reason-act` | explore, reason, root cause, read before write | 3-phase explore-reason-act before code modification |
| `anti-deception-checklist` | deception, fake success, regression | Fake success prevention verification checklist |
| `code-review-quality` | quality, SOLID, dead code, resource leak | Python code quality 6-lens review |
| `dependency-review` | dependency, import, layer, circular, lazy | 6-Layer dependency health review |
| `kent-beck-review` | kent beck, simple design, simplify, god object, SRP | Simple Design 4-rule code review |
| `codebase-audit` | audit, dead code, refactor, god object, duplication | Code audit + refactoring workflow (v0.24.0 proven) |
| `geode-serve` | serve, gateway, slack, binding, poller, config.toml | Slack Gateway operations + debugging guide |
| `long-task-watcher` | monitor, tail -F, progress, background, live audit, stdbuf, buffering | Long-running task watching patterns. Covers the Petri × GEODE N7' Monitor timeout case and stable watch patterns (cat-and-grep / stdbuf streaming / polling). |
| `manim-scene-craft` | manim, scene, 영상, 비디오, 1080p60, EN/KO 렌더, GEODE_HERO_LANG | Manim Community Scene 작성 표준 — EN/KO 다국어 lang, Helvetica Neue + Pretendard 폰트 페어링, Anthropic-style 팔레트, layout ratchet + CI 가드. 4 검증 scene (`geode_hero` / `autoresearch_filewalk` / `autoresearch_compare` / `critical_floor`) 의 공통 패턴. |
| `viz-frame-audit` | 노이즈, slop, 프레임 검수, 영상 audit, 글자 깨짐, 패딩 침범, frame extract, naive arrow | 영상 노이즈/slop 검수 워크플로우 — ffmpeg 프레임 추출 + Read 시각 확인 + 4 카테고리 결함 식별 (naive 화살표 / 패딩 침범 / 글자 깨짐 / 프레임 순서). 12+ 사례 카탈로그 (filewalk 7 + hero 7). |
| `docs-link-audit` | broken link, 404, docs link, hyperlink, 링크 점검, 링크 깨짐, audit links, link checker | Docs-site (`site/` Next.js) body / JSX / markdown link audit. `scripts/check_docs_links.py` validates 4 categories (internal /docs / internal /other / anchor / external), build-time copy awareness, and exit-code-based CI guard wiring. Includes PR #1157/#1161 case studies. |
| `seed-generation-cycle` | seed-generation, sprint, cycle, S2, S3, …, scaffold cycle | Session 63 의 6-PR (S0/S1/S2/S2-wire/S2-fix/cycle-skill) 검증 사이클 — Phase A-F (Allocation / Implement+P1-P7 / Verify+Codex MCP / PR&CI / Merge / Optional Review). S2.5-S12 + 모든 fix-up PR 적용. |
