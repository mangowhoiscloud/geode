"""Guard for scripts/check_llms_version.py — committed llms version drift."""

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


def _stage(tmp_path: Path, *, pyproject_ver: str, llms_ver: str, full_ver: str) -> None:
    """Point the guard's module globals at a temp repo and write the fixtures."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "geode"\nversion = "{pyproject_ver}"\n')
    public = tmp_path / "site" / "public"
    public.mkdir(parents=True)
    llms = public / "llms.txt"
    full = public / "llms-full.txt"
    llms.write_text(_HEADER.format(ver=llms_ver))
    full.write_text(_HEADER.format(ver=full_ver))
    guard.PYPROJECT = pyproject
    guard.REPO_ROOT = tmp_path
    guard.LLMS_FILES = (llms, full)


def test_matching_versions_pass(tmp_path: Path) -> None:
    _stage(tmp_path, pyproject_ver="1.0.0", llms_ver="1.0.0", full_ver="1.0.0")
    assert guard.main([]) == 0


def test_drift_fails(tmp_path: Path) -> None:
    _stage(tmp_path, pyproject_ver="1.0.0", llms_ver="0.99.189", full_ver="1.0.0")
    assert guard.main([]) == 1


def test_fix_rewrites_both_headers(tmp_path: Path) -> None:
    _stage(tmp_path, pyproject_ver="1.2.3", llms_ver="0.99.189", full_ver="0.99.0")
    assert guard.main(["--fix"]) == 0
    # post-fix, a plain verify is clean
    assert guard.main([]) == 0
    assert guard.read_header_version(guard.LLMS_FILES[0]) == "1.2.3"
    assert guard.read_header_version(guard.LLMS_FILES[1]) == "1.2.3"
    # the "Last sync" date is left untouched (it marks the last full body sync)
    assert "Last sync 2026-06-12" in guard.LLMS_FILES[0].read_text()


def test_missing_header_reports_drift(tmp_path: Path) -> None:
    _stage(tmp_path, pyproject_ver="1.0.0", llms_ver="1.0.0", full_ver="1.0.0")
    guard.LLMS_FILES[1].write_text("# GEODE\n\nno version header here\n")
    assert guard.main([]) == 1


@pytest.fixture(autouse=True)
def _restore_globals() -> object:
    saved = (guard.PYPROJECT, guard.REPO_ROOT, guard.LLMS_FILES)
    yield
    guard.PYPROJECT, guard.REPO_ROOT, guard.LLMS_FILES = saved
