---
name: viz-frame-audit
description: |
  Trigger when: (1) the user mentions "noise", "slop", "frame audit", "video
  review", "letter spacing", "padding intrusion", "frame extract", "naive
  arrow", or Korean equivalents (노이즈, slop, 프레임 검수, 글자 깨짐), or
  (2) after rendering a new or modified Manim scene, or (3) the user asks to
  review an mp4 in `media/videos/` or `~/Downloads/`.

  Post-render audit workflow for Manim 1080p60 videos. Extracts keyframes via
  ffmpeg, inspects them through Claude Code's Read tool, and classifies any
  defects into four standing categories (naive arrow / padding intrusion /
  glyph kerning drift / frame-order error). Catalogues 12+ verified incidents
  across the four GEODE scenes so each is caught the first time, not
  rediscovered. The companion authoring skill is [[manim-scene-craft]].
when_to_use: |
  Use AFTER a render (or a re-render after a fix) to verify the four defect
  categories. Skip when only running the layout ratchet `--static-check` is
  needed.
user-invocable: false
---

# Viz Frame Audit

## The four categories

Videos are inspected against the four standing defect categories below. The
catalogue of verified incidents per category lives in
[references/defect-catalogue.md](references/defect-catalogue.md).

| # | Category | Definition | Detection signal |
|---|---|---|---|
| 1 | **Naive arrow** | Head too small, head colour mismatch with body, label crossing the dashed line | `head_size ≤ 0.24`, `head_color ≠ body color` with near-vertical arrow + label at `UP * 0.25` |
| 2 | **Padding intrusion** | Text or box within 0.1 of another box edge, or crossing the canvas edge | Box height < content height, row labels at `LEFT * 6.0`+, 7+ outline lines in a small box |
| 3 | **Glyph kerning drift** | Helvetica Neue + Pango misreads specific glyph pairs ("GE ODE", "g eneration", "fit ness", "cr itic") | Spurious space inside a word, more pronounced at smaller `font_size` |
| 4 | **Frame-order error** | Empty / half-empty transition frame, content not accumulating, line endpoint missing the last dot | `_clear_section` + `_set_section_title` called separately, `LaggedStart` then separate `Create(connectors)` |

## Workflow

1. **Decide timestamps** — 7-10 per video, one per major bit, avoiding the
   transition zones (target the middle of each bit's wait phase).
2. **Extract** — `ffmpeg -ss <t> -frames:v 1 -update 1 -q:v 2` per timestamp.
3. **Inspect** — Read each `.png` through Claude Code's `Read` tool so the
   model sees the actual frame; `Bash(cat / tail)` will NOT show the image.
4. **Classify** — for every finding, assign one of the four category numbers.
5. **Report** — present a `Bit X — symptom one-liner` table to the user;
   never auto-apply fixes (the user judges whether a layout choice is
   intentional).
6. **Fix → re-render → re-extract → re-Read** the same timestamps. Compare
   before/after; check for collateral regressions in adjacent bits.

Workflow details in [rules/audit-workflow.md](rules/audit-workflow.md) and
[rules/reporting.md](rules/reporting.md).

## File map

| File | Purpose |
|------|---------|
| [rules/audit-workflow.md](rules/audit-workflow.md) | ffmpeg extraction + Read inspection + timestamp selection + iteration loop |
| [rules/reporting.md](rules/reporting.md) | The reporting format to the user (Bit / category / location), tone rules, before/after table format |
| [rules/pixel-ratchet.md](rules/pixel-ratchet.md) | `pixelmatch-py` integration plan — Step 3 deterministic catch for categories 2 + 4 |
| [rules/typography-drift-gate.md](rules/typography-drift-gate.md) | `uharfbuzz` integration plan — Step 2 compile-time catch for category 3 |
| [references/defect-catalogue.md](references/defect-catalogue.md) | 12+ verified incidents (filewalk × 5, hero × 7) — location, symptom, fix |
| [references/external-oss.md](references/external-oss.md) | Yusuke710/manim-skill (4-phase loop), pytest-mpl (baseline UX), pixelmatch-py, uharfbuzz, frames-mcp — stars / last-push verified 2026-05-21 |

## Quick reference — extract + inspect

```bash
mkdir -p /tmp/<name>_audit && rm -f /tmp/<name>_audit/*.png
for t in 2.5 6.5 10.5 14.5 18.5 24.0 28.0; do
    ffmpeg -hide_banner -loglevel error -ss $t \
        -i media/videos/<scene>/1080p60/<Name>-EN.mp4 \
        -frames:v 1 -update 1 -q:v 2 /tmp/<name>_audit/EN_${t}s.png -y
done
```

Then `Read` each `.png` in Claude Code. KO is audited separately because
Korean text width differs from English — typographic and padding defects
do not transfer 1:1.

## Standing line of defence

The `verify_hero_layout.py` ratchet (covered in
[[manim-scene-craft]]'s `rules/layout-ratchet.md`) catches text-vs-container
geometry overflow at compile time. This skill's job is everything the
geometric ratchet cannot see: arrow / label spatial relationships,
typography drift inside the box, and animation timing. Steps 2 and 3
(uharfbuzz, pixelmatch) extend the compile-time ratchet so the model spends
less time inspecting frames manually — see `rules/typography-drift-gate.md`
and `rules/pixel-ratchet.md`.
