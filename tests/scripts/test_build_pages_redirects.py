"""Contract tests for the redirect-only GitHub Pages site."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "github-pages"
BUILDER = REPO_ROOT / "scripts" / "build_pages_redirects.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="the redirect builder runs on Node.js")


def _frozen_paths() -> list[str]:
    paths = json.loads((SOURCE / "redirect-paths.json").read_text(encoding="utf-8"))["paths"]
    assert isinstance(paths, list)
    return paths


def _redirect(path: str, search: str = "", fragment: str = "") -> str:
    script = (
        "const { pagesRedirect } = await import(process.argv[1]);"
        "console.log(pagesRedirect(process.argv[2], process.argv[3], process.argv[4]));"
    )
    result = subprocess.run(  # noqa: S603 - resolved node binary and fixed script
        [
            str(NODE),
            "--input-type=module",
            "-e",
            script,
            (SOURCE / "rules.js").as_uri(),
            path,
            search,
            fragment,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pages")
    subprocess.run([str(NODE), str(BUILDER), "--out", str(out)], check=True, capture_output=True)  # noqa: S603
    return out


def test_frozen_paths_are_sorted_unique_pages_or_text_under_geode() -> None:
    paths = _frozen_paths()

    assert paths == sorted(set(paths))
    assert all(path.startswith("/geode/") for path in paths)
    assert all(re.search(r"(/|\.html|\.md|\.txt)$", path) for path in paths)


def test_every_frozen_path_gets_one_file_plus_the_fallback(site: Path) -> None:
    files = [path for path in site.rglob("*") if path.is_file()]

    assert len(files) == len(_frozen_paths()) + 3
    assert {"404.html", "rules.js", ".nojekyll"} <= {path.name for path in site.iterdir()}


@pytest.mark.parametrize(
    ("path", "file", "target"),
    [
        ("/geode/", "index.html", "https://mangowhois.ai/products/geode/"),
        (
            "/geode/docs/petri/bundle/",
            "docs/petri/bundle/index.html",
            "https://mangowhois.ai/products/geode/docs/petri/bundle/",
        ),
        (
            "/geode/research/geode/",
            "research/geode/index.html",
            "https://tech.mangowhois.ai/geode/",
        ),
        (
            "/geode/petri-bundle/index.html",
            "petri-bundle/index.html",
            "https://tech.mangowhois.ai/self-improving/audits/index.html",
        ),
    ],
)
def test_page_stub_redirects_with_canonical_link_and_noindex(
    site: Path, path: str, file: str, target: str
) -> None:
    html = (site / file).read_text(encoding="utf-8")

    assert path in _frozen_paths()
    assert '<meta name="robots" content="noindex">' in html
    assert f'<link rel="canonical" href="{target}">' in html
    assert f'<meta http-equiv="refresh" content="0; url={target}">' in html
    assert f'<a href="{target}">' in html


def test_retired_operator_doc_points_to_its_last_github_copy(site: Path) -> None:
    note = (site / "self-improving" / "loop-overview.md").read_text(encoding="utf-8")

    assert note == (
        "This file moved to https://github.com/mangowhoiscloud/geode/blob/"
        "10f41ebe2f01718cc92af40153c7deef7b62b4bf/docs/self-improving/loop-overview.md\n"
    )


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/geode/report.pdf", "https://tech.mangowhois.ai/geode/report/ko.pdf"),
        (
            "/geode/self-improving/seed-generation/gen1-x/agent/a.html",
            "https://tech.mangowhois.ai/self-improving/seed-generation/runs/gen1-x/agents/a.html",
        ),
        (
            "/geode/self-improving/petri-bundle/logs/listing.json",
            "https://tech.mangowhois.ai/self-improving/audits/logs/listing.json",
        ),
        ("/geode/never/published", "https://mangowhois.ai/products/geode/never/published"),
        ("/elsewhere", "https://mangowhois.ai/products/geode/"),
    ],
)
def test_fallback_rules_map_unknown_paths_by_prefix(path: str, target: str) -> None:
    assert _redirect(path) == target


def test_fallback_keeps_query_and_fragment() -> None:
    assert _redirect("/geode/docs/run/providers/", "?lang=en", "#oauth") == (
        "https://mangowhois.ai/products/geode/docs/run/providers/?lang=en#oauth"
    )
