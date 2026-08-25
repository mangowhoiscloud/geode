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

# Test count decrease (compare pytest -q output)
uv run pytest tests/ -m "not live" -q 2>&1 | tail -1
```

Verdict: Coverage drop of 5% or more = **FAIL**

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

| Item | Command | FAIL Criteria |
|------|---------|---------------|
| Test count ratchet | `pytest -q` result comparison | Decrease from baseline |
| E2E tier invariant | `geode analyze "Cowboy Bebop" --dry-run` | A (68.4) changed |
| Tool count | `definitions.json` count | Decrease from baseline |
| Module count | `find core/ -name "*.py"` count | Unreasonable decrease |
