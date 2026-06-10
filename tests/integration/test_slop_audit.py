"""Tests for ``scripts/slop_audit.py`` — the slop-prevention audit driver.

Smoke-tests every lens against the current tree so a refactor that
breaks the audit script surfaces immediately. The baseline file at
``docs/audits/2026-05-18-slop-audit-baseline.md`` is the authoritative
contract for "the slop counts we accept as the current floor".
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_slop_audit_module() -> ModuleType:
    """Load scripts/slop_audit.py without putting scripts/ on sys.path."""
    path = REPO_ROOT / "scripts" / "slop_audit.py"
    spec = importlib.util.spec_from_file_location("_slop_audit_for_tests", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_slop_audit_for_tests"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def slop_audit() -> ModuleType:
    return _load_slop_audit_module()


def test_run_all_lenses_returns_six_results(slop_audit: ModuleType) -> None:
    results = slop_audit.run_all_lenses()
    names = [r.name for r in results]
    assert names == [
        "unused_imports",
        "dead_private_functions",
        "duplicate_signatures",
        "abandoned_todos",
        "lint_bypass_markers",
        "stale_references",
    ]


def test_stale_references_zero(slop_audit: ModuleType) -> None:
    """The stale-reference lens must be zero on develop after PR 3.

    PR 0 / PR 1 documentation refers to BudgetGuard / FitnessBaseline /
    seeds_safe10 in historical context — those occurrences carry a
    ``# slop:keep`` marker so this lens stays clean.
    """
    result = slop_audit.lens_stale_references()
    assert result.count == 0, (
        f"stale_references must be 0; got {result.count}. Samples: {result.samples}"
    )


def test_unused_imports_below_threshold(slop_audit: ModuleType) -> None:
    """Unused imports must stay under a coarse threshold.

    Threshold is intentionally loose — the audit fires per-PR via
    `--check`, not at every commit. CI fast-fail is the F401 ruff
    rule on the changed files, not this aggregate.
    """
    result = slop_audit.lens_unused_imports()
    assert result.count <= 50, f"unused_imports count {result.count} exceeds soft threshold 50"


def test_format_report_renders_table(slop_audit: ModuleType) -> None:
    results = slop_audit.run_all_lenses()
    report = slop_audit.format_report(results, header="test run")
    assert "| Lens | Count | Severity |" in report
    assert "## Samples (first 5 per lens)" in report
    for name in [
        "unused_imports",
        "dead_private_functions",
        "duplicate_signatures",
        "abandoned_todos",
        "lint_bypass_markers",
        "stale_references",
    ]:
        assert name in report


def test_baseline_load_round_trip(tmp_path: Path, slop_audit: ModuleType) -> None:
    """`load_baseline` reads a generated report back into a count dict."""
    results = slop_audit.run_all_lenses()
    report = slop_audit.format_report(results, header="round trip")
    baseline_path = tmp_path / "baseline.md"
    baseline_path.write_text(report + "\n", encoding="utf-8")

    loaded = slop_audit.load_baseline(baseline_path)
    for r in results:
        assert loaded[r.name] == r.count, f"round trip mismatch for {r.name}"


def test_baseline_file_committed() -> None:
    """The canonical baseline file must exist for `--check` mode."""
    path = REPO_ROOT / "docs/audits/2026-05-18-slop-audit-baseline.md"
    assert path.is_file(), f"missing baseline file at {path}"


def test_slop_keep_marker_works(
    slop_audit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A line with ``# slop:keep`` and a stale ref is ignored."""
    tmp_root = tmp_path / "fake_repo"
    (tmp_root / "core").mkdir(parents=True)
    sample = tmp_root / "core" / "fake.py"
    sample.write_text(
        '"""Doc that mentions BudgetGuard for historical context."""  # slop:keep\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(slop_audit, "REPO_ROOT", tmp_root)
    monkeypatch.setattr(slop_audit, "SCAN_ROOTS", ("core/",))
    result = slop_audit.lens_stale_references()
    assert result.count == 0
