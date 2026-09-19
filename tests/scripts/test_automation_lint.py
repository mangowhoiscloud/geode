"""Automation scans retain analyzer failures and NUL-delimited file names."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/lint_automation.sh"


@pytest.mark.parametrize("failed_tool", ["", "actionlint", "shellcheck"])
def test_automation_scan_preserves_failures_and_file_boundaries(
    tmp_path: Path, failed_tool: str
) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    stubs = {
        "git": r"""case "$1" in
rev-parse) printf '%s\n' "$SCAN_ROOT";;
ls-files) printf '%s\0' '.claude/hooks/check-progress.sh' 'scripts/with space.sh';;
*) exit 99;;
esac
""",
        "actionlint": """[ "${1:-}" = -version ] && exit 0
[ "$FAILED_TOOL" = actionlint ] && exit 17
exit 0
""",
        "shellcheck": r"""[ "${1:-}" = --version ] && exit 0
printf 'checked:%s\n' "$@"
[ "$FAILED_TOOL" = shellcheck ] && exit 19
exit 0
""",
    }
    for name, body in stubs.items():
        path = tools / name
        path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
        path.chmod(0o755)
    result = subprocess.run(  # noqa: S603 -- fixed runner with inert analyzer stubs
        ["/bin/bash", str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "SCAN_ROOT": str(tmp_path),
            "FAILED_TOOL": failed_tool,
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert (result.returncode != 0) is bool(failed_tool), result.stderr
    if failed_tool != "actionlint":
        assert "checked:.claude/hooks/check-progress.sh" in result.stdout
        assert "checked:scripts/with space.sh" in result.stdout
