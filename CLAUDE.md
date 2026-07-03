# GEODE — Claude Code Scaffold

> This file is the **production scaffold** for building GEODE.
> Claude Code reads this file to understand development workflow, quality gates, and constraints.
> For GEODE's runtime identity and architecture, see `GEODE.md`.

## Project Overview

A general-purpose autonomous execution agent. The core runtime is an **AgenticLoop** (`while tool_use`) — sub-agents, plans, and batches are all instances of the same loop. Autonomously performs research, analysis, automation, and scheduling.

- **Version**: 0.99.272
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Points**: `geode` (`core.cli:app`, Typer) / `geode-mcp` (`core.mcp_server:main`)
- **Modules**: 405 core + 77 plugins = 482
- **Tests**: 9264 (+1 live)
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
| Agent Identity | `GEODE.md` | Identity, Voice & Conduct, runtime architecture, LLM models |
| Operational Workflow | `docs/workflow.md` + `.claude/skills/geode-workflow/` | Evidence-first execution scaffold shared by Claude Code, Codex, and contributors |
| Hook System | `docs/architecture/hook-system.md` | HookSystem 65 events |
| Scaffold | `CLAUDE.md` | Development workflow, quality gates, CANNOT/CAN (this file) |

## Project Structure

Production code splits into two top-level Python packages:
- `core/` — general-purpose autonomous agent runtime. 5-layer stack (layer diagram → `GEODE.md` → Architecture).
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

The canonical execution loop is `docs/workflow.md` plus the Claude Code project
skill `.claude/skills/geode-workflow/`. Claude Code should use the skill as the
step-by-step scaffold with progressive disclosure, while this file remains the
rulebook for constraints, quality gates, and project-specific rationale.

> **Design Principle**: CANNOT (guardrails) comes before CAN (freedom). Constraints guarantee quality. (Karpathy P1, OpenClaw Policy Chain, Codex Sandbox)

### CANNOT — Absolute Prohibition Rules

> Development-time guardrails — what the *engineer* must not do when building GEODE.
> For runtime guardrails (what GEODE the *agent* refuses to do at execution time), see `GEODE.md` → `## RUNTIME CANNOT`.

These cannot be violated at any stage. Violations must be immediately halted and corrected.
Rationale cites the originating incident when one exists. The `karpathy-patterns` skill's "Anti-patterns" table is the abstract counterpart — this table holds the concrete project-level rules and the sprint incidents that produced them. Before every PR push, scan for an analogous pattern; if your PR could match a row, it probably does.

