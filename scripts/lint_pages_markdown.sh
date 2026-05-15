#!/usr/bin/env bash
# Lint the markdown files that get published to GitHub Pages or linked
# from the petri-bundle README. The allowlist below is intentionally
# narrow — see docs/architecture/render-lint.md for the rule-by-rule
# rationale and the policy on legacy audit docs.
#
# Add new audit docs here as they land. The accompanying ratchet at
# tests/test_render_lint_config.py verifies the four caveat docs PR #2
# touched exist so a rename does not silently drop them from this list.

set -euo pipefail

cd "$(dirname "$0")/.."

# Render-gated files. Anything listed here must pass .pymarkdown.json.
# Keep this list small — only files that get served by GitHub Pages
# verbatim (the petri-bundle README) or that the bundle README links to
# as the canonical caveat docs. Other audit docs predating the gate
# have their own structural debt; adding them here without fixing the
# violations first would force a content rewrite of those reports.
TARGETS=(
  # PR #2 caveat files — the original motivation for the gate.
  "docs/audits/2026-05-12-petri-geode-audit-v3.md"
  "docs/audits/2026-05-12-petri-insights.md"
  "docs/audits/2026-05-12-petri-multi-model-partial.md"
  "docs/petri-bundle/README.md"
  # The gate's own architecture doc — keep it lint-clean as documentation
  # that the rules are achievable.
  "docs/architecture/render-lint.md"
)

# Drop targets that no longer exist (e.g. file renamed). The ratchet
# test catches the rename for the four caveat docs; for follow-ups we
# silently skip so the gate keeps green during reorganisation.
EXISTING=()
for t in "${TARGETS[@]}"; do
  if [ -f "$t" ]; then
    EXISTING+=("$t")
  fi
done

if [ "${#EXISTING[@]}" -eq 0 ]; then
  echo "no render-gated markdown targets — nothing to lint"
  exit 0
fi

# pymarkdownlnt may be invoked via `uvx` (pre-commit local hook) or via
# direct install (CI). Pick whichever is on PATH.
if command -v pymarkdown >/dev/null 2>&1; then
  exec pymarkdown --config .pymarkdown.json scan "${EXISTING[@]}"
else
  exec uvx --from pymarkdownlnt pymarkdown --config .pymarkdown.json \
    scan "${EXISTING[@]}"
fi
