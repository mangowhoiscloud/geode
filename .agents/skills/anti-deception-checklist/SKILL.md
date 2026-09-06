---
name: anti-deception-checklist
description: Verification checklist to prevent fake success. Detects test deletion/disabling, coverage regression, lint bypass, secret exposure. Triggered by "deception", "fake" ("가짜"), "fake success", "verification" ("검증"), "checklist" ("체크리스트"), "deletion detection" ("삭제 탐지"), "regression" keywords.
---

# Anti-Deception Verification Checklist

Use this checklist after code changes to detect "fake success."
Even if the build turns green, it may be hiding problems rather than solving them.

## Sensitive-Data Handling Contract

This skill detects possible exposure; it never needs the secret value. Do not
read credential files or `.env` content to validate a finding. Detection output
must contain only a file path and rule class, never the matching line, token,
password, private key, PII, or surrounding context. Test fixtures must be
obviously non-live and must not match a provider-valid credential format.

If a real secret may have entered Git history or CI output:

1. stop the gate and avoid reproducing the value in an issue, PR, prompt, or
   log;
2. identify the provider and owner from metadata, not by printing the secret;
3. revoke or rotate it first;
4. coordinate history and cache cleanup separately; deleting the current line
   is not remediation.

PII and user content are not secret-scanning test material. Minimize them,
retain them only in their approved private store, and report an opaque ID or
redacted aggregate.

## Check 1: Test Deletion/Disabling Detection

```bash
# Deleted test files
git diff --name-status HEAD~1 | grep "^D.*test_"

# Newly added @pytest.mark.skip / skipIf
git diff HEAD~1 -- "*.py" | grep -E "^\+.*@pytest\.mark\.(skip|skipIf|xfail)"

# Test exclusion patterns (pyproject.toml)
git diff HEAD~1 -- pyproject.toml | grep -E "^\+.*(ignore|exclude|deselect)"
```

Verdict: Test deletion/disabling without legitimate justification = **FAIL**

## Check 2: Lint/Type Check Bypass Detection

```bash
# type: ignore overuse
git diff HEAD~1 -- "*.py" | grep -E "^\+.*# type: ignore"

# noqa overuse
git diff HEAD~1 -- "*.py" | grep -E "^\+.*# noqa"

# Rule disabling in ruff/mypy config
git diff HEAD~1 -- pyproject.toml | grep -E "^\+.*(ignore|exclude|per-file-ignores)"
```

Verdict: 3+ new `type: ignore` additions = **WARNING**, rule disabling = **FAIL**

## Check 3: Coverage Regression Detection

```bash
# Coverage threshold lowered in config
git diff HEAD~1 -- pyproject.toml | grep -E "^\+.*(fail_under|min_coverage)"

# Run the selected non-live suite without hiding its exit status.
uv run pytest tests/ -m "not live" -q
```

Use the coverage command in `.github/workflows/ci.yml` and the threshold in
`pyproject.toml` (`tool.coverage.report.fail_under`); plain pytest output does
not measure coverage. A failing coverage gate or an unjustified threshold,
omit, or test exclusion change is **FAIL**. Compare coverage on the same scope
and review regressions even when the configured threshold still passes.

## Check 4: Secret Exposure Detection

```bash
# Candidate files only; -l reports paths without echoing matched content.
git grep -IlE '(sk-ant-|sk-proj-|sk-[[:alnum:]_-]{20,}|Bearer[[:space:]]+[[:alnum:]_.-]{20,})' -- ':(glob)**/*.py' || true
git grep -IlE 'token[^=]*=[[:space:]]*[^[:space:]]{20,}' -- ':(glob)**/*.py' || true

# .env file committed
git diff --name-status HEAD~1 | grep -E "^A.*\.env$"
```

Verdict: candidate path = **FAIL** until an authorized local review classifies
it as revoked/test-only/false-positive without copying the value into output.

## Check 5: Dependency Downgrade Detection

```bash
# Version changes in pyproject.toml
git diff HEAD~1 -- pyproject.toml | grep -E "^\+.*(version|requires-python)"

# Package version downgrade via uv.lock changes
git diff HEAD~1 -- uv.lock | grep -E "^-.*version" | head -10
```

Verdict: Dependency downgrade without explicit justification = **WARNING**

## GEODE-Specific Checks

| Item | Current authority | Review requirement |
|------|-------------------|--------------------|
| Tests | `uv run pytest tests/ -m "not live"` and `uv run pytest tests/ --collect-only` | Explain removed cases and identify surviving behavior checks; a count decrease alone is not a regression verdict |
| CLI surface | `uv run geode version` plus targeted command tests | Preserve the current CLI contract; the retired `geode analyze` domain fixture is not a runtime gate |
| Tool/module inventory | `uv run python scripts/architecture_baseline.py --check` | Review inventory and parity changes; do not regenerate the baseline merely to hide drift |
| Prompt ratchet | `verify_prompt_integrity(raise_on_drift=True)` in `core.llm.prompts` | Preserve pinned prompt hashes or update them with the reviewed prompt change |

Use [verification gates](../geode-workflow/references/verification-gates.md)
for executable checks and the [deletion gate](../agent-anti-pattern/references/field-guide.md#deletion-gate)
before removing code or tests. Inventory counts and source scans discover
candidates; they do not establish behavior, authorize deletion, or replace CI.