| Area | Rule | Rationale |
|------|------|-----------|
| **Git** | No code work without a worktree (allocation procedure → [§0](#0-board--worktree-alloc)) | Isolated execution (OpenClaw Session) |
| | No direct push to main/develop — PR → CI → merge | Ratchet (P4) |
| | No deleting other sessions' worktrees (`.owner` mismatch) | Ownership protection |
| | No `git checkout` switching within a worktree | Isolation maintenance |
| | No modifying tracking documents from feature/develop | Single source of truth on main |
| | No branch creation when remote is out of sync | Conflict prevention |
| | No claiming "branch needs sync" from commit count alone — verify content with `git diff A B --stat` first | Graph asymmetry ≠ content asymmetry (gitflow merge commits) |
| **Planning** | No starting implementation without Socratic Gate (except bugs/docs) | Prevent over-engineering |
| | No interpreting ambiguous "제거"/"remove" as code-path deletion — disambiguate first (knob vs deletion) | Avoid wasted reverts. *Incident: PR-fallback-knob ~30-file revert (2026-05-21)* |
| **Quality** | No committing with lint/type/test failures | Ratchet (P4) |
| | No placeholders (XXXX) in metrics — measured values only | Truth guarantee |
| | No excessive `# type: ignore` — fix type errors instead | Correctness |
| | No bare `_` for unused variables — use `_prefix` naming (e.g. `_tok_before`) | Readability |
| | No unauthorized live test (`-m live`) execution | Cost control (P3) |
| | No gate / CI-status command behind an exit-code absorber — never `gate \| tail`, `gate \| grep -c`, or `check; merge`. Assert gates bare; gate merges on the REAL result (`test "$(gh pr checks N \| grep -cE 'fail\|pending')" -eq 0 && gh pr merge …`) | Gate integrity. *Incidents (2026-07-02/03, same session): PR #2463 merged with a failing Test job because the check was chained with `;`; the slop-ratchet failure on PR #2482 was invisible locally behind `\| tail -1`. A swallowed exit code turns every downstream "green" claim into fiction.* |
| | No "graceful" return contract without applying it at every schema-typed cast (not just outer try) | Boundary completeness. *Incident: PR-G3 #1347 (2026-05-20) — `float()` on non-numeric raised before contract* |
| | No seed / pool referencing a dim outside the live fitness taxonomy (`core.self_improving.fitness.AXIS_TIERS`) — a phantom-dim "hallucination" (the audit probes a removed dimension, the held-out ruler pins at the floor, the gate rejects every cycle for a measurement reason = invalid experiment). When a dim is dropped (e.g. PR-DROP-ANALYTICS-DIMS), every pool referencing it goes stale. Validate at **assemble time** (`scripts/assemble_seed_pool.py` → `validate_pool_target_dims`), not only at campaign runtime. | Phantom-dim drift. *Incident: held-out `gen-2605-*-redundant_tool_invocation` stale after the dim was removed; the campaign HALTed but the stale pool had already shipped — fail at assemble so it never enters the pipeline (2026-06-11). Guard: `tests/scripts/test_assemble_stale_dim_guard.py`* |
| | No conflating "latest" and "promoted" SoTs — readers must document which they assume; persist both if the loop needs both | SoT clarity. *Incident: PR-G2 #1346 (2026-05-20) — downstream read stale evidence forever* |
| | No dual SoT (disk + fallback literal) without shared anchor + drift invariant test | Drift prevention. *Incident: PR-MINIMAL-2 #1398 (2026-05-21) — `program.md` ↔ `_FALLBACK_SYSTEM_PROMPT` divergence* |
| | No external-SDK / 3rd-party-backend capability assumption (e.g. ``supports_X=True``, hosted tool acceptance, model availability) hardcoded as ``True`` without `ctx7 library` + `ctx7 docs` verification first; if ctx7 is ambiguous, mark the assumption ``unverified — live test required`` in the docstring and surface the live-test as an explicit pending verification | Doc-before-behaviour. *Incident: PR-NO-FALLBACK #1839 (2026-05-28) — `codex_oauth.supports_web_search` flipped False → True based on SDK ``ToolParam`` Union alone; Codex backend's actual acceptance of ``{"type": "web_search"}`` is undocumented in ctx7 / Codex CLI repo, so the assumption needed a live-test gate rather than a behavioural test* |
| | No deep-linking into a vendored SPA viewer (Inspect View / petri-bundle / seed-generation bundle) by *assuming* its URL/route scheme — verify the route against the bundle's actual JS (`createHashRouter`, `navigate(...)` calls) before generating links. Inspect View exposes only `#/logs/<encodeURIComponent(eval_filename)>`; there is **no** `/tasks/<id>` route. Key deep-links on the `logs/listing.json` filename, never the task_id. | Artifact-before-behaviour. *Incident: PR-HUB-AUDIT-DEEPLINK (2026-05-30) — `#/tasks/<task_id>` (plus a `.eval`-header-scan apparatus built only to extract the 22-char task_id) targeted a route that does not exist, so every audit/seedgen deep-link silently fell back to the run list. Guard: `tests/test_self_improving_hub_e2e.py::test_audit_deeplinks_use_logs_route_and_resolve`* |
| **Docs** | No omitting CHANGELOG from code commits | Traceability |
| | No leaving `[Unreleased]` on main | Release discipline |
| | No version mismatch across 5 locations | Single source of truth |
| | No non-English content in files injected into LLM context (`GEODE.md`, memory, prompts) — the model consumes them at runtime | Prompt clarity (moved from GEODE.md Conventions, PR-GEODE-SOUL) |
| | No emoji as section anchors / nav prefixes; no decorative card grids when content is data — dense table/list only on docs/site/CLI surfaces | Slop signal. *Incident: PR-CSP-14-UI mockup (2026-05-23) — see [[feedback-no-box-ui-no-emoji]]* |
| | No colored left-border accent bars on cards/blocks (`border-left: Npx solid var(--bucket-*)`); use a neutral hairline (`var(--rule)`), an uppercase role-label, or spacing. No box-card grid as a *navigation* surface (extends the card-grid rule above) — use a dense inline link row/list. Minimize decorative `--`/`&mdash;` separators (prefer `·` / `.` / `,`). | Slop signal. *Incident: lineage-station / mutator-banner accent bars + run-page sub-view card grid, PR-HUB-DESLOP (2026-05-29) — see [[feedback-no-box-ui-no-emoji]]* |
| **Naming** | No abstract-noun package names (`text`, `storage`, `runtime_state`, `helpers`, `common`, `lib`, `manager`) — use domain-verb / domain-noun (claude-code-ref / openclaw / hermes / crumb all converge). *Incident: PR-CLEANUP-2 #1562 (2026-05-23) folded 3 such packages.* | Frontier convergence + [[feedback-explicit-naming]] |
| | No same-name-nested folders (`X/X/`) — flatten or rename inner | Frontier 0/7 do this; GEODE had `core/scheduler/scheduler/` |
| | No single-file packages — fold into the nearest domain sibling | PR-CLEANUP-2 precedent (`core/text/`, `core/storage/`) |
| | No `_helpers.py` / `_utils.py` / `_misc.py` filenames once a caller appears — rename to the actual responsibility (the catch-all suffix hides intent) | autoresearch / openclaw avoid; PR-CLEANUP-1 absorbed `_announce.py` + `_decomposition.py` for similar reason |
| **Compat** | No re-export shim / backward-compat module past its 1-release grace — delete it and migrate callers in the same PR | *Incidents: `core/llm/client.py` removed PR-CLEANUP-4, `core/agent/loop/loop.py` removed PR-CLEANUP-1* |
| **Registry** | No two registries for the same domain (skill / tool / adapter / plugin) — one schema, one loader, one call surface | *Incident: `core/llm/skill_registry.py` ↔ `core/skills/skills.py` parsing the same `~/.geode/skills/*.md` twice* |
| **PR** | No PR that violates the [§6 template](#6-pr--merge) (HEREDOC body with Summary/Why/Changes/Verification) or merges without CI 5/5 green | Format + traceability + Ratchet (P4) |

### CAN — Permitted Freedoms

Anything not in CANNOT is freely permitted. Specifically:

| Freedom | Description |
|---------|-------------|
| Simple bug/doc fixes | Skip Plan, implement directly in worktree |
| Discovering improvements not in plan | Handle in next iteration after completing current work |
| Selective test execution | Run only tests relevant to changes first, full suite at the end |
| Commit message language | Korean/English freely (maintain consistency only) |
| Tool selection | Freely choose faster tool if results are equivalent. For external library/SDK API questions, ground via `ctx7 library <name>` → `ctx7 docs <id>` before quoting (avoid recalled-from-training hallucination). |
| Cleanup / refactor PRs may bundle aggressively | The Socratic Q4 "minimum change" guard does **not** apply when the PR's purpose *is* cleanup — find every fold, prune, and rename in scope and ship them together. (cf. [[feedback-cleanup-no-minimal-change]]) |

### Wiring Verification (Anti-Disconnection)

> Static parity invariants for runtime wiring (writer-reader, hook-bootstrap, ContextVar set-get).
> For *pre-change* workflow (read-before-write, hypothesis), see `explore-reason-act` skill.
> For *static dependency health* (layer violations, circular imports, eager loading), see `dependency-review` skill.

| Item | Rule |
|------|------|
| **Read-Write parity** | Every read path (context injection) must have a corresponding write path (data producer). Verify both ends before marking complete. |
| **Hook registration** | Every hook handler must be registered in bootstrap.py. Handler exists ≠ handler fires. |
| **ContextVar injection** | Every `get_*()` accessor must have a corresponding `set_*()` call in bootstrap. Unset ContextVar → None → silent skip. |
| **Singleton lifecycle** | Singleton created at startup may use stale data. Verify refresh/invalidation path exists for mutable state (OAuth tokens, config). |
| **Conditional read parity** | A reader that loads context in ONE branch (e.g. auto-pick) must load it in the SYMMETRIC branch (explicit input) too — otherwise the feature half-disconnects depending on call shape. *Incident: PR-G3 #1347 (2026-05-20) — `_resolve_target_dim` loaded baseline only for `--target-dim auto`.* |
| **Writer destination tracked** | Every file the code writes for "audit / history / ledger" must be `git check-ignore`-clean. An ignored path silently breaks `git add`; the writer thinks it persisted, history doesn't. *Incident: PR-G5b #1350 (2026-05-20) — `autoresearch/state/mutations.jsonl` silently ignored, caught by Codex MCP after 8/8 CI green; pinned by `test_policy_files_not_gitignored`.* |
| **Index regenerated, not just read** | A renderer that reads an index/listing file (hub seeds `listing.json`, search index, manifest) must REGENERATE it from the source dir, not assume an upstream step refreshed it. A read-only renderer over a stale index silently drops newly-added items with no error. *Incident: a seed-gen run synced to the bundle rendered no hub page because `geode hub build` only read a stale `listing.json` — the operator had to remember the separate `build_seeds_listing` step (frontier-2612-bt, 2026-06-12). Fixed: `load_seedgen` rebuilds the listing first. Guard: `tests/scripts/test_hub_listing_autobuild.py`* |

### Refactoring Deception Prevention

| Item | Rule |
|------|------|
| **Implementation completeness** | No marking plan items complete when partially implemented, stubbed (`pass` only), or shelled out as re-exports while code remains in the original. An independent zero-context agent cross-checks plan + diff and FAILs on any omission. See `verification-team` + `anti-deception-checklist` skills for the operational checklist. |
| **CHANGELOG/PR-body parity** | Every verb/adjective in the PR title + CHANGELOG ("git-tracked", "X-driven", "automatic", "committed") must be grep-provable in code. Run `git check-ignore`, `grep -rn "<source-doc>"`, and "is there a caller?" before push. *Incident: PR-G5b #1350 (2026-05-20) — both "git-tracked audit log" and "program.md-driven runner" were un-backed; fixed in `runner.py:_load_program_md` and pinned by `test_load_program_md_actually_reads_disk_file`.* |

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

Record on Progress Board then allocate Worktree. On completion (after the PR merges): tear down all three stale artifacts — remote branch, worktree, local branch — per [§6 Post-Merge Cleanup](#post-merge-cleanup-mandatory-after-every-merge).

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

Code changes → re-run the [Quality Gates](#quality-gates) on each iteration. Fix on failure before continuing.

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

All 4 [Quality Gates](#quality-gates) must pass (lint / type / test / CLI smoke) plus any E2E relevant to the change.

**4c. Cleanliness — Dead code & regression audit**

Run the `anti-deception-checklist` skill — it covers test deletion/disabling, lint bypass (`# noqa`, `# type: ignore`), coverage regression, secret exposure, and dependency downgrade. Any FAIL verdict blocks merge.

**4d. External-contract attestation — doc-before-behaviour**

When the PR introduces or flips an assumption about an external SDK or 3rd-party backend (capability flag, hosted tool acceptance, endpoint behaviour, model availability), run `ctx7 library <name>` → `ctx7 docs <id> "<question>"` **before** any agent-behaviour live test. Three outcomes:

| ctx7 result | Action |
|-------------|--------|
| Confirms the assumption | Cite the ctx7 source (file path on GitHub) in the docstring next to the assumption (`# ref: openai/types/responses/tool_param.py:ToolParam`). |
| Refutes the assumption | Revert the change. Open a separate decision branch about why the assumption was tempting (often a misread doc, fix the misread). |
| **Ambiguous** (SDK contract allows, backend acceptance undocumented) | Mark the assumption ``unverified — live test required`` in the docstring + open a follow-up task. Do not let the behaviour land in production behind a True-flag without the live-test gate. Honest error message on the dispatch path is the safety net but does not substitute for the gate. |

*Incident: PR-NO-FALLBACK #1839 (2026-05-28) flipped `codex_oauth.supports_web_search` to `True` based on the SDK `ToolParam` Union alone; ctx7 of `/openai/codex` showed Responses API accepts a `tools` array but does NOT document which `type` values the Codex backend accepts. The assumption should have shipped as `unverified` until a live test confirmed.*

**4e. Verification team (large-scale changes only)**

See `verification-team` + `anti-deception-checklist` skills.

#### 5. Docs-Sync

See `geode-changelog` skill.

| Sync Target | Verification |
|-------------|--------------|
| Version across 5 locations | CHANGELOG, CLAUDE.md, README.md, README.ko.md, pyproject.toml |
| Metrics | Tests, Modules, Commands — measured values |
| 사이트 버전 SoT | `site/public/llms.txt` + `llms-full.txt`의 `Version vX` 헤더 **및** `site/src/data/geode/sot.ts`의 `version` == pyproject. 버전 범프 시 `node site/scripts/sync-stats.mjs` (llms.txt + sot.ts + changelog.ts 재생성) + `uv run python scripts/check_llms_version.py --fix` (llms-full 헤더). 드리프트는 ci.yml `check_llms_version.py` ratchet가 3파일 전부 차단(committed 스냅샷이 12버전 stale했던 사건). llms-full 본문은 배포 빌드(pages.yml)가 갱신. |

**Versioning**: New feature = MINOR, Bug fix = PATCH, Docs only = none.

#### 6. PR & Merge

See `geode-gitflow` skill. **Flow**: `feature → develop` **squash-merged** (one commit per change — collapses Codex-round fix commits; no per-feature merge commit on main), then `develop → main` pass-through `--merge`. HEREDOC PR. CI 5/5 required.

> **Before EVERY `develop → main` merge, sync `main → develop` first** (`gh pr create --base develop --head main` → merge) so develop ⊇ main and never merges while lagging. The only recurring main-only drift is the kanban (`docs/progress.md`, committed on main post-merge); the pre-sync pulls the prior cycle's kanban into develop each time, so it self-heals and never accumulates. *This replaces the deleted `auto-backmerge.yml` workflow, which fired on every push to main and piled up unmerged main→develop PRs (10 open at once, 2026-06-14) because the feature/main divergence is never a fast-forward. Manual pre-sync is the single, deliberate back-merge per cycle.*

> **Concurrent-session drift is expected, not an anomaly.** While your feature PR is open, another session (Tau2 promotion, a scheduled routine) may merge to develop — your PR then goes `CONFLICTING`/`DIRTY` (usually a CHANGELOG top-entry collision) and/or your version number gets taken. Recover per `geode-gitflow` skill § "Concurrent-session drift & CI-trigger recovery": merge `origin/develop`, **fold** the concurrent `[Unreleased]`/entry into your release version (never leave `[Unreleased]`), re-verify the version number is still free, then **regenerate the derived version SoT** (`sync-stats.mjs` + `check_llms_version.py --fix`) or the CI ratchet blocks on a stale `changelog.ts`. Separately, a freshly-opened PR that attaches **0 CI checks** (webhook miss — verify with `gh api commits/<sha>/check-runs .total_count`, not `gh pr checks` alone) is re-triggered by `gh pr close <N> && gh pr reopen <N>`; don't leave a monitor spinning on the repeating "no checks" error.

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
| LLM adapter | `core/llm/router/` + `core/llm/providers/` + E2E |

##### Post-Merge Cleanup (MANDATORY after every merge)

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

#### 7. Rebuild & Restart

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

#### 8. Progress Board

Update project tracking from main. Backlog → In Progress → Done.

### Quality Gates

| Gate | Command | Criteria |
|------|---------|----------|
| Lint | `uv run ruff check core/ tests/ plugins/ scripts/` | 0 errors — `scripts/` 포함 (CI ci.yml:60과 동일 범위; PR-CLEANUP-D2에서 로컬 게이트가 scripts/를 빼먹어 CI에서 2회 반려된 사건) |
| Format | `uv run ruff format --check core/ tests/ plugins/ scripts/` | 0 reformats |
| Type | `uv run mypy core/ plugins/` | 0 errors |
| Imports | `uv run lint-imports` | contracts kept |
| Test | `uv run pytest tests/ -m "not live"` | 9200+ pass |
| CLI smoke | `uv run geode version` | version prints |

> 게이트 명령을 파이프로 감싸지 말 것 — `ruff check … \| tail -1` 은 zsh 기본
> pipefail off라 ruff의 exit 1을 삼켜 `&&` 체인이 실패를 통과시킨다. heredoc
> 수정 스크립트는 실패가 후속 명령을 막도록 같은 `&&` 체인에 묶고, push 직전
> 게이트를 풀 출력으로 한 번 더 단언한다 (PR-CLEANUP-D2 no-op 커밋 사건).

## Custom Skills (Scaffold)

Skills used by Scaffold during GEODE development (`.claude/skills/`). Separate from GEODE runtime's `core/skills/` SkillRegistry.

> `.claude/skills/` is gitignored (scaffold-local); the rows below are the repo-tracked set that ships with a clone. Additional local-only skills (e.g. `model-onboarding`, `codex-mcp-verify`, `smoke-green-loop`) may exist per machine and are intentionally not listed.

| Skill | Triggers | Content |
|-------|----------|---------|
| `geode-workflow` | workflow, scaffold, feature work, provider/model changes, GUI/computer-use, observability, verification | Evidence-first execution scaffold with progressive-disclosure references |
| `geode-gitflow` | branch, git, pr, merge, commit | Gitflow strategy, PR templates, CI fix loops |
| `geode-changelog` | changelog, release, version, release | CHANGELOG management, SemVer versioning |
| `agent-ops-debugging` | safe default, root cause, contextvar, multi-gap | Agent-ops debugging patterns — Safe Default anti-pattern, multi-gap root cause, ContextVar DI |
| `architecture-patterns` | architecture, layering, pattern, design | Cross-harness architecture patterns reference |
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
| `baseline-epoch-partition` | baseline epoch, baseline 아카이빙, epoch partition, spec hash, content-addressed, margin_rule namespace, production logic 구분, baseline 하위 서빙 | Content-addressed baseline-archive epoch 분할 — baseline 산출+측정 명세(margin_rule + logic version tag + 4-role model/source + rubric/dim-set + bench + seed-pool identity)를 canonical 해시 → epoch 구분자. spec vs instance 분리, version-tag(소스해시 아님), write-time frozen hash + spec_schema_version, hash+label 병기. hub baseline-하위 epoch 적재(gen-* 미러). |
