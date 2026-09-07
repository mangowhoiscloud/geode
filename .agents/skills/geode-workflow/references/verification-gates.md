# Verification Gates

Run targeted checks first, then broaden based on blast radius. Read-only audits
need source evidence, not a full test run. For documentation-only edits, check
affected links, examples, or generated output; runtime-loaded prompts also need
the relevant assembly and mode-boundary tests.

For a changed behavior, preserve the smallest meaningful regression check.
Do not add tests that only repeat arbitrary wording or implementation details.
Once the required checks pass, reuse results for unchanged code, configuration,
and verification environment. Repeat or broaden only after changes, failures,
or unresolved concerns. Record the tested revision or diff and exact commands.
Required remote CI must still pass on the actual PR head before merge.

## Targeted

```bash
uv run pytest -q tests/<targeted_path>.py
```

Use targeted suites for new modules, changed adapters, lifecycle events,
tool handlers, prompt assembly, or schema changes.

## Static Gates

```bash
uv run ruff check core/ evals/ evolve/ tests/ scripts/
uv run ruff format --check core/ evals/ evolve/ tests/ scripts/
uv run mypy core/ evals/ evolve/ scripts/
uv run lint-imports
git diff --check
```

Do not pipe gate output through commands that can hide non-zero exit codes.

## Prompt Integrity

Run this when `core/llm/prompts/` changed:

```bash
uv run python - <<'PY'
from core.llm.prompts import verify_prompt_integrity
verify_prompt_integrity(raise_on_drift=True)
PY
```

## Full Suite

For broad runtime changes, use `scripts/preflight.sh` and inspect its results
and skips. The full Python suite is:

```bash
uv run pytest tests/ -m "not live"
```

A known environment or fixture failure remains a failed check: report exact
groups and the remaining verification. `--fast`, missing optional dependencies,
and unavailable site tooling do not establish a full pass.

## Live Tests

Live provider checks require explicit user approval. Without approval, mark
ambiguous provider acceptance as `live_test_required` and keep the production
path guarded.

## Independent Review

Non-trivial changes get an independent, read-only review when a suitable
reviewer is available. Give it the exact diff/base and relevant invariants;
verify findings locally and resolve or explicitly disposition them. Re-review
changed or unresolved parts, not an unchanged, already-reviewed diff.

Use the [Codex MCP skill](../../codex-mcp-verify/SKILL.md) when its user-request
and tool-availability conditions hold. Otherwise an available independent
subagent can review; if no reviewer is available, disclose that limit instead
of inventing tools, reading credentials, or blocking indefinitely. Review is
evidence, not a replacement for deterministic checks or required CI.

For architecture/extensibility **implementation PRs**, verification also
confirms that canonical `develop` contains the selected package's
`IN_PROGRESS` active claim, the implementation branch/owner match it, the
implementation diff does not prospectively change status, and a post-merge
reconciliation path exists. Roadmap-only readiness, claim, GAP-registration,
reconciliation, full-ledger audit, and main-based tracking PRs perform ledger
maintenance and are exempt from the implementation active-claim prerequisite.
A registration PR adds only `OPEN` scope and does not authorize implementation.
Neither local gates nor review can justify a prospective `IN_DEVELOP` or `DONE`
status in an implementation PR.

Every roadmap-only PR runs the canonical ledger validator
against its actual target: `--base-ref origin/develop` for ordinary ledger
work and `--base-ref origin/main` for a tracking-only closure PR.

## Repo Hygiene Ratchet

Run before every push (CI's Lint & Format job includes it; local ruff does not):

```bash
uv run python scripts/check_repo_hygiene.py
```

Catches hardcoded home paths with real usernames (placeholders like
``/Users/x/…`` are allowlisted in ``_PLACEHOLDER_USERS``), dangling/absolute
symlinks, and orphan worktrees.
