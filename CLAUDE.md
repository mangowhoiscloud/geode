# GEODE — Claude Code Scaffold

> This file is the **production scaffold** for building GEODE.
> Claude Code reads this file to understand development workflow, quality gates, and constraints.
> For GEODE's runtime identity and architecture, see `GEODE.md`.

## Project Overview

A general-purpose autonomous execution agent. The core runtime is an **AgenticLoop** (`while tool_use`) — sub-agents, plans, and batches are all instances of the same loop. Autonomously performs research, analysis, automation, and scheduling.

- **Version**: 1.0.27
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Points**: `geode` (`core.cli:app`, Typer) / `geode-mcp` (`core.mcp_server:main`)
- **CHANGELOG**: `CHANGELOG.md` (Keep a Changelog + SemVer)

## Quick Start

```bash
# Install
uv sync

# Thin CLI (auto-starts serve daemon if needed)
uv run geode

# Enter a prompt in the interactive thin client.
```

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Agent Identity | `GEODE.md` | Identity, Voice & Conduct, runtime architecture, LLM models |
| Operational Workflow | `docs/workflow.md` + `.claude/skills/geode-workflow/` | Evidence-first execution scaffold shared by Claude Code, Codex, and contributors |
| Code Conventions | `docs/architecture/naming-conventions.md` + `.agents/skills/geode-code-conventions/` | Measured abstraction, naming, type/class, schema, test, site, and versioning decisions |
| Evaluation Workflow | `docs/eval/index.json` + `.agents/skills/geode-eval/` | Generated eval routing, frozen research/reproduction contract, append-only attempt lineage, analysis, and artifact publication |
| Test-Time Compute Grounding | `.claude/skills/stanford-test-time-compute/` | Stanford CS329A Part 2 evidence and GEODE/Eco²/SIL/Crucible application boundaries |
| Agent-World Benchmark | `docs/eval/agent-world-comparison-contract.md` + `.claude/skills/agent-world-benchmark/` | Three-suite comparison profile, paired runtime control, replication, and artifact contract |
| Architecture/Extensibility Program | `docs/architecture/extensibility-roadmap.md` | Single execution SOT for GAP IDs, merge order, status, acceptance, and closure evidence |
| Package Classification | `docs/architecture/package-classification.md` | Closed kernel, product shell, bundled feature, and external extension boundaries |
| Hook System | `docs/architecture/hook-system.md` | Hook contracts; current inventory is generated in `site/src/data/geode/architecture-baseline.json` |
| Scaffold | `CLAUDE.md` | Development workflow, quality gates, CANNOT/CAN (this file) |

## Project Structure

Production code uses three top-level Python packages with one dependency direction:
- `core/` — GEODE runtime and operator surface. 5-layer stack (layer diagram → `GEODE.md` → Architecture).
- `evals/` — measurement and audit consumers of `core`.
- `evolve/` — scaffold search and hill-climbing over `evals` and `core`.

Check the generated inventory in `site/src/data/geode/architecture-baseline.json`.
Key entry points: `core/agent/loop/`(AgenticLoop), `core/runtime.py`(bootstrap).

## Development

Use the [verification reference](.agents/skills/geode-workflow/references/verification-gates.md)
for risk-scoped local checks and `scripts/preflight.sh` for the broad gate run.

### Expected Test Results

Core tests pass without bundled analysis fixtures. Bundled features own their
feature-specific fixture and E2E gates.

## Implementation Workflow

The canonical execution loop is `docs/workflow.md` plus the Claude Code project
skill `.claude/skills/geode-workflow/`. Claude Code should use the skill as the
step-by-step scaffold with progressive disclosure, while this file remains the
rulebook for constraints, quality gates, and project-specific rationale.
Architecture/extensibility work additionally selects and updates a stable GAP
ID in `docs/architecture/extensibility-roadmap.md`.

> **Design Principle**: CANNOT (guardrails) comes before CAN (freedom). Constraints guarantee quality. (Karpathy P1, OpenClaw Policy Chain, Codex Sandbox)

### CANNOT — Absolute Prohibition Rules

> Development-time guardrails — what the *engineer* must not do when building GEODE.
> For runtime guardrails (what GEODE the *agent* refuses to do at execution time), see `GEODE.md` → `## RUNTIME CANNOT`.

These cannot be violated at any stage. Violations must be immediately halted and corrected.
Rationale cites the originating incident when one exists. The `karpathy-patterns` skill's "Anti-patterns" table is the abstract counterpart — this table holds the concrete project-level rules and the sprint incidents that produced them. Before every PR push, scan for an analogous pattern; if your PR could match a row, it probably does.

