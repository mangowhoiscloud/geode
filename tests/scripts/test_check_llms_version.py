"""Guard for scripts/check_llms_version.py — committed site version drift."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

guard = importlib.import_module("scripts.check_llms_version")

_HEADER = (
    "# GEODE\n\n> summary line\n\n"
    "Version v{ver}. Last sync 2026-06-12. Docs links point to twins.\n\n"
    "## Start here\n- [Docs](x)\n"
)
_SOT = 'export const SOT = {{\n  version: "{ver}",\n  syncedAt: "2026-06-12",\n}};\n'


def _stage(
    tmp_path: Path,
    *,
    pyproject_ver: str,
    llms_ver: str,
    full_ver: str,
    sot_ver: str | None = None,
) -> None:
    """Point the guard's module globals at a temp repo and write the fixtures."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "geode"\nversion = "{pyproject_ver}"\n')
    public = tmp_path / "site" / "public"
    public.mkdir(parents=True)
    llms = public / "llms.txt"
    full = public / "llms-full.txt"
    llms.write_text(_HEADER.format(ver=llms_ver))
    full.write_text(_HEADER.format(ver=full_ver))
    sot = tmp_path / "site" / "src" / "data" / "geode" / "sot.ts"
    sot.parent.mkdir(parents=True)
    sot.write_text(_SOT.format(ver=sot_ver if sot_ver is not None else pyproject_ver))
    guard.PYPROJECT = pyproject
    guard.REPO_ROOT = tmp_path
    guard.LLMS_FILES = (llms, full)
    guard.SOT_FILE = sot


def test_matching_versions_pass(tmp_path: Path) -> None:
    _stage(tmp_path, pyproject_ver="1.0.0", llms_ver="1.0.0", full_ver="1.0.0")
    assert guard.main([]) == 0


def test_llms_drift_fails(tmp_path: Path) -> None:
    _stage(tmp_path, pyproject_ver="1.0.0", llms_ver="0.99.189", full_ver="1.0.0")
    assert guard.main([]) == 1


def test_sot_drift_fails_even_when_llms_clean(tmp_path: Path) -> None:
    """The false pass Codex demonstrated: llms headers current but sot.ts stale."""
    _stage(tmp_path, pyproject_ver="1.0.0", llms_ver="1.0.0", full_ver="1.0.0", sot_ver="0.99.189")
    assert guard.main([]) == 1


def test_fix_rewrites_llms_headers_but_not_sot(tmp_path: Path) -> None:
    _stage(tmp_path, pyproject_ver="1.2.3", llms_ver="0.99.189", full_ver="0.99.0")
    assert guard.main(["--fix"]) == 0
    assert guard.main([]) == 0  # post-fix verify clean
    assert guard.read_header_version(guard.LLMS_FILES[0]) == "1.2.3"
    assert guard.read_header_version(guard.LLMS_FILES[1]) == "1.2.3"
    # the "Last sync" date is left untouched (it marks the last full body sync)
    assert "Last sync 2026-06-12" in guard.LLMS_FILES[0].read_text()


def test_fix_cannot_resolve_sot_drift(tmp_path: Path) -> None:
    """--fix patches llms headers but sot.ts is generated — drift still fails,
    nudging the operator to rerun sync-stats."""
    _stage(tmp_path, pyproject_ver="2.0.0", llms_ver="0.99.0", full_ver="0.99.0", sot_ver="0.99.0")
    assert guard.main(["--fix"]) == 1  # llms patched, sot.ts still stale
    assert guard.read_sot_version() == "0.99.0"  # untouched by --fix


def test_missing_header_reports_drift(tmp_path: Path) -> None:
    _stage(tmp_path, pyproject_ver="1.0.0", llms_ver="1.0.0", full_ver="1.0.0")
    guard.LLMS_FILES[1].write_text("# GEODE\n\nno version header here\n")
    assert guard.main([]) == 1


@pytest.fixture(autouse=True)
def _restore_globals() -> object:
    saved = (guard.PYPROJECT, guard.REPO_ROOT, guard.LLMS_FILES, guard.SOT_FILE)
    yield
    guard.PYPROJECT, guard.REPO_ROOT, guard.LLMS_FILES, guard.SOT_FILE = saved
