#!/usr/bin/env bash
# Check every workflow (including embedded shell) and tracked shell script.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
command -v actionlint >/dev/null
command -v shellcheck >/dev/null
actionlint -version
shellcheck --version
actionlint
git ls-files -z -- '*.sh' | xargs -0 shellcheck
