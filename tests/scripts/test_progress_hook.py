"""Progress reminders must preserve unknown state and cannot authorize a merge."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude/hooks/check-progress.sh"


@pytest.mark.parametrize(
    "history,fetch,branch,ahead,expected",
    [
        (0, 0, 0, 0, ""),
        (1, 0, 0, 0, "커밋 조회 실패"),
        (0, 1, 0, 0, "원격 조회 실패"),
        (0, 0, 1, 0, "브랜치 조회 실패"),
        (0, 0, 0, 3, "커밋 수는 병합 근거가 아닙니다"),
    ],
)
def test_reminder_is_truthful_and_advisory(
    tmp_path: Path, history: int, fetch: int, branch: int, ahead: int, expected: str
) -> None:
    shell = r"""
git() {
  case "$*" in
    'rev-list --count --since='*) printf '0\n'; return "$HISTORY_EXIT" ;;
    'fetch origin --quiet') return "$FETCH_EXIT" ;;
    'rev-list --count origin/main..origin/develop') printf '%s\n' "$AHEAD"; return "$BRANCH_EXIT" ;;
    *) return 99 ;;
  esac
}
source "$1"
"""
    result = subprocess.run(  # noqa: S603 -- inert Git stubs, fixed hook under test
        ["/bin/bash", "-c", shell, "progress-hook-test", str(HOOK)],
        cwd=tmp_path,
        env={
            **os.environ,
            "HISTORY_EXIT": str(history),
            "FETCH_EXIT": str(fetch),
            "BRANCH_EXIT": str(branch),
            "AHEAD": str(ahead),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["continue"] is True
    if expected:
        assert expected in report["message"]
        assert "merge를 진행하세요" not in report["message"]
    else:
        assert report == {"continue": True}
