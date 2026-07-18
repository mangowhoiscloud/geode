"""Regression tests for the public-site metadata generator."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_project_version(root: Path, version: str) -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "geode-agent"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def _prepare_site_fixture(root: Path) -> Path:
    site = root / "site"
    scripts = site / "scripts"
    data = site / "src" / "data" / "geode"
    sitemap = site / "src" / "lib" / "geode-docs"
    public = site / "public"
    scripts.mkdir(parents=True)
    data.mkdir(parents=True)
    sitemap.mkdir(parents=True)
    public.mkdir(parents=True)

    for name in ("sync-stats.mjs", "sitemap-pages.mjs"):
        shutil.copy2(REPO_ROOT / "site" / "scripts" / name, scripts / name)

    (sitemap / "sitemap.ts").write_text(
        """export const sitemap = [
  {
    title: "Start",
    titleKo: "시작",
    pages: [
      { slug: "quick-start", title: "Quick start", titleKo: "빠른 시작", summary: "Install GEODE", summaryKo: "GEODE 설치" },
    ],
  },
];
""",
        encoding="utf-8",
    )
    (data / "sot.ts").write_text(
        'export const GEODE_SOT = {\n  version: "0.99.331",\n  syncedAt: "2026-07-14",\n} as const;\n',
        encoding="utf-8",
    )
    (data / "architecture-baseline.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "packages": {
                    "core": {"python_files": 1},
                    "plugins": {"python_files": 1},
                    "tests": {"python_files": 1},
                },
                "tools": {"definition_count": 2},
                "hook_events": {"count": 3},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n- Pending.\n\n## [0.99.331] - 2026-07-14\n\n- Released.\n",
        encoding="utf-8",
    )
    return site


def _run_sync_stats(node: str, root: Path, site: Path, epoch: int) -> str:
    env = {
        **os.environ,
        "GEODE_REPO": str(root),
        "SOURCE_DATE_EPOCH": str(epoch),
    }
    subprocess.run(  # noqa: S603 - fixed local script and isolated fixture
        [node, str(site / "scripts" / "sync-stats.mjs")],
        cwd=site,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return (site / "src" / "data" / "geode" / "sot.ts").read_text(encoding="utf-8")


def test_sync_stats_preserves_same_version_date_before_source_epoch(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the site metadata generator")

    site = _prepare_site_fixture(tmp_path)
    epoch = int(datetime(2030, 1, 2, tzinfo=UTC).timestamp())
    _write_project_version(tmp_path, "0.99.331")

    same_version = _run_sync_stats(node, tmp_path, site, epoch)
    assert 'syncedAt: "2026-07-14"' in same_version

    _write_project_version(tmp_path, "0.99.332")
    next_version = _run_sync_stats(node, tmp_path, site, epoch)
    assert 'syncedAt: "2030-01-02"' in next_version


def test_sync_stats_rejects_missing_architecture_baseline(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the site metadata generator")

    site = _prepare_site_fixture(tmp_path)
    _write_project_version(tmp_path, "0.99.331")
    (site / "src" / "data" / "geode" / "architecture-baseline.json").unlink()

    env = {**os.environ, "GEODE_REPO": str(tmp_path)}
    process = subprocess.run(  # noqa: S603 - fixed local script and isolated fixture
        [node, str(site / "scripts" / "sync-stats.mjs")],
        cwd=site,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode != 0
    assert "cannot read generated architecture baseline" in process.stderr
