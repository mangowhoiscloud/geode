# GEODE Evidence-First Development Workflow

> Canonical public summary for GEODE contributors. Claude Code should use the
> project skill at `.claude/skills/geode-workflow/SKILL.md`, which applies this
> workflow through progressive disclosure.

GEODE uses an evidence-first workflow for feature work, provider/model changes,
GUI/computer-use work, PDF/document ingestion, observability changes, and large
audits. The full procedure is split across the `geode-workflow` skill and its
`references/` files so agents load only the detail needed for the task.

## Core Loop

1. **Scope**: confirm branch, dirty files, objective, and unrelated work.
2. **GAP audit**: search before designing; classify existing, partial, absent,
   or misfit.
3. **Grounding**: verify external provider, SDK, model, OS, browser, package,
   or current API behaviour with official docs/source.
4. **Preflight**: capture task class, affected providers, required tools,
   evidence class, and explicit non-goals.
5. **Design contract**: define schema, log, event, state, trajectory, provider
   split, and rollback behaviour before code.
6. **Implement**: use existing GEODE registries, adapters, redaction helpers,
   transcript helpers, and atomic-write utilities.
7. **Observe**: make runtime behaviour inspectable with bounded structured
   records.
8. **Verify**: run targeted checks first, then broaden when risk justifies it.
9. **Report/GitFlow**: state what changed, what ran, what failed or was
   skipped, and only claim merge/push/cleanup after commands complete.

## Architecture And Extensibility Program

Architecture/extensibility changes use
[`docs/architecture/extensibility-roadmap.md`](architecture/extensibility-roadmap.md)
as their execution SOT. Before implementation, a reconciliation PR atomically
promotes every row in a dependency-satisfied package from `OPEN` to `READY`.
Select that package, re-audit it against current `origin/develop`, and merge a
roadmap-only claim PR that records `IN_PROGRESS`, its owner, and its intended
implementation branch. Only then allocate the implementation worktree. The
implementation PR references that canonical claim and does not predict its own
merge. After it merges, the roadmap's narrow, explicitly authorized
reconciliation PR atomically records `IN_DEVELOP` for the whole package; a
main-based tracking PR atomically records `DONE` plus per-GAP closure evidence
after release. That tracking worktree starts from current `origin/main`, its PR
targets `main`, and its merge is followed by a CI-gated `main -> develop` sync
PR. Detailed subsystem docs continue to own behavior contracts, but they do
not independently claim program completion or reorder the roadmap. Untracked
architecture scope discovered during implementation is registered as an
`OPEN` package in a separate roadmap-only GAP-registration PR; registration
does not claim the package or authorize expanding the implementation diff.

## Progressive Disclosure Map

| Need | Skill reference |
|---|---|
| Ordinary code-work checklist | `.claude/skills/geode-workflow/references/phase-checklist.md` |
| Provider/model/API capability claims | `.claude/skills/geode-workflow/references/provider-grounding.md` |
| Schema/log/event/state/trajectory consistency | `.claude/skills/geode-workflow/references/observability-contract.md` |
| Test, lint, type, prompt, and full-suite gates | `.claude/skills/geode-workflow/references/verification-gates.md` |
| Branch, PR, merge, and cleanup operations | `.claude/skills/geode-workflow/references/gitflow.md` |

## Worktree And GitFlow

```text
feature/<name> -> develop -> main
```

- Feature branches and develop-targeted roadmap branches start from the
  fetched `origin/develop` tip.
- A roadmap tracking-only `DONE` branch starts from `origin/main`, targets
  `main`, and is followed by a CI-gated `main -> develop` sync.
- Feature PRs merge into `develop` with squash merge.
- Before `develop -> main`, sync `main -> develop` if main has drift.
- `develop -> main` is a pass-through merge after gates are satisfied.
- Post-merge cleanup removes remote branch, worktree, local branch, then prunes.

## Minimum Verification

Use targeted tests for the changed behaviour, then broaden based on blast
radius:

```bash
uv run pytest -q tests/<targeted_path>.py
uv run ruff check core/ tests/ plugins/ scripts/
uv run ruff format --check core/ tests/ plugins/ scripts/
uv run mypy core/ plugins/
uv run lint-imports
git diff --check
```

Live tests require explicit user approval. Provider acceptance that cannot be
proven without a live call must remain guarded or marked `live_test_required`.

## Cross-Verification (Codex MCP)

Local gates alone do not close verification. Before pushing a non-trivial PR,
run an independent second-opinion review of the committed diff through the
Codex MCP server (read-only sandbox, numbered findings with HIGH/MED/LOW
severity). Fix or explicitly accept every finding, then re-verify the fixes.
Historical yield is ~1.6 real catches per PR that local gates missed.
