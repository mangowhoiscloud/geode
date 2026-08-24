"""Tests for ``scripts/slop_audit.py`` — the diagnostic audit driver.

Smoke-tests every lens against the current tree so a refactor that breaks the
audit script surfaces immediately. Its heuristic counts are diagnostic; the
old absolute-count snapshot is preserved under ``docs/reference/`` as
historical evidence only.
"""

from __future__ import annotations

import importlib.util
import subprocess
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


def test_scan_roots_cover_every_production_package(slop_audit: ModuleType) -> None:
    assert slop_audit.SCAN_ROOTS == (
        "core/",
        "evals/",
        "evolve/",
        "scripts/",
    )


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


@pytest.mark.parametrize(("returncode", "stdout"), [(2, ""), (1, "not-json")])
def test_unused_import_scan_fails_closed(
    slop_audit: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
) -> None:
    monkeypatch.setattr(
        slop_audit.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr="ruff failed"
        ),
    )

    with pytest.raises(RuntimeError, match="ruff F401 scan"):
        slop_audit.lens_unused_imports()


def test_unused_import_scan_accepts_ruff_findings(
    slop_audit: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    finding = {
        "filename": str(slop_audit.REPO_ROOT / "core" / "example.py"),
        "location": {"row": 7},
        "code": "F401",
    }
    monkeypatch.setattr(
        slop_audit.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout=slop_audit.json.dumps([finding]), stderr=""
        ),
    )

    result = slop_audit.lens_unused_imports()

    assert result.count == 1
    assert result.samples == ["core/example.py:7 F401"]
    assert result.severity == "warning"


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


def test_historical_baseline_is_reference_only() -> None:
    path = REPO_ROOT / "docs" / "reference" / "2026-05-18-slop-audit-baseline.md"
    text = path.read_text(encoding="utf-8")
    assert "status: historical" in text
    assert "authority: reference-only" in text
    assert "source_repository: https://github.com/mangowhoiscloud/geode" in text
    assert "source_commit: 4fe594eb66b5de6bb3daedef7b433d59fcf719bb" in text
    assert "superseded_by: docs/plans/2026-08-19-runtime-evidence-debt-modernization.md" in text
    assert "| dead_private_functions | 139 |" in text
    assert "| duplicate_signatures | 76 |" in text
    assert "| lint_bypass_markers | 91 |" in text
    assert not (REPO_ROOT / "scripts" / "slop_audit_baseline.md").exists()


def test_obsolete_baseline_flag_is_rejected() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, REPO_ROOT / "scripts" / "slop_audit.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments: --check" in result.stderr


def test_stale_reference_lens_reports_candidate_and_honors_keep_marker(
    slop_audit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_root = tmp_path / "fake_repo"
    (tmp_root / "core").mkdir(parents=True)
    (tmp_root / "core" / "candidate.py").write_text(
        '"""Runtime still mentions BudgetGuard."""\n',
        encoding="utf-8",
    )
    (tmp_root / "core" / "historical.py").write_text(
        '"""Doc that mentions BudgetGuard for historical context."""  # slop:keep\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(slop_audit, "REPO_ROOT", tmp_root)
    monkeypatch.setattr(slop_audit, "SCAN_ROOTS", ("core/",))

    result = slop_audit.lens_stale_references()

    assert result.count == 1
    assert result.samples == ["core/candidate.py:1 :: BudgetGuard"]


def test_current_stale_reference_lens_is_clean(slop_audit: ModuleType) -> None:
    result = slop_audit.lens_stale_references()

    assert result.count == 0
    assert result.severity == "info"
