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

- Feature branches start from `develop`.
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
