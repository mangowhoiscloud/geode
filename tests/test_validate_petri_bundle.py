"""Unit tests for scripts/validate_petri_bundle.py ratchet.

Validator gates the GitHub Pages deploy of docs/self-improving/petri-bundle/. Failure modes
exercised here mirror the regressions that previously broke the live viewer
(PR #1129 partial archive, PR #1130 error archive, results=None TypeError).
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "validate_petri_bundle.py"


_VALID_HEADER: dict[str, object] = {
    "version": 2,
    "status": "success",
    "eval": {"eval_id": "abc", "task": "inspect_petri/audit"},
    "results": {
        "total_samples": 1,
        "completed_samples": 1,
        "scores": [
            {
                "name": "demo",
                "scorer": "audit_judge",
                "metrics": {
                    "mean": {"name": "mean", "value": 1.0, "params": {}},
                    "stderr": {"name": "stderr", "value": 0.0, "params": {}},
                },
            }
        ],
    },
}


def _write_eval(path: Path, header: dict[str, object]) -> None:
    """Create a minimal .eval (STORED-compression zip with header.json)."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("header.json", json.dumps(header))


def _scaffold_bundle(root: Path, listing: dict[str, dict[str, object]]) -> Path:
    """Build a minimal docs/self-improving/petri-bundle/ scaffold under root."""
    bundle = root / "docs" / "self-improving/petri-bundle"
    (bundle / "logs").mkdir(parents=True)
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>")
    (bundle / "assets" / "index.js").write_text("// noop")
    (bundle / "assets" / "index.css").write_text("/* noop */")
    (bundle / "logs" / "listing.json").write_text(json.dumps(listing))
    return bundle


def run_validator(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_listing_fails(tmp_path: Path) -> None:
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "missing" in result.stderr.lower()


def test_listing_invalid_json_fails(tmp_path: Path) -> None:
    bundle = tmp_path / "docs" / "self-improving/petri-bundle" / "logs"
    bundle.mkdir(parents=True)
    (bundle / "listing.json").write_text("{not json")
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "not valid JSON" in result.stderr


def test_status_started_fails(tmp_path: Path) -> None:
    bundle = _scaffold_bundle(
        tmp_path,
        {"partial.eval": {"status": "started"}},
    )
    (bundle / "logs" / "partial.eval").write_text("placeholder")
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "started" in result.stdout


def test_status_error_fails(tmp_path: Path) -> None:
    bundle = _scaffold_bundle(
        tmp_path,
        {"broken.eval": {"status": "error"}},
    )
    (bundle / "logs" / "broken.eval").write_text("placeholder")
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "error" in result.stdout


def test_missing_eval_file_fails(tmp_path: Path) -> None:
    _scaffold_bundle(
        tmp_path,
        {"phantom.eval": {"status": "success"}},
    )
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "missing on disk" in result.stdout


def test_missing_asset_fails(tmp_path: Path) -> None:
    bundle = _scaffold_bundle(tmp_path, {})
    (bundle / "index.html").unlink()
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "asset missing" in result.stdout


def test_valid_bundle_passes(tmp_path: Path) -> None:
    bundle = _scaffold_bundle(
        tmp_path,
        {"good.eval": {"status": "success"}},
    )
    _write_eval(bundle / "logs" / "good.eval", _VALID_HEADER)
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK:" in result.stdout


def test_archive_results_none_fails(tmp_path: Path) -> None:
    """Empty results = the inspect_ai #1747 TypeError trigger."""
    bundle = _scaffold_bundle(
        tmp_path,
        {"empty.eval": {"status": "success"}},
    )
    bad_header = {**_VALID_HEADER, "results": None}
    _write_eval(bundle / "logs" / "empty.eval", bad_header)
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "results missing" in result.stdout or "results.scores" in result.stdout


def test_archive_empty_scores_fails(tmp_path: Path) -> None:
    bundle = _scaffold_bundle(
        tmp_path,
        {"noscores.eval": {"status": "success"}},
    )
    bad_header = {**_VALID_HEADER, "results": {"scores": []}}
    _write_eval(bundle / "logs" / "noscores.eval", bad_header)
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "scores" in result.stdout


def test_archive_empty_metrics_fails(tmp_path: Path) -> None:
    bundle = _scaffold_bundle(
        tmp_path,
        {"nometrics.eval": {"status": "success"}},
    )
    bad_header = {
        **_VALID_HEADER,
        "results": {
            "scores": [{"name": "demo", "scorer": "audit_judge", "metrics": {}}],
        },
    }
    _write_eval(bundle / "logs" / "nometrics.eval", bad_header)
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "metrics" in result.stdout


def test_archive_bad_zip_fails(tmp_path: Path) -> None:
    bundle = _scaffold_bundle(
        tmp_path,
        {"corrupt.eval": {"status": "success"}},
    )
    (bundle / "logs" / "corrupt.eval").write_bytes(b"\x00\x01not-a-zip")
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "zip" in result.stdout.lower()


def test_archive_header_missing_inside_fails(tmp_path: Path) -> None:
    bundle = _scaffold_bundle(
        tmp_path,
        {"noheader.eval": {"status": "success"}},
    )
    # zip with no header.json entry
    with zipfile.ZipFile(bundle / "logs" / "noheader.eval", "w") as zf:
        zf.writestr("summaries.json", "[]")
    result = run_validator(tmp_path)
    assert result.returncode == 1
    assert "header.json missing" in result.stdout


def test_real_bundle_passes() -> None:
    """Smoke test against the committed bundle. Guards against silent drift."""
    repo_root = Path(__file__).resolve().parent.parent
    if not (repo_root / "docs" / "self-improving/petri-bundle" / "logs" / "listing.json").exists():
        pytest.skip("petri-bundle not present in this checkout")
    result = run_validator(repo_root)
    assert result.returncode == 0, result.stdout + result.stderr
