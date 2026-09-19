import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/preflight.sh"
NPM_COMMANDS = ["run sync-stats", "run build", "run export-md"]
SITE_CHECKS = ["run lint", "run typecheck"]


def _run_preflight(
    tmp_path: Path,
    *,
    fail: str = "",
    drift: bool = False,
    fast: bool = False,
    modules: bool = True,
    audit: bool = True,
    fail_uv: str = "",
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    site = tmp_path / "site"
    site.mkdir()
    if modules:
        (site / "node_modules").mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    automation = scripts / "lint_automation.sh"
    automation.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    automation.chmod(0o755)
    calls = tmp_path / "calls"
    calls.touch()
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
            "PREFLIGHT_AUDIT": "1" if audit else "0",
            "PREFLIGHT_FAIL_UV": fail_uv,
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
    assert calls == [*SITE_CHECKS, *NPM_COMMANDS[: NPM_COMMANDS.index(command) + 1], "git diff"]


def test_site_generators_and_clean_diff_pass(tmp_path: Path) -> None:
    completed, calls = _run_preflight(tmp_path)
    assert completed.returncode == 0, completed.stdout
    assert "all gates passed" in completed.stdout
    assert calls == [*SITE_CHECKS, *NPM_COMMANDS, "git diff"]


def test_generated_docs_drift_fails_gate(tmp_path: Path) -> None:
    completed, calls = _run_preflight(tmp_path, drift=True)
    assert completed.returncode == 1, completed.stdout
    assert "1 gate(s) failed:" in completed.stdout
    assert "public-doc generators" in completed.stdout
    assert "generated docs drift" in completed.stdout
    assert "all gates passed" not in completed.stdout
    assert calls == [*SITE_CHECKS, *NPM_COMMANDS, "git diff"]


@pytest.mark.parametrize("fast,modules", [(True, True), (False, False)])
def test_skipped_site_reports_incomplete_gate_coverage(
    tmp_path: Path, fast: bool, modules: bool
) -> None:
    completed, calls = _run_preflight(tmp_path, fast=fast, modules=modules)
    assert completed.returncode == (0 if fast else 1), completed.stdout
    assert "NOT all ran" in completed.stdout
    assert "site generated docs" in completed.stdout
    assert "all gates passed" not in completed.stdout
    assert calls == []


@pytest.mark.parametrize("audit,modules,exit_code", [(False, True, 1), (False, False, 2)])
def test_missing_full_mode_prerequisites_fail_closed(
    tmp_path: Path, audit: bool, modules: bool, exit_code: int
) -> None:
    completed, _ = _run_preflight(tmp_path, audit=audit, modules=modules)
    assert completed.returncode == exit_code, completed.stdout
    assert "NOT all ran" in completed.stdout
    assert "all gates passed" not in completed.stdout


@pytest.mark.parametrize("command", SITE_CHECKS)
def test_site_static_check_failure_survives_successful_generation(
    tmp_path: Path, command: str
) -> None:
    completed, calls = _run_preflight(tmp_path, fail=command)
    assert completed.returncode == 1, completed.stdout
    assert "site lint / types" in completed.stdout
    assert calls == [*SITE_CHECKS[: SITE_CHECKS.index(command) + 1], *NPM_COMMANDS, "git diff"]


@pytest.mark.parametrize(
    "command",
    [
        "run lint-imports --no-cache",
        "run python scripts/check_architecture_exceptions.py --check --base-ref origin/develop",
        "run ruff check --config ruff-production.toml core/ evals/ evolve/",
    ],
)
def test_new_static_gate_failures_propagate(tmp_path: Path, command: str) -> None:
    completed, _ = _run_preflight(tmp_path, fast=True, fail_uv=command)
    assert completed.returncode == 1, completed.stdout
    assert command in (tmp_path / "uv-calls").read_text(encoding="utf-8").splitlines()
