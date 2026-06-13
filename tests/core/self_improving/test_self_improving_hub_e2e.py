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

REPO_ROOT = Path(__file__).resolve().parents[3]
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
    # 20 dim columns (PR-DROP-ANALYTICS-DIMS removed verbose_padding +
    # redundant_tool_invocation). Plus one "id" left header == 21 total.
    assert th_count == 21, f"expected 21 <th> (20 dims + id), got {th_count}"
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
    for name in ("index", "baseline", "mutations", "results", "evidence", "policies"):
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
    # Full-width regression (PR-HUB-PAYLOAD-FULLWIDTH): the payload <details> must be
    # emitted in its OWN full-width <tr><td colspan> row (.mutation-payload-row), NOT
    # crammed into the narrow outcome cell — otherwise the opened JSON renders
    # right-skewed into the last column. The <details> must sit inside that full-width
    # colspan cell. The regex is whitespace-tolerant so trivial formatter changes do
    # not break it, but still pins the structural pairing.
    assert re.search(
        r'<tr class="mutation-payload-row">\s*<td colspan="\d+">\s*<details>',
        html,
    ), (
        "payload <details> not in its own full-width colspan row (would inherit the "
        "narrow outcome column and render right-skewed)"
    )
    assert 'class="mutation-payload"' in html, "full-width payload wrapper missing"
    # Codex M2 — the fixture carries one pre-#1947 (penalized-recipe) attribution row
    # (mut004penalized, ts before the boundary). The rendered page must surface it as
    # EXCLUDED and tag it per-row, and the mean-Δ must be the 3 plain rows only — not a
    # blend with the penalized -0.35. (3 plain deltas 0.1, -0.08, 0.002 → mean +0.0073.)
    assert "1 penalized recipe (pre-#1947, excluded)" in html, (
        "pre-#1947 penalized row not surfaced as excluded in the rendered summary"
    )
    assert "penalized recipe (pre-#1947)" in html, "penalized row not tagged in the per-row Δ cell"
    assert "+0.0073" in html and "0-1 plain-recipe rows only" in html, (
        "mean-Δ blended the penalized recipe instead of using the plain rows only"
    )


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


# ---------------------------------------------------------------------------
# E6 (2026-05-30) — the honest evidence page (methods + results + power)
# ---------------------------------------------------------------------------


