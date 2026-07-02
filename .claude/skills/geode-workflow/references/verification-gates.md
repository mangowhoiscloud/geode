# Verification Gates

Run targeted checks first, then broaden based on blast radius.

## Targeted

```bash
uv run pytest -q tests/<targeted_path>.py
```

Use targeted suites for new modules, changed adapters, lifecycle events,
tool handlers, prompt assembly, or schema changes.

## Static Gates

```bash
uv run ruff check core/ tests/ plugins/ scripts/
uv run ruff format --check core/ tests/ plugins/ scripts/
uv run mypy core/ plugins/
uv run lint-imports
git diff --check
```

Do not pipe gate output through commands that can hide non-zero exit codes.

## Prompt Integrity

Run this when `core/llm/prompts/` changed:

```bash
uv run python - <<'PY'
from core.llm.prompts import check_prompt_integrity
print(check_prompt_integrity())
PY
```

## Full Suite

For broad runtime work, run when feasible:

```bash
uv run pytest tests/ -m "not live"
```

If it fails because of known environment or fixture gaps, report exact failing
groups and keep targeted tests clean.

## Live Tests

Live provider checks require explicit user approval. Without approval, mark
ambiguous provider acceptance as `live_test_required` and keep the production
path guarded.

## Cross-Verification (Codex MCP)

Local gates alone do not close verification — run an independent
second-opinion review before push:

- Commit first, then ask the Codex MCP server to review the committed diff
  against the base branch (read-only sandbox, `approval-policy: never`).
- The prompt names the exact scope, the invariants to attack (threading,
  ANSI/cursor math, scope/lifetime, CHANGELOG parity), and demands numbered
  findings with HIGH/MED/LOW severity + file:line, or "No findings".
- Fix or explicitly accept every finding; amend and re-verify fixes.
- Historical yield: ~1.6 real catches per PR that local gates missed.
