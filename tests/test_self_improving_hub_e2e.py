"""E2E self-verification suite for the GEODE Self-Improving Hub.

Sprint context: PR-SELF-IMPROVING-HUB (#1710) shipped
``docs/self-improving/index.html`` built by
``scripts/build_self_improving_hub.py``. Operator directive 2026-05-26:
"검증 절차 높이고. E2E로 자체 동작 검증도 가능하게 해" — raise
verification rigor and enable self E2E verification.

This suite runs the builder against fixture data
(``tests/fixtures/self_improving_hub/``) and asserts every contract
documented in ``docs/design/self-improving-hub-system.md`` +
``docs/design/self-improving-hub.md``:

1. **Build invariants** — script runs, exit 0, writes output to expected
   path, idempotent (same content on re-run).
2. **Sidebar contract** — all 7 sections present (Hub / Petri Audit /
   Seed Generation / Autoresearch / Docs / Meta) plus GitHub repo link
   in Meta.
3. **Section contract** — 4 main sections (Petri Audit / Seed Generation
   / Autoresearch / Documentation) each render with expected columns.
4. **Harness chip mapping** — every model prefix resolves to the
   correct chip class (PAYG / Claude Code / Codex / GEODE).
5. **URL safety** — every ``href`` starts with ``/geode/`` (no missing
   basePath) or is an external ``https://``.
6. **Version stamp** — ``pyproject.toml`` version is interpolated into
   the build-info footer.
7. **Empty state** — when a fixture data file is missing, the
   corresponding section renders the documented empty state.
8. **Accessibility** — sidebar has ``<nav>`` + ``aria-label``,
   active link gets ``aria-current``.
9. **No emoji / no card-lifts** — design system anti-patterns are
   absent from the rendered output.
10. **DESIGN.md frontmatter parity** — all 10 hub DESIGN.md docs carry
    matching ``geode_version`` (drift detection).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER = REPO_ROOT / "scripts" / "build_self_improving_hub.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "self_improving_hub"
DESIGN_DIR = REPO_ROOT / "docs" / "design"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_builder(
    out_dir: Path,
    *,
    bundle_root: Path | None = None,
    autoresearch_root: Path | None = None,
    seedgen_out_dir: Path | None = None,
    autoresearch_out_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the hub builder against fixture roots, output into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Redirect EVERY output dir to a sibling under the test's own out_dir so a
    # builder run never writes into the production docs/ tree. The builder
    # defaults --out / --seedgen-out-dir / --autoresearch-out-dir to
    # docs/self-improving/..., so any flag left at its default silently renders
    # fixture data into the worktree (the contamination this isolation fixes).
    if seedgen_out_dir is None:
        seedgen_out_dir = out_dir / "seed-generation"
    if autoresearch_out_dir is None:
        autoresearch_out_dir = out_dir / "autoresearch"
    cmd: list[str] = [
        sys.executable,
        str(BUILDER),
        "--out",
        str(out_dir / "index.html"),
        "--seedgen-out-dir",
        str(seedgen_out_dir),
        "--autoresearch-out-dir",
        str(autoresearch_out_dir),
    ]
    if bundle_root is not None:
        cmd.extend(["--bundle-root", str(bundle_root)])
    if autoresearch_root is not None:
        cmd.extend(["--autoresearch-root", str(autoresearch_root)])
    return subprocess.run(  # noqa: S603 — fixture-only invocation, no user input
        cmd, check=False, capture_output=True, text=True, cwd=str(REPO_ROOT)
    )


def _read_built(out_dir: Path) -> str:
    return (out_dir / "index.html").read_text(encoding="utf-8")


class _LinkCollector(HTMLParser):
    """Collect every ``href`` attribute in the rendered HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for k, v in attrs:
            if k == "href" and v is not None:
                self.hrefs.append(v)


def _collect_hrefs(html: str) -> list[str]:
    parser = _LinkCollector()
    parser.feed(html)
    return parser.hrefs


def _pyproject_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert m is not None, "pyproject.toml has no version field"
    return m.group(1)


# ---------------------------------------------------------------------------
# 1. Build invariants
# ---------------------------------------------------------------------------


