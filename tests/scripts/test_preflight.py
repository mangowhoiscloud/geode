import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/preflight.sh"


def _run_preflight(
    tmp_path: Path,
    *,
    fast: bool = False,
    audit: bool = True,
    fail_uv: str = "",
) -> subprocess.CompletedProcess[str]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    automation = scripts / "lint_automation.sh"
    automation.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    automation.chmod(0o755)
    # Source the full script, but never invoke real build, package, or Git commands.
    shell = r"""
uv() {
  printf '%s\n' "$*" >> "$PREFLIGHT_ROOT/uv-calls"
  if [ "$*" = 'run python -c import inspect_ai' ] && [ "$PREFLIGHT_AUDIT" = 0 ]; then
    return 1
  fi
  if [ "$*" = "$PREFLIGHT_FAIL_UV" ]; then
    return 17
  fi
  return 0
}
git() {
  case "$*" in
    'rev-parse --show-toplevel') printf '%s\n' "$PREFLIGHT_ROOT" ;;
    *) return 99 ;;
  esac
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
            "PREFLIGHT_AUDIT": "1" if audit else "0",
            "PREFLIGHT_FAIL_UV": fail_uv,
            "TMPDIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return completed


def test_all_gates_pass_with_complete_prerequisites(tmp_path: Path) -> None:
    completed = _run_preflight(tmp_path)
    assert completed.returncode == 0, completed.stdout
    assert "all gates passed" in completed.stdout
    calls = (tmp_path / "uv-calls").read_text(encoding="utf-8").splitlines()
    assert "run python scripts/check_official_docs.py" in calls
    assert "run pytest tests/ -m not live -q" in calls


def test_fast_mode_reports_skipped_tests(tmp_path: Path) -> None:
    completed = _run_preflight(tmp_path, fast=True)
    assert completed.returncode == 0, completed.stdout
    assert "NOT all ran — skipped: pytest" in completed.stdout
    assert "all gates passed" not in completed.stdout


def test_missing_audit_extra_fails_closed(tmp_path: Path) -> None:
    completed = _run_preflight(tmp_path, audit=False)
    assert completed.returncode == 1, completed.stdout
    assert "NOT all ran" in completed.stdout
    assert "all gates passed" not in completed.stdout


def test_gate_failure_keeps_a_full_log(tmp_path: Path) -> None:
    completed = _run_preflight(tmp_path, fail_uv="run python scripts/check_official_docs.py")
    assert completed.returncode == 1, completed.stdout
    assert "1 gate(s) failed:" in completed.stdout
    assert completed.stdout.rstrip().endswith("official docs")
    log = Path(completed.stdout.split("full log: ", 1)[1].splitlines()[0])
    assert log.is_relative_to(tmp_path)


@pytest.mark.parametrize(
    "command",
    [
        "run lint-imports --no-cache",
        "run python scripts/check_architecture_exceptions.py --check --base-ref origin/develop",
        "run python scripts/check_architecture_performance.py --check",
        "run ruff check --config ruff-production.toml core/ evals/ evolve/",
    ],
)
def test_new_static_gate_failures_propagate(tmp_path: Path, command: str) -> None:
    completed = _run_preflight(tmp_path, fast=True, fail_uv=command)
    assert completed.returncode == 1, completed.stdout
    assert command in (tmp_path / "uv-calls").read_text(encoding="utf-8").splitlines()
