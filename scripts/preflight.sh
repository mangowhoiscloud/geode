#!/usr/bin/env bash
# Run every gate CI enforces, locally, in CI's own scope.
#
# Why this exists: the Pre-PR checklist listed five commands while CI enforced
# seventeen gates, and three of the five were documented at a NARROWER scope
# than CI runs them (mypy without scripts/, ruff without plugins/ scripts/).
# A branch could pass the documented checklist and still fail CI — measured at
# 5 of 60 sampled July failures for the scope mismatch alone. Editing a
# checklist does not fix that; a runnable command does.
#
# Usage:
#   scripts/preflight.sh            # everything
#   scripts/preflight.sh --fast     # skip the full test suite and site build
#
# Exit code is the number of failed gates, so `scripts/preflight.sh && gh pr create`
# is safe — no exit-code absorber (CLAUDE.md CANNOT: never `gate | tail`).

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

FAILED=0
declare -a FAILURES=()
declare -a SKIPPED=()

run() {
  local name="$1"
  shift
  printf '\033[2m··\033[0m %s ' "$name"
  local out
  if out=$("$@" 2>&1); then
    printf '\033[32mok\033[0m\n'
  else
    printf '\033[31mFAIL\033[0m\n'
    printf '%s\n' "$out" | tail -15 | sed 's/^/     /'
    FAILED=$((FAILED + 1))
    FAILURES+=("$name")
  fi
}

echo "── lint / type / security ──"
run "ruff check"    uv run ruff check core/ tests/ plugins/ scripts/
run "ruff format"   uv run ruff format --check core/ tests/ plugins/ scripts/
run "mypy"          uv run mypy core/ plugins/ scripts/
run "bandit"        uv run bandit -r core/ -c pyproject.toml

echo "── ratchets / generated artifacts ──"
run "deptry"                 uv run deptry .
run "legacy imports"         uv run python scripts/check_legacy_imports.py --base-ref origin/develop
run "repo hygiene"           uv run python scripts/check_repo_hygiene.py
run "slop growth"            uv run python scripts/check_slop_ratchet.py
run "architecture baseline"  uv run python scripts/architecture_baseline.py --check
# CI resolves --target-branch from the PR base and --trusted-*-ref from a trust
# resolver; locally the base is develop for every feature branch, and the trusted
# ref is omitted so the check runs in its untrusted (stricter) mode.
run "architecture roadmap"   uv run python scripts/check_architecture_roadmap.py \
  --check --base-ref origin/develop --target-branch develop --event-mode pull_request
run "llms.txt drift"         uv run python scripts/check_llms_version.py
run "petri bundle"           uv run python scripts/validate_petri_bundle.py
run "hero viz layout"        uv run python scripts/visualizations/verify_hero_layout.py --static-check
run "docs canon"             uv run python scripts/check_docs_canon.py
run "prompt integrity"       uv run python -c \
  "from core.llm.prompts import verify_prompt_integrity; verify_prompt_integrity(raise_on_drift=True)"

if [ "$FAST" -eq 0 ]; then
  echo "── tests ──"
  # CI's Test job installs `uv sync --extra audit`; a plain `uv sync` leaves
  # inspect_ai out and 4 seed-generation tests fail on import alone. Naming that
  # beats letting preflight sit permanently red — a gate nobody believes is worse
  # than no gate.
  if uv run python -c "import inspect_ai" >/dev/null 2>&1; then
    run "pytest" uv run pytest tests/ -m "not live" -q
  else
    printf '\033[33m··\033[0m pytest \033[33mSKIPPED\033[0m — optional extra missing\n'
    printf '     run: uv sync --extra audit   (CI installs this for the Test job)\n'
    SKIPPED+=("pytest")
  fi

  # llms-full.txt is written by export-docs-md.mjs, which runs AFTER the site
  # build — sync-stats alone leaves it stale and the pages gate then fails on a
  # file the local checklist never mentioned.
  if [ -d site/node_modules ]; then
    echo "── site generated docs ──"
    ( cd site && npm run sync-stats >/dev/null 2>&1 && npm run build >/dev/null 2>&1 \
        && npm run export-md >/dev/null 2>&1 )
    run "public-doc generators" git diff --exit-code -- \
      site/public/llms.txt site/public/llms-full.txt \
      site/src/data/geode/sot.ts site/src/data/geode/changelog.ts
  else
    printf '\033[33m··\033[0m site generated docs \033[33mSKIPPED\033[0m — site/node_modules absent\n'
    printf "     run: (cd site && npm ci)\n"
    SKIPPED+=("site generated docs")
  fi
else
  echo "── tests / site ── skipped (--fast)"
fi

echo
if [ "$FAILED" -ne 0 ]; then
  echo -e "\033[31m$FAILED gate(s) failed:\033[0m ${FAILURES[*]}"
elif [ "$FAST" -eq 1 ] || [ ${#SKIPPED[@]} -gt 0 ]; then
  # --fast skips exactly the gates that fail most often (stale generated docs,
  # the test suite). Saying "passed" here would be the same false green the
  # narrow checklist produced, so name what was not run.
  notrun="${SKIPPED[*]:-}"
  [ "$FAST" -eq 1 ] && notrun="pytest, site generated docs"
  echo -e "\033[33mgates passed, but NOT all ran — skipped: ${notrun}\033[0m"
  echo "  a green here does not mean CI is green; resolve the skips before opening a PR"
else
  echo -e "\033[32mall gates passed\033[0m"
fi
exit "$FAILED"
