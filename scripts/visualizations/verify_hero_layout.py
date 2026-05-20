"""Hero-viz layout verifier — overflow + missing-font guard with ratchet.

Detects two failure modes that bit previous v3/v4 renders:

1. **Text-overflow** — a text mobject's measured width / height exceeds
   the container it's placed inside (e.g. an agent box label spilling
   past the rectangle, or a dim_extractor dict literal touching the
   left edge of its yellow card). Site list is hard-coded against the
   scene source so the verifier doesn't depend on rendering the whole
   33-second video.
2. **Font missing** — both ``EN_FONT`` and ``KOR_FONT`` must be visible
   to fontconfig before Manim's Pango backend tries to render with them
   (Inter ligature artifacts on macOS, Pretendard not installed on a
   fresh Linux CI runner).

Ratchet behaviour
=================

* Each (lang, site) measurement is compared against
  ``scripts/visualizations/layout_baseline.json``.
* A new run that **shrinks** the measured ratio (text width / box
  width) — i.e. improves headroom — is accepted and the baseline is
  refreshed when ``--update-baseline`` is passed.
* A new run that **grows** the ratio past the recorded baseline by
  more than ``RATCHET_TOLERANCE`` is rejected (exit 1). The verifier
  prints the offending sites so the regressing PR can fix or pin the
  text length.
* Missing fonts always fail; no ratchet for "fonts are gone".

Usage
=====

::

    uv run python scripts/visualizations/verify_hero_layout.py            # check
    uv run python scripts/visualizations/verify_hero_layout.py --update-baseline   # accept improvements

CI wires the first form; engineers run the second when they
deliberately widen a label and want the ratchet to track the new
safe upper bound.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / "scripts" / "visualizations" / "layout_baseline.json"
RATCHET_TOLERANCE = 0.03  # 3 % growth tolerated; beyond that → fail.


# Make scene module importable without a manim render.
sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class Site:
    """One layout check — text label inside a known container box."""

    site_id: str
    text_key: str
    font_size: int
    container_width: float
    container_height: float
    # Optional `text_string` overrides the lookup — used for inline
    # literals that don't live in the EN/KO translation table
    # (e.g. ``dim_means: {broken_tool_use: 2.5, …}``).
    text_string_en: str | None = None
    text_string_ko: str | None = None


# Layout sites — keyed by site_id; covers every "text inside box" pair
# in scripts/visualizations/geode_hero.py. When the scene adds a new
# box, append a Site here and run with --update-baseline.
SITES: tuple[Site, ...] = (
    Site("agent_generator", "agent_generator", 14, 1.05, 0.5),
    Site("agent_proximity", "agent_proximity", 14, 1.05, 0.5),
    Site("agent_critic", "agent_critic", 14, 1.05, 0.5),
    Site("agent_pilot", "agent_pilot", 14, 1.05, 0.5),
    Site("agent_ranker", "agent_ranker", 14, 1.05, 0.5),
    Site("agent_evolver", "agent_evolver", 14, 1.05, 0.5),
    Site("agent_meta_reviewer", "agent_meta_reviewer", 14, 1.4, 0.5),
    Site("petri_box", "petri_box", 18, 3.0, 1.0),
    Site(
        "dim_means_dict",
        "",
        10,
        3.4,
        0.45,
        text_string_en="dim_means: {broken_tool_use: 2.5, …}",
        text_string_ko="dim_means: {broken_tool_use: 2.5, …}",
    ),
    Site(
        "dim_stderr_dict",
        "",
        10,
        3.4,
        0.45,
        text_string_en="dim_stderr: {broken_tool_use: 0.4, …}",
        text_string_ko="dim_stderr: {broken_tool_use: 0.4, …}",
    ),
    Site("baseline_json", "baseline_json", 14, 2.4, 0.5),
    Site(
        "fitness_formula",
        "",
        14,
        3.5,
        0.4,
        text_string_en="fitness = Σ wᵢ × (10 − dim_meansᵢ) / 10",
        text_string_ko="fitness = Σ wᵢ × (10 − dim_meansᵢ) / 10",
    ),
)


def _ensure_fonts_installed() -> None:
    """Abort if EN_FONT or KOR_FONT is missing from fontconfig.

    Uses ``fc-list`` rather than importing the scene so this check
    runs in environments that haven't yet brought in manim.
    """
    if shutil.which("fc-list") is None:
        print(
            "verify_hero_layout: WARN fc-list not available; "
            "skipping font-presence check.",
            file=sys.stderr,
        )
        return

    from scripts.visualizations.geode_hero import EN_FONT, KOR_FONT  # type: ignore[import-not-found]

    fonts = subprocess.check_output(["fc-list"], text=True)
    missing: list[str] = []
    for label, name in (("EN_FONT", EN_FONT), ("KOR_FONT", KOR_FONT)):
        # Case-insensitive substring search — fc-list ships entries
        # like "Pretendard:style=Regular".
        if name.lower() not in fonts.lower():
            missing.append(f"{label}={name!r}")
    if missing:
        msg = (
            "verify_hero_layout: FAIL missing fonts — "
            + ", ".join(missing)
            + ". Install via `brew install --cask font-pretendard` "
            "(or the platform equivalent) before rendering."
        )
        print(msg, file=sys.stderr)
        sys.exit(1)


def _measure_site(site: Site, lang: str) -> tuple[float, float]:
    """Render one text label and return ``(width, height)`` in scene units."""
    # Import inside the function so a missing manim doesn't fail
    # the font-only smoke check above.
    os.environ.setdefault("GEODE_HERO_LANG", lang)
    from scripts.visualizations.geode_hero import _make_text  # type: ignore[import-not-found]
    from scripts.visualizations.geode_hero import _t

    if site.text_key:
        text = _t(site.text_key)
    else:
        text = (site.text_string_en if lang == "en" else site.text_string_ko) or ""
    if not text:
        return 0.0, 0.0
    mobj = _make_text(text, font_size=site.font_size)
    return float(mobj.width), float(mobj.height)


def _load_baseline() -> dict:
    if not BASELINE_PATH.is_file():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _write_baseline(payload: dict) -> None:
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _check_static() -> int:
    """CI-friendly check that doesn't import manim.

    Validates that ``layout_baseline.json`` exists, covers every
    ``SITES`` entry for both languages, and that every recorded ratio
    is below the OVERFLOW threshold (1.0). Used by the CI ratchet step
    on Linux runners where Manim + Pango + Pretendard would otherwise
    cost ~10 minutes to set up per PR. Local dev updates the baseline
    with ``--update-baseline`` (full Manim measurement path).
    """
    if not BASELINE_PATH.is_file():
        print(
            f"verify_hero_layout: FAIL baseline missing at {BASELINE_PATH}",
            file=sys.stderr,
        )
        return 1
    baseline = _load_baseline()
    failures: list[str] = []
    for lang in ("en", "ko"):
        lang_table = baseline.get(lang, {})
        for site in SITES:
            entry = lang_table.get(site.site_id)
            if entry is None:
                failures.append(
                    f"[{lang}/{site.site_id}] MISSING from baseline — "
                    "run `--update-baseline` locally and commit the JSON."
                )
                continue
            ratio_w = float(entry.get("ratio_w", 1.0))
            ratio_h = float(entry.get("ratio_h", 1.0))
            if ratio_w > 1.0:
                failures.append(
                    f"[{lang}/{site.site_id}] OVERFLOW baseline width: ratio_w={ratio_w:.3f}"
                )
            if ratio_h > 1.0:
                failures.append(
                    f"[{lang}/{site.site_id}] OVERFLOW baseline height: ratio_h={ratio_h:.3f}"
                )
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        print(
            f"verify_hero_layout: static check FAILED ({len(failures)} violations).",
            file=sys.stderr,
        )
        return 1
    print(
        f"verify_hero_layout: static check OK — {len(SITES) * 2} site/lang baseline "
        "entries within overflow threshold."
    )
    return 0


def _check(*, update_baseline: bool) -> int:
    _ensure_fonts_installed()
    baseline = _load_baseline()
    failures: list[str] = []
    new_baseline: dict[str, dict[str, float]] = {}

    for lang in ("en", "ko"):
        new_baseline.setdefault(lang, {})
        for site in SITES:
            try:
                w, h = _measure_site(site, lang)
            except Exception as exc:  # pragma: no cover - defensive
                failures.append(f"[{lang}/{site.site_id}] measurement crashed: {exc!r}")
                continue
            ratio_w = w / site.container_width if site.container_width > 0 else 0.0
            ratio_h = h / site.container_height if site.container_height > 0 else 0.0
            new_baseline[lang][site.site_id] = {
                "width": round(w, 4),
                "height": round(h, 4),
                "ratio_w": round(ratio_w, 4),
                "ratio_h": round(ratio_h, 4),
            }
            prior = baseline.get(lang, {}).get(site.site_id, {})
            prior_ratio_w = float(prior.get("ratio_w", 1.0))
            prior_ratio_h = float(prior.get("ratio_h", 1.0))

            # Hard fail: any ratio > 1.0 (text exceeds its container).
            if ratio_w > 1.0:
                failures.append(
                    f"[{lang}/{site.site_id}] OVERFLOW width: text {w:.3f} > box "
                    f"{site.container_width:.3f} (ratio {ratio_w:.3f})"
                )
            elif ratio_h > 1.0:
                failures.append(
                    f"[{lang}/{site.site_id}] OVERFLOW height: text {h:.3f} > box "
                    f"{site.container_height:.3f} (ratio {ratio_h:.3f})"
                )
            # Soft fail: ratchet regression beyond tolerance.
            elif ratio_w > prior_ratio_w + RATCHET_TOLERANCE:
                failures.append(
                    f"[{lang}/{site.site_id}] RATCHET width regressed: "
                    f"ratio_w {ratio_w:.3f} > baseline {prior_ratio_w:.3f} + "
                    f"tolerance {RATCHET_TOLERANCE}"
                )
            elif ratio_h > prior_ratio_h + RATCHET_TOLERANCE:
                failures.append(
                    f"[{lang}/{site.site_id}] RATCHET height regressed: "
                    f"ratio_h {ratio_h:.3f} > baseline {prior_ratio_h:.3f} + "
                    f"tolerance {RATCHET_TOLERANCE}"
                )

    if update_baseline:
        _write_baseline(new_baseline)
        print(f"verify_hero_layout: baseline written to {BASELINE_PATH.name}.")
        return 0

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        print(
            f"verify_hero_layout: {len(failures)} layout violation(s).",
            file=sys.stderr,
        )
        return 1

    print(
        f"verify_hero_layout: OK — {len(SITES) * 2} site/lang pairs within ratchet "
        f"(tolerance {RATCHET_TOLERANCE})."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Refresh the ratchet baseline JSON with the current measurements.",
    )
    parser.add_argument(
        "--static-check",
        action="store_true",
        help=(
            "Validate the committed baseline JSON without importing manim — "
            "used by the CI ratchet step on Linux runners."
        ),
    )
    args = parser.parse_args()
    if args.static_check:
        return _check_static()
    return _check(update_baseline=args.update_baseline)


if __name__ == "__main__":
    sys.exit(main())
