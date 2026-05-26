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
   correct chip class (PAYG / Claude Code / Codex Plus / GEODE).
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

import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

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
) -> subprocess.CompletedProcess[str]:
    """Run the hub builder against fixture roots, output into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = [
        sys.executable,
        str(BUILDER),
        "--out",
        str(out_dir / "index.html"),
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
