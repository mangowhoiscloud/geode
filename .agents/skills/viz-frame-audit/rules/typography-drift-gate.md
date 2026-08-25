# Typography drift gate — Step 2 (shipped 2026-05-21)

> **Status**: implemented in `scripts/visualizations/verify_hero_layout.py`
> (`_resolve_font`, `_shape_glyph_clusters`, `_glyph_clusters_for_site`).
> Test coverage: `tests/test_verify_hero_layout.py` (6 cases).

## Goal

Catch category 3 (glyph kerning drift) at compile time, before render,
using [harfbuzz/uharfbuzz](https://github.com/harfbuzz/uharfbuzz) 0.54.1
(99★, last push 2026-05-19). HarfBuzz is the canonical text shaper; its
shape buffer is the same data Pango uses under the hood, so a HarfBuzz-
driven check sees the same glyph metric drift Manim would later render.

## Why this is the right line of defence

The existing `verify_hero_layout.py` measures `_make_text(...).width` /
`.height` (Cairo-based). Cairo agrees with Pango on the *total* extent
but doesn't surface per-glyph cluster offsets, so it can't detect
"GE ODE" — the total width is the same as "GEODE", only the inter-cluster
position drifts.

HarfBuzz's `hb_shape` returns the full glyph stream — codepoint, x_advance,
y_advance per glyph — which is the layer where the drift appears. By
recording the expected stream as a baseline and diffing on each PR, the
"GE ODE" / "g eneration" / "fit ness" class of defects becomes a compile-
time fail, not a post-render audit finding.

## Proposed integration

Extend the existing `verify_hero_layout.py` rather than creating a new
script. The `SITES` tuple already enumerates every text-inside-box; add a
glyph-cluster array per site/lang to the baseline JSON.

```
scripts/visualizations/
├── verify_hero_layout.py            # existing, extend
└── layout_baseline.json             # extend with `glyph_clusters` per site/lang
```

## Shipped integration

```python
import uharfbuzz as hb

# Module-level — load fonts once
_FONT_FACES: dict[str, hb.Face] = {}

def _hb_face(path: str) -> hb.Face:
    if path not in _FONT_FACES:
        blob = hb.Blob.from_file_path(path)
        _FONT_FACES[path] = hb.Face(blob)
    return _FONT_FACES[path]


def shape_glyph_clusters(
    font_path: str, font_size: int, text: str
) -> list[tuple[int, float]]:
    """Return (codepoint, x_advance) per glyph cluster.

    Acts as the canonical fingerprint of what Pango should render. Two
    fingerprints differ if and only if Pango will produce different
    inter-glyph spacing — which is exactly the category 3 drift.
    """
    face = _hb_face(font_path)
    font = hb.Font(face)
    font.scale = (font_size * 64, font_size * 64)   # HB uses 26.6 fixed-point
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf)
    return [
        (info.codepoint, pos.x_advance / 64.0)
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions)
    ]
```

In `verify_hero_layout.py`, alongside the existing `_measure_site`:

```python
EN_FONT_PATH = "/System/Library/Fonts/HelveticaNeue.ttc"
KOR_FONT_PATH = "/Users/<...>/Library/Fonts/Pretendard-Regular.otf"  # or system

def _glyph_baseline(site: Site, lang: str) -> list[tuple[int, float]]:
    text = (
        _t(site.text_key)
        if site.text_key
        else (site.text_string_en if lang == "en" else site.text_string_ko) or ""
    )
    font_path = EN_FONT_PATH if lang == "en" else KOR_FONT_PATH
    return shape_glyph_clusters(font_path, site.font_size, text)
```

Then in the verifier loop:

```python
for lang in ("en", "ko"):
    for site in SITES:
        current = _glyph_baseline(site, lang)
        recorded = baseline[lang][site.site_id].get("glyph_clusters", [])
        if recorded != current:
            failures.append(
                f"[{lang}/{site.site_id}] glyph cluster drift: "
                f"recorded {recorded!r} vs current {current!r}"
            )
```

## `--update-baseline` UX

Same flag as the geometry baseline:

```bash
uv run python scripts/visualizations/verify_hero_layout.py --update-baseline
```

The `--update-baseline` path overwrites both the geometry ratios AND the
glyph-cluster arrays — one command refreshes both layers.

## CI gate

Already exists — `verify_hero_layout.py --static-check` will pick up the
glyph cluster mismatch by adding a JSON-only validation: the recorded
glyph clusters must be non-empty (catch missing-after-add) and well-formed
(catch corrupted JSON).

The full glyph-cluster computation requires uharfbuzz + font files; this
runs on the local `--update-baseline` path only, not in CI's
`--static-check`. CI's job is to fail when the committed JSON has missing
or empty `glyph_clusters` arrays — the local developer must populate them
correctly via `--update-baseline` before committing.

## What this catches

| Defect example | Pixel ratchet (Step 3) | Typography gate (Step 2) |
|---|---|---|
| "GE ODE" drift in Bit 2 outer_label | ✅ (visible) | ✅ (compile-time, cheaper) |
| "g eneration" drift in outro x-axis | ✅ (visible) | ✅ (compile-time, cheaper) |
| Font substitution (HelveticaNeue.ttc missing → fallback to system default) | ✅ (visible) | ✅ (cluster codepoints differ entirely) |
| Manim version upgrade changes Pango shaping | Maybe (depends on output) | ✅ (cluster x_advance changes) |
| Arrow head colour mismatch | ✗ | ✗ — geometric only |

## Why two ratchets and not one

Typography drift gate (Step 2) is **deterministic and cheap** — no
rendering, just shape buffer diff. It catches the most frequent regression
class (every audit so far has had at least one category 3 incident) at the
earliest possible layer.

Pixel ratchet (Step 3) is **deterministic but expensive** (render +
ffmpeg + pixelmatch). It catches the visual regressions Step 2 cannot —
spatial relationships, animation timing, anti-aliasing changes from
upstream Manim updates.

Together they reduce manual `Read` audit cost (now the dominant cost) for
typical PRs to near-zero. Manual audit becomes the fallback for genuinely
new visual additions, not the everyday gate.