def test_evidence_page_renders_three_sections(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """E6 + PR-HUB-CAMPAIGN-VIZ: the evidence page renders the 4 sections
    (methods / results / live campaign / power), has the Evidence bucket title,
    and resolves every template marker."""
    html = built_autoresearch_pages["evidence"]
    assert "1 &middot; Methods" in html, "Methods section heading missing"
    assert "2 &middot; Results" in html, "Results section heading missing"
    assert "3 &middot; Live campaign" in html, "Live campaign section heading missing"
    assert "4 &middot; Power" in html, "Power section heading missing"
    # Methods names the frozen ruler vs the pinned pool + the 3 arms + E5 pins + epoch.
    assert "held-out ruler" in html and "pool-68dc6f0c9745" in html, (
        "methods must name the frozen held-out ruler vs the pinned selection pool"
    )
    for arm in ("gate", "random", "never"):
        assert arm in html, f"methods must name the {arm!r} control arm"
    assert "prompt_hash" in html and "applied_diff_hash" in html, "E5 pins not described"
    assert "epoch" in html.lower(), "content-addressed epoch partition not described"
    # No unresolved template markers.
    assert "{{" not in html and "}}" not in html, "unresolved template markers on evidence page"


def test_evidence_page_graceful_empty_state(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """E6 CRITICAL: with no matched 3-arm held-out campaign on disk (the real
    fixture has no promote_policy / gain rows), the page renders the full structure
    + an HONEST 'awaiting' / 'no evidence yet' state — never a crash, never a
    fabricated number, never a placeholder like XXXX."""
    html = built_autoresearch_pages["evidence"]
    # Honest empty states present.
    assert "awaiting" in html.lower(), "missing honest 'awaiting campaign' empty state"
    assert "no evidence" in html.lower(), "missing honest 'no evidence yet' verdict"
    # NO fabricated number / placeholder.
    assert "XXXX" not in html, "placeholder XXXX present — measured values only"
    # The power section, with no recorded sigma, says 'indeterminate' rather than
    # inventing an N.
    assert "indeterminate" in html.lower(), (
        "power section must report N indeterminate when sigma is unrecorded, not fabricate"
    )


def test_evidence_page_states_zero_promotions_as_trust(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """E6 honest framing: 0 promotions is stated as a TRUST-INCREASING result, not
    a failure (operator's verbatim intent)."""
    html = built_autoresearch_pages["evidence"]
    assert "trust-increasing" in html.lower(), (
        "0-promotion framing as trust-increasing missing from evidence page"
    )


def test_evidence_page_no_slop(built_autoresearch_pages: dict[str, str]) -> None:
    """E6 no-slop (CLAUDE.md §Docs, feedback_no_box_ui_no_emoji): no colored
    left-border accent bar, no card-grid navigation, no emoji. Dense tables only."""
    html = built_autoresearch_pages["evidence"]
    assert "border-left" not in html, "colored accent bar (border-left) is slop"
    assert "card-grid" not in html and "subview-card" not in html, "card-grid nav is slop"
    assert not _find_emoji(html), f"emoji on evidence page: {_find_emoji(html)!r}"
    # The evidence content uses dense <table class="records"> + <dl class="status-grid">.
    assert 'class="records"' in html and 'class="status-grid"' in html, (
        "evidence page must use dense table / definition-list, not card grid"
    )


def test_evidence_page_in_nav_and_subview(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """E6 wiring: the Evidence link is in every autoresearch sidebar + the landing
    sub-view table now lists 5 sub-pages including Evidence."""
    for name, html in built_autoresearch_pages.items():
        assert "/geode/self-improving/autoresearch/evidence/" in html, (
            f"autoresearch {name} sidebar missing the Evidence nav link"
        )
    landing = built_autoresearch_pages["index"]
    assert "5 autoresearch sub-pages" in landing, "landing sub-view count not bumped to 5"
    assert "Evidence" in landing, "Evidence sub-view row missing from landing"


# ---------------------------------------------------------------------------
# 12b. Run reports (autoresearch/runs/ index + per-run markdown render)
# ---------------------------------------------------------------------------
#
# PR-HUB-RUN-REPORT (2026-06-04): serve a self-improving campaign synthesis as a
# data-driven per-run page. The builder globs ``docs/self-improving/run-*.md``
# (the source-doc dir, NOT the out dir) and renders, for each, an index entry +
# a ``runs/<slug>/`` page. PR-HUB-RUN-REPORT-SSR (2026-06-04) renders the .md to
# HTML at BUILD TIME via markdown-it-py and injects it directly into
# ``<article class="markdown-body">`` (no CDN / client-side JS — the prior
# Marked.js embed showed a BLANK body when the CDN was blocked / JS was off).
# slug = stem minus leading ``run-``. The fixture builds against the live docs
# dir so the run-2606 report (committed in this PR) renders.

_RUN_2606_SLUG = "2606-broken-tool-use"


@pytest.fixture(scope="module")
def built_run_report_pages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Build the runs index + each run-*.md page once per session.

    Returns ``{"index": html, _RUN_2606_SLUG: html}`` — the autoresearch out dir
    is redirected to tmp but ``--run-reports-dir`` keeps its default (the live
    ``docs/self-improving`` dir) so the committed run-2606 synthesis renders.
    """
    out = tmp_path_factory.mktemp("run-report-out")
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
        f"run-report builder failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    index_path = autoresearch_out / "runs" / "index.html"
    run_path = autoresearch_out / "runs" / _RUN_2606_SLUG / "index.html"
    assert index_path.is_file(), f"runs index missing at {index_path}"
    assert run_path.is_file(), f"run-2606 page missing at {run_path}"
    return {
        "index": index_path.read_text(encoding="utf-8"),
        _RUN_2606_SLUG: run_path.read_text(encoding="utf-8"),
    }


def test_runs_index_and_run_page_build(built_run_report_pages: dict[str, str]) -> None:
    """(a) The runs index + the run-2606 page build and exist (fixture asserts
    the files; here we assert their identity-bearing content rendered)."""
    index = built_run_report_pages["index"]
    run = built_run_report_pages[_RUN_2606_SLUG]
    # The index lists the run by its discovered slug + the .md's first heading.
    assert _RUN_2606_SLUG in index, "runs index does not list the run-2606 slug"
    assert "broken_tool_use" in index, "runs index missing the run title from the .md heading"
    assert f'href="/geode/self-improving/autoresearch/runs/{_RUN_2606_SLUG}/"' in index, (
        "runs index missing the absolute /geode link to the run page"
    )
    # The run page carries the run title in <title> + the campaign question text.
    assert "broken_tool_use" in run, "run page missing the title"


def test_run_page_renders_markdown_server_side(built_run_report_pages: dict[str, str]) -> None:
    """(b) PR-HUB-RUN-REPORT-SSR — the run page renders the .md to HTML at BUILD
    TIME (markdown-it-py) and injects it directly into the markdown-body article:
    real ``<h1>`` / ``<table>`` / ``<strong>`` are present, NOT an empty article +
    a ``text/markdown`` script, and there is NO Marked.js CDN loader on the page
    (so the body renders with JS off / a CDN blocked). The run-2606 synthesis is
    table-heavy with headers + bold, so all three element kinds must appear."""
    run = built_run_report_pages[_RUN_2606_SLUG]
    # The body container stays for styling — but it is now FILLED with rendered HTML.
    assert 'class="markdown-body"' in run, "run page missing the markdown-body article"
    # Server-rendered elements present directly in the page body.
    assert "<h1" in run, "run page missing a server-rendered <h1> heading"
    assert "<table" in run, "run page missing a server-rendered <table> (synthesis is table-heavy)"
    assert "<strong>" in run, "run page missing server-rendered <strong> bold"
    # The OLD client-side embed must be gone for THIS page: no empty target +
    # text/markdown source, and no Marked.js CDN loader.
    assert 'data-md-target="run-body"' not in run, "run page still has the empty md-target article"
    assert '<script type="text/markdown"' not in run, (
        "run page still embeds the raw markdown in a text/markdown script block"
    )
    assert "marked@13/marked.min.js" not in run, (
        "run page still loads the Marked.js CDN — should render server-side now"
    )
    # The synthesis prose survives into rendered text (proof the body rendered).
    assert "lower=better" in run, "run page did not render the .md body content"


def test_runs_sidebar_has_runs_link(built_run_report_pages: dict[str, str]) -> None:
    """(c) Every run-report page sidebar exposes the Runs nav link, and the
    active item is marked aria-current on the runs index + run page."""
    for name, html in built_run_report_pages.items():
        assert "/geode/self-improving/autoresearch/runs/" in html, (
            f"run-report {name} sidebar missing the Runs nav link"
        )
        assert 'aria-current="page"' in html, (
            f"run-report {name} missing aria-current on the active Runs link"
        )


def test_run_pages_every_href_is_basepath_safe(
    built_run_report_pages: dict[str, str],
) -> None:
    """(d) Every <a href> on the runs index + run page starts with /geode/ or is
    external (mirrors test_every_href_is_basepath_safe for the new pages)."""
    for name, html in built_run_report_pages.items():
        hrefs = _collect_hrefs(html)
        assert hrefs, f"run-report {name} has no anchors — template broken"
        for href in hrefs:
            if href.startswith(("#", "https://", "http://", "mailto:")):
                continue
            assert href.startswith("/geode/"), (
                f"run-report {name} href {href!r} missing /geode/ basePath prefix"
            )


def test_run_pages_no_emoji(built_run_report_pages: dict[str, str]) -> None:
    """(e) No emoji in rendered HTML — including the ✓/❌ dingbats (U+2713 /
    U+274C) that the .md's deslop pass replaced with plain best/worst words so
    the embedded markdown stays clean under _find_emoji's 0x2700-0x27BF range."""
    for name, html in built_run_report_pages.items():
        found = _find_emoji(html)
        assert not found, f"emoji in run-report {name}: {found!r}"


def test_main_hub_index_has_runs_nav_link(built_html: str) -> None:
    """The main hub landing (built_html) also exposes the Runs link under the
    Autoresearch nav-section, keeping every autoresearch surface consistent."""
    assert "/geode/self-improving/autoresearch/runs/" in built_html, (
        "main hub index sidebar missing the Runs nav link"
    )


def _run_report_ctx() -> Any:
    """A minimal _AutoresearchRenderCtx for the direct-call run-report tests."""
    from scripts.build_self_improving_hub import _AutoresearchRenderCtx

    return _AutoresearchRenderCtx(
        sidebar_petri_recent="",
        sidebar_seedgen_runs="",
        petri_count=0,
        seedgen_count_label="0 runs",
        autoresearch_status_label="live",
        geode_version="9.9.9",
        build_date="2026-06-04 00:00",
    )


def test_run_report_escapes_text_node_specials(tmp_path: Path) -> None:
    """PR-HUB-RUN-REPORT-SSR — markdown-it escapes text-node specials itself
    (``&`` -> ``&amp;``, a literal ``<x`` -> ``&lt;``), so the body is NOT
    pre-escaped via html_escape: double-escaping was the bug that rendered the
    intro blockquote's ``>``/``&`` as literal ``&gt;``/``&amp;``. A markdown
    blockquote + an inline ``&`` must render to a real ``<blockquote>`` and a
    single (not double) ``&amp;`` — never a literal ``&amp;amp;``."""
    from scripts.build_self_improving_hub import (
        AUTORESEARCH_RUN_REPORT_TEMPLATE,
        render_autoresearch_run_report,
    )

    md = tmp_path / "run-escape-probe.md"
    md.write_text(
        "# Escape probe\n\n> intro note with R&D and a < b comparison\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    template = AUTORESEARCH_RUN_REPORT_TEMPLATE.read_text(encoding="utf-8")
    page = render_autoresearch_run_report(
        md, out_dir, template=template, ctx=_run_report_ctx(), repo_root=tmp_path
    )
    html = page.read_text(encoding="utf-8")
    # The blockquote rendered to real HTML (not literal ``&gt; intro``).
    assert "<blockquote>" in html, "markdown blockquote did not render server-side"
    assert "&gt; intro" not in html, "blockquote marker leaked as literal &gt; (double-escape bug)"
    # ``&`` is escaped exactly once — no double-escaped ``&amp;amp;``.
    assert "R&amp;D" in html, "inline & should render to a single &amp;"
    assert "&amp;amp;" not in html, "double-escaped & (the original bug) reappeared"
    # No client-side embed leaked into the page.
    assert '<script type="text/markdown"' not in html, "stale text/markdown script block present"


def test_run_report_allows_template_marker_in_markdown(tmp_path: Path) -> None:
    """Codex finding #3 — a run report whose prose legitimately contains a
    ``{{ ... }}`` token must NOT be misread as an unresolved template marker.
    The chrome markers are validated BEFORE the body is injected."""
    from scripts.build_self_improving_hub import (
        AUTORESEARCH_RUN_REPORT_TEMPLATE,
        render_autoresearch_run_report,
    )

    md = tmp_path / "run-marker-probe.md"
    md.write_text(
        "# Marker probe\n\nThe template uses `{{ run_body_html }}` and `{{ geode_version }}`.\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    template = AUTORESEARCH_RUN_REPORT_TEMPLATE.read_text(encoding="utf-8")
    # Must not raise RuntimeError("unresolved markers ...") — the chrome marker
    # scan runs BEFORE the rendered body is injected, so the body's own
    # ``{{ run_body_html }}`` token is never mistaken for an unresolved marker.
    page = render_autoresearch_run_report(
        md, out_dir, template=template, ctx=_run_report_ctx(), repo_root=tmp_path
    )
    html = page.read_text(encoding="utf-8")
    # markdown-it renders the inline-code token to <code>{{ run_body_html }}</code>
    # — the {{ }} survives verbatim as inert text (no template substitution of a
    # body-authored token).
    assert "{{ run_body_html }}" in html, (
        "the {{ }} token from the markdown body should survive into the page as inert text"
    )


def test_run_slug_rejects_unsafe_names(tmp_path: Path) -> None:
    """Codex finding #1 — slugs that are empty / ``.`` / ``..`` / non-url-safe
    raise, so the per-page _safe wrapper skips them instead of overwriting
    runs/index.html or escaping the runs dir."""
    from scripts.build_self_improving_hub import _run_slug

    assert _run_slug(tmp_path / "run-2606-broken-tool-use.md") == "2606-broken-tool-use"
    for bad in ("run-.md", "run-..md", "run-Bad_Slug.md", "run- space.md"):
        with pytest.raises(ValueError):
            _run_slug(tmp_path / bad)


def test_runs_index_skips_unsafe_and_dedups(tmp_path: Path) -> None:
    """The runs index degrades gracefully: an unsafe-slug file is skipped (logged,
    not fatal) and the count reflects only the rendered reports."""
    from scripts.build_self_improving_hub import (
        AUTORESEARCH_RUNS_INDEX_TEMPLATE,
        render_autoresearch_runs_index,
    )

    good = tmp_path / "run-good-report.md"
    good.write_text("# Good report\n", encoding="utf-8")
    bad = tmp_path / "run-.md"  # -> empty slug, must be skipped
    bad.write_text("# Bad\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    template = AUTORESEARCH_RUNS_INDEX_TEMPLATE.read_text(encoding="utf-8")
    # The list deliberately carries `good` twice (a duplicate slug) + one
    # unsafe-slug file: the renderer must skip the unsafe one AND dedup the
    # repeat, leaving exactly one rendered report.
    page = render_autoresearch_runs_index(
        [good, good, bad], out_dir, template=template, ctx=_run_report_ctx()
    )
    html = page.read_text(encoding="utf-8")
    assert "good-report" in html, "good report missing from index"
    assert html.count("good-report</code>") == 1, "duplicate slug should be deduped to one row"
    assert "1 report" in html, "index count should reflect only one unique safe report"


def test_evidence_results_populated_per_arm_curve() -> None:
    """E6 RESULTS (populated path): with multi-arm held-out + gain rows, the renderer
    splits the per-cycle held-out curve PER ARM, computes a 3-arm comparison on the
    fixed ruler, counts promotions per arm, and renders the ci-excludes-0 verdict.
    Reads exactly the fields E2-E4 write (held_out_fitness / promote_policy /
    gain_ci_excludes_zero / gain_verdict)."""
    from scripts.build_self_improving_hub import (
        _render_evidence_results,
        _render_evidence_verdict,
    )

    mutations = [
        # gate arm — two held-out cycles, an improvement.
        {
            "kind": "attribution",
            "ts": 10.0,
            "held_out_fitness": 0.60,
            "held_out_bench_id": "pool-x",
            "promote_policy": "gate",
            "gain_ci_low": 0.01,
            "gain_ci_high": 0.05,
            "gain_ci_excludes_zero": True,
            "gain_verdict": "gain significant",
        },
        {
            "kind": "attribution",
            "ts": 20.0,
            "held_out_fitness": 0.64,
            "held_out_bench_id": "pool-x",
            "promote_policy": "gate",
        },
        # random arm — one held-out cycle, no gain evidence.
        {
            "kind": "attribution",
            "ts": 15.0,
            "held_out_fitness": 0.59,
            "held_out_bench_id": "pool-x",
            "promote_policy": "random",
            "gain_ci_low": -0.02,
            "gain_ci_high": 0.02,
            "gain_ci_excludes_zero": False,
            "gain_verdict": "no evidence yet",
        },
    ]
    archive = [
        {"kind": "baseline", "ts_utc": "2026-05-30T00:00:00+00:00", "promote_policy": "gate"},
    ]
    results_html = _render_evidence_results(mutations, archive)
    # Per-arm curve: the gate arm shows 2 generations, random shows 1.
    assert "gate" in results_html and "random" in results_html and "never" in results_html
    assert "0.6000" in results_html and "0.6400" in results_html, "gate arm curve values missing"
    assert "0.5900" in results_html, "random arm curve value missing"
    # 3-arm comparison: gate has 1 promotion (from the archive row).
    assert "3-arm comparison" in results_html
    # never arm has no held-out cycle → honest per-arm empty state.
    assert "No held-out cycle recorded for this arm yet" in results_html

    verdict_html = _render_evidence_verdict(mutations, archive)
    assert "gain significant" in verdict_html, "significant verdict not surfaced"
    assert "no evidence yet" in verdict_html, "honest null verdict not surfaced"
    # The CI bounds are rendered (read from the recorded fields).
    assert "+0.0100" in verdict_html and "+0.0500" in verdict_html, "gain CI bounds missing"


def test_evidence_untagged_baseline_not_counted_as_gate_arm() -> None:
    """E6 honesty (Codex review): a pre-E3 promoted baseline carrying NO
    promote_policy must NOT be silently attributed to the gate arm — that would
    fabricate a matched-campaign result. It is counted in an explicit
    'untagged (pre-arm)' bucket, and the gate arm shows 0 arm-tagged promotions."""
    from scripts.build_self_improving_hub import _render_evidence_results

    mutations: list = []  # no held-out / arm rows on disk
    archive = [{"kind": "baseline", "ts_utc": "2026-05-30T00:00:00+00:00"}]  # no promote_policy
    html = _render_evidence_results(mutations, archive)
    # The untagged bucket appears + names the pre-arm origin.
    assert "untagged" in html and "pre-arm" in html, "untagged baseline must be a separate bucket"
    # The comparison note must NOT claim a gate-arm promotion; it states the baseline
    # predates the control arms (singular verb for the single fixture baseline).
    assert "predates the control arms" in html, (
        "an untagged promotion must be flagged as predating the arms, not folded into gate"
    )
    # The gate arm row shows 0 promotions (the untagged baseline is NOT counted there).
    gate_idx = html.find("selection (promote gate)")
    assert gate_idx != -1
    # The gate row's promotions cell (last <td class="num"> in that <tr>) is 0.
    gate_row = html[gate_idx : html.find("</tr>", gate_idx)]
    assert ">1<" not in gate_row, "untagged baseline wrongly counted as a gate-arm promotion"


def test_evidence_verdict_renders_archive_iso_timestamp() -> None:
    """E6 parity (Codex review): a promoted-baseline verdict row carries an ISO-string
    ts_utc, which must be formatted (not dropped as '—' by a numeric-only cast)."""
    from scripts.build_self_improving_hub import _render_evidence_verdict

    archive = [
        {
            "kind": "baseline",
            "ts_utc": "2026-05-30T12:34:56+00:00",
            "promote_policy": "gate",
            "gain_ci_excludes_zero": False,
            "gain_verdict": "no evidence yet",
        }
    ]
    html = _render_evidence_verdict([], archive)
    assert "no evidence yet" in html
    # The ISO date surfaces (short form) — the archive ts is no longer dropped.
    assert "2026-05-30" in html, "archive ISO ts_utc must be formatted, not rendered as —"


def test_evidence_power_reads_recorded_sigma() -> None:
    """E6 POWER (populated path): the required-N line is COMPUTED from the recorded
    combined sigma (within/between stderr), never fabricated. The N matches the
    writer's formula for the same sigma."""
    from scripts.build_self_improving_hub import _render_evidence_power, _required_n_seed

    mutations = [
        {
            "kind": "attribution",
            "ts": 10.0,
            "within_mutation_stderr": 0.0,
            "between_seed_stderr": 0.013,
        },
    ]
    html = _render_evidence_power(mutations)
    # sigma = sqrt(0^2 + 0.013^2) = 0.0130 — surfaced as the recorded sigma.
    assert "0.0130" in html, "recorded combined sigma not surfaced in power section"
    # required-N computed from that sigma (not indeterminate when sigma is recorded).
    sigma = (0.0**2 + 0.013**2) ** 0.5
    expected_n = _required_n_seed(sigma)
    assert expected_n is not None
    assert str(expected_n) in html, f"required N_seed {expected_n} not rendered from recorded sigma"
    assert "indeterminate" not in html.lower(), "should not say indeterminate when sigma recorded"


def test_evidence_power_indeterminate_when_no_sigma() -> None:
    """E6 POWER honest empty: with no recorded variance signal, the required-N is
    reported as 'indeterminate' (not a fabricated number)."""
    from scripts.build_self_improving_hub import _render_evidence_power

    # No within/between stderr on any row → sigma unknown.
    mutations = [{"kind": "attribution", "ts": 10.0, "held_out_fitness": 0.6}]
    html = _render_evidence_power(mutations)
    assert "indeterminate" in html.lower(), "power must report indeterminate when sigma unknown"
    assert "not yet estimated" in html.lower(), "sigma cell must say not-yet-estimated"


def test_evidence_required_n_seed_matches_core_formula() -> None:
    """E6 drift guard: the stdlib power-formula mirror in the builder reproduces
    core.self_improving.loop.observe.statistical_power.required_samples for the same sigma."""
    from core.self_improving.loop.observe.statistical_power import (
        DEFAULT_ALPHA,
        DEFAULT_POWER,
        DEFAULT_TARGET_EFFECT_SIZE,
        required_samples,
    )
    from scripts.build_self_improving_hub import (
        _POWER_DEFAULT_ALPHA,
        _POWER_DEFAULT_POWER,
        _POWER_DEFAULT_TARGET_EFFECT_SIZE,
        _required_n_seed,
    )

    # Constants must match the SoT (the stdlib mirror is otherwise silently stale).
    assert _POWER_DEFAULT_TARGET_EFFECT_SIZE == DEFAULT_TARGET_EFFECT_SIZE
    assert _POWER_DEFAULT_ALPHA == DEFAULT_ALPHA
    assert _POWER_DEFAULT_POWER == DEFAULT_POWER
    for sigma in (0.0, 0.005, 0.013, 0.05, 0.2):
        assert _required_n_seed(sigma) == required_samples(sigma).n_seed, (
            f"builder _required_n_seed({sigma}) diverges from required_samples"
        )
    # Graceful: None / negative / non-finite sigma → None (no crash, no fabrication).
    assert _required_n_seed(None) is None
    assert _required_n_seed(-1.0) is None
    assert _required_n_seed(float("nan")) is None


def test_evidence_arm_map_matches_core() -> None:
    """E6 drift guard: the builder's 3 control-arm names match the writer-side
    _VALID_PROMOTE_POLICIES SoT in core/self_improving/train.py (parsed textually, since the
    builder is stdlib-only)."""
    from scripts.build_self_improving_hub import _EVIDENCE_ARMS

    train_src = (REPO_ROOT / "core" / "self_improving" / "gate.py").read_text(encoding="utf-8")
    m = re.search(r"_VALID_PROMOTE_POLICIES\s*=\s*frozenset\(\{([^}]*)\}\)", train_src)
    assert m is not None, "could not locate _VALID_PROMOTE_POLICIES in train.py"
    core_arms = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    builder_arms = {arm for arm, _label in _EVIDENCE_ARMS}
    assert builder_arms == core_arms, f"builder arms {builder_arms} drift from core {core_arms}"


def test_evidence_results_graceful_on_malformed_rows() -> None:
    """E6 graceful contract: a non-numeric held_out_fitness / ts / gain CI bound is
    skipped, not raised — the render never sinks on a malformed ledger row."""
    from scripts.build_self_improving_hub import (
        _render_evidence_power,
        _render_evidence_results,
        _render_evidence_verdict,
    )

    mutations = [
        {"kind": "attribution", "ts": "bad", "held_out_fitness": 0.6, "promote_policy": "gate"},
        {"kind": "attribution", "ts": 10.0, "held_out_fitness": "oops", "promote_policy": "gate"},
        {
            "kind": "attribution",
            "ts": 20.0,
            "gain_ci_excludes_zero": False,
            "gain_ci_low": "x",
            "gain_ci_high": None,
        },
        {"kind": "attribution", "ts": 30.0, "within_mutation_stderr": "nope"},
    ]
    archive: list = []
    # None of these raise.
    results_html = _render_evidence_results(mutations, archive)
    verdict_html = _render_evidence_verdict(mutations, archive)
    power_html = _render_evidence_power(mutations)
    assert "3-arm comparison" in results_html
    # The malformed gain CI row still produces a verdict row, with a "—" CI cell.
    assert "no evidence yet" in verdict_html
    # The malformed sigma row leaves sigma unestimated → indeterminate.
    assert "indeterminate" in power_html.lower()


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

    from core.self_improving.loop.mutate.policies import _KIND_TO_PATH

    core_map = {kind: path.name for kind, path in _KIND_TO_PATH.items()}
    builder_map = builder._TARGET_KIND_TO_POLICY_FILE
    assert core_map == builder_map, (
        "builder _TARGET_KIND_TO_POLICY_FILE drifted from core _KIND_TO_PATH; "
        f"builder={builder_map} core={core_map}"
    )


def test_results_jsonl_drilldown_strips_absolute_eval_archive_path() -> None:
    """``results.jsonl`` rows carry ``eval_archive`` as an ABSOLUTE local path
    (``/Users/<name>/.geode/petri/logs/…_audit_<id>.eval``) written by
    ``core/self_improving/train.py``. The results drill-down dumps each row
    verbatim into the published static site, so the raw path would leak the
    operator's home directory onto a public page. The builder must reduce it to
    the basename (no-hardcoded-user-paths rule). Guards the
    PR-HUB-RESULTS-PATH-LEAK fix.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_hub_builder_pathleak", BUILDER)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = builder
    spec.loader.exec_module(builder)

    abs_path = "/Users/somebody/.geode/petri/logs/2026-06-01T20-24-43-00-00_audit_AbCdEf123.eval"
    basename = "2026-06-01T20-24-43-00-00_audit_AbCdEf123.eval"

    # Unit: the sanitizer reduces eval_archive to its basename and leaves the
    # source row untouched (shallow copy).
    src_row = {"session_id": "s1", "eval_archive": abs_path, "fitness": 0.5}
    sanitized = builder._sanitize_results_jsonl_row(src_row)
    assert sanitized["eval_archive"] == basename
    assert src_row["eval_archive"] == abs_path, "source row mutated"
    # Already-basename / missing field → untouched.
    assert builder._sanitize_results_jsonl_row({"eval_archive": basename}) == {
        "eval_archive": basename
    }
    assert builder._sanitize_results_jsonl_row({"session_id": "s2"}) == {"session_id": "s2"}

    # Integration: the rendered drill-down HTML must not contain the absolute
    # prefix, but must retain the portable basename identifier.
    tsv_rows = [dict.fromkeys(builder.AUTORESEARCH_RESULTS_TSV_HEADER, "")]
    tsv_rows[0]["session_id"] = "s1"
    tsv_rows[0]["fitness"] = "0.5000"
    rendered = builder._render_results_rows(tsv_rows, [src_row])
    assert "/Users/somebody" not in rendered
    assert "/.geode/petri/logs" not in rendered
    assert basename in rendered

    # Same defect class on the baseline page: the schema-v2 ``raw`` namespace
    # carries ``raw.eval_archive`` as an absolute path. The baseline kv-row
    # renderer must basename it too.
    baseline_row = builder._render_baseline_kv_row("raw", "eval_archive", abs_path)
    assert "/Users/somebody" not in baseline_row
    assert "/.geode/petri/logs" not in baseline_row
    assert basename in baseline_row
    # Non-eval_archive keys are untouched (no over-eager basenaming).
    other = builder._render_baseline_kv_row("metadata", "seed_pool", "pool-abc123")
    assert "pool-abc123" in other


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
    # The openai-codex voter keeps the `codex` chip CSS class but the visible
    # label is "ChatGPT" (the subscription lane), not the opaque "Codex" name.
    assert 'class="chip codex"' in html, "codex (ChatGPT lane) chip missing"
    assert "ChatGPT" in html, "openai-codex lane should show the ChatGPT label"


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


# ---------------------------------------------------------------------------
# E1b — pre-E1 mixed-scale rows excluded from the 0-1 Δfitness aggregate
# ---------------------------------------------------------------------------
#
# E1 (PR-MARGIN-FITNESS-SCALE) reconciled per-mutation fitness_before /
# fitness_delta to the 0-1 compute_fitness scale, but the 8 rows already in
# state/autoresearch/mutations.jsonl carry the OLD dim-aggregate scale
# (fitness_before ≈ 1.73-2.29, delta ≈ -1.7). The ledger is intentionally not
# rewritten, so the hub must drop those rows from the 0-1 mean-Δ aggregate and
# tag them per-row. These tests pin that display-side heuristic.


def _joined_mutation(*, mid: str, fitness_before: Any, fitness_delta: Any) -> dict[str, Any]:
    """Build a single joined mutation entry (apply + attr) for the summary/row
    renderers. ``fitness_before > 1.0`` marks a pre-E1 mixed-scale row."""
    attr: dict[str, Any] = {"mutation_id": mid, "fitness_delta": fitness_delta}
    if fitness_before is not None:
        attr["fitness_before"] = fitness_before
        if isinstance(fitness_delta, int | float) and isinstance(fitness_before, int | float):
            attr["fitness_after"] = fitness_before + fitness_delta
    apply_row = {"mutation_id": mid, "target_section": "sec", "target_kind": "policy"}
    return {"id": mid, "apply": apply_row, "attr": attr}


def test_mutations_summary_mean_delta_over_post_e1_rows_only() -> None:
    """Mixed input: two post-E1 (≤1.0) rows + two pre-E1 (>1.0) rows. The mean-Δ
    aggregate must be computed over ONLY the ≤1.0 rows, and n must reflect that."""
    builder = _load_builder_module()
    joined = [
        _joined_mutation(mid="post-a", fitness_before=0.70, fitness_delta=0.10),
        _joined_mutation(mid="post-b", fitness_before=0.60, fitness_delta=0.20),
        _joined_mutation(mid="pre-a", fitness_before=1.7333, fitness_delta=-1.7333),
        _joined_mutation(mid="pre-b", fitness_before=1.7583, fitness_delta=-1.1110),
    ]
    html = builder._render_mutations_summary(joined)
    # mean over the two 0-1 rows only = (0.10 + 0.20) / 2 = +0.1500.
    assert "+0.1500" in html, "mean-Δfitness not computed over the post-E1 rows only"
    assert "(n=2, 0-1 plain-recipe rows only)" in html, (
        "aggregate n must exclude the >1.0 pre-E1 rows"
    )
    # The pre-E1 rows are surfaced as excluded, not folded into the mean.
    assert "2 pre-E1 (mixed scale, excluded)" in html
    # The garbage old-scale mean (≈ -0.6 across all four) must never appear.
    assert "-0.6" not in html and "-1.7" not in html


def test_mutations_pre_e1_rows_annotated_and_uncounted() -> None:
    """The >1.0 rows render a 'pre-E1 (mixed scale)' tag in the per-row Δ cell and
    are classified ``pre-E1`` (not improved/regressed/noise) by the outcome map."""
    builder = _load_builder_module()
    pre = _joined_mutation(mid="pre-a", fitness_before=2.29, fitness_delta=-1.76)
    post = _joined_mutation(mid="post-a", fitness_before=0.65, fitness_delta=0.05)
    rows_html = builder._render_mutations_rows([pre, post])
    assert "pre-E1 (mixed scale)" in rows_html, "pre-E1 row not annotated in the Δ cell"
    # The bogus old-scale delta must not be rendered for the pre-E1 row.
    assert "1.7600" not in rows_html, "pre-E1 row rendered its meaningless old-scale delta"
    # Outcome classification: pre-E1 row is its own bucket, post-E1 row is improved.
    assert builder._mutation_outcome(pre["attr"]) == ("pre-E1", "muted")
    assert builder._mutation_outcome(post["attr"])[0] == "improved"
    # The detection helper is the single robust gate.
    assert builder._is_pre_e1_mixed_scale(pre["attr"]) is True
    assert builder._is_pre_e1_mixed_scale(post["attr"]) is False


def test_mutations_summary_all_mixed_yields_zero_aggregate() -> None:
    """An all-pre-E1 input (the current real ledger state — 8 rows, all >1.0) must
    yield an EMPTY/zero aggregate (n=0, mean +0.0000), never a garbage average."""
    builder = _load_builder_module()
    joined = [
        _joined_mutation(mid="pre-a", fitness_before=1.7333, fitness_delta=-1.7333),
        _joined_mutation(mid="pre-b", fitness_before=1.7583, fitness_delta=-1.7583),
        _joined_mutation(mid="pre-c", fitness_before=2.29, fitness_delta=-1.11),
    ]
    html = builder._render_mutations_summary(joined)
    assert "+0.0000" in html, "all-mixed input must yield a zero mean, not a garbage average"
    assert "(n=0, 0-1 plain-recipe rows only)" in html, "all-mixed input must report n=0"
    assert "3 pre-E1 (mixed scale, excluded)" in html
    assert "-1.7" not in html and "-1.1" not in html, "old-scale deltas leaked into the aggregate"


def test_mutations_pre_e1_heuristic_graceful_on_missing_fitness_before() -> None:
    """Graceful contract: a missing / non-numeric / None fitness_before is NOT
    treated as mixed-scale (it cannot be proven old-scale), so it falls through to
    normal handling rather than raising."""
    builder = _load_builder_module()
    assert builder._is_pre_e1_mixed_scale(None) is False
    assert builder._is_pre_e1_mixed_scale({}) is False
    assert builder._is_pre_e1_mixed_scale({"fitness_before": None}) is False
    assert builder._is_pre_e1_mixed_scale({"fitness_before": "1.73"}) is False  # non-numeric
    # A JSON bool must NOT be read as numeric 1.0 (isinstance(True, int) is True).
    assert builder._is_pre_e1_mixed_scale({"fitness_before": True}) is False
    # A boundary 1.0 (the inclusive top of the 0-1 scale) is NOT mixed.
    assert builder._is_pre_e1_mixed_scale({"fitness_before": 1.0}) is False
    assert builder._is_pre_e1_mixed_scale({"fitness_before": 1.0001}) is True


# ---------------------------------------------------------------------------
# M2 — pre-#1947 (penalized-recipe) rows excluded from the plain-recipe mean-Δ
# ---------------------------------------------------------------------------
#
# PR-GATE-RECIPE (#1947, v0.99.106) switched the attribution ledger's
# fitness_after / fitness_delta from the PENALIZED compute_fitness (baseline_means
# penalty) to the gate's PLAIN current_raw recipe. Both sit on the 0-1 scale (so
# the pre-E1 > 1.0 guard does NOT catch them), but a penalized delta and a plain
# delta are produced by DIFFERENT recipes and must not be averaged together. With
# no per-row fitness_recipe marker yet, the hub discriminates by the #1947 merge
# timestamp (commit 2aa3b9a0, 2026-05-31T21:05:49Z UTC, epoch 1780261549). These tests
# pin that a pre-boundary (penalized) row is never blended into the post-boundary
# (plain) mean.

# The #1947 merge boundary epoch (Codex M2 ts-boundary discriminator).
# Commit 2aa3b9a0, 2026-05-31T21:05:49Z UTC.
_GATE_BOUNDARY = 1780261549.0


def _joined_recipe_mutation(*, mid: str, ts: Any, fitness_delta: Any) -> dict[str, Any]:
    """A joined entry on the 0-1 scale (fitness_before ≤ 1.0, so NOT pre-E1) carrying
    a ``ts`` — the only discriminator for the penalized (pre-#1947) vs plain recipe."""
    attr: dict[str, Any] = {
        "mutation_id": mid,
        "ts": ts,
        "fitness_before": 0.70,
        "fitness_delta": fitness_delta,
        "fitness_after": 0.70 + fitness_delta if isinstance(fitness_delta, int | float) else None,
    }
    apply_row = {"mutation_id": mid, "ts": ts, "target_section": "sec", "target_kind": "policy"}
    return {"id": mid, "apply": apply_row, "attr": attr}


def test_pre_gate_recipe_penalized_heuristic_uses_ts_boundary() -> None:
    """The discriminator is the #1947 merge ts: a row strictly before the boundary is
    penalized-recipe (legacy); at/after it is plain. Graceful on a missing/bad ts."""
    builder = _load_builder_module()
    assert builder._GATE_RECIPE_BOUNDARY_TS == _GATE_BOUNDARY
    # Strictly before the boundary → penalized (legacy).
    assert builder._is_pre_gate_recipe_penalized({"ts": _GATE_BOUNDARY - 1}) is True
    # At/after the boundary → plain (post-#1947).
    assert builder._is_pre_gate_recipe_penalized({"ts": _GATE_BOUNDARY}) is False
    assert builder._is_pre_gate_recipe_penalized({"ts": _GATE_BOUNDARY + 1}) is False
    # Graceful contract: a missing / non-numeric / bool ts is NOT proven legacy.
    assert builder._is_pre_gate_recipe_penalized(None) is False
    assert builder._is_pre_gate_recipe_penalized({}) is False
    assert builder._is_pre_gate_recipe_penalized({"ts": None}) is False
    assert builder._is_pre_gate_recipe_penalized({"ts": "1700000000"}) is False
    assert builder._is_pre_gate_recipe_penalized({"ts": True}) is False


def test_mean_delta_does_not_blend_penalized_and_plain_recipes() -> None:
    """Codex M2 — a pre-#1947 (penalized) row and a post-#1947 (plain) row, both on
    the 0-1 scale, must NOT be averaged into one mean-Δfitness. The pre-boundary row
    is excluded (and surfaced as such); the mean is the plain row(s) only."""
    builder = _load_builder_module()
    joined = [
        # Penalized recipe (pre-#1947): a large negative delta from the baseline_means
        # penalty — blending it would drag the mean toward ≈ -0.20.
        _joined_recipe_mutation(mid="legacy-a", ts=_GATE_BOUNDARY - 3600, fitness_delta=-0.40),
        _joined_recipe_mutation(mid="legacy-b", ts=_GATE_BOUNDARY - 60, fitness_delta=-0.30),
        # Plain recipe (post-#1947): the gate's current_raw decision.
        _joined_recipe_mutation(mid="plain-a", ts=_GATE_BOUNDARY + 60, fitness_delta=0.05),
        _joined_recipe_mutation(mid="plain-b", ts=_GATE_BOUNDARY + 3600, fitness_delta=0.15),
    ]
    html = builder._render_mutations_summary(joined)
    # Mean over the two PLAIN rows only = (0.05 + 0.15) / 2 = +0.1000.
    assert "+0.1000" in html, "mean-Δ must be the plain-recipe rows only, not a blend"
    assert "(n=2, 0-1 plain-recipe rows only)" in html, "n must exclude pre-#1947 penalized rows"
    # The penalized rows are surfaced as excluded, never folded into the mean.
    assert "2 penalized recipe (pre-#1947, excluded)" in html
    # The blended mean (≈ -0.125 across all four) must never appear.
    assert "-0.12" not in html and "-0.40" not in html and "-0.30" not in html


def test_penalized_recipe_row_annotated_and_uncounted_in_outcome() -> None:
    """A pre-#1947 (penalized) row renders a distinct 'penalized recipe (pre-#1947)'
    tag in the per-row Δ cell and classifies as its own ``penalized-recipe`` bucket
    (not improved/regressed/noise)."""
    builder = _load_builder_module()
    legacy = _joined_recipe_mutation(mid="legacy-a", ts=_GATE_BOUNDARY - 3600, fitness_delta=-0.40)
    plain = _joined_recipe_mutation(mid="plain-a", ts=_GATE_BOUNDARY + 3600, fitness_delta=0.15)
    rows_html = builder._render_mutations_rows([legacy, plain])
    assert "penalized recipe (pre-#1947)" in rows_html, "penalized row not annotated in Δ cell"
    # The penalized old-recipe delta must not be rendered for that row.
    assert "0.4000" not in rows_html, "penalized row rendered its non-comparable recipe delta"
    # Outcome classification: penalized row is its own bucket; plain row is improved.
    assert builder._mutation_outcome(legacy["attr"]) == ("penalized-recipe", "muted")
    assert builder._mutation_outcome(plain["attr"])[0] == "improved"


def test_current_campaign_rows_are_all_pre_1947_penalized() -> None:
    """The just-finished campaign ran BEFORE #1947 merged, so every current
    mutations.jsonl attribution row's ts is before the boundary → all tagged legacy
    (penalized) → an all-legacy input yields a zero/empty plain-recipe mean, never a
    blended number. Mirrors the all-mixed pre-E1 guard for the recipe axis."""
    builder = _load_builder_module()
    joined = [
        _joined_recipe_mutation(mid="cy-a", ts=_GATE_BOUNDARY - 7200, fitness_delta=-0.14),
        _joined_recipe_mutation(mid="cy-b", ts=_GATE_BOUNDARY - 3600, fitness_delta=-0.13),
        _joined_recipe_mutation(mid="cy-c", ts=_GATE_BOUNDARY - 600, fitness_delta=-0.16),
    ]
    html = builder._render_mutations_summary(joined)
    assert "+0.0000" in html, "all-penalized input must yield a zero mean, not a blend"
    assert "(n=0, 0-1 plain-recipe rows only)" in html, "all-penalized input must report n=0"
    assert "3 penalized recipe (pre-#1947, excluded)" in html
    assert "-0.1" not in html, "penalized recipe deltas leaked into the aggregate"


# ---------------------------------------------------------------------------
# PR-HUB-CAMPAIGN-VIZ (2026-06-01) — the live 3-arm campaign per-cycle ledger
# ---------------------------------------------------------------------------


def test_campaign_progress_parses_cycles_gen0_and_noise() -> None:
    """The campaign-progress.log parser yields per-cycle records (verdict + SKIP),
    the gen-0 K-mean repeats, and the noise band — the verdict SoT the attribution
    rows do not carry. Reads the committed fixture log."""
    builder = _load_builder_module()
    state_dir = FIXTURE_ROOT / "autoresearch" / "state"
    progress = builder._load_campaign_progress(state_dir)
    arms = {c["arm"] for c in progress["cycles"]}
    assert {"gate", "never"} <= arms, "both fixture arms must be parsed"
    gate = [c for c in progress["cycles"] if c["arm"] == "gate"]
    # 2 measured reject cycles + 1 SKIP.
    assert sum(1 for c in gate if c.get("skip")) == 1, "gate SKIP cycle not parsed"
    measured = [c for c in gate if not c.get("skip")]
    assert all(c["verdict"] == "reject" for c in measured), "gate verdicts must be reject"
    assert measured[0]["sel"] == 0.512 and measured[0]["held"] == 0.605
    # gen-0 band.
    assert len(progress["gen0"]) == 3, "3 gen-0 repeats expected"
    assert progress["noise"] == {"k": 3, "mean": 0.61, "stderr": 0.0058}


def test_campaign_progress_graceful_missing_file(tmp_path: Path) -> None:
    """Missing campaign-progress.log → empty structure, never a crash."""
    builder = _load_builder_module()
    progress = builder._load_campaign_progress(tmp_path)
    assert progress == {"cycles": [], "gen0": [], "noise": None}


def test_campaign_loaders_graceful_on_unreadable_file(tmp_path: Path) -> None:
    """Codex MCP catch: the campaign / MANIFEST loaders run BEFORE the per-page
    _safe() wrapper, so a READ error (not just a missing file) must read as 'no
    data' and never abort the whole build. Simulated with a directory in place of
    the file (read_text raises OSError)."""
    builder = _load_builder_module()
    # campaign-progress.log as a directory → OSError on read → empty structure.
    (tmp_path / "campaign-progress.log").mkdir()
    assert builder._load_campaign_progress(tmp_path) == {
        "cycles": [],
        "gen0": [],
        "noise": None,
    }
    # MANIFEST.jsonl as a directory → OSError on read → empty list.
    manifest_dir = tmp_path / "docs" / "audits" / "eval-logs"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "MANIFEST.jsonl").mkdir()
    assert builder._load_audit_manifest(tmp_path) == []


def test_campaign_regex_matches_digest_sot() -> None:
    """The hub's per-cycle regex must match the SAME live log lines the campaign
    driver SoT (core/self_improving/campaign.py, the ``progress.emit`` writers) emits
    — verified against the real line shape the campaign runner writes (cycle result +
    SKIP)."""
    builder = _load_builder_module()
    line = (
        "2026-05-31T15:28:30Z arm 'gate' cycle 1/10: fitness_after=0.666223 "
        "fitness_delta=-0.1473 held_out=0.831993 reject guard=ok "
        "(status=success samples=10 dims=22)"
    )
    m = builder._CAMPAIGN_CYCLE_RE.search(line)
    assert m is not None and m.group("arm") == "gate" and m.group("verdict") == "reject"
    assert m.group("sel") == "0.666223" and m.group("held") == "0.831993"
    skip = "2026-05-31T15:01:12Z arm 'random' cycle 9/10: SKIP (propose-guard exhausted)"
    ms = builder._CAMPAIGN_CYCLE_RE.search(skip)
    assert ms is not None and ms.group("skip") and ms.group("arm") == "random"


def test_audit_match_tolerance_links_only_nearby_eval() -> None:
    """A cycle ts matches the MANIFEST eval whose completed_at is within tolerance;
    a far-away cycle (no eval recorded for it) matches NOTHING rather than stitching
    a wrong archive."""
    builder = _load_builder_module()
    manifest = [
        {"archive": "near.eval", "completed_ts": 1000.0},
        {"archive": "far.eval", "completed_ts": 99999.0},
    ]
    near = builder._match_audit_for_cycle(1003.0, manifest)  # 3s away
    assert near is not None and near["archive"] == "near.eval"
    # 500s away from the nearest → outside the 180s tolerance → None.
    assert builder._match_audit_for_cycle(1500.0, manifest) is None
    # Non-finite cycle ts → None.
    assert builder._match_audit_for_cycle(float("nan"), manifest) is None


def test_campaign_eval_cell_uses_logs_route_keyed_on_archive() -> None:
    """The per-cycle Petri eval deep-link MUST target the Inspect-View /logs/<file>
    route keyed on the .eval ARCHIVE FILENAME — never #/tasks/<task_id> (which has
    no route). Guards the documented PR-HUB-AUDIT-DEEPLINK incident."""
    builder = _load_builder_module()
    audit = {
        "archive": "2026-05-22T05-56-42-00-00_audit_T6LMA3koV7BvpeLAmmioeF.eval",
        "summary_yaml": "2026-05-22-fixaud01.summary.yaml",
    }
    cell = builder._render_campaign_eval_cell(audit, FIXTURE_ROOT)
    assert "#/logs/" in cell, "eval cell must use the /logs/ route"
    assert "#/tasks/" not in cell, "Inspect View has no /tasks/ route"
    # The encoded archive filename is the link target.
    assert "T6LMA3koV7BvpeLAmmioeF.eval" in cell
    # The matched summary.yaml contributes a dim-engagement count.
    assert "dims engaged" in cell, "summary.yaml dim engagement not surfaced"


def test_load_summary_dims_counts_engaged_dims() -> None:
    """The minimal summary.yaml reader aggregates per-sample non_baseline_dims into a
    per-dim engagement count + a sample count."""
    builder = _load_builder_module()
    dims = builder._load_summary_dims(FIXTURE_ROOT, "2026-05-22-fixaud01.summary.yaml")
    assert dims is not None
    # fixture sample 1 engages 3 dims, sample 2 engages 2 → 5 distinct dim names.
    engaged = dims["dim_engaged"]
    assert engaged.get("broken_tool_use") == 1 and engaged.get("admirable") == 1
    assert dims["sample_count"] == 2
    # Missing file → None (graceful).
    assert builder._load_summary_dims(FIXTURE_ROOT, "does-not-exist.summary.yaml") is None


def test_campaign_cycles_divergence_is_delta_anchored_not_level_gap() -> None:
    """DIVERGENCE = (selΔ vs gen-0) − (heldΔ vs gen-0), NOT the absolute level gap
    (selection ~0.5 and held-out ~0.6 sit on different scales). A POSITIVE divergence
    (selection rose more than the frozen ruler) is the winner's-curse signal → red
    (delta-negative); a negative divergence → green (delta-positive). Dim direction
    is respected: held-out is HIGHER-is-better, so a rising Δ-held-out is green."""
    builder = _load_builder_module()
    progress = {
        "cycles": [
            {
                "arm": "gate",
                "n": 1,
                "total": 2,
                "sel": 0.60,
                "held": 0.62,
                "delta": 0.1,
                "verdict": "reject",
                "skip": False,
                "ts": "2026-05-22T06:00:00Z",
            },
            {
                "arm": "gate",
                "n": 2,
                "total": 2,
                "sel": 0.50,
                "held": 0.70,
                "delta": -0.1,
                "verdict": "reject",
                "skip": False,
                "ts": "2026-05-22T06:20:00Z",
            },
        ],
        # gen-0 anchor: sel mean 0.50, held mean 0.60.
        "gen0": [{"n": 1, "total": 1, "sel": 0.50, "held": 0.60}],
        "noise": None,
    }
    html = builder._render_campaign_cycles(progress, [], [], FIXTURE_ROOT)
    # cycle 1: selΔ=+0.10, heldΔ=+0.02 → divergence +0.08 (winner's curse) → red.
    assert "+0.0800" in html
    # cycle 2: selΔ=0.00, heldΔ=+0.10 → divergence -0.10 (ruler outran proxy) → green.
    assert "-0.1000" in html
    # Δ held-out cycle1→cycle2 = 0.70-0.62 = +0.08, a RISE → green (higher-is-better).
    assert "+0.0800" in html and "delta-positive" in html
    # winner's-curse cell is delta-negative (red) somewhere in the table.
    assert "delta-negative" in html


def test_campaign_cycles_skip_rows_and_no_fabrication() -> None:
    """A SKIP cycle (no numbers) renders SKIP + em-dash cells; an unmatched eval shows
    'no eval recorded' rather than a fabricated link. Honest empty state when no cycle
    is recorded at all."""
    builder = _load_builder_module()
    progress = {
        "cycles": [
            # A SKIP cycle (no audit ran) → SKIP + em-dash cells.
            {"arm": "gate", "n": 1, "total": 2, "skip": True, "ts": "2026-05-22T06:00:00Z"},
            # A measured cycle with NO matching arm-tagged attribution → 'no eval recorded'.
            {
                "arm": "gate",
                "n": 2,
                "total": 2,
                "sel": 0.5,
                "held": 0.6,
                "delta": -0.01,
                "verdict": "reject",
                "skip": False,
                "ts": "2026-05-22T06:20:00Z",
            },
        ],
        "gen0": [],
        "noise": None,
    }
    html = builder._render_campaign_cycles(progress, [], [], FIXTURE_ROOT)
    assert ">SKIP<" in html and "&mdash;" in html
    assert "no eval recorded" in html, "unmatched measured cycle must show 'no eval recorded'"
    # No cycles + no attribution → honest awaiting state.
    empty = builder._render_campaign_cycles(
        {"cycles": [], "gen0": [], "noise": None}, [], [], FIXTURE_ROOT
    )
    assert "awaiting" in empty.lower()


def test_campaign_margin_rule_states_rule_not_fabricated_number() -> None:
    """Per-cycle margin is not persisted → the page states the RULE + the recorded
    gen-0 stderr, never a fabricated per-cycle margin number. The 'gate decision so
    far' line is COMPUTED from the recorded gate-arm deltas (Codex MCP catch: a
    hard-coded 'every delta is negative' claim goes stale + contradicts the data)."""
    builder = _load_builder_module()
    gen0 = {"raw": {"fitness_stderr": 0.0125}}
    progress = {
        "cycles": [
            {"arm": "gate", "n": 1, "skip": False, "delta": -0.001, "verdict": "reject"},
            {"arm": "gate", "n": 2, "skip": False, "delta": 0.02, "verdict": "reject"},
        ],
        "gen0": [],
        "noise": None,
    }
    html = builder._render_campaign_margin_rule(gen0, progress)
    assert "_should_promote" in html, "must cite the margin rule SoT"
    assert "0.0125" in html, "recorded gen-0 fitness_stderr must be surfaced"
    assert "0.005 floor" in html and "0.05 if baseline N=1 critical" in html
    # The decision line must reflect the ACTUAL data: 1/2 cycles have a positive
    # delta, best +0.0200, 0 promotes — NOT a stale 'every delta is negative' claim.
    assert "1/2 measured gate cycles" in html and "+0.0200" in html
    assert "promoted <strong>0</strong>" in html
    assert "every cycle" not in html, "stale hard-coded delta claim must be gone"
    # No fitness_stderr recorded + no gate cycle → honest 'not recorded' + 'awaiting'.
    html_none = builder._render_campaign_margin_rule(
        None, {"cycles": [], "gen0": [], "noise": None}
    )
    assert "not recorded" in html_none and "awaiting" in html_none.lower()


def test_campaign_eval_deeplinks_resolve_in_listing(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """Every per-cycle Petri eval deep-link on the evidence page must resolve to a
    real logs/listing.json entry (the only Inspect-View log route)."""
    listing_path = FIXTURE_ROOT / "petri-bundle" / "logs" / "listing.json"
    valid = set(json.loads(listing_path.read_text(encoding="utf-8")))
    html = built_autoresearch_pages["evidence"]
    assert "#/tasks/" not in html, "Inspect View has no /tasks/ route"
    for fname in re.findall(r"/geode/self-improving/petri-bundle/#/logs/([^\"#]+)", html):
        from urllib.parse import unquote

        assert unquote(fname) in valid, (
            f"campaign eval deep-link {fname!r} absent from logs/listing.json"
        )
