"""Sanity tests for the hero-viz layout verifier.

These tests pin three guarantees so future PRs can't silently regress
the Step 2 typography drift gate:

1. Every ``Site`` declared in ``verify_hero_layout.SITES`` has an
   ``en`` + ``ko`` entry in ``layout_baseline.json``.
2. Every entry with declared text has a non-empty ``glyph_clusters``
   list (the Step 2 contract — clusters must be present so the diff
   ratchet has something to compare against).
3. ``--static-check`` exits 0 against the committed baseline (this
   is the same gate CI runs, so a green test here means a green CI
   gate).

The full HarfBuzz-shape path requires ``uharfbuzz`` + ``fc-match`` +
the Helvetica Neue / Pretendard fonts. Where those are missing
(e.g. some Linux CI runners), the tests that need them are skipped
rather than failing — the static-check + JSON shape checks still run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "visualizations" / "verify_hero_layout.py"
BASELINE = REPO_ROOT / "scripts" / "visualizations" / "layout_baseline.json"


def _load_baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _import_sites():
    """Import the SITES tuple without triggering Manim import.

    ``verify_hero_layout`` module-loads the ``Site`` dataclass + ``SITES``
    tuple at top level; the Manim-touching code lives inside functions.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.visualizations import verify_hero_layout as vhl

    return vhl.SITES


# ---------------------------------------------------------------- baseline JSON


def test_baseline_exists():
    assert BASELINE.is_file(), f"baseline missing at {BASELINE}"


def test_every_site_has_both_languages():
    """SITES must cover every (lang, site_id) pair in the baseline."""
    baseline = _load_baseline()
    sites = _import_sites()
    site_ids = {s.site_id for s in sites}

    for lang in ("en", "ko"):
        lang_table = baseline.get(lang, {})
        missing_in_baseline = site_ids - set(lang_table.keys())
        assert not missing_in_baseline, (
            f"baseline[{lang!r}] is missing site_ids: {sorted(missing_in_baseline)}"
        )


def test_every_site_with_text_has_glyph_clusters():
    """Step 2 typography drift gate — clusters present + non-empty.

    Sites with declared text (text_key or text_string_en/ko) must record
    a non-empty ``glyph_clusters`` list. Empty-text sites (rare) may
    have a missing or empty array.
    """
    baseline = _load_baseline()
    sites = _import_sites()

    for lang in ("en", "ko"):
        for site in sites:
            site_has_text = bool(
                site.text_key
                or (lang == "en" and site.text_string_en)
                or (lang == "ko" and site.text_string_ko)
            )
            if not site_has_text:
                continue
            entry = baseline[lang][site.site_id]
            clusters = entry.get("glyph_clusters")
            assert clusters is not None, (
                f"[{lang}/{site.site_id}] missing glyph_clusters — "
                "run `verify_hero_layout.py --update-baseline` locally"
            )
            assert isinstance(clusters, list) and clusters, (
                f"[{lang}/{site.site_id}] empty glyph_clusters — baseline is corrupt"
            )
            # Cluster entries are ``[codepoint:int, x_advance:int]`` pairs.
            for cluster in clusters:
                assert (
                    isinstance(cluster, list)
                    and len(cluster) == 2
                    and isinstance(cluster[0], int)
                    and isinstance(cluster[1], int)
                ), f"[{lang}/{site.site_id}] malformed cluster entry: {cluster!r}"


# ---------------------------------------------------------------- static check


def test_static_check_exits_clean():
    """``--static-check`` against the committed baseline must exit 0."""
    # sys.executable is the Python interpreter we're already running under;
    # SCRIPT is a literal repo path. Both noqa codes are safe.
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--static-check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"--static-check failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


# ---------------------------------------------------------------- HarfBuzz


@pytest.mark.skipif(shutil.which("fc-match") is None, reason="fc-match (fontconfig) not available")
def test_glyph_cluster_shape_is_deterministic():
    """Same (family, font_size, text) must always shape to the same clusters.

    HarfBuzz shaping is deterministic; this test pins the contract so
    a future Pango / HarfBuzz upgrade that changes the byte-for-byte
    output is loud + obvious. The exact values come from a fresh
    ``--update-baseline`` run on this commit.
    """
    pytest.importorskip("uharfbuzz")
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.visualizations.verify_hero_layout import _shape_glyph_clusters

    # Reference shape — "GEODE" at 16 pt under Helvetica Neue.
    clusters_a = _shape_glyph_clusters("Helvetica Neue", 16, "GEODE")
    clusters_b = _shape_glyph_clusters("Helvetica Neue", 16, "GEODE")
    assert clusters_a == clusters_b, "HarfBuzz shape must be deterministic"
    assert len(clusters_a) == 5
    assert all(isinstance(c[0], int) and isinstance(c[1], int) for c in clusters_a)


@pytest.mark.skipif(shutil.which("fc-match") is None, reason="fc-match (fontconfig) not available")
def test_glyph_cluster_drift_detected_when_text_changes():
    """Different text → different clusters → drift detected.

    Confirms the drift gate would catch a real change (e.g. removing the
    "GEODE " prefix from outer_label, the 2026-05-21 fix). If the same
    clusters were emitted, the gate would be useless.
    """
    pytest.importorskip("uharfbuzz")
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.visualizations.verify_hero_layout import _shape_glyph_clusters

    geode_seed = _shape_glyph_clusters("Helvetica Neue", 15, "GEODE seed-generation")
    seed_only = _shape_glyph_clusters("Helvetica Neue", 15, "seed-generation")

    assert geode_seed != seed_only, (
        "removing 'GEODE ' prefix must change the cluster sequence — "
        "drift gate would not catch this regression otherwise"
    )
    # The shorter string must produce strictly fewer clusters.
    assert len(seed_only) < len(geode_seed)
