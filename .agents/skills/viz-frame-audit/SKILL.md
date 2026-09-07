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
---

# Viz Frame Audit

Use after a render or re-render to verify the four defect categories. Skip it
when only the deterministic layout `--static-check` is needed.

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

1. **Decide timestamps** — cover the changed sections and adjacent transitions;
   use existing key-frame manifests when applicable. Stable layout frames and
   transition frames answer different questions.
2. **Extract** — `ffmpeg -ss <t> -frames:v 1 -update 1 -q:v 2` per timestamp.
3. **Inspect** — Use the available image-viewing tool so the model sees the
   actual frame; `Bash(cat / tail)` will NOT show the image.
4. **Classify** — for every finding, assign one of the four category numbers.
5. **Report** — present findings with timestamps and visible evidence. A review
   request does not authorize edits; if fixes were requested, implement clear
   defects and ask only about choices that materially change the intended design.
6. **When fixes are in scope**, re-render and inspect the same timestamps. Compare
   before/after; check for collateral regressions in adjacent bits.

Workflow details in [rules/audit-workflow.md](rules/audit-workflow.md) and
[rules/reporting.md](rules/reporting.md).

## File map

| File | Purpose |
|------|---------|
| [rules/audit-workflow.md](rules/audit-workflow.md) | ffmpeg extraction + Read inspection + timestamp selection + iteration loop |
| [rules/reporting.md](rules/reporting.md) | The reporting format to the user (Bit / category / location), tone rules, before/after table format |
| [rules/pixel-ratchet.md](rules/pixel-ratchet.md) | Existing `pixelmatch-py` frame comparison and evidence limits |
| [rules/typography-drift-gate.md](rules/typography-drift-gate.md) | `uharfbuzz` typography gate reference; verify current code before using historical snippets |
| [references/defect-catalogue.md](references/defect-catalogue.md) | 12+ verified incidents (filewalk × 5, hero × 7) — location, symptom, fix |
| [references/external-oss.md](references/external-oss.md) | Yusuke710/manim-skill (4-phase loop), pytest-mpl (baseline UX), pixelmatch-py, uharfbuzz, frames-mcp — stars / last-push verified 2026-05-21 |

## Quick reference — extract + inspect

Use the isolated extraction example in
[audit workflow](rules/audit-workflow.md#2-extract-frames), then inspect each
PNG with the available image viewer. Preserve prior renders and audit frames.
KO is audited separately because
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