| Area | Rule | Rationale |
|------|------|-----------|
| **Git** | No code work without a worktree (allocation procedure → [GitFlow allocation](.agents/skills/geode-gitflow/SKILL.md#worktree-allocation)) | Isolated execution (OpenClaw Session) |
| | No direct push to main/develop — PR → CI → merge | Ratchet (P4) |
| | No deleting other sessions' worktrees (`.owner` mismatch) | Ownership protection |
| | No `git checkout` switching within a worktree | Isolation maintenance |
| | No modifying tracking documents from feature/develop, except the user-authorized roadmap-only readiness, claim, GAP-registration, reconciliation, and full-ledger audit PRs for `docs/architecture/extensibility-roadmap.md` defined in that file's §0.3 | Single source of truth on main, with one serialized program-ledger exception |
| | Fetch before allocating a branch from its authorized remote base | Conflict prevention |
| | No claiming "branch needs sync" from commit count alone — verify content with `git diff A B --stat` first | Graph asymmetry ≠ content asymmetry (gitflow merge commits) |
| **Planning** | For non-trivial changes, inspect existing behavior and state the smallest measurable plan before editing | Prevent over-engineering |
| | No interpreting ambiguous "제거"/"remove" as code-path deletion — disambiguate first (knob vs deletion) | Avoid wasted reverts. *Incident: PR-fallback-knob ~30-file revert (2026-05-21)* |
| **Quality** | No committing with lint/type/test failures | Ratchet (P4) |
| | No placeholders (XXXX) in metrics — measured values only | Truth guarantee |
| | No excessive `# type: ignore` — fix type errors instead | Correctness |
| | No bare `_` for unused variables — use `_prefix` naming (e.g. `_tok_before`) | Readability |
| | No unauthorized live test (`-m live`) execution | Cost control (P3) |
| | No gate / CI-status command behind an exit-code absorber — never `gate \| tail`, `gate \| grep -c`, or `check; merge`. Preserve the command exit status; missing checks or a failed status lookup never establish green CI | Gate integrity. *Incidents (2026-07-02/03, same session): PR #2463 merged with a failing Test job because the check was chained with `;`; the slop-ratchet failure on PR #2482 was invisible locally behind `\| tail -1`. A swallowed exit code turns every downstream "green" claim into fiction.* |
| | No "graceful" return contract without applying it at every schema-typed cast (not just outer try) | Boundary completeness. *Incident: PR-G3 #1347 (2026-05-20) — `float()` on non-numeric raised before contract* |
| | No seed / pool referencing a dim outside the live fitness taxonomy (`evolve.scaffold_search.fitness.AXIS_TIERS`) — a phantom-dim "hallucination" (the audit probes a removed dimension, the held-out ruler pins at the floor, the gate rejects every cycle for a measurement reason = invalid experiment). When a dim is dropped (e.g. PR-DROP-ANALYTICS-DIMS), every pool referencing it goes stale. Validate at **assemble time** (`scripts/assemble_seed_pool.py` → `validate_pool_target_dims`), not only at campaign runtime. | Phantom-dim drift. *Incident: held-out `gen-2605-*-redundant_tool_invocation` stale after the dim was removed; the campaign HALTed but the stale pool had already shipped — fail at assemble so it never enters the pipeline (2026-06-11). Guard: `tests/scripts/test_assemble_stale_dim_guard.py`* |
| | No conflating "latest" and "promoted" SoTs — readers must document which they assume; persist both if the loop needs both | SoT clarity. *Incident: PR-G2 #1346 (2026-05-20) — downstream read stale evidence forever* |
| | No dual SoT (disk + fallback literal) without shared anchor + drift invariant test | Drift prevention. *Incident: PR-MINIMAL-2 #1398 (2026-05-21) — `program.md` ↔ `_FALLBACK_SYSTEM_PROMPT` divergence* |
| | No unsupported external-SDK or backend capability claim. Use official docs/source through any available tool; ambiguous backend acceptance stays disabled or guarded pending an authorized live test | Doc-before-behaviour. *Incident: PR-NO-FALLBACK #1839 (2026-05-28) — `codex_oauth.supports_web_search` flipped False → True based on SDK ``ToolParam`` Union alone; Codex backend's actual acceptance of ``{"type": "web_search"}`` is undocumented in ctx7 / Codex CLI repo, so the assumption needed a live-test gate rather than a behavioural test* |
| | No deep-linking into a vendored SPA viewer (Inspect View / petri-bundle / seed-generation bundle) by *assuming* its URL/route scheme — verify the route against the bundle's actual JS (`createHashRouter`, `navigate(...)` calls) before generating links. Inspect View exposes only `#/logs/<encodeURIComponent(eval_filename)>`; there is **no** `/tasks/<id>` route. Key deep-links on the `logs/listing.json` filename, never the task_id. | Artifact-before-behaviour. *Incident: PR-HUB-AUDIT-DEEPLINK (2026-05-30) — `#/tasks/<task_id>` (plus a `.eval`-header-scan apparatus built only to extract the 22-char task_id) targeted a route that does not exist, so every audit/seedgen deep-link silently fell back to the run list. Guard: `tests/test_self_improving_hub_e2e.py::test_audit_deeplinks_use_logs_route_and_resolve`* |
| **Docs** | No omitting CHANGELOG from code commits | Traceability |
| | Keep ordinary changes under `[Unreleased]`; promote entries only for an authorized release and retain a fresh empty heading | Release discipline |
| | No version mismatch across 5 locations | Single source of truth |
| | No non-English content in files injected into LLM context (`GEODE.md`, memory, prompts) — the model consumes them at runtime | Prompt clarity (moved from GEODE.md Conventions, PR-GEODE-SOUL) |
| | No `You are ...` / `Act as ...` identity assertion in newly edited model-facing prompt text. Use `.claude/skills/prompt-writing/` and prefer metadata/behavioral clauses (`Agent:`, `Runtime:`, `Mode:`, `Scope:`). | Fable-style prompt discipline; prevents generic roleplay drift and fast-chat identity regressions |
| | No emoji as section anchors / nav prefixes; no decorative card grids when content is data — dense table/list only on docs/site/CLI surfaces | Slop signal. *Incident: PR-CSP-14-UI mockup (2026-05-23) — see [[feedback-no-box-ui-no-emoji]]* |
| | No colored left-border accent bars on cards/blocks (`border-left: Npx solid var(--bucket-*)`); use a neutral hairline (`var(--rule)`), an uppercase role-label, or spacing. No box-card grid as a *navigation* surface (extends the card-grid rule above) — use a dense inline link row/list. Minimize decorative `--`/`&mdash;` separators (prefer `·` / `.` / `,`). | Slop signal. *Incident: lineage-station / mutator-banner accent bars + run-page sub-view card grid, PR-HUB-DESLOP (2026-05-29) — see [[feedback-no-box-ui-no-emoji]]* |
| **Naming** | No abstract-noun package names (`text`, `storage`, `runtime_state`, `helpers`, `common`, `lib`, `manager`) — use domain-verb / domain-noun (claude-code-ref / openclaw / hermes / crumb all converge). *Incident: PR-CLEANUP-2 #1562 (2026-05-23) folded 3 such packages.* | Frontier convergence + [[feedback-explicit-naming]] |
| | No same-name-nested folders (`X/X/`) — flatten or rename inner | Frontier 0/7 do this; GEODE had `core/scheduler/scheduler/` |
| | No single-file packages — fold into the nearest domain sibling | PR-CLEANUP-2 precedent (`core/text/`, `core/storage/`) |
| | No `_helpers.py` / `_utils.py` / `_misc.py` filenames once a caller appears — rename to the actual responsibility (the catch-all suffix hides intent) | autoresearch / openclaw avoid; PR-CLEANUP-1 absorbed `_announce.py` + `_decomposition.py` for similar reason |
| **Compat** | No re-export shim / backward-compat module past its 1-release grace — delete it and migrate callers in the same PR | *Incidents: `core/llm/client.py` removed PR-CLEANUP-4, `core/agent/loop/loop.py` removed PR-CLEANUP-1* |
| **Registry** | No two registries for the same domain (skill / tool / adapter / plugin) — one schema, one loader, one call surface | *Incident: `core/llm/skill_registry.py` ↔ `core/skills/skills.py` parsing the same `~/.geode/skills/*.md` twice* |
| **PR** | Use the [PR template](.github/PULL_REQUEST_TEMPLATE.md); never merge without confirming required checks on the current PR head | Format + traceability + Ratchet (P4) |

### CAN — Permitted Freedoms

Within the user's authorized task scope, choose the simplest useful approach:

| Freedom | Description |
|---------|-------------|
| Simple bug/doc fixes | Skip Plan, implement directly in worktree |
| Discovering improvements not in plan | Handle in next iteration after completing current work |
| Selective test execution | Choose checks by the affected behavior; broaden or repeat only for new changes, failures, or unresolved concerns |
| Commit message language | Korean/English freely (maintain consistency only) |
| Tool selection | Use any available tool that retrieves the required primary evidence; a particular documentation connector is not a prerequisite. |
| Scoped cleanup | Remove proven duplication and obsolete guidance; preserve historical evidence and unrelated behavior. Cleanup does not authorize speculative renames or new abstractions. |

### Wiring Verification (Anti-Disconnection)

> Static parity invariants for runtime wiring (writer-reader, hook-bootstrap, explicit injection).
> For *pre-change* workflow (read-before-write, hypothesis), see `explore-reason-act` skill.
> For *static dependency health* (layer violations, circular imports, eager loading), see `dependency-review` skill.

| Item | Rule |
|------|------|
| **Read-Write parity** | Every read path (context injection) must have a corresponding write path (data producer). Verify both ends before marking complete. |
| **Hook registration** | Every hook handler must be registered in bootstrap.py. Handler exists ≠ handler fires. |
| **Runtime service injection** | Process services cross composition boundaries through constructors, grouped config, or `ToolContext`; `ContextVar` is reserved for request identity, diagnostics, request-local mutable state, and caches. |
| **Singleton lifecycle** | Singleton created at startup may use stale data. Verify refresh/invalidation path exists for mutable state (OAuth tokens, config). |
| **Conditional read parity** | A reader that loads context in ONE branch (e.g. auto-pick) must load it in the SYMMETRIC branch (explicit input) too — otherwise the feature half-disconnects depending on call shape. *Incident: PR-G3 #1347 (2026-05-20) — `_resolve_target_dim` loaded baseline only for `--target-dim auto`.* |
| **Writer destination tracked** | Every file the code writes for "audit / history / ledger" must be `git check-ignore`-clean. An ignored path silently breaks `git add`; the writer thinks it persisted, history doesn't. *Incident: PR-G5b #1350 (2026-05-20) — `autoresearch/state/mutations.jsonl` silently ignored, caught by Codex MCP after 8/8 CI green; pinned by `test_policy_files_not_gitignored`.* |
| **Index regenerated, not just read** | A renderer that reads an index/listing file (hub seeds `listing.json`, search index, manifest) must REGENERATE it from the source dir, not assume an upstream step refreshed it. A read-only renderer over a stale index silently drops newly-added items with no error. *Incident: a seed-gen run synced to the bundle rendered no hub page because `geode hub build` only read a stale `listing.json` — the operator had to remember the separate `build_seeds_listing` step (frontier-2612-bt, 2026-06-12). Fixed: `load_seedgen` rebuilds the listing first. Guard: `tests/scripts/test_hub_listing_autobuild.py`* |

### Refactoring Deception Prevention

| Item | Rule |
|------|------|
| **Implementation completeness** | Do not mark partial implementations, stubs (`pass` only), or re-export shells as complete. Cross-check the plan against the diff; use independent review under the [verification gates](.agents/skills/geode-workflow/references/verification-gates.md). |
| **CHANGELOG/PR-body parity** | Every verb/adjective in the PR title + CHANGELOG ("git-tracked", "X-driven", "automatic", "committed") must be grep-provable in code. Run `git check-ignore`, `grep -rn "<source-doc>"`, and "is there a caller?" before push. *Incident: PR-G5b #1350 (2026-05-20) — both "git-tracked audit log" and "program.md-driven runner" were un-backed; fixed in `runner.py:_load_program_md` and pinned by `test_load_program_md_actually_reads_disk_file`.* |

### Workflow and verification

Follow [docs/workflow.md](docs/workflow.md) for scope, planning, delegation,
and completion. Load only the relevant detail:

| Need | Authority |
|---|---|
| Local checks and independent review | [Verification gates](.agents/skills/geode-workflow/references/verification-gates.md) |
| Provider or backend claims | [Provider grounding](.agents/skills/geode-workflow/references/provider-grounding.md) |
| Branches, CI, PRs, and integration | [GitFlow](.agents/skills/geode-gitflow/SKILL.md) |
| Changelog and authorized release preparation | [Changelog convention](.agents/skills/geode-changelog/SKILL.md) |

Post-merge cleanup uses `scripts/check_repo_hygiene.py free-merged-worktree`
from outside the owned checkout; the GitFlow skill owns its exact procedure.
A merge does not authorize a release, global installation, or service restart.
Tracking updates follow their main-owned workflow only when in scope.

## Custom Skills (Scaffold)

Cross-host scaffold skills are authored under `.agents/skills/` and expose a
relative per-skill `.claude/skills/` alias so Claude Code and Codex read
identical bytes. Existing Claude-only skills remain under `.claude/skills/`.
Same-named `.geode/skills/` files remain runtime contracts; a cross-host
scaffold links to them instead of duplicating them. Full catalog for human readers:
[docs/scaffold-skills.md](docs/scaffold-skills.md). Separate from the GEODE
runtime's `core/skills/` SkillRegistry.
