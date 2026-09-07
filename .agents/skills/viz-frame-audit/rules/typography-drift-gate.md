# Typography drift gate — Step 2 (shipped 2026-05-21)

> **Status**: implemented in [`scripts/visualizations/verify_hero_layout.py`](../../../../scripts/visualizations/verify_hero_layout.py)
> (`_resolve_font`, `_shape_glyph_clusters`, `_glyph_clusters_for_site`).
> Test coverage: [`tests/visualizations/test_verify_hero_layout.py`](../../../../tests/visualizations/test_verify_hero_layout.py)
> (6 cases; HarfBuzz-dependent cases can skip when dependencies are absent).

## Goal

Detect changes in the recorded glyph sequence before a full video render,
using [harfbuzz/uharfbuzz](https://github.com/harfbuzz/uharfbuzz).
The original 2026-05-21 research snapshot recorded version 0.54.1,
99★, and last push 2026-05-19; these are historical, not current catalog data.
The direct HarfBuzz check is a shaping fingerprint, not proof of identical
Manim/Pango output: the verifier does not compare every render-time layout
setting or resulting pixel.

## Why this is the right line of defence

The geometry check measures `_make_text(...).width` / `.height`.
Total extents alone do not describe spacing inside the label, so the
verifier also records per-glyph data for each registered site.

The implementation records `[[codepoint, x_advance], ...]` as raw integers
and compares the sequence exactly during local measurement. It does not
record `y_advance`, offsets, or glyph cluster indexes. The historical
"GE ODE" / "g eneration" / "fit ness" examples motivate the check; defects
that occur only in the render path still require frame inspection.

## Integration location

The existing verifier owns the geometry and glyph checks. Its `SITES`
tuple registers the supported sites; the baseline stores both measurements
per site/language. No additional script is needed.

```
scripts/visualizations/
├── verify_hero_layout.py            # geometry + glyph checks
└── layout_baseline.json             # ratios + glyph_clusters per site/lang
```

## Shipped integration

Use the linked implementation instead of copying a second shaping routine:

- `_resolve_font` uses `fc-match` to resolve and cache a Regular font's
  path and face index; there is no fixed user-home font path.
- `_shape_glyph_clusters` lazily imports uharfbuzz, applies the font-size
  scale, and returns integer glyph/advance pairs without float conversion.
- `_glyph_clusters_for_site` honors `Site.font_family` before choosing
  the EN/KO family; `_check` compares against existing baseline sequences.

## `--update-baseline` UX

Same flag as the geometry baseline:

```bash
uv run python scripts/visualizations/verify_hero_layout.py --update-baseline
```

The `--update-baseline` path overwrites both the geometry ratios AND the
glyph-cluster arrays — one command refreshes both layers. It writes and
returns 0 even when the measurement loop collected failures, so update
success is not a validation result. After an intentional, reviewed update,
inspect the diff and run both checks without updating:

```bash
uv run python scripts/visualizations/verify_hero_layout.py
uv run python scripts/visualizations/verify_hero_layout.py --static-check
```

## CI gate

The existing `--static-check` path checks JSON site coverage, overflow
ratios, and a non-empty `glyph_clusters` list for each site with text.
It does not compute or compare current glyphs. The baseline tests also
validate that each recorded pair contains two integers.

The full glyph-cluster computation requires uharfbuzz + font files; this
runs in the local measurement path, with or without `--update-baseline`,
not in CI's static path. A green static check is baseline-structure evidence,
not evidence that fonts, shaping, or rendered frames were revalidated.

## What this catches

| Defect example | Pixel ratchet (Step 3) | Typography gate (Step 2) |
|---|---|---|
| "GE ODE" drift in Bit 2 outer_label | If sampled pixels differ beyond tolerance | Only if a registered site's shaped sequence changes |
| "g eneration" drift in outro x-axis | If sampled pixels differ beyond tolerance | Only if a registered site's shaped sequence changes |
| Font substitution (HelveticaNeue.ttc missing → fallback to system default) | If the rendered change is sampled | Font-presence check or sequence comparison may detect it; not proof of render parity |
| Manim version upgrade changes Pango shaping | If sampled output changes beyond tolerance | Not guaranteed when direct HarfBuzz output is unchanged |
| Arrow head colour mismatch | If sampled pixels differ beyond tolerance | Not covered |

## Why two ratchets and not one

Typography shaping avoids a full video render, but the combined local
verifier also measures Manim text objects. Reproducibility depends on the
text, font files, size, and shaping environment matching the baseline.

The [pixel ratchet](pixel-ratchet.md) compares sampled rendered frames and
can detect differences outside the shaping fingerprint. Its coverage is
limited by timestamps, dependencies, baselines, and per-frame tolerances.

Neither substitutes for the relevant [post-render audit](audit-workflow.md),
especially for new content, unregistered text, or transitions between samples.