def test_fixture_files_not_gitignored() -> None:
    """Every fixture file must be git-tracked. Otherwise CI clones the
    repo without it and the builder produces a different render than
    local — exactly the PR-G5b #1350 anti-pattern (Writer destination
    tracked rule in CLAUDE.md). The audit-row fixture under
    ``petri-bundle/logs/`` is the one we got bitten by; assert the
    whole tree to catch any sibling regression.
    """
    files = [
        p
        for p in FIXTURE_ROOT.rglob("*")
        if p.is_file()
        and not any(part.startswith(".") for part in p.relative_to(FIXTURE_ROOT).parts)
    ]
    assert files, f"no fixture files found under {FIXTURE_ROOT}"
    git_bin = shutil.which("git")
    assert git_bin is not None, "git executable not found on PATH"
    result = subprocess.run(  # noqa: S603 — fixture-only invocation, no user input
        [git_bin, "check-ignore", "--", *[str(p) for p in files]],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    # `git check-ignore` exits 0 when ANY path matches an ignore rule,
    # 1 when none match (the state we want), 128 on error.
    assert result.returncode == 1, (
        f"the following fixture files are gitignored — CI will not see them:\n{result.stdout}"
    )


def test_builder_runs_and_emits_output(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _run_builder(
        out,
        bundle_root=FIXTURE_ROOT / "petri-bundle",
        autoresearch_root=FIXTURE_ROOT / "autoresearch",
    )
    assert result.returncode == 0, (
        f"builder failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert (out / "index.html").is_file()
    html = _read_built(out)
    # Size sanity: too small means stub, too big means runaway template.
    assert 5_000 < len(html) < 100_000, f"output size out of range: {len(html)}"


def test_builder_is_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _run_builder(
        out,
        bundle_root=FIXTURE_ROOT / "petri-bundle",
        autoresearch_root=FIXTURE_ROOT / "autoresearch",
    )
    first = _read_built(out)
    _run_builder(
        out,
        bundle_root=FIXTURE_ROOT / "petri-bundle",
        autoresearch_root=FIXTURE_ROOT / "autoresearch",
    )
    second = _read_built(out)
    # Strip any timestamp-bearing date stamp (build_date) before comparing —
    # we don't want clock differences to fail this. The version-stamp date
    # comes from datetime.now() so it can vary between runs.
    date_re = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    assert date_re.sub("DATE", first) == date_re.sub("DATE", second), (
        "non-date content drifted between two builder runs"
    )


# ---------------------------------------------------------------------------
# 2. Sidebar contract
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built_html(tmp_path_factory: pytest.TempPathFactory) -> str:
    out = tmp_path_factory.mktemp("hub-out")
    _run_builder(
        out,
        bundle_root=FIXTURE_ROOT / "petri-bundle",
        autoresearch_root=FIXTURE_ROOT / "autoresearch",
    )
    return _read_built(out)


def test_sidebar_has_all_seven_sections(built_html: str) -> None:
    """Master DESIGN.md §7 specifies 7 sidebar sections."""
    required_labels = [
        "Hub",
        "Petri Audit",
        "Seed Generation",
        "Autoresearch",
        "Docs",
        "Meta",
    ]
    # Sidebar nav-section labels appear inside the sidebar nav block.
    for label in required_labels:
        assert label in built_html, f"sidebar section {label!r} missing"


def test_sidebar_has_github_link(built_html: str) -> None:
    """Operator directive 2026-05-26: GitHub link in Meta section."""
    assert "github.com/mangowhoiscloud/geode" in built_html, (
        "GitHub repo link missing from sidebar Meta section"
    )


def test_sidebar_has_aria_label(built_html: str) -> None:
    """Master DESIGN.md §12 accessibility minimum."""
    assert re.search(r"<nav[^>]+aria-label=", built_html), "<nav> sidebar missing aria-label"


def test_active_link_has_aria_current(built_html: str) -> None:
    """Master DESIGN.md §12: active link gets ``aria-current='page'``."""
    assert 'aria-current="page"' in built_html, "no aria-current='page' on active sidebar link"


# ---------------------------------------------------------------------------
# 3. Section contract
# ---------------------------------------------------------------------------


def test_four_main_sections_present(built_html: str) -> None:
    """Hub DESIGN.md §4: 4 main h2.section blocks."""
    sections = re.findall(r'<h2 class="section"[^>]*>.*?</h2>', built_html, flags=re.DOTALL)
    assert len(sections) >= 4, f"expected ≥4 h2.section elements, got {len(sections)}"
    section_text = " ".join(sections).lower()
    for keyword in ("petri", "seed", "autoresearch", "documentation"):
        assert keyword in section_text, f"section keyword {keyword!r} missing"


# ---------------------------------------------------------------------------
# 4. Harness chip mapping
# ---------------------------------------------------------------------------


def test_harness_chips_map_correctly(built_html: str) -> None:
    """Master DESIGN.md §3 + per-page DESIGN.md harness chip rules.
    Fixture uses 4 model prefixes; each must produce its chip class."""
    # claude-cli/* present in fixture audit + autoresearch
    assert "chip claude" in built_html and "claude-cli/claude-opus-4-7" in built_html
    # geode/* present
    assert "chip geode" in built_html and "geode/gpt-5.5" in built_html
    # anthropic/* and openai/* present in 2nd audit row → PAYG
    assert "chip payg" in built_html
    assert "anthropic/claude-sonnet-4-6" in built_html
    assert "openai/gpt-5.5" in built_html


# ---------------------------------------------------------------------------
# 5. URL safety
# ---------------------------------------------------------------------------


def test_every_href_is_basepath_safe(built_html: str) -> None:
    """Master DESIGN.md §8: every ``<a href>`` starts with ``/geode/``
    or is external (``https://``). No relative paths, no missing basePath."""
    hrefs = _collect_hrefs(built_html)
    assert hrefs, "no anchors found at all — template broken"
    for href in hrefs:
        if href.startswith("#"):
            continue  # in-page anchor allowed
        if href.startswith("https://") or href.startswith("http://"):
            continue
        if href.startswith("mailto:"):
            continue
        assert href.startswith("/geode/"), f"href {href!r} missing /geode/ basePath prefix"


def test_docs_petri_links_match_next_routes(built_html: str) -> None:
    """Every ``/geode/docs/petri/<slug>`` link in the hub must point at an
    existing Next.js route under ``site/src/app/docs/petri/<slug>/page.tsx``.
    Otherwise the live site returns 404 even though the local preview path
    looks valid. Caught after PR-SELF-IMPROVING-P5 shipped with stale slugs
    (``/petri`` → 404 instead of ``/petri/overview``; ``/petri/dimensions`` →
    404 instead of ``/petri/judge-dimensions``).
    """
    routes_root = REPO_ROOT / "site" / "src" / "app" / "docs" / "petri"
    assert routes_root.is_dir(), f"Next.js docs/petri/ routes dir missing at {routes_root}"
    valid_slugs = {
        p.name for p in routes_root.iterdir() if p.is_dir() and (p / "page.tsx").is_file()
    }
    bad: list[str] = []
    for href in _collect_hrefs(built_html):
        m = re.match(r"^/geode/docs/petri/([^/?#]+)/?$", href)
        if not m:
            continue
        slug = m.group(1)
        if slug not in valid_slugs:
            bad.append(href)
    assert not bad, (
        f"links point at non-existent Next.js routes: {bad}. "
        f"Valid slugs under site/src/app/docs/petri/: {sorted(valid_slugs)}"
    )


def test_audit_deeplinks_use_logs_route_and_resolve(built_html: str) -> None:
    """Audit/seed deep-links must target the Inspect View ``/logs/<file>``
    route and each linked filename must exist in the bundle's
    ``logs/listing.json`` so the link actually opens the transcript.

    Regression guard for PR-HUB-AUDIT-DEEPLINK (2026-05-30): the prior
    ``#/tasks/<task_id>`` form has no matching route in the bundle's hash
    router (``createHashRouter`` exposes only ``/logs/*``; the SPA navigates
    via ``/logs/${encodeURIComponent(file)}``), so every deep-link silently
    fell back to the run list instead of the specific log. Verified against
    the real bundle JS, not assumption — see the CANNOT rule in CLAUDE.md.
    """
    from urllib.parse import unquote

    # 1. The dead route must never reappear anywhere in the rendered hub.
    assert "#/tasks/" not in built_html, (
        "Inspect View has no /tasks/ route — use #/logs/<encodeURIComponent(eval_filename)>"
    )

    # 2. Every petri-bundle deep-link must resolve to a real listing entry.
    listing_path = FIXTURE_ROOT / "petri-bundle" / "logs" / "listing.json"
    valid_files = set(json.loads(listing_path.read_text(encoding="utf-8")))
    deeplinks = re.findall(r"/geode/self-improving/petri-bundle/#/logs/([^\"#]+)", built_html)
    assert deeplinks, "no petri audit /logs/ deep-links rendered — generator regressed"
    for enc in deeplinks:
        fname = unquote(enc)
        assert fname in valid_files, (
            f"audit deep-link targets {fname!r}, absent from logs/listing.json "
            f"(link would fall back to the run list)"
        )


# ---------------------------------------------------------------------------
# 6. Version stamp
# ---------------------------------------------------------------------------


def test_version_stamp_matches_pyproject(built_html: str) -> None:
    """Master DESIGN.md §15: build-time version stamp pulled from
    pyproject.toml — never a hand-written placeholder."""
    version = _pyproject_version()
    assert version in built_html, f"pyproject version {version!r} not in built HTML"
    # And no placeholder leakage.
    assert "{GEODE_VERSION}" not in built_html, "unresolved {GEODE_VERSION} placeholder in output"
    assert "{BUILD_DATE}" not in built_html, "unresolved {BUILD_DATE} placeholder"


# ---------------------------------------------------------------------------
# 7. Empty state
# ---------------------------------------------------------------------------


def test_missing_seed_listing_renders_empty_state(tmp_path: Path) -> None:
    """Hub DESIGN.md §7: seed-gen 0 rows produces empty state."""
    # Copy fixture but blank out seeds/listing.json
    fixture = tmp_path / "petri-bundle"
    shutil.copytree(FIXTURE_ROOT / "petri-bundle", fixture)
    (fixture / "seeds" / "listing.json").write_text(
        '{"kind": "seeds", "count": 0, "runs": []}', encoding="utf-8"
    )
    out = tmp_path / "out"
    result = _run_builder(
        out,
        bundle_root=fixture,
        autoresearch_root=FIXTURE_ROOT / "autoresearch",
    )
    assert result.returncode == 0, result.stderr
    html = _read_built(out)
    # Empty-state copy from DESIGN.md §7.
    empty_signals = ("No seed-generation runs", "no runs", "<em>")
    assert any(s in html for s in empty_signals), (
        "no empty-state marker rendered when listing has 0 runs"
    )


def test_missing_autoresearch_baseline_renders_warning(tmp_path: Path) -> None:
    """Hub DESIGN.md §7 + autoresearch DESIGN.md §7: baseline absent
    produces a documented warning / informational row."""
    out = tmp_path / "out"
    # Point autoresearch at a non-existent dir entirely.
    fake_ar = tmp_path / "no-autoresearch"
    fake_ar.mkdir()
    (fake_ar / "state").mkdir()  # empty state dir, no baseline.json
    result = _run_builder(
        out,
        bundle_root=FIXTURE_ROOT / "petri-bundle",
        autoresearch_root=fake_ar,
    )
    assert result.returncode == 0, result.stderr
    html = _read_built(out)
    # Should still render the page (graceful degradation), not error out.
    assert "Autoresearch" in html


# ---------------------------------------------------------------------------
# 8. Anti-patterns absent
# ---------------------------------------------------------------------------


# Emoji character ranges per Unicode. We allow ASCII arrows like ↗ ↓ →.
_EMOJI_RANGES = [
    (0x1F300, 0x1F6FF),  # symbols + pictographs
    (0x1F900, 0x1F9FF),  # supplementals + emoticons
    (0x2700, 0x27BF),  # dingbats (excluding common arrows)
]
_ALLOWED_DINGBATS = {"↗", "↘", "↑", "↓", "→", "←", "·", "—", "▾", "▸"}


def _find_emoji(text: str) -> list[str]:
    found: list[str] = []
    for ch in text:
        if ch in _ALLOWED_DINGBATS:
            continue
        codepoint = ord(ch)
        for low, high in _EMOJI_RANGES:
            if low <= codepoint <= high:
                found.append(ch)
                break
    return found


def test_no_emoji_in_rendered_html(built_html: str) -> None:
    """Master DESIGN.md §3 strict rule 4: no emoji."""
    found = _find_emoji(built_html)
    assert not found, f"emoji characters in output: {found!r}"


# ---------------------------------------------------------------------------
# 9. DESIGN.md frontmatter parity
# ---------------------------------------------------------------------------


def test_design_md_versioning_consistent() -> None:
    """Master DESIGN.md §15 versioning policy: every per-page DESIGN.md
    frontmatter ``geode_version`` matches the master."""
    master = (DESIGN_DIR / "self-improving-hub-system.md").read_text(encoding="utf-8")
    m = re.search(r"^geode_version:\s*([^\s]+)", master, flags=re.MULTILINE)
    assert m is not None, "master DESIGN.md missing geode_version frontmatter"
    master_version = m.group(1)
    siblings = list(DESIGN_DIR.glob("self-improving-*.md"))
    assert len(siblings) >= 10, f"expected ≥10 hub DESIGN.md docs, got {len(siblings)}"
    for sibling in siblings:
        text = sibling.read_text(encoding="utf-8")
        m2 = re.search(r"^geode_version:\s*([^\s]+)", text, flags=re.MULTILINE)
        assert m2 is not None, f"{sibling.name} missing geode_version frontmatter"
        assert m2.group(1) == master_version, (
            f"{sibling.name} geode_version={m2.group(1)} drifts from master {master_version}"
        )


# ---------------------------------------------------------------------------
# 10. CSS asset
# ---------------------------------------------------------------------------


def test_css_asset_referenced_and_present(built_html: str) -> None:
    """The built HTML must reference ``hub.css`` and the asset must
    exist at the documented path under ``docs/self-improving/``."""
    assert "hub.css" in built_html, "hub.css not referenced in built HTML"
    css = REPO_ROOT / "docs" / "self-improving" / "assets" / "hub.css"
    assert css.is_file(), f"hub.css missing at {css}"
    # CSS must define every chip class.
    css_text = css.read_text(encoding="utf-8")
    for chip in ("chip.payg", "chip.claude", "chip.codex", "chip.geode"):
        assert f".{chip}" in css_text, f"hub.css missing .{chip} rule"


# ---------------------------------------------------------------------------
# 11. Seed-generation surface (index + per-run detail)
# ---------------------------------------------------------------------------
#
# Phase 5 ships two new static pages built by the same script:
#   - docs/self-improving/seed-generation/index.html               (runs catalog)
#   - docs/self-improving/seed-generation/<run_id>/index.html      (per-run)
#
# Contracts:
#   docs/design/self-improving-seed-generation-index.md
#   docs/design/self-improving-seed-generation-run.md
# Master tokens shared with hub:
#   docs/design/self-improving-hub-system.md


SEEDGEN_FIXTURE_RUN_ID = "test-run-001"


@pytest.fixture(scope="module")
def built_seedgen_pages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Build the seed-generation index + per-run page once per session.

    Returns a dict ``{"index": html, "run": html, "run_dir": Path}`` so the
    tests below can share the same render.
    """
    out = tmp_path_factory.mktemp("seedgen-out")
    hub_out = out / "hub"
    seedgen_out = out / "seedgen"
    autoresearch_out = out / "autoresearch"
    result = subprocess.run(  # noqa: S603 — fixture invocation
        [
            sys.executable,
            str(BUILDER),
            "--out",
            str(hub_out / "index.html"),
            "--bundle-root",
            str(FIXTURE_ROOT / "petri-bundle"),
            "--autoresearch-root",
            str(FIXTURE_ROOT / "autoresearch"),
            "--seedgen-out-dir",
            str(seedgen_out),
            # Redirect autoresearch output to tmp too — without this flag the
            # builder renders into docs/self-improving/autoresearch/, dirtying
            # the worktree on every run.
            "--autoresearch-out-dir",
            str(autoresearch_out),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"seedgen builder failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    index_path = seedgen_out / "index.html"
    run_path = seedgen_out / SEEDGEN_FIXTURE_RUN_ID / "index.html"
    assert index_path.is_file(), f"seedgen index missing at {index_path}"
    assert run_path.is_file(), f"seedgen run page missing at {run_path}"
    pages: dict[str, str] = {
        "index": index_path.read_text(encoding="utf-8"),
        "run": run_path.read_text(encoding="utf-8"),
    }
    # PR-SEEDS-HIRES P2 (2026-05-26) — load every emitted hi-res sub-page
    # so tests below can assert on them directly (no separate build needed).
    run_root = seedgen_out / SEEDGEN_FIXTURE_RUN_ID
    for sub in ("agents", "timeline", "tournament"):
        sub_path = run_root / sub / "index.html"
        if sub_path.is_file():
            pages[f"{SEEDGEN_FIXTURE_RUN_ID}/{sub}"] = sub_path.read_text(encoding="utf-8")
    agent_root = run_root / "agent"
    if agent_root.is_dir():
        for task_dir in agent_root.iterdir():
            page = task_dir / "index.html"
            if page.is_file():
                pages[f"{SEEDGEN_FIXTURE_RUN_ID}/agent/{task_dir.name}"] = page.read_text(
                    encoding="utf-8"
                )
    return pages


def test_seedgen_index_renders(built_seedgen_pages: dict[str, str], built_html: str) -> None:
    """Seed-gen index has the runs table with at least 1 row + sidebar identical to hub."""
    index_html = built_seedgen_pages["index"]
    # Sidebar 7 sections shared with hub.
    for label in ("Hub", "Petri Audit", "Seed Generation", "Autoresearch", "Docs", "Meta"):
        assert label in index_html, f"seedgen index missing sidebar section {label!r}"
    assert "github.com/mangowhoiscloud/geode" in index_html, "GitHub link missing"
    # The seed-runs sidebar link goes to the docs site, so it is labeled as
    # such — not the misleading "Run dashboard" (2026-05-29).
    assert "Run dashboard" not in index_html, "stale 'Run dashboard' label should be relabeled"
    assert "Seed runs (docs)" in index_html, "relabeled seed-runs docs link missing"
    # Runs table — at least 1 row, fixture run id present.
    assert SEEDGEN_FIXTURE_RUN_ID in index_html, "fixture run row missing from index"
    # PR-HUB-LOOP-VIZ: the co-scientist loop is a static iteration-aware diagram
    # (prelude + iterating core + feed-back), not the old animated 8-box hero.
    assert 'class="seedgen-pipeline"' in index_html, "loop pipeline diagram missing"
    assert "Iteration loop" in index_html, "iteration-loop stage label missing"
    assert "feed back" in index_html, "evolved feed-back (the iterator) not shown"
    assert "seedgen-hero" not in index_html, "old animated hero must be gone (slop)"
    # Active link contract — All runs is active on this page.
    assert 'aria-current="page"' in index_html, "no aria-current on active link"
    # Sidebar tree (sections list) is byte-equal across hub + seedgen index.
    aside_re = re.compile(r"<aside[^>]*>.*?</aside>", flags=re.DOTALL)

    def _section_labels(html: str) -> list[str]:
        match = aside_re.search(html)
        assert match is not None
        return re.findall(
            r'<div class="nav-section">([A-Za-z][A-Za-z ]*)',
            match.group(0),
        )

    assert _section_labels(index_html) == _section_labels(built_html), (
        "sidebar section order differs between hub and seedgen index"
    )


def test_seedgen_run_page_renders(built_seedgen_pages: dict[str, str]) -> None:
    """Per-run page exists and has every required section per DESIGN.md §4."""
    run_html = built_seedgen_pages["run"]
    # 9 required sections — match by name fragment.
    required_sections = [
        "Candidates",
        "Survivors",
        "Evolved",
        "Phase .eval cards",
        "Reflections",
        "Pilot scores",
        "Meta-review",
        "Token rollup",
    ]
    # Section heads live in <h2 class="section"> OR (for the foldable heavy
    # sections — reflections / pilot) in a <details> <summary>. PR-HUB-DESLOP.
    head_blocks = re.findall(
        r"<h2 class=\"section\"[^>]*>.*?</h2>|<summary>.*?</summary>",
        run_html,
        flags=re.DOTALL,
    )
    heads_joined = " ".join(head_blocks)
    for section in required_sections:
        assert section in heads_joined, f"run page missing section head {section!r}"
    # Header banner + mutator banner present.
    assert "run-detail-header" in run_html, "run page missing run-detail-header banner"
    assert "mutator-banner" in run_html, "run page missing mutator-banner"
    # Run id appears in the page title.
    assert f'<h1 class="page-title">{SEEDGEN_FIXTURE_RUN_ID}' in run_html, (
        "run id missing from <h1>"
    )
    # PR-HUB-DESLOP: dense inline sub-view nav + in-page section map (no box cards).
    assert 'class="subview-nav"' in run_html, "run page missing dense sub-view nav"
    assert "subview-card" not in run_html, "box-card sub-view grid is slop"
    assert 'class="run-map"' in run_html, "run page missing in-page section map"
    # Candidate ids link to the generated-original viewer, not an in-page #cand anchor.
    assert f"/seed-generation/{SEEDGEN_FIXTURE_RUN_ID}/candidates/" in run_html, (
        "candidate ids must link to the /candidates/<cid>/ viewer"
    )
    assert 'href="#cand-' not in run_html, "candidate ids must not link to in-page #cand anchors"


def test_hub_css_has_no_slop_patterns() -> None:
    """Guard the two registered slop patterns (CLAUDE.md §Docs, PR-HUB-DESLOP):
    colored left-border accent bars (`border-left … var(--bucket-*)`) and
    box-card navigation (`.subview-card` / `.run-subviews`)."""
    css = (REPO_ROOT / "docs/self-improving/assets/hub.css").read_text(encoding="utf-8")
    colored_left = re.findall(r"border-left:[^;]*var\(--bucket", css)
    assert not colored_left, f"colored left-border accent bars are slop: {colored_left}"
    assert ".subview-card" not in css, "box-card sub-view nav (.subview-card) is slop"
    assert ".run-subviews" not in css, "box-card sub-view grid (.run-subviews) is slop"
    assert ".subview-nav" in css, "expected the dense inline .subview-nav replacement"


def test_seedgen_pilot_heatmap_renders(built_seedgen_pages: dict[str, str]) -> None:
    """Heatmap table renders 22 dim columns (plus the id column on the left)."""
    run_html = built_seedgen_pages["run"]
    match = re.search(
        r'<table class="records heatmap">(.*?)</table>',
        run_html,
        flags=re.DOTALL,
    )
    assert match is not None, "no heatmap table in run page"
    table_html = match.group(1)
    thead_match = re.search(r"<thead>(.*?)</thead>", table_html, flags=re.DOTALL)
    assert thead_match is not None, "heatmap has no <thead>"
    th_count = len(re.findall(r"<th[\s>]", thead_match.group(1)))
    # Per DESIGN.md §5.6: 22 dim columns. Plus one "id" left header == 23 total.
    assert th_count == 23, f"expected 23 <th> (22 dims + id), got {th_count}"
    # And at least one warm-bucket cell appears (fixture has score=6.0 + 8.0).
    assert "score-warn" in table_html, "no warm-bucket cell rendered despite >1 score"


def test_seedgen_phase_eval_links_point_at_spa(built_seedgen_pages: dict[str, str]) -> None:
    """Each phase .eval card links to the SEED-GENERATION bundle viewer.

    PR-SEEDGEN-BUNDLE-SPLIT (2026-05-29) — seedgen phase logs live in the
    seed-generation's own inspect bundle, so deep-links target
    ``/geode/self-improving/seed-generation/bundle/``.

    PR-HUB-AUDIT-DEEPLINK (2026-05-30) — the deep-link uses the Inspect View
    ``#/logs/<encodeURIComponent(filename)>`` route (the only log route the
    bundle's hash router exposes); the prior ``#/tasks/<task_id>`` form had no
    matching route and silently fell back to the run list. When a phase has no
    .eval yet, the link is the bundle run-list root (no dead hash).
    """
    run_html = built_seedgen_pages["run"]
    bundle_base = "/geode/self-improving/seed-generation/bundle/"
    # Pull the phase-link table cells.
    phase_links = re.findall(
        r'<td class="phase-link"><a href="([^"]+)"',
        run_html,
    )
    assert phase_links, "no phase .eval card links rendered"
    assert "#/tasks/" not in run_html, "Inspect View has no /tasks/ route — use #/logs/<file>"
    for link in phase_links:
        # Either a resolvable /logs/<file> deep-link or the bundle run-list root.
        ok = link == bundle_base or link.startswith(f"{bundle_base}#/logs/")
        assert ok, f"phase link {link!r} not pointing at the seed-generation bundle viewer"
    # No phase link may point at the audit petri-bundle (scope split).
    assert all("petri-bundle" not in link for link in phase_links), (
        "phase links must not target the audit petri-bundle after the split"
    )
    # 8 phases per DESIGN.md §6.
    assert len(phase_links) == 8, f"expected 8 phase links, got {len(phase_links)}"


def test_petri_bundle_excludes_seedgen_logs() -> None:
    """The audit petri-bundle must not carry seed-generation phase logs.

    PR-SEEDGEN-BUNDLE-SPLIT (2026-05-29) — seedgen phase .eval logs live in
    their own inspect bundle so the alignment-audit viewer stays scoped to
    audits. Pins the split against drift (an eval_export regression that
    repopulates the audit bundle, or a stale listing key).
    """
    pb_listing = REPO_ROOT / "docs/self-improving/petri-bundle/logs/listing.json"
    pb = json.loads(pb_listing.read_text(encoding="utf-8"))
    seedgen_in_audit = [k for k in pb if "seedgen" in k]
    assert not seedgen_in_audit, (
        f"audit petri-bundle still lists seedgen logs: {seedgen_in_audit[:3]}"
    )

    sg_listing = REPO_ROOT / "docs/self-improving/seed-generation/bundle/logs/listing.json"
    assert sg_listing.is_file(), "seed-generation bundle listing.json missing"
    sg = json.loads(sg_listing.read_text(encoding="utf-8"))
    assert any("seedgen" in k for k in sg), "seed-generation bundle has no seedgen logs"

    # The seed-generation bundle ships its own SPA shell reading co-located logs.
    idx = REPO_ROOT / "docs/self-improving/seed-generation/bundle/index.html"
    assert idx.is_file(), "seed-generation bundle index.html (SPA shell) missing"
    assert '"log_dir": "logs"' in idx.read_text(encoding="utf-8"), (
        "seed-generation bundle SPA must read its co-located ./logs"
    )


def test_seedgen_eval_samples_populate_viewer_tabs() -> None:
    """Seed-generation .eval samples follow the 3-axis tab contract — each
    datum lives in exactly ONE viewer tab, no triplication.

    PR-SEEDGEN-EVAL-ALIGN (2026-05-29). A seed-generation phase is a structured
    output, not a chat, so the synthetic MESSAGES + the TRANSCRIPT ``ModelEvent``
    were dropped (they duplicated the InfoEvent), and the output scalars no
    longer appear in BOTH the Score's metadata and the sample's metadata. The
    invariants on a committed critic .eval:
      - MESSAGES  empty (`sample.messages == []`).
      - TRANSCRIPT carries a single ``InfoEvent`` (`event == "info"`, no
        ``model`` event) whose ``data`` holds the full reflection.
      - SCORING   has a per-sample score WITH a non-empty ``explanation`` (no
        "(No Explanation)") and NO ``Score.metadata`` (scalars are in the Info
        record, not re-copied).
      - METADATA  is provenance only — never the output scalars
        (``judge_risk`` / ``discrimination_estimate`` / ``intended_dim_match``).

    .eval members are zstd-compressed (compress_type=93), which stdlib
    zipfile cannot decode on Python 3.12, so we read via inspect_ai (which
    handles it). Skips when the [audit] extra is absent — the CI audit job
    (`uv sync --extra audit`) runs it; the structural split invariant is
    pinned separately by ``test_petri_bundle_excludes_seedgen_logs``.
    """
    pytest.importorskip("inspect_ai.log")
    from inspect_ai.log import read_eval_log

    logs = REPO_ROOT / "docs/self-improving/seed-generation/bundle/logs"
    all_logs = sorted(logs.glob("*seedgen-*.eval"))
    assert all_logs, "no seedgen .eval in the seed-generation bundle"
    critic = [p for p in all_logs if "_seedgen-critic_" in p.name]
    assert critic, "no critic .eval in the seed-generation bundle"
    # Provenance is the ONLY thing allowed in per-sample metadata; any output
    # scalar (judge_risk, discrimination, status, survived, elo_rating, …)
    # leaking here means it is duplicated against the InfoEvent record.
    provenance_keys = {"iteration", "max_iterations", "task_id"}
    # Sweep EVERY phase's EVERY sample — not just the first critic — so a
    # regression in any one phase (pilot/ranker/meta/…) is caught, not masked.
    for log_path in all_logs:
        log_obj = read_eval_log(str(log_path))
        assert log_obj.samples, f"{log_path.name}: no samples"
        is_generator = "_seedgen-generator_" in log_path.name
        for sample in log_obj.samples:
            assert not sample.messages, (
                f"{log_path.name}: MESSAGES should be empty (a phase is a structured "
                "output, not a chat)"
            )
            event_types = {getattr(e, "event", None) for e in (sample.events or [])}
            assert "model" not in event_types, (
                f"{log_path.name}: TRANSCRIPT still has a ModelEvent (should be Info-only)"
            )
            if is_generator:
                # Seed .md body lives in EvalSample.output (read from the
                # published bundle copy, not the absent local state path).
                assert (sample.output.completion or "").strip(), (
                    f"{log_path.name}: generator OUTPUT empty — candidate .md body not "
                    "read from the bundle"
                )
            else:
                assert "info" in event_types, (
                    f"{log_path.name}: TRANSCRIPT missing the InfoEvent; got {event_types}"
                )
                info = next(e for e in sample.events if getattr(e, "event", None) == "info")
                assert info.data, f"{log_path.name}: InfoEvent.data empty"
            score = next(iter(sample.scores.values()))
            assert score.explanation, (
                f"{log_path.name}: SCORING shows '(No Explanation)' — explanation unset"
            )
            assert score.metadata is None, (
                f"{log_path.name}: Score.metadata duplicates the Info record / sample metadata"
            )
            leaked = set((sample.metadata or {}).keys()) - provenance_keys
            assert not leaked, (
                f"{log_path.name}: METADATA carries non-provenance keys {leaked} "
                "(output scalars belong only in the Info record)"
            )

    # Critic record completeness — the full reflection, not a trimmed subset.
    crit_sample = read_eval_log(str(critic[0])).samples[0]
    crit_info = next(e for e in crit_sample.events if getattr(e, "event", None) == "info")
    assert {"strengths", "weaknesses", "rewrite_section"} <= set(crit_info.data.keys()), (
        f"{critic[0].name}: InfoEvent.data missing the full reflection record"
    )


def test_seedgen_url_basepath_safety(built_seedgen_pages: dict[str, str]) -> None:
    """Every ``<a href>`` on both seedgen pages is /geode/-prefixed or external."""
    for label in ("index", "run"):
        hrefs = _collect_hrefs(built_seedgen_pages[label])
        assert hrefs, f"no anchors found on seedgen {label} page"
        for href in hrefs:
            if href.startswith("#"):
                continue
            if href.startswith("https://") or href.startswith("http://"):
                continue
            if href.startswith("mailto:"):
                continue
            assert href.startswith("/geode/"), (
                f"seedgen {label} href {href!r} missing /geode/ basePath"
            )


def test_seedgen_coverage_bars_render(built_seedgen_pages: dict[str, str]) -> None:
    """Meta-review coverage section renders ``.coverage-bar`` elements."""
    run_html = built_seedgen_pages["run"]
    assert "coverage-list" in run_html, "coverage-list missing"
    assert "coverage-bar" in run_html, "coverage-bar missing"
    assert "coverage-bar-fill" in run_html, "coverage-bar-fill missing"
    # CSS rule must define the chart container.
    css = (REPO_ROOT / "docs" / "self-improving" / "assets" / "hub.css").read_text(encoding="utf-8")
    assert ".coverage-bar" in css, "hub.css missing .coverage-bar rule"
    assert ".coverage-bar-fill" in css, "hub.css missing .coverage-bar-fill rule"


# ---------------------------------------------------------------------------
# 12. Autoresearch surface (5 sub-pages)
# ---------------------------------------------------------------------------
#
# Phase 6 ships the 5-page autoresearch surface built by the same script:
#   - docs/self-improving/autoresearch/index.html       (landing)
#   - docs/self-improving/autoresearch/baseline/    (7 namespace blocks)
#   - docs/self-improving/autoresearch/mutations/   (ledger table)
#   - docs/self-improving/autoresearch/results/     (12-col table + sparkline)
#   - docs/self-improving/autoresearch/policies/    (14-file table)
#
# Contracts:
#   docs/design/self-improving-autoresearch.md (+ -baseline / -mutations
#   / -results / -policies sibling docs)
# Master tokens shared with hub:
#   docs/design/self-improving-hub-system.md


@pytest.fixture(scope="module")
def built_autoresearch_pages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Build the 5 autoresearch pages once per session against fixture data.

    Returns a dict keyed by page name (``index`` / ``baseline`` /
    ``mutations`` / ``results`` / ``policies``) -> rendered HTML text.
    """
    out = tmp_path_factory.mktemp("autoresearch-out")
    hub_out = out / "hub"
    seedgen_out = out / "seedgen"
    autoresearch_out = out / "autoresearch"
    result = subprocess.run(  # noqa: S603 — fixture invocation
        [
            sys.executable,
            str(BUILDER),
            "--out",
            str(hub_out / "index.html"),
            "--bundle-root",
            str(FIXTURE_ROOT / "petri-bundle"),
            "--autoresearch-root",
            str(FIXTURE_ROOT / "autoresearch"),
            "--seedgen-out-dir",
            str(seedgen_out),
            "--autoresearch-out-dir",
            str(autoresearch_out),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"autoresearch builder failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    pages: dict[str, str] = {}
    for name in ("index", "baseline", "mutations", "results", "policies"):
        # `index` is the landing page; the rest are dir/index.html for trailing-slash URLs.
        path = (
            autoresearch_out / "index.html"
            if name == "index"
            else autoresearch_out / name / "index.html"
        )
        assert path.is_file(), f"autoresearch {name} page missing at {path}"
        pages[name] = path.read_text(encoding="utf-8")
    return pages


def test_autoresearch_landing_renders(built_autoresearch_pages: dict[str, str]) -> None:
    """Landing page has status block, generation timeline (3 rows from
    fixture archive), and the 4-row sub-view table."""
    html = built_autoresearch_pages["index"]
    # Status grid section header + grid rows.
    assert "Status" in html and "status-grid" in html, "status block missing"
    # Generation timeline section with all 3 fixture archive rows.
    assert "Generation timeline" in html, "timeline section header missing"
    for gen in ("gen-1", "gen-2", "gen-3"):
        assert gen in html, f"timeline row for {gen!r} missing"
    # The 4 sub-view rows must all be present with their absolute paths.
    for label, href in (
        ("Baseline", "/geode/self-improving/autoresearch/baseline/"),
        ("Mutations", "/geode/self-improving/autoresearch/mutations/"),
        ("Results", "/geode/self-improving/autoresearch/results/"),
        ("Policies", "/geode/self-improving/autoresearch/policies/"),
    ):
        assert label in html, f"sub-view row {label!r} missing"
        assert href in html, f"sub-view link {href!r} missing"
    # PR-BASELINE-EPOCH: the content-addressed baseline-registry section is present
    # (its token resolved — an unresolved {{ }} marker would fail the builder).
    assert "Baseline registry" in html, "baseline registry section header missing"


def _load_builder_module() -> Any:
    """Import the stdlib-only hub builder as a module (mirrors
    test_policy_file_map_matches_core)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_hub_builder_epoch", BUILDER)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = builder
    spec.loader.exec_module(builder)
    return builder


def _epoch_row(*, eid: str, ts: str, epoch_hash: str, epoch_label: str, margin: str) -> dict:
    return {
        "kind": "baseline",
        "id": eid,
        "ts_utc": ts,
        "fitness": 0.73,
        "fitness_stderr": 0.013,
        "promoted_by": "gate",
        "epoch_hash": epoch_hash,
        "epoch_label": epoch_label,
        "baseline_spec": {
            "margin_rule": margin,
            "dim_set": "subset",
            "rubric_version": "v3-22dim-PR0",
            "bench": False,
            "seed_pool_id": "sel-aaaa",
        },
        "role_provenance": {
            "auditor": {"model": "opus-4-8", "source": "api_key", "lane": "PAYG"},
            "target": {"model": "gpt-5.5", "source": "openai-codex", "lane": "Subscription"},
            "judge": {"model": "opus-4-8", "source": "claude-cli", "lane": "CLI"},
            "mutator": {"model": "gpt-5.5", "source": "openai-codex", "lane": "Subscription"},
        },
    }


def test_baseline_registry_index_groups_distinct_epochs() -> None:
    """Two margin_rule epochs render as two SEPARATE blocks (never merged), and
    the legacy gen-* timeline (different schema) is unaffected."""
    builder = _load_builder_module()
    vanilla = _epoch_row(
        eid="baseline-2605-1",
        ts="2026-05-29T09:18:30Z",
        epoch_hash="36c4727cf762",
        epoch_label="be-001",
        margin="dim-stderr",
    )
    fixed = _epoch_row(
        eid="baseline-2606-1",
        ts="2026-05-30T10:00:00Z",
        epoch_hash="33d454c3523e",
        epoch_label="be-002",
        margin="fitness-stderr",
    )
    html = builder._render_baseline_registry_index([vanilla, fixed])
    # two distinct epoch blocks, not one comparison table
    assert html.count('class="namespace-block"') == 2
    assert "be-001" in html and "be-002" in html
    # newest epoch first
    assert html.index("be-002") < html.index("be-001")
    # both margin rules surfaced as the epoch discriminator
    assert "dim-stderr" in html and "fitness-stderr" in html
    # credential-lane observability present per role
    assert "Subscription" in html and "CLI" in html and "PAYG" in html
    # no slop (accent bars / card grids)
    assert "border-left" not in html and "card-grid" not in html


def test_baseline_registry_index_empty_state() -> None:
    builder = _load_builder_module()
    # legacy gen-* rows (no kind="baseline") → empty state, not a crash
    legacy = [{"gen_tag": "gen-1", "ts_utc": "2026-05-01T00:00:00Z", "fitness": 0.5}]
    html = builder._render_baseline_registry_index(legacy)
    assert "No <code>" in html and "namespace-block" not in html


def test_baseline_registry_index_pre_epoch_row_honest() -> None:
    """A committed kind="baseline" row WITHOUT epoch fields (pre-schema) renders
    in an honest 'pre-epoch (backfill pending)' bucket — never a fabricated hash —
    and that bucket sorts AFTER real epochs even when its ts is newer."""
    builder = _load_builder_module()
    pre = {
        "kind": "baseline",
        "id": "baseline-2605-1",
        "ts_utc": "2026-06-30T00:00:00Z",  # deliberately newest
        "fitness": 0.7915,
        "fitness_stderr": None,
        "promoted_by": "backfill",
    }  # no epoch_hash / epoch_label / baseline_spec
    real = _epoch_row(
        eid="baseline-2606-1",
        ts="2026-05-30T10:00:00Z",
        epoch_hash="33d454c3523e",
        epoch_label="be-002",
        margin="fitness-stderr",
    )
    html = builder._render_baseline_registry_index([pre, real])
    assert "pre-epoch (backfill pending)" in html
    assert "Predates the content-addressed epoch schema" in html
    # real epoch (be-002) renders BEFORE the pre-epoch bucket despite older ts
    assert html.index("be-002") < html.index("pre-epoch (backfill pending)")
    # no fabricated hash for the pre-epoch bucket
    assert '<code class="muted">pre-epoch</code>' not in html


def test_autoresearch_baseline_renders(built_autoresearch_pages: dict[str, str]) -> None:
    """Baseline page renders the 7 v2-schema namespace blocks plus the 3
    "show its work" sections (process / seed corpus / audit transcripts),
    and harness chips on the audit namespace's 3 model fields.

    PR-BASELINE-HUB-SHOW-WORK (2026-05-29): the page gained process / seeds /
    transcripts sections (each a `namespace-block` container), so the total
    block count is now 7 baseline namespaces + 3 sections = 10. The 3 sections
    render their empty-state block when no `transcripts.json` is present (the
    fixture case), so the count holds regardless of transcript data.
    """
    html = built_autoresearch_pages["baseline"]
    # 7 baseline.json namespace block ids (no warning banner for live baseline).
    expected_blocks = ("metadata", "raw", "normalized", "axes", "fitness", "audit", "promotion")
    for ns in expected_blocks:
        assert f'id="ns-{ns}"' in html, f"baseline namespace block {ns!r} missing"
    # 3 "show its work" section block ids.
    for section in ("process", "seeds", "transcripts"):
        assert f'id="ns-{section}"' in html, f"baseline section {section!r} missing"
    # Total `namespace-block` divs = 7 namespaces + 3 sections.
    assert html.count('class="namespace-block"') == 10, (
        f"expected 10 namespace blocks (7 namespaces + 3 sections), "
        f"got {html.count('class="namespace-block"')}"
    )
    # Audit namespace renders harness chips for 3 model roles.
    assert "chip claude" in html, "auditor/judge claude chip missing"
    assert "chip geode" in html, "target geode chip missing"
    assert "claude-cli/claude-opus-4-7" in html
    assert "geode/gpt-5.5" in html


def test_autoresearch_baseline_stale_warning(tmp_path: Path) -> None:
    """When live baseline.json is absent but `.outdated-*` exists, the
    `.warning-banner` div renders on baseline + landing pages."""
    # Build a fixture variant: only an outdated baseline file.
    fake_ar = tmp_path / "fake-autoresearch"
    state = fake_ar / "state"
    state.mkdir(parents=True)
    (state / "baseline.json.outdated-20260520").write_text(
        '{"schema_version": 2, "metadata": {"gen_tag": "gen-old"}, '
        '"fitness": {"value": 0.5}, "audit": {}, "promotion": {}}',
        encoding="utf-8",
    )
    out = tmp_path / "out"
    autoresearch_out = out / "autoresearch"
    result = subprocess.run(  # noqa: S603 — fixture invocation
        [
            sys.executable,
            str(BUILDER),
            "--out",
            str(out / "index.html"),
            "--bundle-root",
            str(FIXTURE_ROOT / "petri-bundle"),
            "--autoresearch-root",
            str(fake_ar),
            "--seedgen-out-dir",
            str(out / "seedgen"),
            "--autoresearch-out-dir",
            str(autoresearch_out),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    baseline_html = (autoresearch_out / "baseline" / "index.html").read_text(encoding="utf-8")
    assert "warning-banner" in baseline_html, "warning banner missing on stale baseline page"
    assert "outdated-20260520" in baseline_html, "stale source filename missing from banner"
    # CSS rule must exist.
    css = (REPO_ROOT / "docs" / "self-improving" / "assets" / "hub.css").read_text(encoding="utf-8")
    assert ".warning-banner" in css, "hub.css missing .warning-banner rule"


def test_autoresearch_mutations_table_renders(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """Mutations page joins apply+attribution records into one row each, with a
    summary block, real columns, outcome chips, and a payload drill-down.

    Regression for the 2026-05-29 schema drift: the renderer keyed off a
    nested ``ts_utc``/``mutation``/``verdict`` schema the runner no longer
    emits, so every column rendered empty against production data. The
    fixture now uses the live flat schema (apply rows + attribution rows).
    """
    html = built_autoresearch_pages["mutations"]
    # Non-functional filter mockup removed.
    assert 'class="filter-strip"' not in html, "non-functional filter-strip should be removed"
    # Summary block (replaces the filter) with real aggregates.
    assert "status-grid" in html, "mutations summary status-grid missing"
    assert "improved" in html and "regressed" in html and "pending audit" in html, (
        "summary outcome breakdown missing"
    )
    # Real flat-schema fields surface (apply record).
    assert "tool_result_handling" in html, "apply target_section missing"
    assert "dispatch" in html, "apply target_section (regress row) missing"
    assert "redundant_tool_invocation" in html, "aimed dim missing"
    # Δfitness colours from the joined attribution records.
    assert "delta-positive" in html, "delta-positive (improved) missing"
    assert "delta-negative" in html, "delta-negative (regressed) missing"
    # Outcome labels for each branch.
    for outcome in ("improved", "regressed", "noise", "pending"):
        assert outcome in html, f"outcome label {outcome!r} missing"
    # before -> after change surfaces in the payload drill-down.
    assert "<details>" in html and "previous" in html, "payload drill-down (before/after) missing"


def test_autoresearch_held_out_curve_renders(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """E2: the per-cycle held-out (fixed-ruler) fitness curve renders as a dense
    table on the mutations page, reading ``held_out_fitness`` from the attribution
    rows, ordered chronologically with a Δ-vs-prior column and the bench id."""
    html = built_autoresearch_pages["mutations"]
    assert "Held-out fitness curve" in html, "held-out curve section heading missing"
    # The fixture has 3 attribution rows with held_out_fitness → 3 generations.
    assert "3 generations" in html, "held-out curve generation count wrong"
    # The recorded fixed-ruler values surface (rounded to 4 dp in the table).
    assert "0.6120" in html and "0.5980" in html and "0.6340" in html, (
        "held-out fitness values missing from the curve"
    )
    # Δ-vs-prior direction: gen2 regressed (negative), gen3 improved (positive).
    assert "delta-negative" in html and "delta-positive" in html, (
        "held-out curve Δ-vs-prior direction classes missing"
    )
    # The content-addressed bench id (the fixed ruler's fingerprint) is shown.
    assert "pool-c16d186178e1" in html, "held-out bench id missing"
    # NO-SLOP: the curve uses a dense <table class="records">, never a card grid /
    # accent bar / emoji (CLAUDE.md §Docs, feedback_no_box_ui_no_emoji).
    assert "border-left" not in html and "card-grid" not in html, (
        "held-out curve must not introduce accent-bar / card-grid slop"
    )
    assert not _find_emoji(html), "held-out curve must not introduce emoji"


def test_autoresearch_held_out_curve_omitted_without_bench(tmp_path: Path) -> None:
    """E2: with NO held-out fields in any attribution row (no bench configured),
    the curve section is omitted entirely — no empty scaffolding."""
    import json as _json

    # Copy the fixture, then strip the held_out_* fields from every row.
    fixture_copy = tmp_path / "fixture"
    shutil.copytree(FIXTURE_ROOT, fixture_copy)
    mutations_path = fixture_copy / "autoresearch" / "state" / "mutations.jsonl"
    stripped_lines: list[str] = []
    for line in mutations_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = _json.loads(line)
        row.pop("held_out_fitness", None)
        row.pop("held_out_bench_id", None)
        stripped_lines.append(_json.dumps(row))
    mutations_path.write_text("\n".join(stripped_lines) + "\n", encoding="utf-8")

    out = tmp_path / "out"
    result = subprocess.run(  # noqa: S603 — test invocation
        [
            sys.executable,
            str(BUILDER),
            "--out",
            str(out / "hub" / "index.html"),
            "--bundle-root",
            str(fixture_copy / "petri-bundle"),
            "--autoresearch-root",
            str(fixture_copy / "autoresearch"),
            "--seedgen-out-dir",
            str(out / "seedgen"),
            "--autoresearch-out-dir",
            str(out / "autoresearch"),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"builder failed: {result.stderr!r}"
    mutations_html = (out / "autoresearch" / "mutations" / "index.html").read_text(encoding="utf-8")
    assert "Held-out fitness curve" not in mutations_html, (
        "held-out curve section must be omitted when no row carries held_out_fitness"
    )
    # The unresolved-marker guard must not leave a literal {{ held_out_curve }}.
    assert "held_out_curve" not in mutations_html


def test_held_out_curve_unit_orders_and_signs_deltas() -> None:
    """Direct unit test of the curve renderer: rows are ordered by ts (not file
    order), the first generation has no Δ, and a regress vs an improvement on the
    FIXED ruler get the correct signed delta classes."""
    from scripts.build_self_improving_hub import _render_held_out_curve

    # Deliberately out of ts order in the list — the renderer must sort by ts.
    rows = [
        {
            "kind": "attribution",
            "ts": 30.0,
            "held_out_fitness": 0.70,
            "held_out_bench_id": "pool-x",
        },
        {
            "kind": "attribution",
            "ts": 10.0,
            "held_out_fitness": 0.60,
            "held_out_bench_id": "pool-x",
        },
        {
            "kind": "attribution",
            "ts": 20.0,
            "held_out_fitness": 0.55,
            "held_out_bench_id": "pool-x",
        },
        # An apply row + a no-bench attribution row are ignored.
        {"kind": "applied", "ts": 25.0, "target_section": "x"},
        {"kind": "attribution", "ts": 40.0},
    ]
    html = _render_held_out_curve(rows)
    # 3 generations (only the 3 attribution rows with held_out_fitness).
    assert "3 generations" in html
    # Chronological: 0.60 (gen1, no delta) → 0.55 (gen2, -0.0500) → 0.70 (gen3, +0.1500).
    assert html.index("0.6000") < html.index("0.5500") < html.index("0.7000")
    assert "-0.0500" in html and "delta-negative" in html
    assert "+0.1500" in html and "delta-positive" in html
    # Single ruler → "fixed ruler <code>pool-x</code>".
    assert "fixed ruler" in html and "pool-x" in html


def test_held_out_curve_unit_flags_changed_ruler() -> None:
    """If the frozen bench id changes mid-run (a 'frozen' set was edited), the
    curve note flags that the values are NOT fully comparable."""
    from scripts.build_self_improving_hub import _render_held_out_curve

    rows = [
        {"kind": "attribution", "ts": 10.0, "held_out_fitness": 0.6, "held_out_bench_id": "pool-a"},
        {"kind": "attribution", "ts": 20.0, "held_out_fitness": 0.6, "held_out_bench_id": "pool-b"},
    ]
    html = _render_held_out_curve(rows)
    assert "rulers changed" in html and "NOT fully comparable" in html


def test_held_out_curve_unit_graceful_skips_bad_values() -> None:
    """Graceful contract: a non-numeric held_out_fitness AND a non-numeric ts are
    BOTH skipped (neither can place a positionable curve point) rather than
    raising — the render never sinks on a malformed row, and an unpositionable
    point never mis-orders the order-dependent Δ column."""
    from scripts.build_self_improving_hub import _render_held_out_curve

    rows = [
        # bad fitness → skipped (cannot place a value)
        {"kind": "attribution", "ts": 10.0, "held_out_fitness": "oops", "held_out_bench_id": "p"},
        # bad ts → skipped (cannot position on the generation axis)
        {
            "kind": "attribution",
            "ts": "bad",
            "held_out_fitness": 0.5,
            "held_out_bench_id": "pool-x",
        },
        # the only well-formed row places the single point
        {"kind": "attribution", "ts": 20.0, "held_out_fitness": 0.7, "held_out_bench_id": "pool-x"},
    ]
    html = _render_held_out_curve(rows)
    assert "1 generation" in html
    assert "0.7000" in html
    # The bad-ts row's fitness (0.5) must NOT appear — it was skipped, not floated.
    assert "0.5000" not in html


def test_autoresearch_results_sparkline(built_autoresearch_pages: dict[str, str]) -> None:
    """Results page renders the Unicode block-char fitness sparkline +
    a 12-col table header sourced from RESULTS_TSV_HEADER."""
    html = built_autoresearch_pages["results"]
    assert 'class="fitness-sparkline"' in html, "fitness-sparkline span missing"
    # At least one of the 8 block chars present (▁▂▃▄▅▆▇█).
    block_chars = "▁▂▃▄▅▆▇█"
    assert any(c in html for c in block_chars), (
        "no Unicode block char rendered inside fitness-sparkline"
    )
    # All 12 header columns from RESULTS_TSV_HEADER.
    expected_cols = (
        "session_id",
        "gen_tag",
        "commit",
        "fitness",
        "critical_min",
        "critical_mean",
        "auxiliary_mean",
        "stability_score",
        "info_mean",
        "dim_count_engaged",
        "verdict",
        "description",
    )
    th_count = html.count('<th scope="col">')
    assert th_count >= 12, f"expected ≥12 <th scope='col'>, got {th_count}"
    for col in expected_cols:
        assert col in html, f"results table missing column {col!r}"
    # CSS rule must exist.
    css = (REPO_ROOT / "docs" / "self-improving" / "assets" / "hub.css").read_text(encoding="utf-8")
    assert ".fitness-sparkline" in css, "hub.css missing .fitness-sparkline rule"


def test_autoresearch_policies_lists_14_files(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """Policies page has at least 1 row per fixture file (4 fixtures
    used here; production would ship 14). Each row has JSON pretty-
    print drill-down via .policy-json + <details>."""
    html = built_autoresearch_pages["policies"]
    fixture_files = (
        "wrapper-sections.json",
        "tool-policy.json",
        "decomposition.json",
        "retrieval.json",
    )
    for filename in fixture_files:
        assert filename in html, f"policies row missing for {filename!r}"
    # Drill-down: <details>/<pre> + .policy-json class on each row.
    assert "<details>" in html, "policy drill-down <details> missing"
    assert 'class="policy-json"' in html, ".policy-json class missing on drill-down"
    # CSS rule must exist.
    css = (REPO_ROOT / "docs" / "self-improving" / "assets" / "hub.css").read_text(encoding="utf-8")
    assert ".policy-json" in css, "hub.css missing .policy-json rule"
    # Row count == fixture file count (the test never ships 14 fixture
    # files; that scale is verified in production builds).
    tbody_match = re.search(r"<tbody>(.*?)</tbody>", html, flags=re.DOTALL)
    assert tbody_match is not None, "policies <tbody> missing"
    row_count = tbody_match.group(1).count("<tr>")
    assert row_count == len(fixture_files), (
        f"expected {len(fixture_files)} policy rows, got {row_count}"
    )


def test_policies_mutated_by_cross_ref_uses_flat_schema(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """The 'mutated by' column links the latest mutation per policy file via the
    flat target_kind -> filename map (not the stale nested ts_utc/mutation schema).

    Fixture mutations target prompt (-> wrapper-sections.json),
    tool_policy (-> tool-policy.json) and decomposition (-> decomposition.json),
    so those rows show the section + outcome rather than an em-dash. Regression
    guard for the schema drift that also broke this cross-ref (Codex MCP catch).
    """
    html = built_autoresearch_pages["policies"]
    # The latest prompt mutation's section surfaces on the wrapper-sections row.
    assert "verbosity_control" in html, "prompt mutation cross-ref missing on policies page"
    # The regressed tool_policy mutation surfaces its dispatch section + outcome.
    assert "regressed" in html, "tool_policy mutation outcome cross-ref missing"


def test_policy_file_map_matches_core() -> None:
    """Drift guard for the dual SoT: the builder's stdlib-only
    ``_TARGET_KIND_TO_POLICY_FILE`` must match core's authoritative
    ``_KIND_TO_PATH`` filenames. If the runner adds/renames a target_kind,
    this fails until the builder map is synced.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_hub_builder", BUILDER)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass decorators in the module resolve
    # their __module__ via sys.modules (else dataclasses._is_type crashes).
    sys.modules[spec.name] = builder
    spec.loader.exec_module(builder)

    from core.self_improving_loop.policies import _KIND_TO_PATH

    core_map = {kind: path.name for kind, path in _KIND_TO_PATH.items()}
    builder_map = builder._TARGET_KIND_TO_POLICY_FILE
    assert core_map == builder_map, (
        "builder _TARGET_KIND_TO_POLICY_FILE drifted from core _KIND_TO_PATH; "
        f"builder={builder_map} core={core_map}"
    )


def test_autoresearch_pages_url_basepath_safety(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """Master DESIGN.md §8: every ``<a href>`` on each of the 5 pages
    is either ``/geode/``-prefixed or external (``https://``)."""
    for name, html in built_autoresearch_pages.items():
        hrefs = _collect_hrefs(html)
        assert hrefs, f"autoresearch {name} page has no anchors at all"
        for href in hrefs:
            if href.startswith("#"):
                continue
            if href.startswith("https://") or href.startswith("http://"):
                continue
            if href.startswith("mailto:"):
                continue
            assert href.startswith("/geode/"), (
                f"autoresearch {name} href {href!r} missing /geode/ basePath"
            )


def test_autoresearch_sidebar_consistent(
    built_autoresearch_pages: dict[str, str],
    built_html: str,
) -> None:
    """All 5 autoresearch pages share the same sidebar section order as
    the hub landing (modulo the .active highlight)."""
    aside_re = re.compile(r"<aside[^>]*>.*?</aside>", flags=re.DOTALL)

    def _section_labels(html: str) -> list[str]:
        match = aside_re.search(html)
        assert match is not None, "no <aside> in page"
        return re.findall(
            r'<div class="nav-section">([A-Za-z][A-Za-z ]*)',
            match.group(0),
        )

    hub_sections = _section_labels(built_html)
    assert hub_sections, "hub sidebar has no nav-section labels"
    for name, html in built_autoresearch_pages.items():
        page_sections = _section_labels(html)
        assert page_sections == hub_sections, (
            f"autoresearch {name} sidebar sections {page_sections} differ from hub {hub_sections}"
        )
        # Each page must have its own active link.
        assert 'aria-current="page"' in html, f"autoresearch {name} has no aria-current='page'"


# ---------------------------------------------------------------------------
# 11. PR-SEEDS-HIRES (2026-05-26) — high-resolution data surface
# ---------------------------------------------------------------------------


_HIRES_FIXTURE = FIXTURE_ROOT / "petri-bundle" / "seeds" / "test-run-001"


def test_pr1_bundle_includes_transcript_progress_tournament_costs() -> None:
    """PR-SEEDS-HIRES bundle: 4 new top-level files alongside state.json."""
    for name in ("transcript.jsonl", "progress.json", "tournament.json", "per_phase_costs.json"):
        assert (_HIRES_FIXTURE / name).is_file(), (
            f"PR-SEEDS-HIRES expected {name} under {_HIRES_FIXTURE}"
        )


def test_pr1_subagent_triple_tracked() -> None:
    """Every ``sub_agents/<task_id>/`` dir carries the dialogue + result + session triple."""
    sub_agents_root = _HIRES_FIXTURE / "sub_agents"
    assert sub_agents_root.is_dir(), "sub_agents/ dir missing from fixture"
    task_dirs = [p for p in sub_agents_root.iterdir() if p.is_dir()]
    assert task_dirs, "sub_agents/ has no task subdirs"
    for td in task_dirs:
        for fname in ("dialogue.jsonl", "result.json", "session.json"):
            assert (td / fname).is_file(), f"sub_agents/{td.name}/{fname} missing"


def test_pr1_checkpoints_tracked() -> None:
    """At least one ``checkpoints/<phase>.json`` snapshot per fixture run."""
    cp = _HIRES_FIXTURE / "checkpoints"
    assert cp.is_dir(), "checkpoints/ dir missing"
    json_files = list(cp.glob("*.json"))
    assert json_files, "checkpoints/ has no *.json snapshots"


def test_pr2_agents_index_renders(built_seedgen_pages: dict[str, str]) -> None:
    """`/agents/` lists each sub-agent with harness chip + cost + duration.

    Regression for the cli-local PAYG-misclassification (2026-05-29): a
    sub-agent that ran via the Claude Code CLI records the bare model provider
    (``anthropic``) in session_start + a ``claude_cli_session_id`` in
    session.json (the gen-c-001 fixture now mirrors that real shape). Keying
    the chip off the provider mislabels it PAYG; ``_resolve_subagent_model``
    overrides the source to ``claude-cli`` so it renders Claude Code with
    source-aligned naming.
    """
    html = built_seedgen_pages.get(f"{SEEDGEN_FIXTURE_RUN_ID}/agents")
    assert html, "agents index sub-page missing"
    assert 'class="records seedgen-agents"' in html
    assert "gen-c-001" in html
    # gen-c-001 ran via claude-cli (cli-local) despite provider=anthropic →
    # Claude Code chip + source-aligned model name, NOT PAYG.
    assert 'class="chip claude"' in html or "Claude Code" in html
    assert "claude-cli/claude-opus-4-7" in html, "expected source-aligned cli-local model name"
    # The codex voter (provider openai-codex) keeps its Codex chip.
    assert 'class="chip codex"' in html or "Codex" in html, "codex voter chip missing"


def test_pr2_agent_detail_paginates_via_details(built_seedgen_pages: dict[str, str]) -> None:
    """`/agent/<task_id>/` renders turn-by-turn `<details>` blocks + session_end summary."""
    html = built_seedgen_pages.get(f"{SEEDGEN_FIXTURE_RUN_ID}/agent/gen-c-001")
    assert html, "gen-c-001 agent detail page missing"
    assert html.count("<details") >= 3, (
        f"expected ≥3 <details> blocks in agent detail; got {html.count('<details')}"
    )
    assert "session_end" in html
    # Cost (USD, $0 on subscription) was replaced by token counts (2026-05-29).
    assert "tokens" in html, "token label missing"
    assert "USD" not in html and "cost (USD)" not in html, "stale USD cost label remains"
    # Anchor back to /agents/ index for navigation.
    assert f"/seed-generation/{SEEDGEN_FIXTURE_RUN_ID}/agents/" in html


def test_pr2_timeline_shows_all_known_phases(built_seedgen_pages: dict[str, str]) -> None:
    """`/timeline/` lists every phase present in transcript.jsonl + per_phase_costs.json."""
    html = built_seedgen_pages.get(f"{SEEDGEN_FIXTURE_RUN_ID}/timeline")
    assert html, "timeline sub-page missing"
    for phase in (
        "supervisor",
        "literature_review",
        "generator",
        "proximity",
        "critic",
        "pilot",
        "ranker",
        "evolver",
        "meta_reviewer",
    ):
        assert phase in html, f"timeline missing phase {phase!r}"


def test_pr2_tournament_renders_three_voter_panel(built_seedgen_pages: dict[str, str]) -> None:
    """`/tournament/` renders match sections + per-voter details + Elo delta.

    PR-HUB-VIS-CYCLE1-FOLLOWUP (2026-05-28) — replaced the inline
    ``<table class="records votes">`` per match with per-voter
    ``<details>`` expanders (each carries the provider chip + rationale
    on click). Voter info is still per-match, just expander-based to
    keep the chronological match list scannable. New Per-candidate Elo
    summary table joins survivors + non-survivors at the top.
    """
    html = built_seedgen_pages.get(f"{SEEDGEN_FIXTURE_RUN_ID}/tournament")
    assert html, "tournament sub-page missing"
    assert html.count('class="page-sub match"') >= 3, (
        "expected ≥3 match sections (fixture has 3 matches)"
    )
    assert html.count("<details>") >= 9, "expected ≥9 voter expanders (3 matches × 3 voters)"
    assert "Elo" in html
    assert "Per-candidate Elo summary" in html
    assert "winner:" in html  # ratified winner chip
    assert ">tie<" in html  # tie chip from one fixture match
    # Elo computation method annotated on the page (2026-05-29).
    assert "how Elo is computed" in html, "Elo method explainer missing"
    assert "1 + 10^" in html, "Elo expected-score formula missing"
    assert "K = 32" in html, "Elo K-factor missing"
    # Voter rationale renders in <pre class="msg">; hub.css must give it a base
    # wrap rule so long rationale does not run off the page horizontally
    # (2026-05-29 — the bare pre.msg had no wrap rule, only details.turn pre.msg).
    assert 'class="msg"' in html, "voter rationale not in pre.msg"
    css = (REPO_ROOT / "docs" / "self-improving" / "assets" / "hub.css").read_text(encoding="utf-8")
    msg_rule = re.search(r"(?<![.\w])pre\.msg\s*\{[^}]*\}", css)
    assert msg_rule is not None, "hub.css missing base pre.msg rule"
    assert "pre-wrap" in msg_rule.group(0) and "overflow-wrap" in msg_rule.group(0), (
        "base pre.msg must wrap responsively (pre-wrap + overflow-wrap)"
    )


def test_pr2_subpages_basepath_safe(built_seedgen_pages: dict[str, str]) -> None:
    """Every href on the new sub-pages is either /geode/-prefixed or external."""
    for key in (
        f"{SEEDGEN_FIXTURE_RUN_ID}/agents",
        f"{SEEDGEN_FIXTURE_RUN_ID}/timeline",
        f"{SEEDGEN_FIXTURE_RUN_ID}/tournament",
        f"{SEEDGEN_FIXTURE_RUN_ID}/agent/gen-c-001",
    ):
        html = built_seedgen_pages.get(key)
        if html is None:
            continue
        for href in _collect_hrefs(html):
            if href.startswith(("#", "mailto:", "https://", "http://")):
                continue
            assert href.startswith("/geode/"), (
                f"sub-page {key} href {href!r} missing /geode/ basePath"
            )


@pytest.fixture(scope="module")
def built_pr3_pages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Build the hub once with the active fixture run included so PR 3 tests can read it.

    Separate module-scoped fixture (not folded into built_seedgen_pages) so PR
    2 tests stay isolated from the test-run-002-active fixture.
    """
    out = tmp_path_factory.mktemp("seedgen-out-p3")
    seedgen_out = out / "seedgen"
    autoresearch_out = out / "autoresearch"
    subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(BUILDER),
            "--out",
            str(out / "hub" / "index.html"),
            "--bundle-root",
            str(FIXTURE_ROOT / "petri-bundle"),
            "--autoresearch-root",
            str(FIXTURE_ROOT / "autoresearch"),
            "--seedgen-out-dir",
            str(seedgen_out),
            # Redirect autoresearch output to tmp too — otherwise the builder
            # writes into docs/self-improving/autoresearch/ and dirties the tree.
            "--autoresearch-out-dir",
            str(autoresearch_out),
        ],
        check=True,
        cwd=str(REPO_ROOT),
    )
    pages: dict[str, str] = {}
    active_path = seedgen_out / "active" / "index.html"
    if active_path.is_file():
        pages["active"] = active_path.read_text(encoding="utf-8")
    lineage_idx = seedgen_out / SEEDGEN_FIXTURE_RUN_ID / "lineage" / "index.html"
    if lineage_idx.is_file():
        pages[f"{SEEDGEN_FIXTURE_RUN_ID}/lineage"] = lineage_idx.read_text(encoding="utf-8")
    lineage_root = seedgen_out / SEEDGEN_FIXTURE_RUN_ID / "lineage"
    if lineage_root.is_dir():
        for cand_dir in lineage_root.iterdir():
            if not cand_dir.is_dir():
                continue
            page = cand_dir / "index.html"
            if page.is_file():
                pages[f"{SEEDGEN_FIXTURE_RUN_ID}/lineage/{cand_dir.name}"] = page.read_text(
                    encoding="utf-8"
                )
    return pages


def test_pr3_active_runs_lists_in_progress(built_pr3_pages: dict[str, str]) -> None:
    """`/active/` lists test-run-002-active and excludes the done test-run-001."""
    html = built_pr3_pages.get("active")
    assert html, "active page missing"
    assert "test-run-002-active" in html, "in-progress fixture run missing"
    # done run must NOT appear in active table
    assert (
        '<td class="id"><a href="/geode/self-improving/seed-generation/test-run-001/">' not in html
    ), "active page rendered a done run in the active table"
    assert "ranker" in html
    assert "vote 3 of 12" in html


def test_pr3_active_has_meta_refresh_and_js_poller(built_pr3_pages: dict[str, str]) -> None:
    """`/active/` has meta-refresh fallback + inline JS poller, no framework, <2KB."""
    html = built_pr3_pages.get("active")
    assert html, "active page missing"
    assert 'http-equiv="refresh"' in html, "meta-refresh fallback missing"
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.DOTALL)
    assert scripts, "no <script> blocks found"
    for s in scripts:
        assert " src=" not in s, "external <script src=> not allowed (cotton)"
        assert "import " not in s and "from " not in s, "ESM imports forbidden (cotton)"
        assert len(s) < 2000, f"inline JS {len(s)} chars exceeds 2 KB cotton cap"


def test_pr3_lineage_index_lists_candidates(built_pr3_pages: dict[str, str]) -> None:
    """`/lineage/` lists both original (c-001/c-002) and evolved (c-001-ev1) candidates."""
    html = built_pr3_pages.get(f"{SEEDGEN_FIXTURE_RUN_ID}/lineage")
    assert html, "lineage index missing"
    assert "c-001" in html and "c-002" in html
    assert "c-001-ev1" in html, "evolved candidate missing from lineage index"


def test_pr3_lineage_detail_renders_stations_and_diff(
    built_pr3_pages: dict[str, str],
) -> None:
    """Per-candidate page has ≥4 phase stations + link to dedicated diff page.

    PR-HUB-VIS-CYCLE1 (2026-05-28) — inline ``<pre class="diff">`` block
    moved out to a separate side-by-side diff route. Lineage detail now
    surfaces a ``→ side-by-side diff (parent ↔ evolved)`` link in the
    evolver station instead, and the diff page itself renders parent +
    evolved MD side-by-side via marked.js.
    """
    html = built_pr3_pages.get(f"{SEEDGEN_FIXTURE_RUN_ID}/lineage/c-001")
    assert html, "lineage c-001 detail missing"
    assert html.count('class="page-sub lineage-station"') >= 4, (
        "expected ≥4 lineage stations for c-001 "
        "(supervisor / generator / critic / pilot / ranker / evolver)"
    )
    assert "side-by-side diff" in html, "evolver diff page link missing"
    assert "/diff/" in html, "evolver diff route link missing"


def test_pr3_lineage_basepath_safe(built_pr3_pages: dict[str, str]) -> None:
    """Every href on lineage + active pages is /geode/-prefixed or external."""
    for key in (
        "active",
        f"{SEEDGEN_FIXTURE_RUN_ID}/lineage",
        f"{SEEDGEN_FIXTURE_RUN_ID}/lineage/c-001",
    ):
        html = built_pr3_pages.get(key)
        if html is None:
            continue
        for href in _collect_hrefs(html):
            if href.startswith(("#", "mailto:", "https://", "http://")):
                continue
            assert href.startswith("/geode/"), (
                f"PR3 page {key} href {href!r} missing /geode/ basePath"
            )


# ---------------------------------------------------------------------------
# 13. Link-emit / page-emit parity (2026-05-29 — legacy gen1 hub gap)
# ---------------------------------------------------------------------------
#
# The hub linked /candidates/<cid>/ + /lineage/<cid>/diff/ pages that the
# builder never emitted, because the viewer + lineage loops keyed off
# state.json.candidates while the tournament page links every match
# participant and the viewer linked a diff page gated only on state.
# Fixture test-run-001 already reproduces the population case (c-003 is a
# tournament participant absent from state.candidates).


@pytest.fixture(scope="module")
def built_seedgen_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the full hub + seedgen tree once and return the seedgen output dir.

    Unlike the page-dict fixtures above, this returns the on-disk output
    root so the parity test can walk every emitted page rather than a
    curated subset.
    """
    build_root = tmp_path_factory.mktemp("seedgen-tree")
    seedgen_out = build_root / "seedgen"
    subprocess.run(  # noqa: S603 — fixture invocation, no user input
        [
            sys.executable,
            str(BUILDER),
            "--out",
            str(build_root / "hub" / "index.html"),
            "--bundle-root",
            str(FIXTURE_ROOT / "petri-bundle"),
            "--autoresearch-root",
            str(FIXTURE_ROOT / "autoresearch"),
            "--seedgen-out-dir",
            str(seedgen_out),
            "--autoresearch-out-dir",
            str(build_root / "autoresearch"),
        ],
        check=True,
        cwd=str(REPO_ROOT),
    )
    return seedgen_out


def test_seedgen_run_internal_links_resolve(built_seedgen_tree: Path) -> None:
    """Every internal seed-generation link under a run subtree resolves.

    Regression for the legacy gen1 gap: the tournament page links every
    match participant to ``/candidates/<cid>/``, but the viewer + lineage
    loops only rendered ``state.json.candidates``. In test-run-001, c-003
    is a tournament participant absent from ``state.candidates``, so
    ``/candidates/c-003/`` dangled. ``_linkable_candidate_cids`` now sources
    the union (drafts ∪ evolved ∪ on-disk .md ∪ tournament participants),
    so every linked cid has a page.
    """
    run_root = built_seedgen_tree / SEEDGEN_FIXTURE_RUN_ID
    assert run_root.is_dir(), f"run subtree missing at {run_root}"
    seedgen_prefix = "/geode/self-improving/seed-generation/"
    run_prefix = f"{seedgen_prefix}{SEEDGEN_FIXTURE_RUN_ID}/"
    broken: list[str] = []
    for page in run_root.rglob("index.html"):
        for href in _collect_hrefs(page.read_text(encoding="utf-8")):
            target = href.split("#", 1)[0]
            if not target.startswith(run_prefix):
                continue
            dest = built_seedgen_tree / target[len(seedgen_prefix) :]
            if target.endswith("/"):
                dest = dest / "index.html"
            if not dest.exists():
                broken.append(f"{page.relative_to(run_root).as_posix()}  ->  {href}")
    assert not broken, "dangling internal seed-gen links:\n" + "\n".join(sorted(set(broken)))


def test_viewer_diff_link_gated_on_diff_page(tmp_path: Path) -> None:
    """The viewer's "evolved → diff" chip links the diff page only when it renders.

    Regression for the legacy gen1 diff gap: the per-cid viewer emitted
    ``/lineage/<parent>/diff/`` whenever state recorded an evolved child,
    even when the evolved MD was missing from disk so the diff page was
    silently skipped (6 dangling links across gen1 runs). With the evolved
    MD removed, the diff page must not render and the chip must fall back
    to the evolved candidate's own viewer instead of dangling.
    """
    bundle = tmp_path / "petri-bundle"
    shutil.copytree(FIXTURE_ROOT / "petri-bundle", bundle)
    evolved_md = bundle / "seeds" / SEEDGEN_FIXTURE_RUN_ID / "candidates" / "c-001-ev1.md"
    assert evolved_md.is_file(), "fixture precondition: evolved MD present"
    evolved_md.unlink()

    out = tmp_path / "out"
    seedgen_out = out / "seedgen"
    result = subprocess.run(  # noqa: S603 — fixture invocation, no user input
        [
            sys.executable,
            str(BUILDER),
            "--out",
            str(out / "hub" / "index.html"),
            "--bundle-root",
            str(bundle),
            "--autoresearch-root",
            str(FIXTURE_ROOT / "autoresearch"),
            "--seedgen-out-dir",
            str(seedgen_out),
            "--autoresearch-out-dir",
            str(out / "autoresearch"),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    run_root = seedgen_out / SEEDGEN_FIXTURE_RUN_ID
    # Diff page must NOT be emitted once the evolved MD is gone.
    assert not (run_root / "lineage" / "c-001" / "diff" / "index.html").exists(), (
        "diff page rendered despite missing evolved MD"
    )
    viewer = (run_root / "candidates" / "c-001" / "index.html").read_text(encoding="utf-8")
    assert "/lineage/c-001/diff/" not in viewer, (
        "viewer linked the skipped diff page — link-emit / page-emit parity violated"
    )
    # Fallback target is the evolved candidate's own viewer, which exists.
    assert "/candidates/c-001-ev1/" in viewer, "viewer missing evolved-candidate fallback link"
    assert (run_root / "candidates" / "c-001-ev1" / "index.html").exists(), (
        "evolved-candidate fallback viewer not emitted"
    )


def test_pr2_subpages_no_js_framework(built_seedgen_pages: dict[str, str]) -> None:
    """Cotton discipline — PR 2 sub-pages must be pure static HTML."""
    for key in (
        f"{SEEDGEN_FIXTURE_RUN_ID}/agents",
        f"{SEEDGEN_FIXTURE_RUN_ID}/timeline",
        f"{SEEDGEN_FIXTURE_RUN_ID}/tournament",
        f"{SEEDGEN_FIXTURE_RUN_ID}/agent/gen-c-001",
    ):
        html = built_seedgen_pages.get(key)
        if html is None:
            continue
        assert "<script" not in html, f"sub-page {key} has JS — cotton rule violated"


def test_pr1_tournament_schema_complete() -> None:
    """tournament.json must carry per-voter rationale + Elo before/after deltas.

    Pinned because the hub /tournament/ page (PR 2) renders these exact
    keys — drift between writer + renderer would silently regress the
    high-resolution surface.
    """
    data = json.loads((_HIRES_FIXTURE / "tournament.json").read_text(encoding="utf-8"))
    assert isinstance(data.get("voter_panel"), list) and len(data["voter_panel"]) >= 2
    matches = data.get("matches")
    assert isinstance(matches, list) and len(matches) >= 1
    seen_winners: set[str] = set()
    for m in matches:
        assert {"match_id", "candidate_a", "candidate_b", "votes"} <= m.keys()
        assert isinstance(m["votes"], list) and len(m["votes"]) >= 2
        for v in m["votes"]:
            assert {"voter_id", "voter_model", "voter_provider", "vote", "rationale"} <= v.keys()
        assert {"elo_before", "elo_after", "elo_delta_a", "elo_delta_b"} <= m.keys()
        assert m["winner"] in {"A", "B", "tie", None}
        if isinstance(m["winner"], str):
            seen_winners.add(m["winner"])
    # Mixed-outcome coverage so the renderer's per-state branches are exercised.
    assert seen_winners == {"A", "B", "tie"}, (
        f"tournament fixture must cover A/B/tie outcomes (got {sorted(seen_winners)})"
    )
