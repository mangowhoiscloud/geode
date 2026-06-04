"""Hero-viz layout verifier — overflow + missing-font + glyph drift ratchet.

Detects three failure modes that bit previous renders:

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
3. **Glyph cluster drift** (Step 2, 2026-05-21) — Helvetica Neue + Pango on
   macOS misreads certain glyph pairs and inserts spurious whitespace
   between consonants ("GE ODE", "g eneration", "fit ness"). Cairo width
   alone (#1) can't see this since the total extent stays roughly the
   same. We shape each site's text via HarfBuzz (``uharfbuzz``) and
   record the per-glyph ``(codepoint, x_advance)`` sequence in the
   baseline JSON. Any drift in that sequence — font substitution, OT
   feature change, kerning regression — fails the ratchet.

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
    uv run python scripts/visualizations/verify_hero_layout.py --update-baseline   # refresh

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
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / "scripts" / "visualizations" / "layout_baseline.json"
RATCHET_TOLERANCE = 0.03  # 3 % growth tolerated; beyond that → fail.


# Make scene module importable without a manim render.
sys.path.insert(0, str(REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────
# HarfBuzz glyph-cluster shaping — Step 2 typography drift gate
#
# We never want to import ``uharfbuzz`` at the module level because the
# ``--static-check`` CI path is supposed to run without any rendering
# dependencies installed. The helpers below import lazily and the
# ``_check`` measurement path opts in via ``HARFBUZZ_AVAILABLE``.
# ─────────────────────────────────────────────────────────────────────────

_FONT_PATH_CACHE: dict[str, tuple[str, int]] = {}


def _resolve_font(family: str) -> tuple[str, int]:
    """Return ``(font_path, face_index)`` for the Regular face of ``family``.

    Uses ``fc-match`` so the lookup is portable across macOS (where
    HelveticaNeue.ttc lives in /System/Library/Fonts/) and Linux CI
    (where Pretendard sits under ~/.local/share/fonts/ after the
    package install in CI).
    """
    if family in _FONT_PATH_CACHE:
        return _FONT_PATH_CACHE[family]
    if shutil.which("fc-match") is None:
        raise RuntimeError(
            "fc-match is required for typography drift gating. "
            "Install via `brew install fontconfig` (macOS) or "
            "`apt-get install fontconfig` (Linux)."
        )
    # fc-match is a system tool; the argv is fully literal (only the
    # family name is interpolated and comes from a hard-coded SITES table
    # via call sites). Both noqa codes are safe here.
    path = subprocess.check_output(  # noqa: S603
        ["fc-match", "-f", "%{file}", f"{family}:style=Regular"],  # noqa: S607
        text=True,
    ).strip()
    try:
        index = int(
            subprocess.check_output(  # noqa: S603
                ["fc-match", "-f", "%{index}", f"{family}:style=Regular"],  # noqa: S607
                text=True,
            ).strip()
        )
    except (subprocess.CalledProcessError, ValueError):
        index = 0
    _FONT_PATH_CACHE[family] = (path, index)
    return path, index


def _shape_glyph_clusters(family: str, font_size: int, text: str) -> list[list[int]]:
    """HarfBuzz-shape ``text`` and return ``[[codepoint, x_advance], ...]``.

    ``x_advance`` is in HarfBuzz's 26.6 fixed-point font units; we keep
    the raw integer because it makes the baseline JSON exactly
    reproducible (no FP rounding). The baseline records the full
    sequence and the verifier compares with ``==``, so any one-pixel
    advance drift fails immediately.
    """
    if not text:
        return []
    import uharfbuzz as hb  # local import only when measuring

    path, index = _resolve_font(family)
    blob = hb.Blob.from_file_path(path)
    face = hb.Face(blob, index)
    font = hb.Font(face)
    # 26.6 fixed-point — scale must match what Pango / Cairo see.
    font.scale = (font_size * 64, font_size * 64)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf)
    return [
        [int(info.codepoint), int(pos.x_advance)]
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions, strict=True)
    ]


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
    # Optional explicit font family override — used by the cold-open
    # scaffold-kind rows, which render in the monospace ``Menlo`` family
    # (code identifiers) instead of the EN/KO Helvetica Neue / Pretendard
    # pair. When set, both the Cairo width measurement and the HarfBuzz
    # glyph-cluster shaping use this family for both languages.
    font_family: str | None = None


# Layout sites — keyed by site_id; covers every "text inside box" pair
# in scripts/visualizations/geode_hero.py. When the scene adds a new
# box, append a Site here and run with --update-baseline.
SITES: tuple[Site, ...] = (
    # ── Cold-open title card (beat 0) ──
    # Full-canvas free text (no rectangle); container width is the canvas
    # safe interior (x ∈ [−7, 7] = 14.0 wide). The ratchet's job here is the
    # edge-overflow guard + glyph-cluster drift gate. The brand wordmark is
    # large (64); the 7-kind rows render in monospace (Menlo) and pin their
    # font via ``font_family`` so the glyph-cluster shaping matches the scene.
    Site("coldopen_brand", "coldopen_brand", 64, 14.0, 1.2),
    Site("coldopen_subtitle", "coldopen_subtitle", 24, 14.0, 0.6),
    Site("coldopen_reinforce_label", "coldopen_reinforce_label", 14, 14.0, 0.5),
    Site(
        "coldopen_kinds_line1",
        "coldopen_kinds_line1",
        16,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "coldopen_kinds_line2",
        "coldopen_kinds_line2",
        16,
        14.0,
        0.5,
        font_family="Menlo",
    ),
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
        13,
        6.0,
        0.5,
        text_string_en="fitness = Σᵢ wᵢ · score(dim_meansᵢ) + w_stab · stability",
        text_string_ko="fitness = Σᵢ wᵢ · score(dim_meansᵢ) + w_stab · stability",
    ),
    # ── 3-Act narrative scaffolding (Problem → 대처 → 트레이드오프) ──
    # Act-title + one-line problem/fix/tradeoff strings. These are free
    # text on the interlude canvas (no rectangle), so the container width
    # is the canvas safe interior (x ∈ [−7, 7] = 14.0 wide); the ratchet's
    # job here is the glyph-cluster drift gate + the edge-overflow guard.
    Site("act1_title", "act1_title", 30, 14.0, 0.7),
    Site("act1_problem", "act1_problem", 22, 14.0, 0.6),
    Site("act1_fix", "act1_fix", 22, 14.0, 0.6),
    Site("act1_tradeoff", "act1_tradeoff", 24, 14.0, 0.6),
    Site("act2_title", "act2_title", 30, 14.0, 0.7),
    Site("act2_problem", "act2_problem", 22, 14.0, 0.6),
    Site("act2_fix", "act2_fix", 22, 14.0, 0.6),
    Site("act2_tradeoff", "act2_tradeoff", 24, 14.0, 0.6),
    Site("act2_invariant", "act2_invariant", 16, 14.0, 0.5),
    Site("act3_title", "act3_title", 30, 14.0, 0.7),
    Site("act3_problem", "act3_problem", 22, 14.0, 0.6),
    Site("act3_fix", "act3_fix", 22, 14.0, 0.6),
    Site("act3_tradeoff", "act3_tradeoff", 24, 14.0, 0.6),
    # Act 4 — judge rewards fluency; name the contracts instead. The Act 4
    # countermeasure is DESIGN-STAGE (see geode_hero.py); the on-screen
    # ``designed_role`` label is the honesty marker. Act-title + one-line
    # problem/fix/tradeoff are free text on the interlude canvas (14.0 wide).
    Site("act4_title", "act4_title", 30, 14.0, 0.7),
    Site("act4_problem", "act4_problem", 22, 14.0, 0.6),
    Site("act4_fix", "act4_fix", 22, 14.0, 0.6),
    Site("act4_tradeoff", "act4_tradeoff", 24, 14.0, 0.6),
    Site("designed_role", "designed_role", 15, 14.0, 0.5),
    # On-screen literal evidence cards (scene-private literals).
    Site("act1_ceiling_label", "act1_ceiling_label", 16, 8.0, 0.5),
    Site("act1_blend_formula", "act1_blend_formula", 16, 8.0, 0.5),
    Site("act1_confidence_formula", "act1_confidence_formula", 14, 8.0, 0.5),
    # Act 1 tradeoff on-screen evidence — measured gen-2606-blend3 N=12 run.
    # Rendered in monospace (Menlo) as data rows on the tradeoff interlude;
    # container width is the canvas safe interior (14.0 wide).
    Site(
        "act1_tradeoff_dist_label",
        "act1_tradeoff_dist_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "act1_tradeoff_variance_label",
        "act1_tradeoff_variance_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "act1_tradeoff_survive_label",
        "act1_tradeoff_survive_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "act1_tradeoff_provenance_label",
        "act1_tradeoff_provenance_label",
        12,
        14.0,
        0.5,
    ),
    Site("act2_dimcount_label", "act2_dimcount_label", 16, 8.0, 0.5),
    Site("act2_arms_label", "act2_arms_label", 15, 8.0, 0.5),
    Site("act2_target_label", "act2_target_label", 15, 8.0, 0.5),
    Site("act3_wallclock_label", "act3_wallclock_label", 15, 8.0, 0.5),
    Site("act3_gatefloor_label", "act3_gatefloor_label", 15, 8.0, 0.5),
    # Provenance label covering ALL Act 3 wall-clock numbers (observed
    # campaign runs) — free text on the canvas (14.0 wide), font 12,
    # mirroring act1_tradeoff_provenance_label.
    Site(
        "act3_wallclock_provenance_label",
        "act3_wallclock_provenance_label",
        12,
        14.0,
        0.5,
    ),
    Site("act3_pathindep_label", "act3_pathindep_label", 14, 8.0, 0.5),
    Site("act3_pathdep_label", "act3_pathdep_label", 14, 8.0, 0.5),
    # Act 4 problem evidence — three observed facts about the CURRENT eval.
    # The code-identifier-bearing rows render in monospace (Menlo) on the
    # interlude canvas (14.0 wide), so they pin ``font_family``.
    Site(
        "act4_problem_obs1_label",
        "act4_problem_obs1_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "act4_problem_obs2_label",
        "act4_problem_obs2_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "act4_problem_obs3_label",
        "act4_problem_obs3_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "act4_problem_provenance_label",
        "act4_problem_provenance_label",
        12,
        14.0,
        0.5,
    ),
    # Act 4 countermeasure (DESIGN-STAGE) — the three named contracts in
    # monospace (exact snake_case) + the framing + the per-contract record.
    Site(
        "act4_contract1_label",
        "act4_contract1_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "act4_contract2_label",
        "act4_contract2_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "act4_contract3_label",
        "act4_contract3_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site("act4_framing_label", "act4_framing_label", 16, 14.0, 0.5),
    Site("act4_record_label", "act4_record_label", 14, 14.0, 0.5),
    # bit_7 transcript fork — the judge-score path (current) vs the
    # DESIGN-STAGE contract-check path. The transcript node label sits inside
    # a 1.7×0.55 box; the branch labels + contract rows are free text on the
    # center canvas (14.0 wide). The three contract rows + the two branch
    # headers render in the Menlo monospace family (code identifiers + the
    # schematic PASS/FAIL worked example), so they pin ``font_family``.
    Site(
        "fork_transcript_label",
        "fork_transcript_label",
        14,
        1.7,
        0.55,
    ),
    Site(
        "fork_judge_branch_label",
        "fork_judge_branch_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site("fork_judge_branch_note", "fork_judge_branch_note", 13, 14.0, 0.5),
    Site(
        "fork_contract_branch_label",
        "fork_contract_branch_label",
        15,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "fork_contract_row1",
        "fork_contract_row1",
        14,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "fork_contract_row2",
        "fork_contract_row2",
        14,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site(
        "fork_contract_row3",
        "fork_contract_row3",
        14,
        14.0,
        0.5,
        font_family="Menlo",
    ),
    Site("fork_attribution_label", "fork_attribution_label", 14, 14.0, 0.5),
    # Act 3 concurrency-split worker pills (text inside a 1.5×0.42 box).
    Site(
        "act3_worker_baseline",
        "",
        12,
        1.5,
        0.42,
        text_string_en="baseline",
        text_string_ko="baseline",
    ),
    Site("act3_worker_never", "", 12, 1.5, 0.42, text_string_en="never", text_string_ko="never"),
    Site(
        "act3_worker_random",
        "",
        12,
        1.5,
        0.42,
        text_string_en="random",
        text_string_ko="random",
    ),
    # ── Resolution — the honest result (measured run-2606 SoT) ──
    # The title + provenance are single-line free text on the closing canvas.
    # The two data columns (per-arm table + the 18-dim headroom-vs-noise
    # ranking) are monospace (Menlo) single-line rows; each column is laid out
    # in a single VGroup so the per-row width is what the ratchet measures. The
    # two columns sit side by side (RIGHT buff 0.9), so each column's safe width
    # is ~6.5; the rows are tracked at that width. The flowing ``resolution_lede``
    # / ``resolution_arm_note`` / ``resolution_finding`` paragraphs are
    # ``_wrap``-ped at render time into multiple lines, so — like the Act
    # ``*_detail`` paragraphs — they are NOT tracked here (the ratchet measures
    # the unwrapped single-line width, which would false-overflow a wrapped
    # paragraph). The ``_wrap`` budgets keep them inside the safe interior.
    Site("resolution_title", "resolution_title", 30, 14.0, 0.7),
    Site("resolution_arms_header", "resolution_arms_header", 14, 6.5, 0.5),
    Site("resolution_arm_row1", "resolution_arm_row1", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_arm_row2", "resolution_arm_row2", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_arm_row3", "resolution_arm_row3", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_arm_row4", "resolution_arm_row4", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_arm_row5", "resolution_arm_row5", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_noise_header", "resolution_noise_header", 14, 6.5, 0.5),
    Site("resolution_noise_row1", "resolution_noise_row1", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_noise_row2", "resolution_noise_row2", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_noise_row3", "resolution_noise_row3", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_noise_row4", "resolution_noise_row4", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_noise_row5", "resolution_noise_row5", 13, 6.5, 0.5, font_family="Menlo"),
    Site("resolution_provenance", "resolution_provenance", 12, 14.0, 0.5),
)


def _ensure_fonts_installed() -> None:
    """Abort if EN_FONT or KOR_FONT is missing from fontconfig.

    Uses ``fc-list`` rather than importing the scene so this check
    runs in environments that haven't yet brought in manim.
    """
    if shutil.which("fc-list") is None:
        print(
            "verify_hero_layout: WARN fc-list not available; skipping font-presence check.",
            file=sys.stderr,
        )
        return

    from scripts.visualizations.geode_hero import EN_FONT, KOR_FONT

    fonts = subprocess.check_output(["fc-list"], text=True)  # noqa: S607
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


def _resolve_text_for_site(site: Site, lang: str) -> str:
    """Return the actual rendered text for a ``Site`` in the given language."""
    os.environ.setdefault("GEODE_HERO_LANG", lang)
    from scripts.visualizations.geode_hero import _t

    if site.text_key:
        return _t(site.text_key)
    return (site.text_string_en if lang == "en" else site.text_string_ko) or ""


def _measure_site(site: Site, lang: str) -> tuple[float, float]:
    """Render one text label and return ``(width, height)`` in scene units."""
    os.environ.setdefault("GEODE_HERO_LANG", lang)
    from scripts.visualizations.geode_hero import _make_text

    text = _resolve_text_for_site(site, lang)
    if not text:
        return 0.0, 0.0
    if site.font_family is not None:
        mobj = _make_text(text, font=site.font_family, font_size=site.font_size)
    else:
        mobj = _make_text(text, font_size=site.font_size)
    return float(mobj.width), float(mobj.height)


def _glyph_clusters_for_site(site: Site, lang: str) -> list[list[int]]:
    """Shape the site's text via HarfBuzz and return its glyph-cluster sequence.

    Returns an empty list if the text is empty. Falls back to an empty
    list (logged warning) when ``uharfbuzz`` or ``fc-match`` is missing
    locally — the baseline can still be written and ``--static-check``
    will treat missing clusters as a soft warning, not a hard fail.
    """
    text = _resolve_text_for_site(site, lang)
    if not text:
        return []
    # Step 2 typography drift gate — EN uses Helvetica Neue, KO Pretendard.
    # The families must match the scene's ``_make_text`` font selection.
    # A Site may pin an explicit ``font_family`` (the cold-open monospace
    # scaffold-kind rows render in Menlo, not the EN/KO pair).
    if site.font_family is not None:
        family = site.font_family
    else:
        family = "Helvetica Neue" if lang == "en" else "Pretendard"
    return _shape_glyph_clusters(family, site.font_size, text)


def _load_baseline() -> dict[str, Any]:
    if not BASELINE_PATH.is_file():
        return {}
    loaded = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _write_baseline(payload: dict[str, Any]) -> None:
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
            # Step 2 typography drift gate — every site that declares
            # text (via text_key or per-lang text_string) must carry a
            # glyph_clusters sequence so the field never silently
            # regresses. The actual cluster contents aren't validated
            # here (that requires uharfbuzz + fc-match + the geode_hero
            # T-table) — that's the local ``--update-baseline`` path.
            # CI's job is just to ensure the field is present + non-empty.
            site_has_text = bool(
                site.text_key
                or (lang == "en" and site.text_string_en)
                or (lang == "ko" and site.text_string_ko)
            )
            clusters = entry.get("glyph_clusters")
            if site_has_text:
                if clusters is None:
                    failures.append(
                        f"[{lang}/{site.site_id}] MISSING glyph_clusters — "
                        "run `--update-baseline` locally to populate."
                    )
                elif not isinstance(clusters, list) or not clusters:
                    failures.append(
                        f"[{lang}/{site.site_id}] EMPTY glyph_clusters — "
                        "baseline is corrupt; re-run `--update-baseline`."
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
        "entries within overflow threshold + glyph clusters populated."
    )
    return 0


def _check(*, update_baseline: bool) -> int:
    _ensure_fonts_installed()
    baseline = _load_baseline()
    failures: list[str] = []
    new_baseline: dict[str, dict[str, Any]] = {}

    for lang in ("en", "ko"):
        new_baseline.setdefault(lang, {})
        for site in SITES:
            try:
                w, h = _measure_site(site, lang)
            except Exception as exc:  # pragma: no cover - defensive
                failures.append(f"[{lang}/{site.site_id}] measurement crashed: {exc!r}")
                continue
            try:
                clusters = _glyph_clusters_for_site(site, lang)
            except Exception as exc:  # pragma: no cover - defensive
                failures.append(f"[{lang}/{site.site_id}] HarfBuzz shape crashed: {exc!r}")
                clusters = []
            ratio_w = w / site.container_width if site.container_width > 0 else 0.0
            ratio_h = h / site.container_height if site.container_height > 0 else 0.0
            new_baseline[lang][site.site_id] = {
                "width": round(w, 4),
                "height": round(h, 4),
                "ratio_w": round(ratio_w, 4),
                "ratio_h": round(ratio_h, 4),
                "glyph_clusters": clusters,
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

            # Step 2 typography drift gate — exact glyph-cluster match.
            # Drift happens when Helvetica Neue + Pango (or its HarfBuzz
            # back-end equivalent) inserts or moves a glyph between
            # baseline and current shape. ``==`` comparison is the right
            # criterion: any single advance change is real drift, since
            # the cluster sequence is canonical for a given (font, size,
            # text). We only enforce this when the baseline already
            # contains a clusters field — otherwise a brand-new site
            # would always fail the first run.
            prior_clusters = prior.get("glyph_clusters")
            if prior_clusters is not None and prior_clusters != clusters:
                failures.append(
                    f"[{lang}/{site.site_id}] GLYPH DRIFT — "
                    f"recorded {prior_clusters!r} vs current {clusters!r}. "
                    "If this is intentional (font change, label edit), "
                    "re-run `--update-baseline`."
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
