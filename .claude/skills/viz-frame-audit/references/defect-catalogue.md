# Defect catalogue — verified incidents

All entries are real defects caught in the four GEODE scenes (`geode_hero`,
`autoresearch_filewalk`, `autoresearch_compare`, `critical_floor`).
"Verified" means: a frame was extracted, the defect was visible in `Read`,
a fix was applied, the same frame was re-extracted, the fix was confirmed
to remove the defect without collateral regressions.

Each row gives location → symptom → fix. When a similar pattern shows up
in a new scene, treat the fix as the default starting point.

## Category 1 — Naive arrow

| Origin | Location | Symptom | Fix |
|--------|----------|---------|-----|
| `geode_hero` #4 | `_dashed_arrow_with_head` default `head_size=0.24` | Triangle head too small at 1080p; arrow appears to end in a dot | Default to `head_size=0.32` |
| `geode_hero` #2 | Bit 9 `arrow_label_s2_to_s3` at `arrow.get_center() + UP * 0.25` | Arrow slope ≈ 2 (near-vertical); dashed line slices through `auto-i[mprove]` glyphs | Move label to `LEFT * 0.72 + UP * 0.05` (perpendicular offset) |
| `geode_hero` #3 | Bit 5 `arrow_label_s1_to_s2` at `arrow.get_center() + UP * 0.25` | Label brushes the evolver box right edge on STAGE 1 | Move label toward Petri end: `RIGHT * 0.55 + UP * 0.22` |

## Category 2 — Padding intrusion

| Origin | Location | Symptom | Fix |
|--------|----------|---------|-----|
| `autoresearch_filewalk` #1 | Bit 1 `_file_card` (`height=2.0`) with 7-item outline | Header (filename + LoC pill) collides with outline first line vertically; glyphs unreadable | Bump box to `height=2.5`; use single VGroup arrange: `VGroup(header_block, lines).arrange(DOWN, buff=0.18).next_to(body.get_top(), DOWN, buff=0.16)` |
| `autoresearch_filewalk` #2 | Bit 1 row labels at `LEFT * 6.0` + `font_size=15` | Label width ~3.0 → left edge at x = −7.5; crops at canvas left limit (−7.11) | Move to `LEFT * 5.6`, drop `font_size` to 13 |
| `autoresearch_filewalk` #4 | Bit 5 LoC chart — legend at y=1.6 with "1308" label top at y=1.56 | Legend bottom overlaps label top by 0.06 units | Raise legend to y=2.05; shrink `chart_h` 3.0 → 2.9 |
| `autoresearch_filewalk` #5 | Bit 6 heatmap row label at x=-2.2 (right edge -1.6) vs col 1 cell left at x=-1.67 | Row label and cell separated by only 0.07 units; visually touching | Push row label to `right_edge − 0.35` |
| `geode_hero` #7 | Rubric Detail tier card; dim font 9 | Long dim names ("cooperation_with_harmful_sysprompt") touch box edge; barely legible | Font 9 → 11; header 14 → 16; chunk dims by `len(dims) // 4` (was `// 3`) |

## Category 3 — Glyph kerning drift

| Origin | Location | Symptom | Fix |
|--------|----------|---------|-----|
| `geode_hero` #1 | Bit 2 `outer_label = "GEODE " + _t("stage_1")` | Helvetica Neue + Pango on macOS inserts ~0.06-unit spurious space between "GE" and "ODE" | Drop the "GEODE " prefix; title bar + footer chain still carry the wordmark |
| `geode_hero` #6 | Outro x-axis `_t("generations_label") = "generation"` at `font_size=16` | Spurious gaps: "g eneratio ns" | Pluralize to "generations" + raise font 16 → 20; larger glyphs amortise the per-pair kerning quirks |
| `geode_hero` (general) | Any English text at `font_size < 16` rendered via Helvetica Neue + Pango | Same drift pattern across words containing "GE", "ge", "fit", "cr" — see [README in this repo's docs/visualizations/text-overflow-map.md](../../../docs/visualizations/text-overflow-map.md) | Use `font_size ≥ 16` for visible labels; Step 2 typography drift gate will catch the others at compile time |

## Category 4 — Frame-order error

| Origin | Location | Symptom | Fix |
|--------|----------|---------|-----|
| `autoresearch_filewalk` #6 | `_clear_section()` and `_set_section_title()` called as separate `self.play(...)` | Bit-to-bit transition shows a ~0.8 s empty / half-empty frame (prior content already faded, new content not yet drawn) | Bundle into one play call inside `_set_section_title`: `self.play(*fade_outs, FadeIn(new_title), run_time=0.4)` |
| `geode_hero` #5 | Outro ratchet — `LaggedStart(*dots, 2.5s)` then separate `Create(connectors, 0.6s)` | All 10 dots appear first; line is drawn afterwards; during the trailing frames the last dot floats above the line | `AnimationGroup(FadeIn(dot), FadeIn(commit), Create(connectors[i-1]))` interleaved per generation inside `LaggedStart` |

## Intentional design exceptions

These look like defects but are intentional per user feedback:

- Bit 11-12 simultaneous display of STAGE 1 + 2 + 3 zones (information
  accumulation, not a layering bug).
- Outro vertical commit column being separate from the in-scene horizontal
  git chain (`a3f → b7c → d92 + HEAD`) — intentional visual contrast.

If a future audit flags these again, append a note here rather than asking
the user a second time.

## How to use this catalogue

1. During audit, after a frame is `Read`, scan for a row in this catalogue
   that matches the symptom. If found, apply the documented fix.
2. When a new defect type appears (not in any row), add a row in the
   appropriate category with `origin`, `location`, `symptom`, `fix` once
   the fix is verified.
3. Quarterly, scan for fix patterns that repeat across many rows — those
   may indicate a missing primitive in
   [[manim-scene-craft]]'s `rules/`.
