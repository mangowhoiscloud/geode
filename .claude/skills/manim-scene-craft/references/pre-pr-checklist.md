# Pre-PR checklist

Before pushing a PR that touches `scripts/visualizations/`, grep these five
items. Each one corresponds to a defect category catalogued in
[[viz-frame-audit]].

## 1. Single text entry point

```bash
grep -nE "(^|[^_a-zA-Z])Text\(" scripts/visualizations/<file>.py
```

Should match `_make_text(` only. Any raw `Text(` means the font + weight
lock is missing for that call site — kerning drift waiting to happen.

## 2. Section transition bundling

```bash
grep -nE "(_clear_section|_set_section_title)" scripts/visualizations/<file>.py
```

`_clear_section()` and `_set_section_title()` must never be called in
sequence (the latter must subsume the former in one play). Pattern checks:

- Bundled: only `_set_section_title(...)` calls; no `_clear_section()` calls
  at all. The helper itself does the prior-content FadeOut.
- Anti-pattern: a `_clear_section()` followed by a `_set_section_title()`
  on the next line — produces a 0.5–0.8 s blank transition frame.

## 3. Arrow label perpendicular offset

```bash
grep -nE "arrow_label.*move_to\(.*\.get_center\(\) \+ UP \* 0\.25" scripts/visualizations/<file>.py
```

Should produce no matches. Labels placed at `arrow.get_center() + UP * 0.25`
get sliced by near-vertical dashed arrows. Use perpendicular offset
(`LEFT * 0.5+`, `RIGHT * 0.5+`, or perpendicular helper).

## 4. Canvas edge clear

```bash
grep -nE "font_size=1[5-9]|font_size=2[0-9]" scripts/visualizations/<file>.py
grep -nE "LEFT \* [67]" scripts/visualizations/<file>.py
```

Cross-check: any large-font text near `LEFT * 6.0` or beyond is at risk of
cropping at the canvas left edge (`x ≤ -7.0`). For row labels, drop to
`font_size=13` + `LEFT * 5.6`.

## 5. Box height vs outline count

For every `_file_card(...)` / similar construction, count the outline lines
and the box height:

```bash
# Look for height values
grep -nE "height=[0-9]\.[0-9]+" scripts/visualizations/<file>.py
```

Rule of thumb: 7-item outline at font 10 needs `height ≥ 2.5`. 5-item at
font 12 needs `height ≥ 2.2`. Use the formula in
[../rules/safe-zones.md#box-height-arithmetic](../rules/safe-zones.md#box-height-arithmetic).

## Render gate

After grep passes, render the EN version at draft quality and scrub
manually:

```bash
uv run manim -ql -o <Name>-EN-draft scripts/visualizations/<file>.py <SceneClass>
open media/videos/<file>/480p15/<Name>-EN-draft.mp4
```

`-ql` is 480p15 — fast (1-2 min vs 3-4 min at 1080p60). Visual scrubbing
catches arrow / transition issues that ratchets miss.

For the full audit workflow (frame extraction + Read-tool 4-category
classification), switch to [[viz-frame-audit]].

## CI fall-back gate

The CI step `Hero viz layout ratchet` (`verify_hero_layout.py
--static-check`) catches any text-vs-container ratio overflow that slips
through local review. But the ratchet only measures geometry — it cannot
catch the four post-render categories in [[viz-frame-audit]]'s defect
taxonomy.
