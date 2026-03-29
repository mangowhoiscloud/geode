---
name: anti-deception-checklist
description: Verification checklist to prevent fake success. Detects test deletion/disabling, coverage regression, lint bypass, secret exposure. Triggered by "deception", "fake" ("가짜"), "fake success", "verification" ("검증"), "checklist" ("체크리스트"), "deletion detection" ("삭제 탐지"), "regression" keywords.
user-invocable: false
---

# Anti-Deception Verification Checklist

Use this checklist after code changes to detect "fake success."
Even if the build turns green, it may be hiding problems rather than solving them.

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
# API key patterns
grep -rn "sk-ant-\|sk-proj-\|sk-[a-zA-Z0-9]\{20,\}" core/ tests/ --include="*.py"

# Hardcoded tokens
grep -rn "Bearer \|token.*=.*['\"][a-zA-Z0-9]\{20,\}" core/ tests/ --include="*.py"

# .env file committed
git diff --name-status HEAD~1 | grep -E "^A.*\.env$"
```

Verdict: API key pattern exposed in code = **FAIL**

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
