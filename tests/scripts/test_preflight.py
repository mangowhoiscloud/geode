import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/preflight.sh"
NPM_COMMANDS = ["run sync-stats", "run build", "run export-md"]


def _run_preflight(
    tmp_path: Path, *, fail: str = "", drift: bool = False, fast: bool = False, modules: bool = True
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    site = tmp_path / "site"
    site.mkdir()
    if modules:
        (site / "node_modules").mkdir()
    calls = tmp_path / "calls"
    calls.touch()
    # Source the full script, but never invoke real build, package, or Git commands.
    shell = r"""
uv() { return 0; }
git() {
  case "$*" in
    'rev-parse --show-toplevel') printf '%s\n' "$PREFLIGHT_ROOT" ;;
    'diff --exit-code -- '*)
      printf 'git diff\n' >> "$PREFLIGHT_CALLS"
      if [ "$PREFLIGHT_DRIFT" = 1 ]; then
        printf 'generated docs drift\n' >&2
        return 1
      fi ;;
    *) return 99 ;;
  esac
}
npm() {
  printf '%s\n' "$*" >> "$PREFLIGHT_CALLS"
  if [ "$*" = "$PREFLIGHT_FAIL" ]; then
    printf 'npm %s failed\n' "$*" >&2
    return 23
  fi
}
preflight_script=$1
shift
source "$preflight_script" "$@"
"""
    completed = subprocess.run(  # noqa: S603 - fixed shell with inert command stubs
        ["/bin/bash", "-c", shell, "preflight-test", str(SCRIPT), *(["--fast"] if fast else [])],
        cwd=tmp_path,
        env={
            "PATH": "/usr/bin:/bin",
            "PREFLIGHT_ROOT": str(tmp_path),
            "PREFLIGHT_CALLS": str(calls),
            "PREFLIGHT_FAIL": fail,
            "PREFLIGHT_DRIFT": "1" if drift else "0",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return completed, calls.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("command", NPM_COMMANDS)
def test_site_generator_failure_fails_gate(tmp_path: Path, command: str) -> None:
    completed, calls = _run_preflight(tmp_path, fail=command)
    assert completed.returncode == 1, completed.stdout
    assert "1 gate(s) failed:" in completed.stdout
    assert "site generation" in completed.stdout
    assert f"npm {command} failed" in completed.stdout
    assert "all gates passed" not in completed.stdout
    assert calls == [*NPM_COMMANDS[: NPM_COMMANDS.index(command) + 1], "git diff"]


def test_site_generators_and_clean_diff_pass(tmp_path: Path) -> None:
    completed, calls = _run_preflight(tmp_path)
    assert completed.returncode == 0, completed.stdout
    assert "all gates passed" in completed.stdout
    assert calls == [*NPM_COMMANDS, "git diff"]


def test_generated_docs_drift_fails_gate(tmp_path: Path) -> None:
    completed, calls = _run_preflight(tmp_path, drift=True)
    assert completed.returncode == 1, completed.stdout
    assert "1 gate(s) failed:" in completed.stdout
    assert "public-doc generators" in completed.stdout
    assert "generated docs drift" in completed.stdout
    assert "all gates passed" not in completed.stdout
    assert calls == [*NPM_COMMANDS, "git diff"]


@pytest.mark.parametrize("fast,modules", [(True, True), (False, False)])
def test_skipped_site_reports_incomplete_gate_coverage(
    tmp_path: Path, fast: bool, modules: bool
) -> None:
    completed, calls = _run_preflight(tmp_path, fast=fast, modules=modules)
    assert completed.returncode == 0, completed.stdout
    assert "gates passed, but NOT all ran" in completed.stdout
    assert "site generated docs" in completed.stdout
    assert "all gates passed" not in completed.stdout
    assert calls == []
